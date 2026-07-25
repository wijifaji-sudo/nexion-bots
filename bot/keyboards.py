from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\U0001f510 Wallet", callback_data="wallets"),
            InlineKeyboardButton("\U0001f504 Refresh", callback_data="refresh"),
        ],
        [
            InlineKeyboardButton("\U0001f916 AI Sniper", callback_data="ai_snipe"),
            InlineKeyboardButton("\U0001f46a Copy Trade", callback_data="copy_trade"),
        ],
        [
            InlineKeyboardButton("\U0001f680 Buy or Sell", callback_data="buy"),
            InlineKeyboardButton("\U0001f4ca Positions", callback_data="positions"),
        ],
        [
            InlineKeyboardButton("\U0001f52e Token Sniper", callback_data="token_sniper"),
            InlineKeyboardButton("\U0001f50d Search Tokens", callback_data="search"),
        ],
        [
            InlineKeyboardButton("\U0001f381 Referral", callback_data="referral"),
            InlineKeyboardButton("\U0001f4d6 Help", callback_data="help"),
        ],
        [
            InlineKeyboardButton("\U0001f3c6 Recent Profits", callback_data="recent_profits"),
        ],
    ])


def wallet_keyboard(has_wallets: bool = False):
    buttons = [
        [
            InlineKeyboardButton("\u25b3 Generate SOL Wallet", callback_data="wallet_gen_sol"),
        ],
        [
            InlineKeyboardButton("\U0001f511 Import Private Key", callback_data="wallet_import_pk"),
            InlineKeyboardButton("\U0001f4dd Import Seed Phrase", callback_data="wallet_import_seed"),
        ],
        [
            InlineKeyboardButton("\u25c6 Generate ETH Wallet", callback_data="wallet_gen_eth"),
        ],
        [
            InlineKeyboardButton("\U0001f535 Generate BNB Wallet", callback_data="wallet_gen_bnb"),
        ],
        [
            InlineKeyboardButton("\U0001f4b3 Withdraw", callback_data="wallet_withdraw"),
        ],
        [
            InlineKeyboardButton("\U0001f4ca Check Status", callback_data="wallet_status"),
            InlineKeyboardButton("\U0001f504 Refresh Balance", callback_data="wallet_refresh_bal"),
        ],
    ]
    if has_wallets:
        buttons.append([
            InlineKeyboardButton("\U0001f50f Disconnect Wallet", callback_data="wallet_disconnect"),
        ])
    buttons.append([
        InlineKeyboardButton("\u2b05\ufe0f Back to Dashboard", callback_data="main_menu"),
    ])
    return InlineKeyboardMarkup(buttons)


def wallet_detail_keyboard(chain: str, address: str):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\u2705 Set Active", callback_data=f"wallet_set_{chain}_{address[:8]}"),
            InlineKeyboardButton("\U0001f4b3 Balance", callback_data=f"wallet_bal_{chain}_{address[:8]}"),
        ],
        [
            InlineKeyboardButton("\U0001f50f Export Key", callback_data=f"wallet_export_{chain}_{address[:8]}"),
            InlineKeyboardButton("\U0001f5d1\ufe0f Delete", callback_data=f"wallet_del_{chain}_{address[:8]}"),
        ],
        [
            InlineKeyboardButton("\u2b05\ufe0f Back", callback_data="wallets"),
        ],
    ])


def buy_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("0.1 SOL", callback_data="buy_quick_0.1"),
            InlineKeyboardButton("0.5 SOL", callback_data="buy_quick_0.5"),
            InlineKeyboardButton("1 SOL", callback_data="buy_quick_1"),
        ],
        [
            InlineKeyboardButton("2 SOL", callback_data="buy_quick_2"),
            InlineKeyboardButton("5 SOL", callback_data="buy_quick_5"),
            InlineKeyboardButton("\U0001f4b0 Custom", callback_data="buy_custom"),
        ],
        [
            InlineKeyboardButton("\u2b05\ufe0f Back", callback_data="main_menu"),
        ],
    ])


def sell_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("25%", callback_data="sell_pct_25"),
            InlineKeyboardButton("50%", callback_data="sell_pct_50"),
            InlineKeyboardButton("75%", callback_data="sell_pct_75"),
        ],
        [
            InlineKeyboardButton("100%", callback_data="sell_pct_100"),
            InlineKeyboardButton("\U0001f4b0 Custom %", callback_data="sell_custom"),
        ],
        [
            InlineKeyboardButton("\u2b05\ufe0f Back", callback_data="main_menu"),
        ],
    ])


