#!/usr/bin/env python3
"""
Redeem resolved/winning Polymarket positions for USDC.

After a market resolves, your winning shares must be redeemed on-chain to
receive USDC. This script finds all redeemable positions and submits the
on-chain transactions.

Requires: web3  (pip install web3)

Usage:
  python redeem.py --dry-run        # show what would be redeemed (no tx)
  python redeem.py                  # redeem all redeemable positions
  python redeem.py --market-id CONDITION_ID  # redeem one specific market
"""
import sys, os, json, argparse, requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _client import get_client, GAMMA_API, DATA_API

# ── On-chain constants (Polygon mainnet) ──────────────────────────────────────
POLYGON_RPC = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")
PARENT_COLLECTION_ID = "0x" + "00" * 32   # top-level (no parent market)

# Minimal ABI — only what we need
CTF_ABI = [
    {
        "name": "redeemPositions",
        "type": "function",
        "inputs": [
            {"name": "collateralToken", "type": "address"},
            {"name": "parentCollectionId", "type": "bytes32"},
            {"name": "conditionId", "type": "bytes32"},
            {"name": "indexSets", "type": "uint256[]"},
        ],
        "outputs": [],
        "stateMutability": "nonpayable",
    },
    {
        "name": "balanceOf",
        "type": "function",
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "id", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
    },
]

