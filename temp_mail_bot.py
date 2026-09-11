import os
import re
import random
import string
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ═══════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

MAILTM_BASE = "https://api.mail.tm"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}

user_sessions = {}


def get_domains():
    try:
        r = requests.get(f"{MAILTM_BASE}/domains", headers=HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                items = data
            else:
                items = data.get("hydra:member", [])
            return [d["domain"] for d in items if isinstance(d, dict) and "domain" in d]
    except Exception as e:
        print(f"[get_domains] error: {e}")
    return []


def create_account(address, password):
    try:
        r = requests.post(
            f"{MAILTM_BASE}/accounts",
            headers=HEADERS,
            json={"address": address, "password": password},
            timeout=10,
        )
        if r.status_code in (200, 201):
            return r.json()
        return {"error": r.json().get("detail", r.text)}
    except Exception as e:
        return {"error": str(e)}


def get_token(address, password):
    try:
        r = requests.post(
            f"{MAILTM_BASE}/token",
            headers=HEADERS,
            json={"address": address, "password": password},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json().get("token")
    except Exception:
        pass
    return None


def get_messages(token):
    try:
        h = {**HEADERS, "Authorization": f"Bearer {token}"}
        r = requests.get(f"{MAILTM_BASE}/messages", headers=h, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                return data
            return data.get("hydra:member", [])
    except Exception as e:
        print(f"[get_messages] error: {e}")
    return []


def get_message_detail(token, msg_id):
    try:
        h = {**HEADERS, "Authorization": f"Bearer {token}"}
        r = requests.get(f"{MAILTM_BASE}/messages/{msg_id}", headers=h, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


def extract_otp(text):
    if not text:
        return None
    patterns = [
        r"\b(\d{4,8})\b",
        r"(?:code|otp|pin|verification)[\s:]*(\d{4,8})",
        r"(\d{4,8})[\s]*(?:is your|as your)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def generate_credentials():
    username = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    password = "".join(random.choices(string.ascii_letters + string.digits, k=12))
    return username, password


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 **Welcome to Temp Mail Bot!**\n\n"
        "Generate a temporary email and receive OTP / verification "
        "codes right here in Telegram.\n\n"
        "**Commands:**\n"
        "• `/newmail` — Create a new temp email\n"
        "• `/check` — Check inbox (with OTP)\n"
        "• `/mymail` — Show your current email\n"
        "• `/deletemail` — Delete your email session\n\n"
        "Send `/newmail` to get started.",
        parse_mode="Markdown",
    )


async def new_mail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    domains = get_domains()

    if not domains:
        await update.message.reply_text(
            "❌ Could not fetch domains. Please try again later."
        )
        return

    username, password = generate_credentials()
    domain = random.choice(domains)
    address = f"{username}@{domain}"

    result = create_account(address, password)
    if "error" in result:
        await update.message.reply_text(
            f"❌ Failed to create email: {result['error']}"
        )
        return

    token = get_token(address, password)
    if not token:
        await update.message.reply_text("❌ Could not get token. Try again.")
        return

    user_sessions[chat_id] = {
        "address": address,
        "password": password,
        "token": token,
    }

    keyboard = [
        [InlineKeyboardButton("📬 Check Inbox", callback_data="check_inbox")],
        [InlineKeyboardButton("🗑️ Delete Email", callback_data="delete_mail")],
    ]

    await update.message.reply_text(
        f"✅ **New temp email created!**\n\n"
        f"📧 **Email:** `{address}`\n"
        f"🔑 **Password:** `{password}`\n\n"
        f"Use this email in any signup form. "
        f"When a verification code arrives, run `/check`.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def check_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = user_sessions.get(chat_id)

    if not session:
        await update.message.reply_text(
            "❌ No email found. Send `/newmail` first.", parse_mode="Markdown"
        )
        return

    msg = await update.message.reply_text("🔄 Checking inbox...")
    token = session["token"]
    messages = get_messages(token)

    if not messages:
        await msg.edit_text(
            "📭 Inbox is empty. No messages yet.\n\nSend `/check` again later."
        )
        return

    output = "📬 **Your Inbox:**\n\n"
    for i, m in enumerate(messages[:5], 1):
        sender = m.get("from", {}).get("address", "Unknown")
        subject = m.get("subject", "(No Subject)")
        output += f"**{i}. {subject}**\n"
        output += f"   From: {sender}\n"

        detail = get_message_detail(token, m["id"])
        body = detail.get("text", "") or detail.get("html", "")
        otp = extract_otp(body)

        if otp:
            output += f"   🔑 **OTP/Code: `{otp}`**\n"
        output += "\n"

    await msg.edit_text(output, parse_mode="Markdown")


async def my_mail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = user_sessions.get(chat_id)

    if not session:
        await update.message.reply_text(
            "❌ No email created yet. Send `/newmail`.", parse_mode="Markdown"
        )
        return

    await update.message.reply_text(
        f"📧 **Your current email:**\n\n"
        f"`{session['address']}`\n\n"
        f"🔑 Password: `{session['password']}`",
        parse_mode="Markdown",
    )


async def delete_mail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in user_sessions:
        del user_sessions[chat_id]
    await update.message.reply_text(
        "🗑️ Email session deleted. Send `/newmail` to create a new one.",
        parse_mode="Markdown",
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id

    if query.data == "check_inbox":
        session = user_sessions.get(chat_id)
        if not session:
            await query.edit_message_text(
                "❌ Create an email first with `/newmail`.", parse_mode="Markdown"
            )
            return

        token = session["token"]
        messages = get_messages(token)
        if not messages:
            await query.edit_message_text("📭 Inbox is empty. No messages yet.")
            return

        output = "📬 **Your Inbox:**\n\n"
        for i, m in enumerate(messages[:5], 1):
            sender = m.get("from", {}).get("address", "Unknown")
            subject = m.get("subject", "(No Subject)")
            output += f"**{i}. {subject}**\n   From: {sender}\n"

            detail = get_message_detail(token, m["id"])
            body = detail.get("text", "") or detail.get("html", "")
            otp = extract_otp(body)
            if otp:
                output += f"   🔑 **OTP: `{otp}`**\n"
            output += "\n"

        await query.edit_message_text(output, parse_mode="Markdown")

    elif query.data == "delete_mail":
        if chat_id in user_sessions:
            del user_sessions[chat_id]
        await query.edit_message_text(
            "🗑️ Email session deleted. Send `/newmail` to create a new one.",
            parse_mode="Markdown",
        )


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("newmail", new_mail))
    app.add_handler(CommandHandler("check", check_inbox))
    app.add_handler(CommandHandler("mymail", my_mail))
    app.add_handler(CommandHandler("deletemail", delete_mail))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("🤖 Bot is running... Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
