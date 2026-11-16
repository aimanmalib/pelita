// SPDX-License-Identifier: MIT
pragma solidity 0.8.29;

import {AbstractCallback} from "reactive-lib/base/AbstractCallback.sol";
import {IPayable} from "reactive-lib/interfaces/IPayable.sol";
import {IBiller} from "./IBiller.sol";

/// @title PelitaTank
/// @notice Fuel tank on a destination chain. `PelitaKeeper` on Reactive Lasna asks for a callback to `refuel()` when a
///         protected contract here goes dark; the tank then pays that contract's debt (plus a refill) to the callback
///         proxy with `depositTo`.
/// @dev `refuel()` never reverts once the caller is authorised, because the proxy bills this contract for failed
///      callbacks too. Every refusal is an event with a reason instead.
contract PelitaTank is AbstractCallback {
    /// @notice Reasons for `Skipped`.
    uint8 public constant SKIP_NOT_OWED = 1;
    uint8 public constant SKIP_DEBT_TOO_HIGH = 2;
    uint8 public constant SKIP_TANK_LIMIT = 3;
    uint8 public constant SKIP_CALL_FAILED = 4;
    uint8 public constant SKIP_PAUSED = 5;

    address public owner;
    address public pendingOwner;
    /// @notice Balance kept back for this contract's own callback fees.
    uint256 public selfFloor;
    /// @notice Largest single payment (debt plus refill) the tank makes.
    uint256 public maxPerRefuel;
    bool public paused;

    event OwnershipTransferStarted(address indexed previousOwner, address indexed newOwner);
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);
    event Refueled(
        uint256 indexed seq,
        address indexed target,
        uint256 amount,
        uint256 owed,
        uint256 originBlock,
        uint256 blockNumber,
        uint256 timestamp
    );
    event Skipped(uint256 indexed seq, address indexed target, uint8 reason);
    event LimitsSet(uint256 selfFloor, uint256 maxPerRefuel);
    event PausedSet(bool paused);
    event Withdrawn(address indexed to, uint256 amount);

    error NotOwner();
    error NotPendingOwner();
    error ZeroAddress();
    error WithdrawFailed();

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    /// @param proxy The chain's callback proxy: it calls `refuel()` and is also the biller the tank pays.
    /// @param keeper The `PelitaKeeper` address on Reactive Lasna, the only accepted callback sender.
    constructor(address proxy, address keeper, uint256 selfFloor_, uint256 maxPerRefuel_)
        payable
        AbstractCallback(IPayable(payable(proxy)), keeper)
    {
        if (proxy == address(0) || keeper == address(0)) revert ZeroAddress();
        owner = msg.sender;
        selfFloor = selfFloor_;
        maxPerRefuel = maxPerRefuel_;
        emit OwnershipTransferred(address(0), msg.sender);
        emit LimitsSet(selfFloor_, maxPerRefuel_);
    }

    /// @notice Callback from the keeper. The proxy replaces `rvm` with the sending reactive contract.
    function refuel(address rvm, address target, uint256 refill, uint256 maxOwed, uint256 originBlock, uint256 seq)
        external
        onlyServiceProvider
        onlyCallbackSender(rvm)
    {
        if (paused) {
            emit Skipped(seq, target, SKIP_PAUSED);
            return;
        }
        IBiller biller = IBiller(address(_SERVICE_PROVIDER));
        uint256 owed;
        try biller.debt(target) returns (uint256 d) {
            owed = d;
        } catch {
            emit Skipped(seq, target, SKIP_CALL_FAILED);
            return;
        }
        if (owed == 0) {
            emit Skipped(seq, target, SKIP_NOT_OWED);
            return;
        }
        if (owed > maxOwed) {
            emit Skipped(seq, target, SKIP_DEBT_TOO_HIGH);
            return;
        }
        uint256 amount = owed + refill;
        if (amount > maxPerRefuel || address(this).balance < amount + selfFloor) {
            emit Skipped(seq, target, SKIP_TANK_LIMIT);
            return;
        }
        try biller.depositTo{value: amount}(target) {
            emit Refueled(seq, target, amount, owed, originBlock, block.number, block.timestamp);
        } catch {
            emit Skipped(seq, target, SKIP_CALL_FAILED);
        }
    }

    /// @notice Pays this tank's own debt to the callback proxy. Anyone may call it.
    function coverDebt() external {
        _coverDebt();
    }

    function withdraw(address payable to, uint256 amount) external onlyOwner {
        if (to == address(0)) revert ZeroAddress();
        (bool ok,) = to.call{value: amount}("");
        if (!ok) revert WithdrawFailed();
        emit Withdrawn(to, amount);
    }

    function setLimits(uint256 selfFloor_, uint256 maxPerRefuel_) external onlyOwner {
        selfFloor = selfFloor_;
        maxPerRefuel = maxPerRefuel_;
        emit LimitsSet(selfFloor_, maxPerRefuel_);
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
}
