// SPDX-License-Identifier: MIT
pragma solidity 0.8.29;

import {Test} from "forge-std/Test.sol";
import {IReactive} from "reactive-lib/interfaces/IReactive.sol";
import {AbstractPayer} from "reactive-lib/base/AbstractPayer.sol";
import {AbstractCallback} from "reactive-lib/base/AbstractCallback.sol";
import {Beacon} from "../../src/demo/Beacon.sol";
import {Flicker} from "../../src/demo/Flicker.sol";
import {Lantern} from "../../src/demo/Lantern.sol";
import {MockBiller, MockSystem} from "../mocks/MockBiller.sol";

contract DemoTest is Test {
    address payable constant SYS = payable(0x8888888888888888888888888888888888888888);
    uint256 constant LASNA = 5318007;
    uint256 constant BASE = 84532;
    uint256 constant IGNORE = 0xa65f96fc951c35ead38878e0f0b7a3c744a6f5ccc1476b313353ce31712313ad;
    uint256 constant BEAT = uint256(keccak256("Beat(uint256,uint256)"));

    // Same values as config/pelita.json "demo" (the config test keeps them in step).
    uint256 constant COOLDOWN = 600;
    uint256 constant MAX_BEATS = 40;
    uint256 constant WINDOW = 86400;

    Beacon beacon;
    Flicker flicker;
    Lantern lantern;
    MockSystem sys;
    MockBiller proxy;
    address stranger = makeAddr("stranger");

    event Beat(uint256 indexed n, uint256 at);
    event Lit(uint256 indexed n, uint256 originBlock, uint256 timestamp);
    event Forwarded(uint256 indexed n, uint256 originBlock);
    event ForwardFailed(uint256 indexed n, uint256 originBlock);

    function setUp() public {
        vm.warp(1_700_000_000);
        vm.chainId(LASNA);
        vm.etch(SYS, address(new MockSystem()).code);
        sys = MockSystem(SYS);
        proxy = new MockBiller();
        beacon = new Beacon(COOLDOWN, MAX_BEATS, WINDOW);
        flicker = new Flicker{value: 0.1 ether}(BASE, address(beacon), 100_000);
        lantern = new Lantern(address(proxy), address(flicker));
        flicker.setLantern(address(lantern));
    }

    function _beatLog(uint256 n) internal view returns (IReactive.LogRecord memory l) {
        l.chainId = BASE;
        l.contractAddress = address(beacon);
        l.topic0 = BEAT;
        l.topic1 = n;
        l.blockNumber = 900 + n;
    }

    function _react(IReactive.LogRecord memory l) internal {
        vm.prank(SYS);
        flicker.react(l);
    }

    // ------------------------------------------------------------ Beacon

    function test_Beacon_PokeEmitsNumberedBeat() public {
        vm.expectEmit(true, false, false, true, address(beacon));
        emit Beat(1, block.timestamp);
        vm.prank(stranger);
        beacon.poke();
        assertEq(beacon.beats(), 1);
    }

    function test_Beacon_CooldownBoundary() public {
        beacon.poke();
        uint256 t0 = block.timestamp;
        vm.warp(t0 + COOLDOWN - 1);
        vm.expectRevert(abi.encodeWithSelector(Beacon.TooSoon.selector, t0 + COOLDOWN));
        beacon.poke();
        assertEq(beacon.waitFor(), 1);
        vm.warp(t0 + COOLDOWN);
        assertEq(beacon.waitFor(), 0);
        beacon.poke();
        assertEq(beacon.beats(), 2);
    }

    function test_Beacon_WindowCapAndRollover() public {
        beacon.setLimits(0, 3, WINDOW);
        uint256 start = block.timestamp;
        beacon.poke();
        beacon.poke();
        beacon.poke();
        vm.expectRevert(abi.encodeWithSelector(Beacon.WindowFull.selector, start + WINDOW));
        beacon.poke();
        vm.warp(start + WINDOW - 1);
        assertEq(beacon.waitFor(), 1);
        vm.expectRevert(abi.encodeWithSelector(Beacon.WindowFull.selector, start + WINDOW));
        beacon.poke();
        vm.warp(start + WINDOW);
        beacon.poke();
        assertEq(beacon.windowBeats(), 1);
        assertEq(beacon.beats(), 4);
    }

    function test_Beacon_FortyBeatsPerDayWithDefaultLimits() public {
        for (uint256 i; i < MAX_BEATS; i++) {
            beacon.poke();
            vm.warp(block.timestamp + COOLDOWN);
        }
        vm.expectRevert();
        beacon.poke();
        assertEq(beacon.beats(), MAX_BEATS);
    }

    function test_Beacon_PokeOwnerIgnoresLimits() public {
        beacon.poke();
        beacon.pokeOwner();
        beacon.pokeOwner();
        assertEq(beacon.beats(), 3);
        assertEq(beacon.windowBeats(), 1);
        vm.prank(stranger);
        vm.expectRevert(Beacon.NotOwner.selector);
        beacon.pokeOwner();
    }

    function test_Beacon_SetLimitsOwnerOnlyAndValidated() public {
        vm.prank(stranger);
        vm.expectRevert(Beacon.NotOwner.selector);
        beacon.setLimits(1, 1, 1);
        vm.expectRevert(Beacon.BadLimits.selector);
        beacon.setLimits(1, 0, 1);
        vm.expectRevert(Beacon.BadLimits.selector);
        beacon.setLimits(1, 1, 0);
    }

    // ------------------------------------------------------------ Flicker

    function test_Flicker_SubscribesToBeatsOfItsBeacon() public view {
        assertEq(sys.subscribedCount(), 1);
        (uint256 c, address b, uint256 t0, uint256 t1, uint256 t2, uint256 t3) = sys.subscribed(0);
        assertEq(c, BASE);
        assertEq(b, address(beacon));
        assertEq(t0, BEAT);
        assertEq(t0, flicker.TOPIC_BEAT());
        assertEq(t1, IGNORE);
        assertEq(t2, IGNORE);
        assertEq(t3, IGNORE);
    }

    function test_Flicker_BeatRequestsLanternCallback() public {
        vm.expectEmit(true, false, false, true, address(flicker));
        emit Forwarded(5, 905);
        _react(_beatLog(5));
        assertEq(sys.callbackCount(), 1);
        MockSystem.CallbackConfiguration_V_1_0 memory cb = sys.callbackAt(0);
        assertEq(cb.chainId, BASE);
        assertEq(cb.recipient, address(lantern));
        assertEq(cb.gasLimit, 100_000);
        assertEq(cb.payload, abi.encodeCall(Lantern.lit, (address(0), 5, 905)));
        assertEq(flicker.forwarded(), 1);
    }

    function test_Flicker_IgnoresForeignLogsWithoutReverting() public {
        IReactive.LogRecord memory l = _beatLog(1);
        l.contractAddress = stranger;
        _react(l);
        l = _beatLog(1);
        l.chainId = LASNA;
        _react(l);
        l = _beatLog(1);
        l.topic0 = 1;
        _react(l);
        assertEq(sys.callbackCount(), 0);
    }

    function test_Flicker_RefusedCallbackDoesNotRevert() public {
        sys.setFailCallback(true);
        vm.expectEmit(true, false, false, true, address(flicker));
        emit ForwardFailed(2, 902);
        _react(_beatLog(2));
        assertEq(flicker.forwarded(), 0);
    }

    function test_Flicker_IgnoresBeatsUntilLanternSet() public {
        Flicker f = new Flicker(BASE, address(beacon), 100_000);
        vm.prank(SYS);
        f.react(_beatLog(1));
        assertEq(sys.callbackCount(), 0);
    }

    function test_Flicker_SetLanternOwnerOnlyOnce() public {
        Flicker f = new Flicker(BASE, address(beacon), 100_000);
        vm.prank(stranger);
        vm.expectRevert(Flicker.NotOwner.selector);
        f.setLantern(address(lantern));
        vm.expectRevert(Flicker.ZeroAddress.selector);
        f.setLantern(address(0));
        f.setLantern(address(lantern));
        vm.expectRevert(Flicker.LanternAlreadySet.selector);
        f.setLantern(stranger);
    }

    function test_Flicker_ReactOnlySystem() public {
        vm.prank(stranger);
        vm.expectRevert(abi.encodeWithSelector(AbstractPayer.NotAuthorized.selector, stranger, SYS));
        flicker.react(_beatLog(1));
    }

    function test_Flicker_CoverDebtByAnyone() public {
        sys.setDebt(address(flicker), 0.04 ether);
        vm.prank(stranger);
        flicker.coverDebt();
        assertEq(sys.debt(address(flicker)), 0);
        assertEq(address(flicker).balance, 0.06 ether);
    }

    // ------------------------------------------------------------ Lantern

    function test_Lantern_LitFromFlickerViaProxy() public {
        vm.expectEmit(true, false, false, true, address(lantern));
        emit Lit(3, 903, block.timestamp);
        vm.prank(address(proxy));
        lantern.lit(address(flicker), 3, 903);
        assertEq(lantern.lits(), 1);
        assertEq(lantern.lastBeat(), 3);
    }

    function test_Lantern_RejectsOtherCallersAndSenders() public {
        vm.prank(stranger);
        vm.expectRevert(abi.encodeWithSelector(AbstractPayer.NotAuthorized.selector, stranger, address(proxy)));
        lantern.lit(address(flicker), 1, 1);
        vm.prank(address(proxy));
        vm.expectRevert(abi.encodeWithSelector(AbstractCallback.CallbackNotAuthorized.selector, stranger, flicker));
        lantern.lit(stranger, 1, 1);
    }

    /// @dev The whole demo loop: a beat becomes a Flicker callback whose payload, delivered by the proxy with the
    ///      sender filled in, lights the lantern.
    function test_DemoLoop_BeatToLit() public {
        vm.recordLogs();
        beacon.poke();
        uint256 n = beacon.beats();
        _react(_beatLog(n));
        bytes memory payload = sys.callbackAt(0).payload;
        // The proxy overwrites the first argument with the sending reactive contract.
        assembly {
            mstore(add(payload, 36), sload(flicker.slot))
        }
        vm.prank(address(proxy));
        (bool ok,) = address(lantern).call(payload);
        assertTrue(ok);
        assertEq(lantern.lastBeat(), n);
    }

    function test_Constructors_RejectZeroAddresses() public {
        vm.expectRevert(Flicker.ZeroAddress.selector);
        new Flicker(BASE, address(0), 1);
        vm.expectRevert(Lantern.ZeroAddress.selector);
        new Lantern(address(0), address(flicker));
        vm.expectRevert(Lantern.ZeroAddress.selector);
        new Lantern(address(proxy), address(0));
    }
}
