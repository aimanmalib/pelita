// SPDX-License-Identifier: MIT
pragma solidity 0.8.29;

import {Test} from "forge-std/Test.sol";
import {IReactive} from "reactive-lib/interfaces/IReactive.sol";
import {PelitaKeeper} from "../../src/PelitaKeeper.sol";
import {MockSystem} from "../mocks/MockBiller.sol";

/// @notice Drives the keeper with random dark logs, debts, failures and time jumps, and records what it paid.
contract KeeperHandler is Test {
    address payable constant SYS = payable(0x8888888888888888888888888888888888888888);
    uint256 constant DARK = uint256(keccak256("BlacklistContract(address)"));

    PelitaKeeper public keeper;
    MockSystem public sys;
    address[] public wards;
    address[] public strangers;

    /// @notice Largest amount paid to one ward inside one rate window, over the whole run.
    mapping(address => uint256) public maxWindowPaid;
    /// @notice Most refuels of one ward inside one rate window, over the whole run.
    mapping(address => uint256) public maxWindowRefuels;
    mapping(address => uint256) internal _paidInWindow;
    mapping(address => uint256) internal _refuelsInWindow;
    mapping(address => uint64) internal _window;
    /// @notice Set when a refuel left the keeper below its floor.
    bool public floorBroken;
    uint256 public refuels;

    constructor(PelitaKeeper keeper_, address[] memory wards_, address[] memory strangers_) {
        keeper = keeper_;
        sys = MockSystem(SYS);
        wards = wards_;
        strangers = strangers_;
    }

    function dark(uint256 who, uint256 debt_, bool stranger, bool failDeposit) external {
        address target = stranger ? strangers[who % strangers.length] : wards[who % wards.length];
        // Half the time the debt sits exactly on the ward's limit, so the spend bound is reached, not just approached.
        uint256 owed = bound(debt_, 0, 0.2 ether);
        if (!stranger && debt_ % 2 == 0) owed = keeper.ward(block.chainid, target).maxOwed;
        sys.setDebt(target, owed);
        sys.setFailDeposit(failDeposit);

        uint256 before = address(keeper).balance;
        IReactive.LogRecord memory l;
        l.chainId = block.chainid;
        l.contractAddress = SYS;
        l.topic0 = DARK;
        l.topic1 = uint256(uint160(target));
        l.blockNumber = block.number;
        vm.prank(SYS);
        keeper.react(l); // a revert here fails the run (fail_on_revert)

        uint256 paid = before - address(keeper).balance;
        if (paid == 0) return;
        refuels++;
        if (address(keeper).balance < keeper.selfFloor()) floorBroken = true;
        uint64 ws = keeper.ward(block.chainid, target).windowStart;
        if (ws != _window[target]) {
            _window[target] = ws;
            _paidInWindow[target] = 0;
            _refuelsInWindow[target] = 0;
        }
        _paidInWindow[target] += paid;
        _refuelsInWindow[target]++;
        if (_refuelsInWindow[target] > maxWindowRefuels[target]) maxWindowRefuels[target] = _refuelsInWindow[target];
        if (_paidInWindow[target] > maxWindowPaid[target]) maxWindowPaid[target] = _paidInWindow[target];
    }

    function warp(uint256 secs) external {
        vm.warp(block.timestamp + bound(secs, 1, 2 days));
        vm.roll(block.number + 1);
    }

    function topUp(uint96 amount) external {
        vm.deal(address(keeper), address(keeper).balance + bound(amount, 0, 2 ether));
    }

    function spend(uint256 amount) external {
        uint256 bal = address(keeper).balance;
        amount = bound(amount, 0, bal);
        vm.prank(keeper.owner());
        keeper.withdraw(payable(address(0xdead)), amount);
    }
}

/// @notice PRD invariants: daily spend per ward is capped, unregistered addresses are never paid, and refuels never
///         take the keeper below its floor.
contract KeeperInvariantTest is Test {
    address payable constant SYS = payable(0x8888888888888888888888888888888888888888);
    uint256 constant LASNA = 5318007;

    PelitaKeeper keeper;
    MockSystem sys;
    KeeperHandler handler;
    address[] wards;
    address[] strangers;

    function setUp() public {
        vm.chainId(LASNA);
        vm.warp(1_700_000_000);
        vm.etch(SYS, address(new MockSystem()).code);
        sys = MockSystem(SYS);
        keeper = new PelitaKeeper{value: 3 ether}(0.3 ether, 1 ether);
        keeper.setChain(LASNA, SYS, address(0), 0);
        wards.push(makeAddr("w1"));
        wards.push(makeAddr("w2"));
        wards.push(makeAddr("w3"));
        strangers.push(makeAddr("s1"));
        strangers.push(makeAddr("s2"));
        keeper.protect(LASNA, wards[0], 0.05 ether, 0.1 ether, 3);
        keeper.protect(LASNA, wards[1], 0.01 ether, 0.02 ether, 1);
        keeper.protect(LASNA, wards[2], 0.05 ether, 0.1 ether, 50);
        handler = new KeeperHandler(keeper, wards, strangers);
        targetContract(address(handler));
    }

    function invariant_DailySpendPerWardIsCapped() public view {
        for (uint256 i; i < wards.length; i++) {
            PelitaKeeper.Ward memory w = keeper.ward(LASNA, wards[i]);
            assertLe(handler.maxWindowPaid(wards[i]), uint256(w.dailyCap) * (w.maxOwed + w.refill));
            assertLe(handler.maxWindowRefuels(wards[i]), w.dailyCap);
        }
    }

    function invariant_UnregisteredAddressesAreNeverPaid() public view {
        for (uint256 i; i < strangers.length; i++) {
            assertEq(sys.deposited(strangers[i]), 0);
        }
    }

    function invariant_RefuelsNeverBreakTheFloor() public view {
        assertFalse(handler.floorBroken());
    }
}
