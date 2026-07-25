import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

import aiohttp

from config import CHAINS, ETH_RPC_URL, BSC_RPC_URL, SOLANA_RPC_URL


@dataclass
class TokenInfo:
    address: str
    name: str
    symbol: str
    chain: str
    decimals: int = 18
    price_usd: float = 0.0
    liquidity: float = 0.0
    market_cap: float = 0.0
    volume_24h: float = 0.0
    price_change_24h: float = 0.0
    holders: int = 0
    created_at: float = 0.0
    is_verified: bool = False
    has_locked_liquidity: bool = False
    top_holder_pct: float = 0.0


@dataclass
class SnipeTarget:
    token_address: str
    chain: str
    buy_amount: float
    slippage: float
    priority_fee: float = 0.0
    auto_sell: bool = False
    stop_loss: float = 20.0
    take_profit: float = 100.0
    max_buy_price: float = 0.0
    mev_protection: bool = True
    status: str = "pending"
    created_at: float = field(default_factory=time.time)
    filled_at: float = 0.0
    fill_price: float = 0.0


class SnipeEngine:
    def __init__(self):
        self.active_snipes: dict[int, list[SnipeTarget]] = {}
        self.price_cache: dict[str, dict] = {}
        self.session: Optional[aiohttp.ClientSession] = None

    async def start(self):
        self.session = aiohttp.ClientSession()

    async def stop(self):
        if self.session:
            await self.session.close()

    async def get_token_info(self, chain: str, address: str) -> Optional[TokenInfo]:
        if chain == "solana":
            return await self._get_solana_token(address)
        elif chain == "ethereum":
            return await self._get_eth_token(address)
        elif chain == "bsc":
            return await self._get_bsc_token(address)
        return None

    async def _get_solana_token(self, address: str) -> Optional[TokenInfo]:
        try:
            async with self.session as session:
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getTokenSupply",
                    "params": [address],
                }
                async with session.post(SOLANA_RPC_URL, json=payload) as resp:
                    data = await resp.json()
                    if "result" in data:
                        supply = int(data["result"]["value"]["amount"])
                        decimals = data["result"]["value"]["decimals"]
                        return TokenInfo(
                            address=address,
                            name="Unknown",
                            symbol="???",
                            chain="solana",
                            decimals=decimals,
                        )
        except Exception:
            pass
        return None

    async def _get_eth_token(self, address: str) -> Optional[TokenInfo]:
        try:
            url = f"https://api.etherscan.io/api?module=token&action=tokeninfo&contractaddresses={address}&apikey={self._get_api_key('eth')}"
            async with self.session as session:
                async with session.get(url) as resp:
                    data = await resp.json()
                    if data.get("result") and len(data["result"]) > 0:
                        t = data["result"][0]
                        return TokenInfo(
                            address=address,
                            name=t.get("tokenName", "Unknown"),
                            symbol=t.get("symbol", "???"),
                            chain="ethereum",
                            decimals=int(t.get("divisor", 18)),
                        )
        except Exception:
            pass
        return None

    async def _get_bsc_token(self, address: str) -> Optional[TokenInfo]:
        try:
            url = f"https://api.bscscan.com/api?module=token&action=tokeninfo&contractaddresses={address}&apikey={self._get_api_key('bsc')}"
            async with self.session as session:
                async with session.get(url) as resp:
                    data = await resp.json()
                    if data.get("result") and len(data["result"]) > 0:
                        t = data["result"][0]
                        return TokenInfo(
                            address=address,
                            name=t.get("tokenName", "Unknown"),
                            symbol=t.get("symbol", "???"),
                            chain="bsc",
                            decimals=int(t.get("divisor", 18)),
                        )
        except Exception:
            pass
        return None

    async def get_price(self, chain: str, token_address: str) -> float:
        cache_key = f"{chain}:{token_address}"
        now = time.time()
        if cache_key in self.price_cache:
            cached = self.price_cache[cache_key]
            if now - cached["time"] < 5:
                return cached["price"]

        price = await self._fetch_price(chain, token_address)
        self.price_cache[cache_key] = {"price": price, "time": now}
        return price

    async def _fetch_price(self, chain: str, token_address: str) -> float:
        try:
            coingecko_id = self._get_coingecko_id(chain, token_address)
            if coingecko_id:
                url = f"https://api.coingecko.com/api/v3/simple/price?ids={coingecko_id}&vs_currencies=usd"
                async with self.session as session:
                    async with session.get(url) as resp:
                        data = await resp.json()
                        if coingecko_id in data:
                            return data[coingecko_id].get("usd", 0.0)
        except Exception:
            pass
        return 0.0

    def _get_coingecko_id(self, chain: str, address: str) -> Optional[str]:
        known_tokens = {
            "ethereum": {
                "0xdac17f958d2ee523a2206206994597c13d831ec7": "tether",
                "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "usd-coin",
                "0x6b175474e89094c44da98b954eedeac495271d0f": "dai",
            },
            "bsc": {
                "0x55d398326f99059ff775485246999027b3197955": "tether",
                "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d": "usd-coin",
            },
            "solana": {
                "So11111111111111111111111111111111111111112": "wrapped-solana",
                "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "usd-coin",
                "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "tether",
            },
        }
        return known_tokens.get(chain, {}).get(address.lower())

    def _get_api_key(self, chain: str) -> str:
        from config import ETH_API_KEY, BSC_API_KEY
        return ETH_API_KEY if chain == "eth" else BSC_API_KEY

    async def execute_snipe(self, target: SnipeTarget) -> dict:
        target.status = "executing"
        try:
            if target.chain == "solana":
                result = await self._snipe_solana(target)
            elif target.chain in ("ethereum", "bsc"):
                result = await self._snipe_evm(target)
            else:
                result = {"success": False, "error": "Unsupported chain"}

            if result.get("success"):
                target.status = "filled"
                target.filled_at = time.time()
                target.fill_price = result.get("price", 0.0)
            else:
                target.status = "failed"

            return result
        except Exception as e:
            target.status = "failed"
            return {"success": False, "error": str(e)}

    async def _snipe_solana(self, target: SnipeTarget) -> dict:
        return {
            "success": True,
            "tx_hash": "simulated_solana_tx",
            "price": 0.001,
            "amount": target.buy_amount,
            "chain": "solana",
        }

    async def _snipe_evm(self, target: SnipeTarget) -> dict:
        return {
            "success": True,
            "tx_hash": "0xsimulated_evm_tx",
            "price": 1.5,
            "amount": target.buy_amount,
            "chain": target.chain,
        }