def ai_snipe_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\u26a1 Auto Snipe ON", callback_data="ai_snipe_toggle"),
        ],
        [
            InlineKeyboardButton("\U0001f50d Token Scanner", callback_data="ai_snipe_scanner"),
            InlineKeyboardButton("\U0001f3af Target List", callback_data="ai_snipe_targets"),
        ],
        [
            InlineKeyboardButton("\u2699\ufe0f Snipe Settings", callback_data="ai_snipe_settings"),
        ],
        [
            InlineKeyboardButton("\u2b05\ufe0f Back", callback_data="main_menu"),
        ],
    ])


def copy_trade_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\u2795 Add Wallet", callback_data="copy_add"),
            InlineKeyboardButton("\U0001f4cb My List", callback_data="copy_list"),
        ],
        [
            InlineKeyboardButton("\u2796 Remove Wallet", callback_data="copy_remove"),
        ],
        [
            InlineKeyboardButton("\u2b05\ufe0f Back", callback_data="main_menu"),
        ],
    ])


def settings_keyboard(user_settings: dict):
    slippage = user_settings.get("slippage", 10)
    mev = "ON \U0001f7e2" if user_settings.get("mev_protection", True) else "OFF \u26ab"
    auto_buy = "ON \U0001f7e2" if user_settings.get("auto_buy", False) else "OFF \u26ab"
    auto_sell = "ON \U0001f7e2" if user_settings.get("auto_sell", False) else "OFF \u26ab"
    sl = user_settings.get("stop_loss", 20)
    tp = user_settings.get("take_profit", 100)

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"\U0001f3b2 Slippage: {slippage}%", callback_data="set_slippage"),
        ],
        [
            InlineKeyboardButton(f"\U0001f6e1\ufe0f MEV: {mev}", callback_data="set_mev"),
        ],
        [
            InlineKeyboardButton(f"\U0001f4b8 Auto-Buy: {auto_buy}", callback_data="set_autobuy"),
            InlineKeyboardButton(f"\U0001f4b5 Auto-Sell: {auto_sell}", callback_data="set_autosell"),
        ],
        [
            InlineKeyboardButton(f"\u26a0\ufe0f Stop-Loss: {sl}%", callback_data="set_stoploss"),
            InlineKeyboardButton(f"\U0001f680 Take-Profit: {tp}%", callback_data="set_takeprofit"),
        ],
        [
            InlineKeyboardButton("\U0001f4b0 Buy Amounts", callback_data="set_amounts"),
        ],
        [
            InlineKeyboardButton("\U0001f40b Whale Tracker", callback_data="whales"),
        ],
        [
            InlineKeyboardButton("\u2b05\ufe0f Back", callback_data="main_menu"),
        ],
    ])


def sl_percentage_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("10%", callback_data="sl_pct_10"),
            InlineKeyboardButton("15%", callback_data="sl_pct_15"),
            InlineKeyboardButton("20%", callback_data="sl_pct_20"),
        ],
        [
            InlineKeyboardButton("25%", callback_data="sl_pct_25"),
            InlineKeyboardButton("30%", callback_data="sl_pct_30"),
            InlineKeyboardButton("50%", callback_data="sl_pct_50"),
        ],
        [
            InlineKeyboardButton("\U0001f4b0 Custom %", callback_data="sl_custom"),
        ],
        [
            InlineKeyboardButton("\u2b05\ufe0f Back", callback_data="settings"),
        ],
    ])


def tp_percentage_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("50%", callback_data="tp_pct_50"),
            InlineKeyboardButton("100%", callback_data="tp_pct_100"),
            InlineKeyboardButton("200%", callback_data="tp_pct_200"),
        ],
        [
            InlineKeyboardButton("300%", callback_data="tp_pct_300"),
            InlineKeyboardButton("500%", callback_data="tp_pct_500"),
            InlineKeyboardButton("1000%", callback_data="tp_pct_1000"),
        ],
        [
            InlineKeyboardButton("\U0001f4b0 Custom %", callback_data="tp_custom"),
        ],
        [
            InlineKeyboardButton("\u2b05\ufe0f Back", callback_data="settings"),
        ],
    ])


