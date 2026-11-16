// SPDX-License-Identifier: MIT
pragma solidity 0.8.29;

import {Test, Vm} from "forge-std/Test.sol";
import {IReactive} from "reactive-lib/interfaces/IReactive.sol";
import {AbstractPayer} from "reactive-lib/base/AbstractPayer.sol";
import {PelitaKeeper} from "../src/PelitaKeeper.sol";
import {MockBiller, MockSystem} from "./mocks/MockBiller.sol";

contract PelitaKeeperTest is Test {
    address payable constant SYS = payable(0x8888888888888888888888888888888888888888);
    uint256 constant LASNA = 5318007;
    uint256 constant BASE = 84532;
    uint256 constant IGNORE = 0xa65f96fc951c35ead38878e0f0b7a3c744a6f5ccc1476b313353ce31712313ad;
    uint256 constant DARK = uint256(keccak256("BlacklistContract(address)"));
    uint256 constant LIT = uint256(keccak256("WhitelistContract(address)"));

    PelitaKeeper keeper;
    MockSystem sys;
    MockBiller proxy;
    address tank = makeAddr("tank");
    address ward = makeAddr("ward");
    address baseWard = makeAddr("baseWard");
    address stranger = makeAddr("stranger");

    event WentDark(uint256 indexed chainId, address indexed target, uint256 originBlock);
    event GaveUp(uint256 indexed chainId, address indexed target, uint8 reason);
    event Refueled(uint256 indexed chainId, address indexed target, uint256 amount, uint256 owed, uint256 originBlock);
    event RefuelRequested(uint256 indexed chainId, address indexed target, uint256 indexed seq, uint256 originBlock);
    event Relit(uint256 indexed chainId, address indexed target, uint256 originBlock);
    event LowTank(uint256 balance);

    function setUp() public {
        vm.chainId(LASNA);
        vm.etch(SYS, address(new MockSystem()).code);
        sys = MockSystem(SYS);
        proxy = new MockBiller();
        keeper = new PelitaKeeper{value: 10 ether}(0.3 ether, 3 ether);
        keeper.setChain(LASNA, SYS, address(0), 0);
        keeper.setChain(BASE, address(proxy), tank, 400_000);
        keeper.protect(LASNA, ward, 0.05 ether, 0.1 ether, 2);
        keeper.protect(BASE, baseWard, 0.0002 ether, 0.001 ether, 2);
    }

    function _log(uint256 chainId, address biller, uint256 topic0, address target)
        internal
        pure
        returns (IReactive.LogRecord memory l)
    {
        l.chainId = chainId;
        l.contractAddress = biller;
        l.topic0 = topic0;
        l.topic1 = uint256(uint160(target));
        l.blockNumber = 777;
    }

    function _react(IReactive.LogRecord memory l) internal {
        vm.prank(SYS);
        keeper.react(l);
    }

    function _darkLocal() internal {
        _react(_log(LASNA, SYS, DARK, ward));
    }

    // ------------------------------------------------------------ setup and access

    function test_ConstructorSetsOwnerFloorAndLowMark() public view {
        assertEq(keeper.owner(), address(this));
        assertEq(keeper.selfFloor(), 0.3 ether);
        assertEq(keeper.lowMark(), 3 ether);
        assertEq(address(keeper).balance, 10 ether);
    }

    function test_SetChain_OnlyOwner() public {
        vm.prank(stranger);
        vm.expectRevert(PelitaKeeper.NotOwner.selector);
        keeper.setChain(BASE, address(proxy), tank, 1);
    }

    function test_SetChain_LocalChainMustHaveNoTank() public {
        vm.expectRevert(PelitaKeeper.BadChain.selector);
        keeper.setChain(LASNA, SYS, tank, 0);
    }

    function test_SetChain_DestinationNeedsTankAndGas() public {
        vm.expectRevert(PelitaKeeper.BadChain.selector);
        keeper.setChain(BASE, address(proxy), address(0), 400_000);
        vm.expectRevert(PelitaKeeper.BadChain.selector);
        keeper.setChain(BASE, address(proxy), tank, 0);
    }

    function test_Protect_LocalSubscribesDarkTopicOnly() public view {
        // setUp protected the Lasna ward first: exactly one subscription, exact arguments.
        (uint256 c, address b, uint256 t0, uint256 t1, uint256 t2, uint256 t3) = sys.subscribed(0);
        assertEq(c, LASNA);
        assertEq(b, SYS);
        assertEq(t0, DARK);
        assertEq(t1, uint256(uint160(ward)));
        assertEq(t2, IGNORE);
        assertEq(t3, IGNORE);
    }

    function test_Protect_DestinationSubscribesDarkAndLit() public view {
        assertEq(sys.subscribedCount(), 3);
        (uint256 c1, address b1, uint256 d0,,,) = sys.subscribed(1);
        (uint256 c2, address b2, uint256 l0, uint256 l1,,) = sys.subscribed(2);
        assertEq(c1, BASE);
        assertEq(b1, address(proxy));
        assertEq(d0, DARK);
        assertEq(c2, BASE);
        assertEq(b2, address(proxy));
        assertEq(l0, LIT);
        assertEq(l1, uint256(uint160(baseWard)));
    }

    function test_Protect_RevertsWhenChainNotSet() public {
        vm.expectRevert(PelitaKeeper.ChainNotSet.selector);
        keeper.protect(1301, ward, 1, 1, 1);
    }

    function test_Protect_RevertsWhenRefillTooLarge() public {
        vm.expectRevert(PelitaKeeper.RefillTooLarge.selector);
        keeper.protect(LASNA, stranger, 1 ether + 1, 1, 1);
    }

    function test_Protect_RevertsWhenDailyCapOutOfRange() public {
        vm.expectRevert(PelitaKeeper.DailyCapOutOfRange.selector);
        keeper.protect(LASNA, stranger, 1, 1, 0);
        vm.expectRevert(PelitaKeeper.DailyCapOutOfRange.selector);
        keeper.protect(LASNA, stranger, 1, 1, 51);
    }

    /// @dev Boundary: refill == MAX_REFILL and dailyCap at both ends of 1..50 are accepted.
    function test_Protect_AcceptsBoundaryValues() public {
        keeper.protect(LASNA, stranger, 1 ether, 1, 50);
        assertEq(keeper.ward(LASNA, stranger).dailyCap, 50);
        assertEq(keeper.ward(LASNA, stranger).refill, 1 ether);
        keeper.protect(LASNA, address(0xBEEF), 1, 1, 1);
        assertEq(keeper.ward(LASNA, address(0xBEEF)).dailyCap, 1);
    }

    function test_Protect_RevertsWhenAlreadyProtected() public {
        vm.expectRevert(PelitaKeeper.AlreadyProtected.selector);
        keeper.protect(LASNA, ward, 1, 1, 1);
    }

    function test_Protect_OnlyOwner() public {
        vm.prank(stranger);
        vm.expectRevert(PelitaKeeper.NotOwner.selector);
        keeper.protect(LASNA, stranger, 1, 1, 1);
    }

    function test_Release_UnsubscribesWithExactSubscribeArguments() public {
        keeper.release(BASE, baseWard);
        assertEq(sys.unsubscribedCount(), 2);
        for (uint256 i; i < 2; i++) {
            (uint256 a, address b, uint256 c, uint256 d, uint256 e, uint256 f) = sys.subscribed(i + 1);
            (uint256 a2, address b2, uint256 c2, uint256 d2, uint256 e2, uint256 f2) = sys.unsubscribed(i);
            assertEq(keccak256(abi.encode(a, b, c, d, e, f)), keccak256(abi.encode(a2, b2, c2, d2, e2, f2)));
        }
        assertFalse(keeper.ward(BASE, baseWard).active);
    }

    function test_Release_RevertsWhenNotProtected() public {
        vm.expectRevert(PelitaKeeper.NotProtected.selector);
        keeper.release(LASNA, stranger);
    }

    function test_Reprotect_AfterReleaseKeepsOneListEntry() public {
        keeper.release(LASNA, ward);
        keeper.protect(LASNA, ward, 0.01 ether, 0.1 ether, 5);
        assertEq(keeper.wardCount(), 2);
        assertEq(keeper.wardAt(0).refill, 0.01 ether);
        assertTrue(keeper.wardAt(0).active);
    }

    // ------------------------------------------------------------ react: filtering

    function test_React_OnlySystem() public {
        vm.prank(stranger);
        vm.expectRevert(abi.encodeWithSelector(AbstractPayer.NotAuthorized.selector, stranger, SYS));
        keeper.react(_log(LASNA, SYS, DARK, ward));
    }

    function test_React_IgnoresLogFromUnknownBiller() public {
        vm.recordLogs();
        _react(_log(LASNA, stranger, DARK, ward));
        assertEq(vm.getRecordedLogs().length, 0);
        assertEq(sys.depositCalls(), 0);
    }

    function test_React_IgnoresUnprotectedTarget() public {
        vm.recordLogs();
        _react(_log(LASNA, SYS, DARK, stranger));
        assertEq(vm.getRecordedLogs().length, 0);
    }

    function test_React_IgnoresUnknownChainAndTopic() public {
        vm.recordLogs();
        _react(_log(1301, SYS, DARK, ward));
        _react(_log(LASNA, SYS, uint256(keccak256("Other()")), ward));
        assertEq(vm.getRecordedLogs().length, 0);
    }

    function test_React_IgnoresReleasedWard() public {
        keeper.release(LASNA, ward);
        vm.recordLogs();
        _darkLocal();
        assertEq(vm.getRecordedLogs().length, 0);
    }

    function test_React_DoesNothingWhenPaused() public {
        keeper.pause();
        vm.recordLogs();
        _darkLocal();
        assertEq(vm.getRecordedLogs().length, 0);
        keeper.unpause();
        _darkLocal();
        assertEq(sys.depositCalls(), 1);
    }

    function testFuzz_React_NeverRevertsForSystemLogs(uint8 chainPick, uint8 topicPick, bool knownTarget, uint256 owed)
        public
    {
        uint256 chainId = [LASNA, BASE, 1301][chainPick % 3];
        uint256 topic0 = [DARK, LIT, uint256(1)][topicPick % 3];
        address biller = chainId == BASE ? address(proxy) : SYS;
        address target = knownTarget ? (chainId == BASE ? baseWard : ward) : stranger;
        sys.setDebt(ward, owed);
        _react(_log(chainId, biller, topic0, target));
    }

    // ------------------------------------------------------------ react: Lasna path

    function test_Local_RefuelsDebtPlusRefill() public {
        sys.setDebt(ward, 0.04 ether);
        vm.expectEmit(address(keeper));
        emit WentDark(LASNA, ward, 777);
        vm.expectEmit(address(keeper));
        emit Refueled(LASNA, ward, 0.09 ether, 0.04 ether, 777);
        _darkLocal();
        assertEq(sys.deposited(ward), 0.09 ether);
        assertEq(sys.debt(ward), 0);
        assertEq(sys.reserves(ward), 0.05 ether);
        PelitaKeeper.Ward memory w = keeper.ward(LASNA, ward);
        assertEq(w.used, 1);
        assertFalse(w.dark);
        assertEq(w.darkSince, block.timestamp);
        assertEq(address(keeper).balance, 10 ether - 0.09 ether);
    }

    function test_GaveUp1_DailyCapReached() public {
        _darkLocal();
        _darkLocal();
        vm.expectEmit(address(keeper));
        emit GaveUp(LASNA, ward, 1);
        _darkLocal();
        assertEq(sys.depositCalls(), 2);
        assertTrue(keeper.ward(LASNA, ward).dark);
    }

    function test_DailyWindowRollsAfter24Hours() public {
        _darkLocal();
        _darkLocal();
        vm.warp(block.timestamp + 1 days - 1);
        _darkLocal();
        assertEq(sys.depositCalls(), 2);
        vm.warp(block.timestamp + 1);
        _darkLocal();
        assertEq(sys.depositCalls(), 3);
        assertEq(keeper.ward(LASNA, ward).used, 1);
    }

    function test_GaveUp2_DebtAboveMaxOwed() public {
        sys.setDebt(ward, 0.1 ether + 1);
        vm.expectEmit(address(keeper));
        emit GaveUp(LASNA, ward, 2);
        _darkLocal();
        assertEq(sys.depositCalls(), 0);
        assertEq(keeper.ward(LASNA, ward).used, 0);
    }

    /// @dev Boundary: only `owed > maxOwed` gives up (PRD §4.3); debt exactly at maxOwed is still refuelled.
    function test_Local_RefuelsWhenDebtEqualsMaxOwed() public {
        sys.setDebt(ward, 0.1 ether);
        vm.expectEmit(address(keeper));
        emit Refueled(LASNA, ward, 0.15 ether, 0.1 ether, 777);
        _darkLocal();
        assertEq(sys.depositCalls(), 1);
        assertEq(sys.deposited(ward), 0.15 ether);
        assertEq(keeper.ward(LASNA, ward).used, 1);
    }

    function test_GaveUp3_TankBelowAmountPlusFloor() public {
        sys.setDebt(ward, 0.01 ether);
        keeper.withdraw(payable(stranger), address(keeper).balance - (0.3 ether + 0.06 ether - 1));
        vm.expectEmit(address(keeper));
        emit GaveUp(LASNA, ward, 3);
        _darkLocal();
        assertEq(sys.depositCalls(), 0);
    }

    /// @dev RT-5: the tank is the keeper's balance. Reserves prepaid at the system contract are not spendable.
    function test_GaveUp3_ReservesWithZeroBalance() public {
        sys.depositTo{value: 5 ether}(address(keeper));
        keeper.withdraw(payable(stranger), address(keeper).balance);
        (uint256 bal, uint256 res,) = keeper.fuel();
        assertEq(bal, 0);
        assertEq(res, 5 ether);
        vm.expectEmit(address(keeper));
        emit GaveUp(LASNA, ward, 3);
        _darkLocal();
    }

    function test_GaveUp4_DepositReverts() public {
        sys.setFailDeposit(true);
        vm.expectEmit(address(keeper));
        emit GaveUp(LASNA, ward, 4);
        _darkLocal();
        assertEq(keeper.ward(LASNA, ward).used, 0);
        assertEq(address(keeper).balance, 10 ether);
    }

    function test_GaveUp4_DebtReadReverts() public {
        sys.setFailDebt(true);
        vm.expectEmit(address(keeper));
        emit GaveUp(LASNA, ward, 4);
        _darkLocal();
    }

    function test_Local_NeverSpendsBelowFloor() public {
        keeper.withdraw(payable(stranger), address(keeper).balance - (0.3 ether + 0.05 ether));
        _darkLocal();
        assertEq(address(keeper).balance, 0.3 ether);
        _darkLocal();
        assertEq(address(keeper).balance, 0.3 ether);
    }

    function test_LowTank_EmittedWhenBalanceDropsBelowMark() public {
        keeper.withdraw(payable(stranger), 7 ether);
        vm.expectEmit(address(keeper));
        emit LowTank(3 ether - 0.05 ether);
        _darkLocal();
    }

    /// @dev Boundary: LowTank fires only when balance is strictly below the mark.
    function test_LowTank_NotEmittedWhenBalanceEqualsMark() public {
        keeper.withdraw(payable(stranger), 7 ether - 0.05 ether);
        vm.recordLogs();
        _darkLocal();
        assertEq(address(keeper).balance, 3 ether);
        Vm.Log[] memory logs = vm.getRecordedLogs();
        for (uint256 i; i < logs.length; ++i) {
            assertTrue(logs[i].topics[0] != LowTank.selector);
        }
    }

    function test_Local_WhitelistTopicIgnored() public {
        vm.recordLogs();
        _react(_log(LASNA, SYS, LIT, ward));
        assertEq(vm.getRecordedLogs().length, 0);
    }

    // ------------------------------------------------------------ react: destination path

    function test_Destination_RequestsCallbackToTank() public {
        vm.expectEmit(address(keeper));
        emit RefuelRequested(BASE, baseWard, 1, 777);
        _react(_log(BASE, address(proxy), DARK, baseWard));
        assertEq(sys.callbackCount(), 1);
        MockSystem.CallbackConfiguration_V_1_0 memory cfg = sys.callbackAt(0);
        assertEq(cfg.chainId, BASE);
        assertEq(cfg.recipient, tank);
        assertEq(cfg.gasLimit, 400_000);
        bytes memory expected = abi.encodeWithSignature(
            "refuel(address,address,uint256,uint256,uint256,uint256)",
            address(0),
            baseWard,
            0.0002 ether,
            0.001 ether,
            777,
            1
        );
        assertEq(cfg.payload, expected);
        assertEq(keeper.seq(), 1);
        assertEq(keeper.ward(BASE, baseWard).used, 1);
        assertTrue(keeper.ward(BASE, baseWard).dark);
        assertEq(sys.depositCalls(), 0);
    }

    function test_Destination_DailyCapAppliesToCallbacks() public {
        _react(_log(BASE, address(proxy), DARK, baseWard));
        _react(_log(BASE, address(proxy), DARK, baseWard));
        vm.expectEmit(address(keeper));
        emit GaveUp(BASE, baseWard, 1);
        _react(_log(BASE, address(proxy), DARK, baseWard));
        assertEq(sys.callbackCount(), 2);
        assertEq(keeper.seq(), 2);
    }

    function test_GaveUp4_CallbackRefused() public {
        sys.setFailCallback(true);
        vm.expectEmit(address(keeper));
        emit GaveUp(BASE, baseWard, 4);
        _react(_log(BASE, address(proxy), DARK, baseWard));
        assertEq(keeper.seq(), 0);
        assertEq(keeper.ward(BASE, baseWard).used, 0);
    }

    function test_Destination_WhitelistRelights() public {
        _react(_log(BASE, address(proxy), DARK, baseWard));
        vm.expectEmit(address(keeper));
        emit Relit(BASE, baseWard, 777);
        _react(_log(BASE, address(proxy), LIT, baseWard));
        assertFalse(keeper.ward(BASE, baseWard).dark);
    }

    // ------------------------------------------------------------ operations

    function test_TwoStepOwnershipTransfer() public {
        keeper.transferOwnership(stranger);
        assertEq(keeper.owner(), address(this));
        vm.prank(stranger);
        keeper.acceptOwnership();
        assertEq(keeper.owner(), stranger);
        assertEq(keeper.pendingOwner(), address(0));
        vm.expectRevert(PelitaKeeper.NotOwner.selector);
        keeper.pause();
    }

    function test_AcceptOwnership_OnlyPendingOwner() public {
        keeper.transferOwnership(stranger);
        vm.prank(makeAddr("other"));
        vm.expectRevert(PelitaKeeper.NotPendingOwner.selector);
        keeper.acceptOwnership();
    }

    function test_Withdraw_OnlyOwnerAndSends() public {
        vm.prank(stranger);
        vm.expectRevert(PelitaKeeper.NotOwner.selector);
        keeper.withdraw(payable(stranger), 1 ether);
        keeper.withdraw(payable(stranger), 1 ether);
        assertEq(stranger.balance, 1 ether);
    }

    function test_OwnerSettersAreGuarded() public {
        vm.startPrank(stranger);
        vm.expectRevert(PelitaKeeper.NotOwner.selector);
        keeper.setFloor(1);
        vm.expectRevert(PelitaKeeper.NotOwner.selector);
        keeper.setLowMark(1);
        vm.expectRevert(PelitaKeeper.NotOwner.selector);
        keeper.pause();
        vm.expectRevert(PelitaKeeper.NotOwner.selector);
        keeper.release(LASNA, ward);
        vm.stopPrank();
        keeper.setFloor(1 ether);
        keeper.setLowMark(2 ether);
        assertEq(keeper.selfFloor(), 1 ether);
        assertEq(keeper.lowMark(), 2 ether);
    }

    function test_CoverDebt_AnyoneCanPayKeeperDebt() public {
        sys.setDebt(address(keeper), 0.2 ether);
        vm.prank(stranger);
        keeper.coverDebt();
        (uint256 bal,, uint256 owed) = keeper.fuel();
        assertEq(owed, 0);
        assertEq(bal, 10 ether - 0.2 ether);
    }

    function test_FundedByPlainTransfer() public {
        (bool ok,) = address(keeper).call{value: 1 ether}("");
        assertTrue(ok);
        assertEq(address(keeper).balance, 11 ether);
    }

    function test_WardListReadsBack() public view {
        assertEq(keeper.wardCount(), 2);
        PelitaKeeper.Ward memory w = keeper.wardAt(1);
        assertEq(w.chainId, BASE);
        assertEq(w.target, baseWard);
        assertEq(w.maxOwed, 0.001 ether);
        assertEq(w.dailyCap, 2);
        assertTrue(w.active);
    }
}
