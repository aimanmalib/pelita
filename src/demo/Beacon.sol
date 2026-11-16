// SPDX-License-Identifier: MIT
pragma solidity 0.8.29;

/// @title Beacon
/// @notice Demo heartbeat on a destination chain. Anyone may `poke()` it, at most once per cooldown and a limited
///         number of times per window; every beat is picked up by `Flicker` on Reactive Lasna.
/// @dev Limits use `block.timestamp` because block intervals differ between chains. Values come from config at deploy.
contract Beacon {
    address public owner;
    uint256 public cooldown;
    uint256 public maxBeats;
    uint256 public window;

    /// @notice Total beats so far; the number of the latest beat.
    uint256 public beats;
    uint256 public lastPublicBeat;
    uint256 public windowStart;
    uint256 public windowBeats;

    event Beat(uint256 indexed n, uint256 at);
    event LimitsSet(uint256 cooldown, uint256 maxBeats, uint256 window);

    error NotOwner();
    error TooSoon(uint256 nextAt);
    error WindowFull(uint256 nextAt);
    error BadLimits();

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    constructor(uint256 cooldown_, uint256 maxBeats_, uint256 window_) {
        owner = msg.sender;
        _setLimits(cooldown_, maxBeats_, window_);
    }

    /// @notice Public heartbeat, rate limited.
    function poke() external {
        uint256 nowTs = block.timestamp;
        if (lastPublicBeat != 0 && nowTs < lastPublicBeat + cooldown) revert TooSoon(lastPublicBeat + cooldown);
        if (nowTs >= windowStart + window) {
            windowStart = nowTs;
            windowBeats = 0;
        }
        if (windowBeats >= maxBeats) revert WindowFull(windowStart + window);
        windowBeats++;
        lastPublicBeat = nowTs;
        _beat();
    }

    /// @notice Owner heartbeat without limits, for the measured series.
    function pokeOwner() external onlyOwner {
        _beat();
    }

    /// @notice Seconds until `poke()` is accepted again (0 = now).
    function waitFor() external view returns (uint256) {
        uint256 nowTs = block.timestamp;
        uint256 at;
        if (lastPublicBeat != 0) at = lastPublicBeat + cooldown;
        if (nowTs < windowStart + window && windowBeats >= maxBeats && windowStart + window > at) {
            at = windowStart + window;
        }
        return at > nowTs ? at - nowTs : 0;
    }

    function setLimits(uint256 cooldown_, uint256 maxBeats_, uint256 window_) external onlyOwner {
        _setLimits(cooldown_, maxBeats_, window_);
    }

    function _setLimits(uint256 cooldown_, uint256 maxBeats_, uint256 window_) internal {
        if (maxBeats_ == 0 || window_ == 0) revert BadLimits();
        cooldown = cooldown_;
        maxBeats = maxBeats_;
        window = window_;
        emit LimitsSet(cooldown_, maxBeats_, window_);
    }

    function _beat() internal {
        uint256 n = ++beats;
        emit Beat(n, block.timestamp);
    }
}
