// SPDX-License-Identifier: MIT
pragma solidity 0.8.29;

import {Test} from "forge-std/Test.sol";
import {IBiller} from "../../src/IBiller.sol";

/// @notice Read-only fork tests against the Base Sepolia callback proxy. Not part of CI:
///         run with scripts/spike/fork-tests.sh.
contract BaseSepoliaForkTest is Test {
    IBiller internal constant PROXY = IBiller(0x476F44b11F5C942c58f4c8E3d0300E5710743585);

    address internal stranger = makeAddr("stranger");
    address internal nobody = makeAddr("never-deployed");

    function setUp() public {
        vm.createSelectFork(vm.envString("PELITA_FORK_RPC_BASE"));
    }

    function test_Fork_ProxyAnswersDebtAndReserves() public view {
        assertEq(PROXY.debt(nobody), 0);
        assertEq(PROXY.reserves(nobody), 0);
    }

    function test_Fork_ProxyDepositToCreditsReserves() public {
        vm.deal(stranger, 0.001 ether);
        vm.prank(stranger);
        PROXY.depositTo{value: 0.001 ether}(nobody);
        assertEq(PROXY.reserves(nobody), 0.001 ether, "deposit with no debt lands in reserves");
    }
}
