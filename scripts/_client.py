#!/usr/bin/env python3
"""
Shared Polymarket client factory.
Imported by all other scripts.
"""
import os
import sys
from pathlib import Path

# Load .env from skill root
skill_dir = Path(__file__).parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(skill_dir / ".env")
except ImportError:
    pass

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds
except ImportError:
    print("Installing py-clob-client...")
    os.system("pip install py-clob-client python-dotenv requests --quiet --break-system-packages")
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds

HOST = "https://clob.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"
DATA_API = "https://data-api.polymarket.com"
CHAIN_ID = 137


def get_client(authenticated: bool = True) -> ClobClient:
    """Return a ClobClient. authenticated=False gives read-only access."""
    if not authenticated:
        return ClobClient(HOST)

    private_key = os.getenv("POLYMARKET_PRIVATE_KEY")
    if not private_key:
        print("ERROR: POLYMARKET_PRIVATE_KEY not set.")
        print("Run: python scripts/setup_credentials.py")
        sys.exit(1)

    funder = os.getenv("POLYMARKET_FUNDER_ADDRESS")
    sig_type = int(os.getenv("POLYMARKET_SIGNATURE_TYPE", "0"))
    api_key = os.getenv("POLYMARKET_API_KEY")
    api_secret = os.getenv("POLYMARKET_API_SECRET")
    api_passphrase = os.getenv("POLYMARKET_API_PASSPHRASE")

    kwargs = dict(host=HOST, key=private_key, chain_id=CHAIN_ID)
    # sig_type: 0=EOA/MetaMask, 1=POLY_PROXY (Magic/email), 2=GNOSIS_SAFE (most common for web signups)
    if funder:
        kwargs["funder"] = funder
        kwargs["signature_type"] = sig_type
    elif sig_type in (1, 2):
        print("WARNING: POLYMARKET_SIGNATURE_TYPE is set but POLYMARKET_FUNDER_ADDRESS is missing.")
        print("Set POLYMARKET_FUNDER_ADDRESS to the wallet address shown on polymarket.com")
        sys.exit(1)

    client = ClobClient(**kwargs)

    if api_key and api_secret and api_passphrase:
        creds = ApiCreds(
            api_key=api_key,
            api_secret=api_secret,
            api_passphrase=api_passphrase,
        )
        client.set_api_creds(creds)
    else:
        # Derive fresh credentials
        client.set_api_creds(client.create_or_derive_api_creds())

    return client
