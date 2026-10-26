// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @title PulseOS audit commitment registry (ADR-027, ADR-035)
/// @notice Write-restricted registry of opaque 32-byte Merkle batch commitments.
///
/// What is stored is `C = keccak256(0x02 ‖ uint8 v ‖ uint64 n ‖ uint32 c ‖ root)` (ADR-027
/// decision 5) and nothing else: no PHI, patient or Health IDs, event ids, event types,
/// per-event digests, leaf hashes or Merkle roots ever reach this contract (decision 12).
/// The sender address and block time are public and unavoidable.
///
/// A commitment is recorded once. A second submission of the same value reverts with
/// `AlreadyAnchored`; the off-chain submitter checks `anchoredBlock` first and treats an
/// existing record as success (ADR-027 decision 11), so retries are safe.
contract AuditCommitmentRegistry {
    /// The only account allowed to record commitments. Fixed at deployment: rotating it
    /// means deploying a new registry, which keeps the trust story trivial to audit.
    address public immutable anchorer;

    /// commitment => block number in which it was recorded (0 = never recorded).
    mapping(bytes32 => uint256) private _anchoredBlock;

    event CommitmentAnchored(bytes32 indexed commitment);

    error NotAnchorer();
    error ZeroCommitment();
    error AlreadyAnchored(bytes32 commitment);
    error ZeroAnchorer();

    constructor(address anchorer_) {
        if (anchorer_ == address(0)) revert ZeroAnchorer();
        anchorer = anchorer_;
    }

    /// @notice Record one batch commitment. Only `anchorer` may call.
    function anchor(bytes32 commitment) external {
        if (msg.sender != anchorer) revert NotAnchorer();
        if (commitment == bytes32(0)) revert ZeroCommitment();
        if (_anchoredBlock[commitment] != 0) revert AlreadyAnchored(commitment);
        _anchoredBlock[commitment] = block.number;
        emit CommitmentAnchored(commitment);
    }

    /// @notice Block number in which `commitment` was recorded, or 0 if it never was.
    function anchoredBlock(bytes32 commitment) external view returns (uint256) {
        return _anchoredBlock[commitment];
    }

    /// @notice ADR-027 decision 5, for independent recomputation by anyone. Packed, never
    /// `abi.encode` (which pads).
    function computeCommitment(uint8 protocolVersion, uint64 batchNumber, uint32 leafCount, bytes32 root)
        external
        pure
        returns (bytes32)
    {
        return keccak256(abi.encodePacked(bytes1(0x02), protocolVersion, batchNumber, leafCount, root));
    }
}
