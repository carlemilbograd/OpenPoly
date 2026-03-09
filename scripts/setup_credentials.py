#!/usr/bin/env python3
"""
Setup / derive Polymarket API credentials from private key.
Run once to generate your API key, secret, and passphrase.
"""
import os
import sys
from pathlib import Path

# Load .env from skill directory
skill_dir = Path(__file__).parent.parent
dotenv_path = skill_dir / ".env"

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path)
except ImportError:
    pass  # dotenv optional, env vars may already be set

try:
    from py_clob_client.client import ClobClient
except ImportError:
    print("Installing py-clob-client...")
    os.system("pip install py-clob-client python-dotenv --quiet --break-system-packages")
    from py_clob_client.client import ClobClient

HOST = "https://clob.polymarket.com"
CHAIN_ID = 137

def main():
    private_key = os.getenv("POLYMARKET_PRIVATE_KEY")
    funder = os.getenv("POLYMARKET_FUNDER_ADDRESS")
    sig_type = int(os.getenv("POLYMARKET_SIGNATURE_TYPE", "0"))

    if not private_key:
        print("ERROR: POLYMARKET_PRIVATE_KEY not set.")
        print(f"Add it to {dotenv_path} or export as environment variable.")
        print("\nFormat of .env file:")
        print("POLYMARKET_PRIVATE_KEY=0xYOUR_PRIVATE_KEY")
        print("POLYMARKET_FUNDER_ADDRESS=0xYOUR_WALLET_ADDRESS  # required for types 1 and 2")
        print("POLYMARKET_SIGNATURE_TYPE=0  # 0=MetaMask/EOA  1=POLY_PROXY(Magic/email)  2=GNOSIS_SAFE(most common)")
        sys.exit(1)

    kwargs = dict(host=HOST, key=private_key, chain_id=CHAIN_ID)
    if funder:
        kwargs["funder"] = funder
        kwargs["signature_type"] = sig_type

    client = ClobClient(**kwargs)

    print("Deriving API credentials...")
    creds = client.create_or_derive_api_creds()

    # Mask private key in output
    masked_key = private_key[:6] + "****" + private_key[-4:]
    print(f"\n✅ Credentials derived for key: {masked_key}")
    print(f"   API Key:    {creds.api_key}")
    print(f"   Secret:     {creds.api_secret[:8]}...{creds.api_secret[-4:]}")
    print(f"   Passphrase: {creds.api_passphrase[:4]}...{creds.api_passphrase[-4:]}")

    # Write to .env
    env_content = dotenv_path.read_text() if dotenv_path.exists() else ""
    updates = {
        "POLYMARKET_API_KEY": creds.api_key,
        "POLYMARKET_API_SECRET": creds.api_secret,
        "POLYMARKET_API_PASSPHRASE": creds.api_passphrase,
    }
    for k, v in updates.items():
        if k in env_content:
            import re
            env_content = re.sub(rf"^{k}=.*$", f"{k}={v}", env_content, flags=re.MULTILINE)
        else:
            env_content += f"\n{k}={v}"
    dotenv_path.write_text(env_content.strip() + "\n")
    print(f"\n💾 Credentials saved to {dotenv_path}")

if __name__ == "__main__":
    main()
