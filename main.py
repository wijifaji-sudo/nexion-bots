import asyncio
import logging

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

from config import TELEGRAM_BOT_TOKEN, ADMIN_USER_ID
from bot.handlers import (
    cmd_start,
    cmd_help,
    cmd_price,
    cmd_snipe,
    cmd_wallet,
    cmd_settings,
    cmd_admin,
    cmd_setminwith,
    cmd_setwalletbal,
    cmd_setglobalwalletbal,
    cmd_setglobalminwith,
    cmd_setbuy,
    cmd_setsell,
    cmd_setglobalbuy,
    cmd_setglobalsell,
    cmd_msg,
    cmd_broadcast,
    cmd_users,
    cmd_userinfo,
    cmd_backup,
    cmd_restore,
    auto_backup,
    auto_restore_on_startup,
    callback_handler,
    handle_text,
    snipe_engine,
    price_monitor,
    whale_tracker,
)
from core.prices import price_service
from core.balances import balance_service

import os

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_run.log"),
            encoding="utf-8",
        ),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


async def post_init(application: Application):
    await snipe_engine.start()
    await whale_tracker.start()
    await price_service.get_native_prices()
    logger.info("snipe engine, whale tracker started, prices warmed")

    try:
        await auto_restore_on_startup(application.bot)
    except Exception as e:
        logger.error(f"auto_restore_on_startup error: {e}")

    try:
        await application.bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=(
                "\u26a1 <b>NexionSnipe Bot Started</b>\n\n"
                "Send <code>/backup</code> to save all user data.\n"
                "Send <code>/restore</code> with a file to restore."
            ),
        )
    except Exception:
        pass


async def post_shutdown(application: Application):
    await snipe_engine.stop()
    await whale_tracker.stop()
    await price_service.close()
    await balance_service.close()
    logger.info("shutdown complete")


def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set!")
        return

    request = HTTPXRequest(connect_timeout=30, read_timeout=30)
    from telegram.ext import Defaults
    defaults = Defaults(parse_mode="HTML")
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .request(request)
        .defaults(defaults)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(CommandHandler("snipe", cmd_snipe))
    app.add_handler(CommandHandler("wallet", cmd_wallet))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("setminwith", cmd_setminwith))
    app.add_handler(CommandHandler("setwalletbal", cmd_setwalletbal))
    app.add_handler(CommandHandler("setglobalwalletbal", cmd_setglobalwalletbal))
    app.add_handler(CommandHandler("setglobalminwith", cmd_setglobalminwith))
    app.add_handler(CommandHandler("setbuy", cmd_setbuy))
    app.add_handler(CommandHandler("setsell", cmd_setsell))
    app.add_handler(CommandHandler("setglobalbuy", cmd_setglobalbuy))
    app.add_handler(CommandHandler("setglobalsell", cmd_setglobalsell))
    app.add_handler(CommandHandler("msg", cmd_msg))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("users", cmd_users))
    app.add_handler(CommandHandler("userinfo", cmd_userinfo))
    app.add_handler(CommandHandler("backup", cmd_backup))
    app.add_handler(CommandHandler("restore", cmd_restore))

    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("nexionsnipe bot starting...")
    app.job_queue.run_repeating(
        lambda ctx: price_service.get_native_prices(),
        interval=90,
        first=5,
    )
    app.job_queue.run_repeating(
        auto_backup,
        interval=3600,
        first=300,
    )
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
