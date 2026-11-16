// SPDX-License-Identifier: MIT
pragma solidity 0.8.29;

import {Test} from "forge-std/Test.sol";
import {IBiller} from "../../src/IBiller.sol";

/// @notice Read-only fork tests against Reactive Lasna. Not part of CI or the offline gate:
///         run with scripts/spike/fork-tests.sh, which picks a contract that is dark right now.
/// @dev Nothing here is broadcast. `vm.deal` and `vm.prank` only change the local fork.
contract LasnaForkTest is Test {
    IBiller internal constant SYSTEM = IBiller(0x8888888888888888888888888888888888888888);

    event WhitelistContract(address indexed contract_);

    address internal dark;
    address internal stranger = makeAddr("stranger");

    function setUp() public {
        vm.createSelectFork(vm.envString("PELITA_FORK_RPC"));
        dark = vm.envAddress("PELITA_DARK_TARGET");
    }

    function test_Fork_DebtSelectorAnswersOnSystemContract() public view {
        assertGt(SYSTEM.debt(dark), 0, "target must be dark (debt > 0)");
    }

    function test_Fork_ReservesSelectorAnswersOnSystemContract() public view {
        // Any value is fine; the call must not revert.
        SYSTEM.reserves(dark);
    }

    function test_Fork_ThirdPartyDepositSettlesDebt() public {
        uint256 owed = SYSTEM.debt(dark);
        vm.deal(stranger, owed + 1 ether);
        vm.prank(stranger);
        SYSTEM.depositTo{value: owed}(dark);
        assertEq(SYSTEM.debt(dark), 0, "debt settled by a stranger");
    }

    function test_Fork_ThirdPartyDepositFromContractSettlesDebt() public {
        uint256 owed = SYSTEM.debt(dark);
        Payer payer = new Payer();
        vm.deal(address(payer), owed);
        payer.pay(SYSTEM, dark, owed);
        assertEq(SYSTEM.debt(dark), 0, "debt settled by a contract");
    }

    function test_Fork_SettlingDebtEmitsWhitelistContract() public {
        uint256 owed = SYSTEM.debt(dark);
        vm.deal(stranger, owed);
        vm.expectEmit(true, false, false, false, address(SYSTEM));
        emit WhitelistContract(dark);
        vm.prank(stranger);
        SYSTEM.depositTo{value: owed}(dark);
    }

    function test_Fork_SurplusGoesToReserves() public {
        uint256 owed = SYSTEM.debt(dark);
        uint256 before = SYSTEM.reserves(dark);
        vm.deal(stranger, owed + 0.05 ether);
        vm.prank(stranger);
        SYSTEM.depositTo{value: owed + 0.05 ether}(dark);
        assertEq(SYSTEM.debt(dark), 0);
        assertEq(SYSTEM.reserves(dark), before + 0.05 ether, "surplus lands in reserves");
    }

    function test_Fork_OneWeiReducesDebtWithoutSettling() public {
        uint256 owed = SYSTEM.debt(dark);
        vm.deal(stranger, 1);
        vm.prank(stranger);
        SYSTEM.depositTo{value: 1}(dark);
        assertEq(SYSTEM.debt(dark), owed - 1, "one wei lowers the debt by one wei");
    }
}

/// @notice Stand-in for the Keeper: a contract, not an EOA, paying someone else's debt.
contract Payer {
    function pay(IBiller biller, address target, uint256 amount) external {
        biller.depositTo{value: amount}(target);
    }
}
