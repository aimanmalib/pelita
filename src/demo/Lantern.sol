// SPDX-License-Identifier: MIT
pragma solidity 0.8.29;

import {AbstractCallback} from "reactive-lib/base/AbstractCallback.sol";
import {IPayable} from "reactive-lib/interfaces/IPayable.sol";

/// @title Lantern
/// @notice Demo callback contract on a destination chain: `Flicker` lights it once per `Beat`. Its proxy reserves are
///         kept small, so it can go dark too.
contract Lantern is AbstractCallback {
    /// @notice Number of times this lantern has been lit.
    uint256 public lits;
    uint256 public lastBeat;

    event Lit(uint256 indexed n, uint256 originBlock, uint256 timestamp);

    error ZeroAddress();

    /// @param proxy The chain's callback proxy.
    /// @param flicker The `Flicker` address on Reactive Lasna, the only accepted callback sender.
    constructor(address proxy, address flicker) payable AbstractCallback(IPayable(payable(proxy)), flicker) {
        if (proxy == address(0) || flicker == address(0)) revert ZeroAddress();
    }

    function lit(address rvm, uint256 n, uint256 originBlock) external onlyServiceProvider onlyCallbackSender(rvm) {
        lits++;
        lastBeat = n;
        emit Lit(n, originBlock, block.timestamp);
    }

    /// @notice Pays this contract's own debt to the callback proxy. Anyone may call it.
    function coverDebt() external {
        _coverDebt();
    }
}
