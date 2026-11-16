// SPDX-License-Identifier: MIT
pragma solidity 0.8.29;

import {Test} from "forge-std/Test.sol";
import {IBiller} from "../src/IBiller.sol";

/// @notice The interface must match the selectors measured on the live system contract and callback proxies.
contract IBillerTest is Test {
    function test_DebtSelectorMatchesSystemContract() public pure {
        assertEq(IBiller.debt.selector, bytes4(0x9b6c56ec));
    }

    function test_ReservesSelectorMatchesSystemContract() public pure {
        assertEq(IBiller.reserves.selector, bytes4(0xd66bd524));
    }

    function test_DepositToSelectorMatchesSystemContract() public pure {
        assertEq(IBiller.depositTo.selector, bytes4(0xb760faf9));
    }
}
