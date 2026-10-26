# contracts/

`src/AuditCommitmentRegistry.sol` — the write-restricted **commitment registry** of ADR-027 /
ADR-035. It stores one opaque 32-byte commitment `C` per sealed Merkle batch, the block it was
recorded in, and emits `CommitmentAnchored(bytes32 indexed C)`. Nothing else is ever on-chain:
no PHI, patient or Health IDs, event ids, digests, leaves or Merkle roots.

Toolchain: [Foundry](https://getfoundry.sh) (`brew install foundry`). No libraries are vendored;
the tests declare the few cheatcodes they use.

```bash
cd contracts
forge build          # artifacts in out/ (git-ignored)
forge test -vv       # 10 tests: pinned ADR-027 vectors, access control, duplicates, fuzz
```

## Local end-to-end (real EVM, no public network)

```bash
anvil --host 127.0.0.1 --port 8545 &            # local chain, id 31337
# From backend/: the opt-in test deploys a fresh registry and runs submit → confirm → verify.
PULSEOS_TEST_EVM_RPC_URL=http://127.0.0.1:8545 \
PULSEOS_TEST_EVM_PRIVATE_KEY="$(cast wallet private-key --mnemonic 'test test test test test test test test test test test junk' --mnemonic-index 0)" \
  .venv/bin/pytest tests/test_chain_anchoring_evm.py
```

## Public testnet (Polygon Amoy) — not yet done

Requires: an Amoy RPC endpoint, a **dedicated testnet-only** deployer/anchorer key funded with
test POL, and Product Owner acceptance of ADR-035. Never use a key that holds real funds; never
target a mainnet (the backend refuses any chain id other than 80002, 11155111, 31337).

```bash
# 1. Deploy (keystore or --interactive keeps the key off the command line and shell history).
forge create src/AuditCommitmentRegistry.sol:AuditCommitmentRegistry \
  --rpc-url "$AMOY_RPC_URL" --account pulseos-anchorer --broadcast \
  --constructor-args <anchorer-address>

# Optional: Verify on Polygonscan Amoy
forge verify-contract <contract-address> src/AuditCommitmentRegistry.sol:AuditCommitmentRegistry \
  --chain-id 80002 --verifier-url https://api-amoy.polygonscan.com/api \
  --etherscan-api-key "$POLYGONSCAN_API_KEY" \
  --constructor-args $(cast abi-encode "constructor(address)" <anchorer-address>)

# 2. Configure the backend (backend/.env — never commit): PULSEOS_CHAIN_RPC_URL, PULSEOS_CHAIN_ID=80002,
#    PULSEOS_CHAIN_CONTRACT_ADDRESS, PULSEOS_CHAIN_EXPLORER_BASE_URL=https://amoy.polygonscan.com,
#    PULSEOS_CHAIN_ANCHORER_PRIVATE_KEY (operator machine only),
#    PULSEOS_CHAIN_MIN_PRIORITY_FEE_PER_GAS=30000000000 (30 Gwei tip floor for Amoy validators).

# 3. Anchor a sealed batch and confirm it (guarded like `seal`).
python scripts/audit_integrity.py anchor --batch-number 1 --confirm-env <env>
python scripts/audit_integrity.py anchor-refresh --batch-number 1 --confirm-env <env>
python scripts/audit_integrity.py verify-chain --batch-number 1      # read-only

# 4. Independent check with no PulseOS code: C recomputed by the contract from the batch's
#    public fields must be recorded on-chain.
cast call <registry> "computeCommitment(uint8,uint64,uint32,bytes32)(bytes32)" 1 1 <leafCount> 0x<root> --rpc-url "$AMOY_RPC_URL"
cast call <registry> "anchoredBlock(bytes32)(uint256)" 0x<commitment> --rpc-url "$AMOY_RPC_URL"   # non-zero = recorded
```
