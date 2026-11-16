// SPDX-License-Identifier: MIT
pragma solidity 0.8.29;

import {AbstractReactive} from "reactive-lib/base/AbstractReactive.sol";
import {ISystemContract} from "reactive-lib/interfaces/ISystemContract.sol";

/// @title Flicker
/// @notice Demo reactive contract on Reactive Lasna. Each `Beat` from `Beacon` becomes a callback to
///         `Lantern.lit()`. It is funded with very little on purpose, so the network blacklists it after a few beats
///         and `PelitaKeeper` has something to relight.
/// @dev `react()` returns early for any log it does not handle; a reverted reactive transaction is still billed.
contract Flicker is AbstractReactive {
    uint256 public constant TOPIC_BEAT = uint256(keccak256("Beat(uint256,uint256)"));

    uint256 public immutable beaconChainId;
    address public immutable beacon;
    uint64 public immutable callbackGas;
    address public immutable owner;
    /// @notice Set once after the lantern exists (it needs this contract's address first). Unset = beats are ignored.
    address public lantern;

    /// @notice Beats forwarded to the lantern.
    uint256 public forwarded;

    event Forwarded(uint256 indexed n, uint256 originBlock);
    event ForwardFailed(uint256 indexed n, uint256 originBlock);
    event LanternSet(address lantern);

    error ZeroAddress();
    error NotOwner();
    error LanternAlreadySet();

    constructor(uint256 beaconChainId_, address beacon_, uint64 callbackGas_) payable {
        if (beacon_ == address(0)) revert ZeroAddress();
        owner = msg.sender;
        beaconChainId = beaconChainId_;
        beacon = beacon_;
        callbackGas = callbackGas_;
        SYSTEM.subscribe(beaconChainId_, beacon_, TOPIC_BEAT, REACTIVE_IGNORE, REACTIVE_IGNORE, REACTIVE_IGNORE);
    }

    /// @notice Points the flicker at its lantern. Owner only, once.
    function setLantern(address lantern_) external {
        if (msg.sender != owner) revert NotOwner();
        if (lantern != address(0)) revert LanternAlreadySet();
        if (lantern_ == address(0)) revert ZeroAddress();
        lantern = lantern_;
        emit LanternSet(lantern_);
    }

    function react(LogRecord calldata log) external onlySystem {
        if (log.chainId != beaconChainId || log.contractAddress != beacon || log.topic0 != TOPIC_BEAT) return;
        address to = lantern;
        if (to == address(0)) return;
        uint256 n = log.topic1;
        bytes memory payload = abi.encodeWithSignature("lit(address,uint256,uint256)", address(0), n, log.blockNumber);
        ISystemContract.CallbackConfiguration_V_1_0 memory cfg = ISystemContract.CallbackConfiguration_V_1_0({
            chainId: beaconChainId, recipient: to, gasLimit: callbackGas, payload: payload
        });
        try SYSTEM.requestCallbackV_1_0(cfg) {
            forwarded++;
            emit Forwarded(n, log.blockNumber);
        } catch {
            emit ForwardFailed(n, log.blockNumber);
        }
    }

    /// @notice Pays this contract's own debt to the system contract. Anyone may call it.
    function coverDebt() external {
        _coverDebt();
    }
}
