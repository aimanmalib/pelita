// SPDX-License-Identifier: MIT
pragma solidity 0.8.29;

import {IBiller} from "../../src/IBiller.sol";

/// @notice Test double for the Lasna system contract and destination callback proxies: debt, reserves and deposits.
contract MockBiller is IBiller {
    mapping(address => uint256) internal _debt;
    mapping(address => uint256) public override reserves;
    mapping(address => uint256) public deposited;
    bool public failDeposit;
    bool public failDebt;
    uint256 public depositCalls;

    function setDebt(address c, uint256 amount) external {
        _debt[c] = amount;
    }

    function setFailDeposit(bool v) external {
        failDeposit = v;
    }

    function setFailDebt(bool v) external {
        failDebt = v;
    }

    function debt(address c) external view override returns (uint256) {
        if (failDebt) revert("debt read failed");
        return _debt[c];
    }

    function depositTo(address c) external payable override {
        if (failDeposit) revert("deposit failed");
        depositCalls++;
        deposited[c] += msg.value;
        uint256 settle = msg.value < _debt[c] ? msg.value : _debt[c];
        _debt[c] -= settle;
        reserves[c] += msg.value - settle;
    }

    /// @dev Plain payments settle the sender's own debt, as `coverDebt()` expects.
    receive() external payable {
        uint256 settle = msg.value < _debt[msg.sender] ? msg.value : _debt[msg.sender];
        _debt[msg.sender] -= settle;
    }
}

/// @notice MockBiller plus the subscription and callback calls of the Reactive system contract. Installed at the
///         system address with `vm.etch`; it records every call so tests can compare exact arguments.
contract MockSystem is MockBiller {
    struct Sub {
        uint256 chainId;
        address contract_;
        uint256 topic0;
        uint256 topic1;
        uint256 topic2;
        uint256 topic3;
    }

    struct CallbackConfiguration_V_1_0 {
        uint256 chainId;
        address recipient;
        uint64 gasLimit;
        bytes payload;
    }

    Sub[] public subscribed;
    Sub[] public unsubscribed;
    CallbackConfiguration_V_1_0[] internal _callbacks;
    bool public failCallback;

    function setFailCallback(bool v) external {
        failCallback = v;
    }

    function subscribe(uint256 a, address b, uint256 c, uint256 d, uint256 e, uint256 f) external {
        subscribed.push(Sub(a, b, c, d, e, f));
    }

    function unsubscribe(uint256 a, address b, uint256 c, uint256 d, uint256 e, uint256 f) external {
        unsubscribed.push(Sub(a, b, c, d, e, f));
    }

    function requestCallbackV_1_0(CallbackConfiguration_V_1_0 memory cfg) external {
        if (failCallback) revert("callback refused");
        _callbacks.push(cfg);
    }

    function subscribedCount() external view returns (uint256) {
        return subscribed.length;
    }

    function unsubscribedCount() external view returns (uint256) {
        return unsubscribed.length;
    }

    function callbackCount() external view returns (uint256) {
        return _callbacks.length;
    }

    function callbackAt(uint256 i) external view returns (CallbackConfiguration_V_1_0 memory) {
        return _callbacks[i];
    }
}
