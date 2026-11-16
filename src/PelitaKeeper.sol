// SPDX-License-Identifier: MIT
pragma solidity 0.8.29;

import {AbstractReactive} from "reactive-lib/base/AbstractReactive.sol";
import {ISystemContract} from "reactive-lib/interfaces/ISystemContract.sol";
import {IBiller} from "./IBiller.sol";

/// @title PelitaKeeper
/// @notice Listens for the biller's `BlacklistContract` log about each protected contract ("ward") and relights it.
///         On Reactive Lasna it pays the system contract directly inside `react()`. On a destination chain it asks for a
///         callback to that chain's `PelitaTank`, which pays the callback proxy there.
/// @dev The tank is this contract's own balance, funded with a plain transfer. `react()` never reverts for a log it
///      does not handle, because a reverted reactive transaction is still billed.
contract PelitaKeeper is AbstractReactive {
    /// @notice Largest refill the owner may configure for one ward.
    uint256 public constant MAX_REFILL = 1 ether;
    /// @notice Daily cap bounds (refuels per ward per window).
    uint32 public constant MIN_DAILY_CAP = 1;
    uint32 public constant MAX_DAILY_CAP = 50;
    /// @notice Length of the per-ward rate window, measured with `block.timestamp`.
    uint256 public constant WINDOW = 1 days;

    uint256 public constant TOPIC_DARK = uint256(keccak256("BlacklistContract(address)"));
    uint256 public constant TOPIC_LIT = uint256(keccak256("WhitelistContract(address)"));

    /// @notice Reasons for `GaveUp`.
    uint8 public constant GAVE_UP_DAILY_CAP = 1;
    uint8 public constant GAVE_UP_DEBT_TOO_HIGH = 2;
    uint8 public constant GAVE_UP_TANK_LOW = 3;
    uint8 public constant GAVE_UP_CALL_FAILED = 4;

    struct Chain {
        address biller;
        address tank;
        uint64 callbackGas;
        bool set;
    }

    struct Ward {
        uint256 chainId;
        address target;
        uint256 refill;
        uint256 maxOwed;
        uint32 dailyCap;
        uint32 used;
        uint64 windowStart;
        uint64 darkSince;
        bool dark;
        bool active;
    }

    address public owner;
    address public pendingOwner;
    uint256 public selfFloor;
    uint256 public lowMark;
    bool public paused;
    uint256 public seq;

    mapping(uint256 chainId => Chain) public chains;
    mapping(bytes32 key => Ward) internal _wards;
    bytes32[] internal _keys;

    event OwnershipTransferStarted(address indexed previousOwner, address indexed newOwner);
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);
    event ChainSet(uint256 indexed chainId, address biller, address tank, uint64 callbackGas);
    event Protected(uint256 indexed chainId, address indexed target, uint256 refill, uint256 maxOwed, uint32 dailyCap);
    event Released(uint256 indexed chainId, address indexed target);
    event WentDark(uint256 indexed chainId, address indexed target, uint256 originBlock);
    event GaveUp(uint256 indexed chainId, address indexed target, uint8 reason);
    event Refueled(uint256 indexed chainId, address indexed target, uint256 amount, uint256 owed, uint256 originBlock);
    event RefuelRequested(uint256 indexed chainId, address indexed target, uint256 indexed seq, uint256 originBlock);
    event Relit(uint256 indexed chainId, address indexed target, uint256 originBlock);
    event LowTank(uint256 balance);
    event FloorSet(uint256 selfFloor);
    event LowMarkSet(uint256 lowMark);
    event PausedSet(bool paused);
    event Withdrawn(address indexed to, uint256 amount);

    error NotOwner();
    error NotPendingOwner();
    error ZeroAddress();
    error BadChain();
    error ChainNotSet();
    error RefillTooLarge();
    error DailyCapOutOfRange();
    error AlreadyProtected();
    error NotProtected();
    error WithdrawFailed();

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    constructor(uint256 selfFloor_, uint256 lowMark_) payable {
        owner = msg.sender;
        selfFloor = selfFloor_;
        lowMark = lowMark_;
        emit OwnershipTransferred(address(0), msg.sender);
    }

    // ---------------------------------------------------------------- owner: setup

    /// @notice Registers the biller (and, for a destination, the tank and callback gas) of a chain.
    /// @dev On the chain this keeper runs on, `tank` must be zero; on any other chain it must be set.
    function setChain(uint256 chainId, address biller, address tank, uint64 callbackGas) external onlyOwner {
        if (biller == address(0)) revert ZeroAddress();
        bool local = chainId == block.chainid;
        if (local != (tank == address(0))) revert BadChain();
        if (!local && callbackGas == 0) revert BadChain();
        chains[chainId] = Chain({biller: biller, tank: tank, callbackGas: callbackGas, set: true});
        emit ChainSet(chainId, biller, tank, callbackGas);
    }

    /// @notice Starts watching `target` on `chainId` and relighting it when its biller blacklists it.
    function protect(uint256 chainId, address target, uint256 refill, uint256 maxOwed, uint32 dailyCap)
        external
        onlyOwner
    {
        if (target == address(0)) revert ZeroAddress();
        if (!chains[chainId].set) revert ChainNotSet();
        if (refill > MAX_REFILL) revert RefillTooLarge();
        if (dailyCap < MIN_DAILY_CAP || dailyCap > MAX_DAILY_CAP) revert DailyCapOutOfRange();
        bytes32 key = wardKey(chainId, target);
        Ward storage w = _wards[key];
        if (w.active) revert AlreadyProtected();
        if (w.target == address(0)) _keys.push(key);
        _wards[key] = Ward({
            chainId: chainId,
            target: target,
            refill: refill,
            maxOwed: maxOwed,
            dailyCap: dailyCap,
            used: 0,
            windowStart: uint64(block.timestamp),
            darkSince: 0,
            dark: false,
            active: true
        });
        emit Protected(chainId, target, refill, maxOwed, dailyCap);
        _subscriptions(true, chainId, target);
    }

    /// @notice Stops watching `target`, removing exactly the subscriptions `protect` created.
    function release(uint256 chainId, address target) external onlyOwner {
        Ward storage w = _wards[wardKey(chainId, target)];
        if (!w.active) revert NotProtected();
        w.active = false;
        emit Released(chainId, target);
        _subscriptions(false, chainId, target);
    }

    // ---------------------------------------------------------------- reactive entry point

    /// @notice Called by the system contract for every log matching a subscription. Returns early for anything it
    ///         does not handle instead of reverting.
    function react(LogRecord calldata log) external onlySystem {
        if (paused) return;
        Chain memory c = chains[log.chainId];
        if (!c.set || log.contractAddress != c.biller) return;
        // forge-lint: disable-next-line(unsafe-typecast)
        address target = address(uint160(log.topic1)); // topic 1 holds an address, left-padded
        Ward storage w = _wards[wardKey(log.chainId, target)];
        if (!w.active) return;

        if (log.topic0 == TOPIC_DARK) {
            _onDark(w, c, log.chainId, target, log.blockNumber);
        } else if (log.topic0 == TOPIC_LIT && log.chainId != block.chainid) {
            w.dark = false;
            emit Relit(log.chainId, target, log.blockNumber);
        }
    }

    function _onDark(Ward storage w, Chain memory c, uint256 chainId, address target, uint256 originBlock) internal {
        w.dark = true;
        w.darkSince = uint64(block.timestamp);
        emit WentDark(chainId, target, originBlock);

        if (block.timestamp >= uint256(w.windowStart) + WINDOW) {
            w.windowStart = uint64(block.timestamp);
            w.used = 0;
        }
        if (w.used >= w.dailyCap) {
            emit GaveUp(chainId, target, GAVE_UP_DAILY_CAP);
            return;
        }

        if (chainId == block.chainid) {
            _refuelLocal(w, IBiller(c.biller), chainId, target, originBlock);
        } else {
            _requestRefuel(w, c, chainId, target, originBlock);
        }
    }

    function _refuelLocal(Ward storage w, IBiller biller, uint256 chainId, address target, uint256 originBlock)
        internal
    {
        uint256 owed;
        try biller.debt(target) returns (uint256 d) {
            owed = d;
        } catch {
            emit GaveUp(chainId, target, GAVE_UP_CALL_FAILED);
            return;
        }
        if (owed > w.maxOwed) {
            emit GaveUp(chainId, target, GAVE_UP_DEBT_TOO_HIGH);
            return;
        }
        uint256 amount = owed + w.refill;
        if (address(this).balance < amount + selfFloor) {
            emit GaveUp(chainId, target, GAVE_UP_TANK_LOW);
            return;
        }
        try biller.depositTo{value: amount}(target) {
            w.used++;
            w.dark = false;
            emit Refueled(chainId, target, amount, owed, originBlock);
        } catch {
            emit GaveUp(chainId, target, GAVE_UP_CALL_FAILED);
            return;
        }
        if (address(this).balance < lowMark) emit LowTank(address(this).balance);
    }

    function _requestRefuel(Ward storage w, Chain memory c, uint256 chainId, address target, uint256 originBlock)
        internal
    {
        uint256 next = seq + 1;
        bytes memory payload = abi.encodeWithSignature(
            "refuel(address,address,uint256,uint256,uint256,uint256)",
            address(0),
            target,
            w.refill,
            w.maxOwed,
            originBlock,
            next
        );
        ISystemContract.CallbackConfiguration_V_1_0 memory cfg = ISystemContract.CallbackConfiguration_V_1_0({
            chainId: chainId, recipient: c.tank, gasLimit: c.callbackGas, payload: payload
        });
        seq = next;
        w.used++;
        try SYSTEM.requestCallbackV_1_0(cfg) {
            emit RefuelRequested(chainId, target, next, originBlock);
        } catch {
            // Undo the reservation so a refused request neither consumes the daily cap nor skips a sequence number.
            seq = next - 1;
            w.used--;
            emit GaveUp(chainId, target, GAVE_UP_CALL_FAILED);
        }
    }

    // ---------------------------------------------------------------- subscriptions

    /// @notice The six subscription arguments for one topic of one ward. `protect` and `release` both use this,
    ///         so an unsubscribe always matches the original subscribe exactly.
    function subscriptionArgs(uint256 chainId, address target, uint256 topic0)
        public
        view
        returns (uint256, address, uint256, uint256, uint256, uint256)
    {
        return (chainId, chains[chainId].biller, topic0, uint256(uint160(target)), REACTIVE_IGNORE, REACTIVE_IGNORE);
    }

    function _subscriptions(bool on, uint256 chainId, address target) internal {
        _subscription(on, chainId, target, TOPIC_DARK);
        if (chainId != block.chainid) _subscription(on, chainId, target, TOPIC_LIT);
    }

    function _subscription(bool on, uint256 chainId, address target, uint256 topic0) internal {
        (uint256 cid, address biller, uint256 t0, uint256 t1, uint256 t2, uint256 t3) =
            subscriptionArgs(chainId, target, topic0);
        if (on) SYSTEM.subscribe(cid, biller, t0, t1, t2, t3);
        else SYSTEM.unsubscribe(cid, biller, t0, t1, t2, t3);
    }

    // ---------------------------------------------------------------- owner: operations

    /// @notice Pays this keeper's own debt to the system contract. Anyone may call it to bring the keeper back.
    function coverDebt() external {
        _coverDebt();
    }

    function withdraw(address payable to, uint256 amount) external onlyOwner {
        if (to == address(0)) revert ZeroAddress();
        (bool ok,) = to.call{value: amount}("");
        if (!ok) revert WithdrawFailed();
        emit Withdrawn(to, amount);
    }

    function setFloor(uint256 selfFloor_) external onlyOwner {
        selfFloor = selfFloor_;
        emit FloorSet(selfFloor_);
    }

    function setLowMark(uint256 lowMark_) external onlyOwner {
        lowMark = lowMark_;
        emit LowMarkSet(lowMark_);
    }

    function pause() external onlyOwner {
        paused = true;
        emit PausedSet(true);
    }

    function unpause() external onlyOwner {
        paused = false;
        emit PausedSet(false);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        pendingOwner = newOwner;
        emit OwnershipTransferStarted(owner, newOwner);
    }

    function acceptOwnership() external {
        if (msg.sender != pendingOwner) revert NotPendingOwner();
        emit OwnershipTransferred(owner, msg.sender);
        owner = msg.sender;
        pendingOwner = address(0);
    }

    // ---------------------------------------------------------------- reads

    function wardKey(uint256 chainId, address target) public pure returns (bytes32) {
        return keccak256(abi.encode(chainId, target));
    }

    function ward(uint256 chainId, address target) external view returns (Ward memory) {
        return _wards[wardKey(chainId, target)];
    }

    function wardCount() external view returns (uint256) {
        return _keys.length;
    }

    function wardAt(uint256 i) external view returns (Ward memory) {
        return _wards[_keys[i]];
    }

    /// @notice The keeper's own fuel: tank balance, prepaid reserves and debt at the system contract.
    function fuel() external view returns (uint256 balance, uint256 reserves, uint256 owed) {
        IBiller sys = IBiller(address(SYSTEM));
        return (address(this).balance, sys.reserves(address(this)), sys.debt(address(this)));
    }
}
