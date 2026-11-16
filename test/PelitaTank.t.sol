// SPDX-License-Identifier: MIT
pragma solidity 0.8.29;

import {Test} from "forge-std/Test.sol";
import {AbstractPayer} from "reactive-lib/base/AbstractPayer.sol";
import {AbstractCallback} from "reactive-lib/base/AbstractCallback.sol";
import {PelitaTank} from "../src/PelitaTank.sol";
import {MockBiller} from "./mocks/MockBiller.sol";

contract PelitaTankTest is Test {
    PelitaTank tank;
    MockBiller proxy;
    address keeper = makeAddr("keeper");
    address target = makeAddr("target");
    address stranger = makeAddr("stranger");

    uint256 constant FLOOR = 0.001 ether;
    uint256 constant MAX_PER = 0.002 ether;
    uint256 constant REFILL = 0.0002 ether;
    uint256 constant MAX_OWED = 0.001 ether;

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

    function setUp() public {
        proxy = new MockBiller();
        tank = new PelitaTank{value: 0.01 ether}(address(proxy), keeper, FLOOR, MAX_PER);
    }

    function _refuel(uint256 refill, uint256 maxOwed, uint256 seq) internal {
        vm.prank(address(proxy));
        tank.refuel(keeper, target, refill, maxOwed, 555, seq);
    }

    // ------------------------------------------------------------ construction and access

    function test_ConstructorSetsState() public view {
        assertEq(tank.owner(), address(this));
        assertEq(tank.selfFloor(), FLOOR);
        assertEq(tank.maxPerRefuel(), MAX_PER);
        assertEq(address(tank._SERVICE_PROVIDER()), address(proxy));
        assertEq(tank._CALLBACK_SENDER(), keeper);
        assertEq(address(tank).balance, 0.01 ether);
    }

    function test_Constructor_RejectsZeroAddresses() public {
        vm.expectRevert(PelitaTank.ZeroAddress.selector);
        new PelitaTank(address(0), keeper, 0, 0);
        vm.expectRevert(PelitaTank.ZeroAddress.selector);
        new PelitaTank(address(proxy), address(0), 0, 0);
    }

    function test_Refuel_OnlyProxy() public {
        vm.prank(stranger);
        vm.expectRevert(abi.encodeWithSelector(AbstractPayer.NotAuthorized.selector, stranger, address(proxy)));
        tank.refuel(keeper, target, REFILL, MAX_OWED, 1, 1);
    }

    function test_Refuel_OnlyKeeperAsSender() public {
        vm.prank(address(proxy));
        vm.expectRevert(abi.encodeWithSelector(AbstractCallback.CallbackNotAuthorized.selector, stranger, keeper));
        tank.refuel(stranger, target, REFILL, MAX_OWED, 1, 1);
    }

    // ------------------------------------------------------------ refuel path

    function test_Refuel_PaysDebtPlusRefill() public {
        proxy.setDebt(target, 0.0005 ether);
        uint256 amount = 0.0005 ether + REFILL;
        vm.expectEmit(true, true, false, true, address(tank));
        emit Refueled(7, target, amount, 0.0005 ether, 555, block.number, block.timestamp);
        _refuel(REFILL, MAX_OWED, 7);
        assertEq(proxy.debt(target), 0);
        assertEq(proxy.deposited(target), amount);
        assertEq(proxy.reserves(target), REFILL);
        assertEq(address(tank).balance, 0.01 ether - amount);
    }

    function test_Skipped1_NotOwed() public {
        vm.expectEmit(true, true, false, true, address(tank));
        emit Skipped(1, target, 1);
        _refuel(REFILL, MAX_OWED, 1);
        assertEq(proxy.depositCalls(), 0);
    }

    function test_Skipped2_DebtTooHigh() public {
        proxy.setDebt(target, MAX_OWED + 1);
        vm.expectEmit(true, true, false, true, address(tank));
        emit Skipped(2, target, 2);
        _refuel(REFILL, MAX_OWED, 2);
        assertEq(proxy.depositCalls(), 0);
    }

    function test_Refuel_DebtEqualToMaxOwedIsPaid() public {
        proxy.setDebt(target, MAX_OWED);
        _refuel(REFILL, MAX_OWED, 1);
        assertEq(proxy.deposited(target), MAX_OWED + REFILL);
    }

    function test_Skipped3_AboveMaxPerRefuel() public {
        proxy.setDebt(target, MAX_OWED);
        vm.expectEmit(true, true, false, true, address(tank));
        emit Skipped(3, target, 3);
        _refuel(MAX_PER - MAX_OWED + 1, MAX_OWED, 3);
        assertEq(proxy.depositCalls(), 0);
    }

    function test_Refuel_AmountEqualToMaxPerRefuelIsPaid() public {
        proxy.setDebt(target, MAX_OWED);
        _refuel(MAX_PER - MAX_OWED, MAX_OWED, 3);
        assertEq(proxy.deposited(target), MAX_PER);
    }

    function test_Skipped3_BalanceBelowAmountPlusFloor() public {
        tank.withdraw(payable(stranger), 0.01 ether - FLOOR - 0.0007 ether + 1);
        proxy.setDebt(target, 0.0005 ether); // amount 0.0007 needs balance >= 0.0017
        vm.expectEmit(true, true, false, true, address(tank));
        emit Skipped(4, target, 3);
        _refuel(REFILL, MAX_OWED, 4);
        assertEq(proxy.depositCalls(), 0);
    }

    function test_Refuel_BalanceExactlyAmountPlusFloorIsPaid() public {
        tank.withdraw(payable(stranger), 0.01 ether - FLOOR - 0.0007 ether);
        proxy.setDebt(target, 0.0005 ether);
        _refuel(REFILL, MAX_OWED, 4);
        assertEq(address(tank).balance, FLOOR);
    }

    function test_Skipped4_DepositFails() public {
        proxy.setDebt(target, 0.0005 ether);
        proxy.setFailDeposit(true);
        vm.expectEmit(true, true, false, true, address(tank));
        emit Skipped(5, target, 4);
        _refuel(REFILL, MAX_OWED, 5);
        assertEq(address(tank).balance, 0.01 ether);
    }

    function test_Skipped4_DebtReadFails() public {
        proxy.setFailDebt(true);
        vm.expectEmit(true, true, false, true, address(tank));
        emit Skipped(6, target, 4);
        _refuel(REFILL, MAX_OWED, 6);
    }

    function test_Skipped5_WhenPaused() public {
        proxy.setDebt(target, 0.0005 ether);
        tank.pause();
        vm.expectEmit(true, true, false, true, address(tank));
        emit Skipped(8, target, 5);
        _refuel(REFILL, MAX_OWED, 8);
        assertEq(proxy.depositCalls(), 0);
        tank.unpause();
        _refuel(REFILL, MAX_OWED, 9);
        assertEq(proxy.depositCalls(), 1);
    }

    /// @dev Any input from the authorised proxy and keeper: refuel returns normally and never spends below the floor.
    function testFuzz_RefuelNeverRevertsAndKeepsFloor(uint256 debt_, uint256 refill, uint256 maxOwed, uint96 balance)
        public
    {
        debt_ = bound(debt_, 0, 1 ether);
        refill = bound(refill, 0, 1 ether);
        maxOwed = bound(maxOwed, 0, 1 ether);
        vm.deal(address(tank), balance);
        proxy.setDebt(target, debt_);
        _refuel(refill, maxOwed, 1);
        if (proxy.depositCalls() > 0) {
            assertGe(address(tank).balance, FLOOR);
            assertLe(proxy.deposited(target), MAX_PER);
        } else {
            assertEq(address(tank).balance, balance);
        }
    }

    // ------------------------------------------------------------ owner operations

    function test_OwnerFunctions_RejectStranger() public {
        vm.startPrank(stranger);
        vm.expectRevert(PelitaTank.NotOwner.selector);
        tank.withdraw(payable(stranger), 1);
        vm.expectRevert(PelitaTank.NotOwner.selector);
        tank.setLimits(0, 0);
        vm.expectRevert(PelitaTank.NotOwner.selector);
        tank.pause();
        vm.expectRevert(PelitaTank.NotOwner.selector);
        tank.unpause();
        vm.expectRevert(PelitaTank.NotOwner.selector);
        tank.transferOwnership(stranger);
        vm.stopPrank();
    }

    function test_SetLimits() public {
        tank.setLimits(1, 2);
        assertEq(tank.selfFloor(), 1);
        assertEq(tank.maxPerRefuel(), 2);
    }

    function test_Withdraw() public {
        tank.withdraw(payable(stranger), 0.004 ether);
        assertEq(stranger.balance, 0.004 ether);
        vm.expectRevert(PelitaTank.ZeroAddress.selector);
        tank.withdraw(payable(address(0)), 1);
    }

    function test_TwoStepOwnership() public {
        tank.transferOwnership(stranger);
        assertEq(tank.owner(), address(this));
        vm.expectRevert(PelitaTank.NotPendingOwner.selector);
        tank.acceptOwnership();
        vm.prank(stranger);
        tank.acceptOwnership();
        assertEq(tank.owner(), stranger);
        assertEq(tank.pendingOwner(), address(0));
    }

    function test_PlainTransferFundsTheTank() public {
        (bool ok,) = address(tank).call{value: 1 ether}("");
        assertTrue(ok);
        assertEq(address(tank).balance, 1.01 ether);
    }

    function test_CoverDebt_AnyoneCanPayTheTanksOwnDebt() public {
        proxy.setDebt(address(tank), 0.003 ether);
        vm.prank(stranger);
        tank.coverDebt();
        assertEq(proxy.debt(address(tank)), 0);
        assertEq(address(tank).balance, 0.007 ether);
    }

    function test_Pay_OnlyProxyMayCharge() public {
        vm.prank(stranger);
        vm.expectRevert(abi.encodeWithSelector(AbstractPayer.NotAuthorized.selector, stranger, address(proxy)));
        tank.pay(1);
        vm.prank(address(proxy));
        tank.pay(0.001 ether);
        assertEq(address(tank).balance, 0.009 ether);
    }
}
