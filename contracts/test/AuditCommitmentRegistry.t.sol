// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {AuditCommitmentRegistry} from "../src/AuditCommitmentRegistry.sol";

/// The few Foundry cheatcodes these tests use, declared locally so the repository vendors
/// no library (forge-std is not needed for this surface).
interface Vm {
    function prank(address sender) external;
    function expectRevert(bytes calldata revertData) external;
    function expectEmit(bool checkTopic1, bool checkTopic2, bool checkTopic3, bool checkData, address emitter) external;
    function roll(uint256 newHeight) external;
}

contract AuditCommitmentRegistryTest {
    Vm private constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));

    event CommitmentAnchored(bytes32 indexed commitment);

    address private constant ANCHORER = address(0xA11CE);
    address private constant STRANGER = address(0xB0B);

    // ADR-027 decision 5 pinned vectors, built on merkle.py's pinned roots.
    bytes32 private constant ROOT_5 = 0x9649d2b300d317f168dd1ac9b6c8db26888dc5cb4d28bd394e22fa75d0cb1952;
    bytes32 private constant ROOT_1 = 0x5f61df1468962c8107c77ae5f01bbd92c363c87a057eba326bd87ca93188e313;
    bytes32 private constant C_1_1_5 = 0x7d2d9dd7205f9adb892bd361857652127df7e954f3132228e7724aeb53476c36;
    bytes32 private constant C_1_2_1 = 0xdcf485fefd095822e3191e95048dfe944a8dcdc7e0412397a9fb1c53af8caa4c;

    AuditCommitmentRegistry private registry;

    function setUp() public {
        registry = new AuditCommitmentRegistry(ANCHORER);
    }

    function _assertEq(uint256 a, uint256 b, string memory message) private pure {
        require(a == b, message);
    }

    function test_commitmentReproducesPinnedVectors() public view {
        require(registry.computeCommitment(1, 1, 5, ROOT_5) == C_1_1_5, "vector (1,1,5)");
        require(registry.computeCommitment(1, 2, 1, ROOT_1) == C_1_2_1, "vector (1,2,1)");
    }

    function test_anchorerIsFixed() public view {
        require(registry.anchorer() == ANCHORER, "anchorer");
    }

    function test_unrecordedCommitmentReadsZero() public view {
        _assertEq(registry.anchoredBlock(C_1_1_5), 0, "unrecorded");
    }

    function test_anchorRecordsBlockAndEmits() public {
        vm.roll(1234);
        vm.expectEmit(true, false, false, true, address(registry));
        emit CommitmentAnchored(C_1_1_5);
        vm.prank(ANCHORER);
        registry.anchor(C_1_1_5);
        _assertEq(registry.anchoredBlock(C_1_1_5), 1234, "recorded block");
        _assertEq(registry.anchoredBlock(C_1_2_1), 0, "other commitment untouched");
    }

    function test_unauthorizedCallerReverts() public {
        vm.prank(STRANGER);
        vm.expectRevert(abi.encodeWithSelector(AuditCommitmentRegistry.NotAnchorer.selector));
        registry.anchor(C_1_1_5);
        _assertEq(registry.anchoredBlock(C_1_1_5), 0, "nothing recorded");
    }

    function test_duplicateSubmissionReverts() public {
        vm.roll(10);
        vm.prank(ANCHORER);
        registry.anchor(C_1_1_5);
        vm.roll(11);
        vm.prank(ANCHORER);
        vm.expectRevert(abi.encodeWithSelector(AuditCommitmentRegistry.AlreadyAnchored.selector, C_1_1_5));
        registry.anchor(C_1_1_5);
        _assertEq(registry.anchoredBlock(C_1_1_5), 10, "first record kept");
    }

    function test_distinctCommitmentsAreIndependent() public {
        vm.roll(20);
        vm.prank(ANCHORER);
        registry.anchor(C_1_1_5);
        vm.roll(21);
        vm.prank(ANCHORER);
        registry.anchor(C_1_2_1);
        _assertEq(registry.anchoredBlock(C_1_1_5), 20, "first");
        _assertEq(registry.anchoredBlock(C_1_2_1), 21, "second");
    }

    function test_zeroCommitmentReverts() public {
        vm.prank(ANCHORER);
        vm.expectRevert(abi.encodeWithSelector(AuditCommitmentRegistry.ZeroCommitment.selector));
        registry.anchor(bytes32(0));
    }

    function test_zeroAnchorerRejectedAtDeployment() public {
        vm.expectRevert(abi.encodeWithSelector(AuditCommitmentRegistry.ZeroAnchorer.selector));
        new AuditCommitmentRegistry(address(0));
    }

    function testFuzz_onlyAnchorerCanRecord(address caller, bytes32 commitment) public {
        if (caller == ANCHORER || commitment == bytes32(0)) return;
        vm.prank(caller);
        vm.expectRevert(abi.encodeWithSelector(AuditCommitmentRegistry.NotAnchorer.selector));
        registry.anchor(commitment);
    }
}
