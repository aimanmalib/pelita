// SPDX-License-Identifier: MIT
pragma solidity 0.8.29;

import {Test} from "forge-std/Test.sol";
import {IReactive} from "reactive-lib/interfaces/IReactive.sol";
import {PelitaKeeper} from "../src/PelitaKeeper.sol";
import {PelitaTank} from "../src/PelitaTank.sol";
import {MockBiller, MockSystem} from "./mocks/MockBiller.sol";

/// @notice The destination loop end to end: the keeper's callback payload, delivered by the proxy, refuels the ward.
contract KeeperTankTest is Test {
    address payable constant SYS = payable(0x8888888888888888888888888888888888888888);
    uint256 constant LASNA = 5318007;
    uint256 constant BASE = 84532;
    uint256 constant DARK = uint256(keccak256("BlacklistContract(address)"));

    PelitaKeeper keeper;
    PelitaTank tank;
    MockSystem sys;
    MockBiller proxy;
    address lanternWard = makeAddr("lanternWard");

    function setUp() public {
        vm.chainId(LASNA);
        vm.etch(SYS, address(new MockSystem()).code);
        sys = MockSystem(SYS);
        proxy = new MockBiller();
        keeper = new PelitaKeeper{value: 1 ether}(0.3 ether, 3 ether);
        tank = new PelitaTank{value: 0.01 ether}(address(proxy), address(keeper), 0.001 ether, 0.002 ether);
        keeper.setChain(BASE, address(proxy), address(tank), 400_000);
        keeper.protect(BASE, lanternWard, 0.0002 ether, 0.001 ether, 20);
    }

    function _deliver(bytes memory payload) internal returns (bool ok) {
        // The proxy overwrites the first argument (a placeholder) with the sending reactive contract.
        address sender = address(keeper);
        assembly {
            mstore(add(payload, 36), sender)
        }
        vm.prank(address(proxy));
        (ok,) = address(tank).call(payload);
    }

    function test_DarkOnBaseIsRelitThroughTheTank() public {
        proxy.setDebt(lanternWard, 0.0004 ether);
        IReactive.LogRecord memory l;
        l.chainId = BASE;
        l.contractAddress = address(proxy);
        l.topic0 = DARK;
        l.topic1 = uint256(uint160(lanternWard));
        l.blockNumber = 4242;
        vm.prank(SYS);
        keeper.react(l);

        MockSystem.CallbackConfiguration_V_1_0 memory cb = sys.callbackAt(0);
        assertEq(cb.recipient, address(tank));
        assertTrue(_deliver(cb.payload));
        assertEq(proxy.debt(lanternWard), 0);
        assertEq(proxy.deposited(lanternWard), 0.0006 ether);
    }

    function test_PayloadSelectorMatchesTank() public view {
        assertEq(
            bytes4(keccak256("refuel(address,address,uint256,uint256,uint256,uint256)")), PelitaTank.refuel.selector
        );
    }
}