class PriceMonitor:
    def __init__(self, snipe_engine: SnipeEngine):
        self.engine = snipe_engine
        self.watches: dict[int, list[dict]] = {}
        self.running = False

    async def add_watch(self, user_id: int, chain: str, address: str, callback):
        if user_id not in self.watches:
            self.watches[user_id] = []
        self.watches[user_id].append({
            "chain": chain,
            "address": address,
            "callback": callback,
            "last_price": 0.0,
            "alerts": {
                "price_up": None,
                "price_down": None,
                "volume_spike": None,
            },
        })

    async def remove_watch(self, user_id: int, chain: str, address: str):
        if user_id in self.watches:
            self.watches[user_id] = [
                w for w in self.watches[user_id]
                if not (w["chain"] == chain and w["address"] == address)
            ]

    async def check_alerts(self):
        for user_id, watches in self.watches.items():
            for watch in watches:
                try:
                    price = await self.engine.get_price(watch["chain"], watch["address"])
                    if price > 0:
                        alerts = watch["alerts"]
                        if alerts["price_up"] and price >= alerts["price_up"]:
                            await watch["callback"](user_id, watch, "price_up", price)
                            alerts["price_up"] = None
                        if alerts["price_down"] and price <= alerts["price_down"]:
                            await watch["callback"](user_id, watch, "price_down", price)
                            alerts["price_down"] = None
                        watch["last_price"] = price
                except Exception:
                    pass

    async def monitor_loop(self, interval: int = 30):
        self.running = True
        while self.running:
            await self.check_alerts()
            await asyncio.sleep(interval)
