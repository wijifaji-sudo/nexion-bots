import asyncio
import time
from typing import Dict, Optional

import aiohttp

from config import SOLANA_RPC_URL, ETH_RPC_URL, BSC_RPC_URL


class BalanceService:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.cache: Dict[str, dict] = {}
        self.cache_ttl = 15
        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    def _cache_key(self, chain: str, address: str) -> str:
        return f"{chain}:{address}"

    async def get_balance(self, chain: str, address: str) -> float:
        key = self._cache_key(chain, address)
        now = time.time()
        if key in self.cache and now - self.cache[key]["time"] < self.cache_ttl:
            return self.cache[key]["balance"]

        balance = 0.0
        if chain == "solana":
            balance = await self._get_solana_balance(address)
        elif chain in ("ethereum", "bsc"):
            balance = await self._get_evm_balance(chain, address)

        self.cache[key] = {"balance": balance, "time": now}
        return balance

    async def _get_solana_balance(self, address: str) -> float:
        session = await self._get_session()
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [address],
        }
        try:
            async with session.post(
                SOLANA_RPC_URL, json=payload, timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    lamports = data.get("result", {}).get("value", 0)
                    return lamports / 1e9
        except Exception:
            pass
        return 0.0

    async def _get_evm_balance(self, chain: str, address: str) -> float:
        session = await self._get_session()
        rpc_url = ETH_RPC_URL if chain == "ethereum" else BSC_RPC_URL
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_getBalance",
            "params": [address, "latest"],
        }
        try:
            async with session.post(
                rpc_url, json=payload, timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    hex_balance = data.get("result", "0x0")
                    wei = int(hex_balance, 16)
                    return wei / 1e18
        except Exception:
            pass
        return 0.0

    async def get_wallet_summary(self, wallets: dict) -> Dict[str, dict]:
        result = {}
        tasks = []
        chain_list = []

        for chain, info in wallets.items():
            address = info.get("address")
            if address:
                tasks.append(self.get_balance(chain, address))
                chain_list.append(chain)

        if tasks:
            balances = await asyncio.gather(*tasks, return_exceptions=True)
            for chain, bal in zip(chain_list, balances):
                result[chain] = {
                    "balance": bal if isinstance(bal, (int, float)) else 0.0,
                }

        return result

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


balance_service = BalanceService()