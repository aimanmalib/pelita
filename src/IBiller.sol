// SPDX-License-Identifier: MIT
pragma solidity 0.8.29;

/// @title IBiller
/// @notice The three calls Pelita needs from a Reactive biller: the system contract on Reactive Lasna
///         and the callback proxy on each destination chain expose the same debt and deposit functions.
interface IBiller {
    /// @notice Outstanding debt of `contract_`. Any value above zero stops the network from serving it.
    function debt(address contract_) external view returns (uint256);

    /// @notice Prepaid reserves of `contract_`, charged before the contract's own balance.
    function reserves(address contract_) external view returns (uint256);

    /// @notice Pays from the caller's funds: settles the debt of `contract_` first, the rest goes to its reserves.
    function depositTo(address contract_) external payable;
}