ERC20_ABI = [
    {
        "name": "balanceOf",
        "type": "function",
        "inputs": [{"name": "owner", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
    }
]


def ensure_web3():
    try:
        from web3 import Web3
        return Web3
    except ImportError:
        print("Installing web3...")
        os.system("pip install web3 --quiet --break-system-packages")
        from web3 import Web3
        return Web3


def get_contract_addresses():
    """Get contract addresses from py_clob_client config."""
    try:
        from py_clob_client.config import get_contract_config
        cfg = get_contract_config(137)  # Polygon
        return cfg.conditional_tokens, cfg.collateral
    except Exception:
        # Fallback hardcoded addresses
        return (
            "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045",  # CTF Exchange
            "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",  # USDC.e on Polygon
        )


def fetch_redeemable_positions(address: str) -> list:
    """Fetch positions that can be redeemed (market resolved)."""
    try:
        resp = requests.get(
            f"{DATA_API}/positions",
            params={"user": address, "sizeThreshold": "0.001"},
            timeout=10,
        )
        positions = resp.json() if resp.ok else []
    except Exception as e:
        print(f"Error fetching positions: {e}")
        return []

    redeemable = []
    for pos in positions:
        # Check various field names the API might use
        is_redeemable = (
            pos.get("redeemable")
            or pos.get("resolved")
            or pos.get("market_resolved")
        )
        if not is_redeemable:
            # Double-check via gamma API
            market_id = pos.get("conditionId", pos.get("market", ""))
            if market_id:
                try:
                    r = requests.get(
                        f"{GAMMA_API}/markets",
                        params={"condition_id": market_id},
                        timeout=5,
                    )
                    if r.ok:
                        markets = r.json()
                        if markets and markets[0].get("closed"):
                            is_redeemable = True
                except Exception:
                    pass

        if is_redeemable or pos.get("size", 0) == 0:
            continue

        if is_redeemable:
            redeemable.append(pos)

    return redeemable


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be redeemed without executing")
    parser.add_argument("--market-id", "-m", default="",
                        help="Condition ID of a specific market to redeem")
    parser.add_argument("--gas-price-gwei", type=float, default=100.0,
                        help="Gas price in Gwei (default 100)")
    args = parser.parse_args()

    Web3 = ensure_web3()

    client = get_client(authenticated=True)
    try:
        address = client.get_address()
    except Exception:
        address = os.getenv("POLYMARKET_FUNDER_ADDRESS", "")

    if not address:
        print("ERROR: Could not determine wallet address.")
        sys.exit(1)

    private_key = os.getenv("POLYMARKET_PRIVATE_KEY")
    if not private_key and not args.dry_run:
        print("ERROR: POLYMARKET_PRIVATE_KEY not set.")
        sys.exit(1)

    ctf_address, usdc_address = get_contract_addresses()

    print(f"\n{'='*60}")
    print(f"  POLYMARKET REDEMPTION")
    print(f"  Wallet: {address[:10]}...{address[-6:]}")
    print(f"  CTF Contract: {ctf_address[:10]}...{ctf_address[-6:]}")
    if args.dry_run:
        print(f"  MODE: DRY RUN — no transactions will be sent")
    print(f"{'='*60}")

    # Connect to Polygon
    w3 = Web3(Web3.HTTPProvider(POLYGON_RPC))
    if not w3.is_connected():
        print(f"  ERROR: Cannot connect to Polygon RPC: {POLYGON_RPC}")
        print(f"  Set POLYGON_RPC_URL env var to use a different provider.")
        sys.exit(1)

    print(f"\n  Connected to Polygon (block #{w3.eth.block_number:,})")

    # USDC balance before
    try:
        usdc_contract = w3.eth.contract(
            address=Web3.to_checksum_address(usdc_address), abi=ERC20_ABI
        )
        usdc_before = usdc_contract.functions.balanceOf(
            Web3.to_checksum_address(address)
        ).call() / 1e6
        print(f"  USDC balance (before): ${usdc_before:,.2f}")
    except Exception:
        usdc_before = None

    # Find redeemable positions
    if args.market_id:
        # Manual specification
        positions = [{"conditionId": args.market_id, "outcome": "ALL",
                      "size": "?", "title": args.market_id}]
    else:
        print("\n  Scanning for redeemable positions...")
        positions = fetch_redeemable_positions(address)

    if not positions:
        print("\n  No redeemable positions found.")
        print("  (Markets must be resolved before redemption is possible.)\n")
        return

    print(f"\n  Found {len(positions)} redeemable position(s):\n")

    ctf_contract = w3.eth.contract(
        address=Web3.to_checksum_address(ctf_address), abi=CTF_ABI
    )
    checksum_address = Web3.to_checksum_address(address)
    gas_price = w3.to_wei(args.gas_price_gwei, "gwei")
    nonce = w3.eth.get_transaction_count(checksum_address) if not args.dry_run else 0

    results = []
    for i, pos in enumerate(positions, 1):
        condition_id = pos.get("conditionId", pos.get("conditionID",
                                                        pos.get("market", "")))
        title = pos.get("title", pos.get("market", condition_id[:16] + "..."))[:50]
        size = pos.get("size", "?")
        outcome = pos.get("outcome", "ALL")

        # Pad condition_id to 32 bytes
        if condition_id.startswith("0x"):
            cid_bytes = bytes.fromhex(condition_id[2:].zfill(64))
        else:
            cid_bytes = bytes.fromhex(condition_id.zfill(64))

        # For binary markets: try both indexSets [1] and [2]
        # (contract silently handles tokens you don't have)
        index_sets = [1, 2]

        print(f"  [{i}] {title}")
        print(f"       Outcome: {outcome} | Size: {size} | "
              f"Condition: {condition_id[:12]}...")

        if args.dry_run:
            print(f"       → DRY RUN: would call redeemPositions("
                  f"USDC, 0x00...00, {condition_id[:10]}..., [1,2])\n")
            continue

        try:
            tx = ctf_contract.functions.redeemPositions(
                Web3.to_checksum_address(usdc_address),
                bytes.fromhex("00" * 32),
                cid_bytes,
                index_sets,
            ).build_transaction({
                "from": checksum_address,
                "nonce": nonce,
                "gas": 200_000,
                "gasPrice": gas_price,
                "chainId": 137,
            })

            signed = w3.eth.account.sign_transaction(tx, private_key=private_key)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            status = "✅ SUCCESS" if receipt.status == 1 else "❌ FAILED"
            print(f"       {status}  tx: {tx_hash.hex()[:20]}...")
            results.append({"condition": condition_id, "tx": tx_hash.hex(),
                             "status": receipt.status})
            nonce += 1

        except Exception as e:
            print(f"       ❌ ERROR: {e}")
            results.append({"condition": condition_id, "error": str(e)})

    if not args.dry_run:
        # USDC balance after
        try:
            usdc_after = usdc_contract.functions.balanceOf(
                Web3.to_checksum_address(address)
            ).call() / 1e6
            gained = usdc_after - (usdc_before or 0)
            print(f"\n  USDC balance (after):  ${usdc_after:,.2f}")
            if gained > 0:
                print(f"  USDC received:         +${gained:,.2f}")
        except Exception:
            pass

        success = sum(1 for r in results if r.get("status") == 1)
        print(f"\n  Redeemed {success}/{len(results)} positions successfully.\n")

    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
