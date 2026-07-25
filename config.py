import os
import logging
from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_USER_ID = 6671161170

SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
ETH_RPC_URL = os.getenv("ETH_RPC_URL", "https://eth.llamarpc.com")
BSC_RPC_URL = os.getenv("BSC_RPC_URL", "https://bsc-dataseed.binance.org")

ETH_API_KEY = os.getenv("ETH_API_KEY", "")
BSC_API_KEY = os.getenv("BSC_API_KEY", "")

WHALE_THRESHOLD_SOL = float(os.getenv("WHALE_THRESHOLD_SOL", "100"))
WHALE_THRESHOLD_ETH = float(os.getenv("WHALE_THRESHOLD_ETH", "10"))
WHALE_THRESHOLD_BNB = float(os.getenv("WHALE_THRESHOLD_BNB", "50"))

SNIPE_SETTINGS = {
    "default_amount_sol": 0.1,
    "default_amount_eth": 0.01,
    "default_amount_bnb": 0.1,
    "default_slippage": 10,
    "default_priority_fee_sol": 0.001,
    "auto_sell_enabled": False,
    "stop_loss_percent": 20,
    "take_profit_percent": 100,
}

CHAINS = {
    "solana": {"name": "Solana", "symbol": "SOL", "rpc": SOLANA_RPC_URL},
    "ethereum": {"name": "Ethereum", "symbol": "ETH", "rpc": ETH_RPC_URL},
    "bsc": {"name": "BNB Chain", "symbol": "BNB", "rpc": BSC_RPC_URL},
}

USER_DATA_DIR = os.getenv("USER_DATA_DIR", "user_data")
os.makedirs(USER_DATA_DIR, exist_ok=True)
logger.info(f"USER_DATA_DIR = {os.path.abspath(USER_DATA_DIR)}")

GITHUB_PAT = os.getenv("GITHUB_PAT", "")
GITHUB_GIST_ID = os.getenv("GITHUB_GIST_ID", "")