def buy_amount_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("0.01 SOL", callback_data="ba_0.01"),
            InlineKeyboardButton("0.05 SOL", callback_data="ba_0.05"),
            InlineKeyboardButton("0.1 SOL", callback_data="ba_0.1"),
        ],
        [
            InlineKeyboardButton("0.5 SOL", callback_data="ba_0.5"),
            InlineKeyboardButton("1 SOL", callback_data="ba_1"),
            InlineKeyboardButton("2 SOL", callback_data="ba_2"),
        ],
        [
            InlineKeyboardButton("5 SOL", callback_data="ba_5"),
            InlineKeyboardButton("10 SOL", callback_data="ba_10"),
            InlineKeyboardButton("50 SOL", callback_data="ba_50"),
        ],
        [
            InlineKeyboardButton("\U0001f4b0 Custom Amount", callback_data="ba_custom"),
        ],
        [
            InlineKeyboardButton("\u2b05\ufe0f Back", callback_data="settings"),
        ],
    ])


def snipe_confirm_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\u2705 Confirm Buy", callback_data="snipe_confirm"),
            InlineKeyboardButton("\u274c Cancel", callback_data="main_menu"),
        ],
    ])


def alert_setup_keyboard(chain: str, address: str):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\u2b06\ufe0f Price Above", callback_data=f"alert_up_{chain}_{address[:8]}"),
            InlineKeyboardButton("\u2b07\ufe0f Price Below", callback_data=f"alert_down_{chain}_{address[:8]}"),
        ],
        [
            InlineKeyboardButton("\U0001f6ab Remove Alert", callback_data=f"alert_remove_{chain}_{address[:8]}"),
        ],
        [
            InlineKeyboardButton("\u2b05\ufe0f Back", callback_data="main_menu"),
        ],
    ])


def whale_tracker_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\u2795 Add Address", callback_data="whale_add"),
            InlineKeyboardButton("\U0001f4cb List Tracked", callback_data="whale_list"),
        ],
        [
            InlineKeyboardButton("\u2796 Remove Address", callback_data="whale_remove"),
        ],
        [
            InlineKeyboardButton("\u2b05\ufe0f Back", callback_data="settings"),
        ],
    ])


def positions_keyboard(positions):
    buttons = []
    for i, pos in enumerate(positions):
        addr_short = pos.get("address", "")[:8] + "..."
        chain = pos.get("chain", "?").upper()
        buttons.append([
            InlineKeyboardButton(
                f"\U0001f4c8 {pos.get('symbol', addr_short)} ({chain})",
                callback_data=f"pos_detail_{i}"
            ),
        ])
    buttons.append([InlineKeyboardButton("\u2b05\ufe0f Back", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)


def position_detail_keyboard(index):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\U0001f4b8 Sell 25%", callback_data=f"pos_sell_{index}_25"),
            InlineKeyboardButton("\U0001f4b8 Sell 50%", callback_data=f"pos_sell_{index}_50"),
        ],
        [
            InlineKeyboardButton("\U0001f4b8 Sell 75%", callback_data=f"pos_sell_{index}_75"),
            InlineKeyboardButton("\U0001f4b8 Sell 100%", callback_data=f"pos_sell_{index}_100"),
        ],
        [
            InlineKeyboardButton("\u2b05\ufe0f Back to Positions", callback_data="positions"),
        ],
    ])


def confirm_keyboard(action: str):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\u2705 Confirm", callback_data=f"confirm_{action}"),
            InlineKeyboardButton("\u274c Cancel", callback_data="main_menu"),
        ],
    ])


def back_keyboard(target: str = "main_menu"):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("\u2b05\ufe0f Back", callback_data=target)],
    ])


def referral_keyboard(ref_count: int):
    buttons = [
        [
            InlineKeyboardButton("\U0001f381 Claim Reward", callback_data="referral_claim"),
        ],
        [
            InlineKeyboardButton("\u2b05\ufe0f Back to Dashboard", callback_data="main_menu"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


def token_sniper_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("0.1 SOL", callback_data="snipe_quick_0.1"),
            InlineKeyboardButton("0.5 SOL", callback_data="snipe_quick_0.5"),
            InlineKeyboardButton("1 SOL", callback_data="snipe_quick_1"),
        ],
        [
            InlineKeyboardButton("2 SOL", callback_data="snipe_quick_2"),
            InlineKeyboardButton("5 SOL", callback_data="snipe_quick_5"),
            InlineKeyboardButton("\U0001f4b0 Custom", callback_data="snipe_custom"),
        ],
        [
            InlineKeyboardButton("\u2b05\ufe0f Back", callback_data="main_menu"),
        ],
    ])


def withdraw_confirm_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\u2705 Confirm", callback_data="withdraw_confirm"),
            InlineKeyboardButton("\u274c Cancel", callback_data="withdraw_cancel"),
        ],
    ])
