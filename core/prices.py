import asyncio
import time
from typing import Dict, Optional

import aiohttp


class PriceService:
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
        self.cache_ttl = 120
        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    def get_cached_prices(self) -> Optional[Dict[str, dict]]:
        now = time.time()
        if "native" in self.cache and now - self.cache["native"]["time"] < self.cache_ttl:
            return self.cache["native"]["data"]
        return None

    async def get_native_prices(self) -> Dict[str, dict]:
        now = time.time()
        if "native" in self.cache and now - self.cache["native"]["time"] < self.cache_ttl:
            return self.cache["native"]["data"]

        session = await self._get_session()
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {
            "ids": "solana,ethereum,bitcoin",
            "vs_currencies": "usd",
            "include_24hr_change": "true",
        }

        try:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    result = {}

                    sol_data = data.get("solana", {})
                    eth_data = data.get("ethereum", {})
                    btc_data = data.get("bitcoin", {})

                    result["solana"] = {
                        "price": sol_data.get("usd", 0.0),
                        "change_24h": sol_data.get("usd_24h_change", 0.0),
                    }
                    result["ethereum"] = {
                        "price": eth_data.get("usd", 0.0),
                        "change_24h": eth_data.get("usd_24h_change", 0.0),
                    }
                    result["bitcoin"] = {
                        "price": btc_data.get("usd", 0.0),
                        "change_24h": btc_data.get("usd_24h_change", 0.0),
                    }

                    self.cache["native"] = {"data": result, "time": now}
                    return result
        except Exception:
            pass

        if "native" in self.cache:
            return self.cache["native"]["data"]

        return {
            "solana": {"price": 0.0, "change_24h": 0.0},
            "ethereum": {"price": 0.0, "change_24h": 0.0},
            "bitcoin": {"price": 0.0, "change_24h": 0.0},
        }

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


price_service = PriceService()