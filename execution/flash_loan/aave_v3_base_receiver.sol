// SPDX-License-Identifier: MIT
// E1.80 Iter 7 — Aave V3 flash loan receiver skeleton (Base mainnet).
//
// THIS CONTRACT IS A SKELETON. It is NOT audited, NOT deployed, and the
// arbitrage execution path (`_executeArbRoute`) is intentionally left as a
// revert placeholder so that any accidental deployment fails closed.
//
// Aave V3 Pool (Base): 0xA238Dd80C259a72e81d7e4664a9801593F98d1c5
// Flash loan premium: 9 bps (charged on `flashLoanSimple`).
//
// Reference: https://docs.aave.com/developers/core-contracts/pool#flashloansimple
pragma solidity ^0.8.20;

interface IERC20 {
    function approve(address spender, uint256 amount) external returns (bool);
    function transfer(address to, uint256 amount) external returns (bool);
    function balanceOf(address owner) external view returns (uint256);
}

interface IPool {
    function flashLoanSimple(
        address receiverAddress,
        address asset,
        uint256 amount,
        bytes calldata params,
        uint16 referralCode
    ) external;
}

abstract contract FlashLoanReceiverBase {
    address public immutable POOL;

    constructor(address pool) {
        POOL = pool;
    }

    /// @notice Aave V3 callback. MUST repay `amount + premium` to POOL by end of call.
    function executeOperation(
        address asset,
        uint256 amount,
        uint256 premium,
        address initiator,
        bytes calldata params
    ) external virtual returns (bool);
}

contract ArbyV3FlashReceiver is FlashLoanReceiverBase {
    address public immutable OWNER;
    // Base mainnet Aave V3 Pool.
    address public constant AAVE_V3_BASE_POOL = 0xA238Dd80C259a72e81d7e4664a9801593F98d1c5;

    error NotOwner();
    error NotPool();
    error NotInitiator();
    error ArbRouteNotImplemented();
    error InsufficientRepayBalance();

    constructor() FlashLoanReceiverBase(AAVE_V3_BASE_POOL) {
        OWNER = msg.sender;
    }

    modifier onlyOwner() {
        if (msg.sender != OWNER) revert NotOwner();
        _;
    }

    function executeOperation(
        address asset,
        uint256 amount,
        uint256 premium,
        address initiator,
        bytes calldata params
    ) external override returns (bool) {
        if (msg.sender != POOL) revert NotPool();
        if (initiator != OWNER) revert NotInitiator();

        // Skeleton: reject by default so accidental deployment fails closed.
        // A future PR will replace this revert with the real arb route
        // (decode `params` -> swap on DEX A -> swap on DEX B -> repay).
        _executeArbRoute(asset, amount, params);

        // Approve POOL to pull principal + premium.
        uint256 owed = amount + premium;
        if (IERC20(asset).balanceOf(address(this)) < owed) {
            revert InsufficientRepayBalance();
        }
        IERC20(asset).approve(POOL, owed);
        return true;
    }

    /// @dev Skeleton stub — must be overridden / replaced before deployment.
    function _executeArbRoute(
        address /*asset*/,
        uint256 /*amount*/,
        bytes calldata /*params*/
    ) internal pure {
        revert ArbRouteNotImplemented();
    }

    /// @notice Owner-only entry that initiates a flash loan from POOL.
    function initiateFlashLoan(
        address asset,
        uint256 amount,
        bytes calldata params
    ) external onlyOwner {
        IPool(POOL).flashLoanSimple(address(this), asset, amount, params, 0);
    }

    /// @notice Owner-only sweep (post-arb profits).
    function sweep(address token, address to, uint256 amount) external onlyOwner {
        IERC20(token).transfer(to, amount);
    }
}
