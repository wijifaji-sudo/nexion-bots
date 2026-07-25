import json
import os
import hashlib
import secrets
import struct
import tempfile
import threading
from pathlib import Path
from typing import Optional

import base58
import nacl.signing
import nacl.encoding
from Crypto.Hash import keccak

from config import USER_DATA_DIR

_locks = {}
_locks_lock = threading.Lock()


def _get_lock(user_id: int) -> threading.Lock:
    with _locks_lock:
        if user_id not in _locks:
            _locks[user_id] = threading.Lock()
        return _locks[user_id]


def get_user_file(user_id: int) -> Path:
    return Path(USER_DATA_DIR) / f"{user_id}.json"


def load_user_data(user_id: int) -> dict:
    lock = _get_lock(user_id)
    with lock:
        path = get_user_file(user_id)
        if path.exists():
            try:
                with open(path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {
            "user_id": user_id,
            "wallets": {},
            "active_wallet": None,
            "settings": {
                "slippage": 10,
                "priority_fee_sol": 0.001,
                "auto_buy": False,
                "auto_sell": False,
                "stop_loss": 20,
                "take_profit": 100,
                "buy_amount_sol": 0.1,
                "buy_amount_eth": 0.01,
                "buy_amount_bnb": 0.1,
                "snipe_mode": "manual",
                "mev_protection": True,
            },
            "watchlist": [],
            "active_snipes": [],
            "trade_history": [],
        }


def save_user_data(user_id: int, data: dict):
    lock = _get_lock(user_id)
    with lock:
        path = get_user_file(user_id)
        dir_name = str(path.parent)
        os.makedirs(dir_name, exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, str(path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


def create_wallet(chain: str) -> Optional[dict]:
    if chain == "solana":
        return _create_solana_wallet()
    elif chain in ("ethereum", "bsc"):
        return _create_evm_wallet()
    return None


def _create_solana_wallet() -> dict:
    seed = secrets.token_bytes(32)
    signing_key = nacl.signing.SigningKey(seed)
    verify_key = signing_key.verify_key

    public_key_bytes = verify_key.encode()
    address = base58.b58encode(public_key_bytes).decode()

    secret_key_bytes = seed + public_key_bytes
    private_key_b58 = base58.b58encode(secret_key_bytes).decode()

    return {
        "address": address,
        "private_key": private_key_b58,
        "chain": "solana",
    }


def _create_evm_wallet() -> dict:
    private_key_bytes = secrets.token_bytes(32)
    private_key_hex = private_key_bytes.hex()

    from ecdsa import SigningKey, SECP256k1
    signing_key = SigningKey.from_string(private_key_bytes, curve=SECP256k1)
    verifying_key = signing_key.get_verifying_key()
    public_key_bytes = verifying_key.to_string()

    k = keccak.new(digest_bits=256)
    k.update(public_key_bytes)
    address_bytes = k.digest()[-20:]
    address = "0x" + address_bytes.hex()

    return {
        "address": address,
        "private_key": private_key_hex,
        "chain": "evm",
    }


def import_wallet_from_key(private_key: str) -> Optional[dict]:
    try:
        pk_clean = private_key.strip()

        if pk_clean.startswith("0x") or (len(pk_clean) == 64 and all(c in "0123456789abcdefABCDEF" for c in pk_clean)):
            pk_hex = pk_clean.replace("0x", "")
            private_key_bytes = bytes.fromhex(pk_hex)
            if len(private_key_bytes) == 32:
                from ecdsa import SigningKey, SECP256k1
                signing_key = SigningKey.from_string(private_key_bytes, curve=SECP256k1)
                verifying_key = signing_key.get_verifying_key()
                public_key_bytes = verifying_key.to_string()

                k = keccak.new(digest_bits=256)
                k.update(public_key_bytes)
                address_bytes = k.digest()[-20:]
                address = "0x" + address_bytes.hex()
                return {
                    "address": address,
                    "private_key": pk_clean,
                    "chain": "evm",
                }
        else:
            seed = base58.b58decode(pk_clean)
            if len(seed) == 64:
                seed_bytes = seed[:32]
                signing_key = nacl.signing.SigningKey(seed_bytes)
                verify_key = signing_key.verify_key
                public_key_bytes = verify_key.encode()
                address = base58.b58encode(public_key_bytes).decode()
                return {
                    "address": address,
                    "private_key": pk_clean,
                    "chain": "solana",
                }
            elif len(seed) == 32:
                signing_key = nacl.signing.SigningKey(seed)
                verify_key = signing_key.verify_key
                public_key_bytes = verify_key.encode()
                address = base58.b58encode(public_key_bytes).decode()
                secret_key = seed + public_key_bytes
                return {
                    "address": address,
                    "private_key": base58.b58encode(secret_key).decode(),
                    "chain": "solana",
                }
    except Exception:
        pass
    return None
