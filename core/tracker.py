import aiohttp
from config import SOLANA_RPC_URL, ETH_RPC_URL, BSC_RPC_URL


class WhaleTracker:
    def __init__(self):
        self.tracked_addresses: dict[str, list[dict]] = {
            "solana": [],
            "ethereum": [],
            "bsc": [],
        }
        self.callbacks: list = []
        self.session: aiohttp.ClientSession | None = None

    async def start(self):
        self.session = aiohttp.ClientSession()

    async def stop(self):
        if self.session:
            await self.session.close()

    def add_address(self, chain: str, address: str, label: str = ""):
        self.tracked_addresses[chain].append({
            "address": address,
            "label": label,
            "last_balance": 0,
        })

    def remove_address(self, chain: str, address: str):
        self.tracked_addresses[chain] = [
            a for a in self.tracked_addresses[chain]
            if a["address"] != address
        ]

    def on_transfer(self, callback):
        self.callbacks.append(callback)

    async def check_solana_whales(self):
        from config import WHALE_THRESHOLD_SOL

        if not self.session:
            return

        for entry in self.tracked_addresses.get("solana", []):
            try:
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getBalance",
                    "params": [entry["address"]],
                }
                async with self.session.post(SOLANA_RPC_URL, json=payload) as resp:
                    data = await resp.json()
                    if "result" in data:
                        balance = data["result"]["value"] / 1e9
                        if entry["last_balance"] > 0:
                            diff = balance - entry["last_balance"]
                            if abs(diff) >= WHALE_THRESHOLD_SOL:
                                for cb in self.callbacks:
                                    await cb({
                                        "chain": "solana",
                                        "address": entry["address"],
                                        "label": entry["label"],
                                        "balance_change": diff,
                                        "new_balance": balance,
                                    })
                        entry["last_balance"] = balance
            except Exception:
                pass

    async def check_evm_whales(self, chain: str):
        from config import WHALE_THRESHOLD_ETH, WHALE_THRESHOLD_BNB

        threshold = WHALE_THRESHOLD_ETH if chain == "ethereum" else WHALE_THRESHOLD_BNB
        rpc_url = ETH_RPC_URL if chain == "ethereum" else BSC_RPC_URL

        if not self.session:
            return

        for entry in self.tracked_addresses.get(chain, []):
            try:
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "eth_getBalance",
                    "params": [entry["address"], "latest"],
                }
                async with self.session.post(rpc_url, json=payload) as resp:
                    data = await resp.json()
                    if "result" in data:
                        balance = int(data["result"], 16) / 1e18
                        if entry["last_balance"] > 0:
                            diff = balance - entry["last_balance"]
                            if abs(diff) >= threshold:
                                for cb in self.callbacks:
                                    await cb({
                                        "chain": chain,
                                        "address": entry["address"],
                                        "label": entry["label"],
                                        "balance_change": diff,
                                        "new_balance": balance,
                                    })
                        entry["last_balance"] = balance
            except Exception:
                pass

    async def run(self, interval: int = 60):
        while True:
            await self.check_solana_whales()
            await self.check_evm_whales("ethereum")
            await self.check_evm_whales("bsc")
            import asyncio
            await asyncio.sleep(interval)
