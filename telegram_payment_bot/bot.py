import logging
import sys
from functools import wraps
from telegram import Update
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)
from database import initialize_db, Admin, Chat, User, Payment, UserSettings, db
from config import BOT_TOKEN, OWNER_ID, PAYMENT_WALLET, TRONGRID_API_URL, TRANSACTION_CONFIRMATION_WINDOW, RENEWAL_REMINDER_DAYS
from localization import load_translations, get_text
import datetime
import requests
from peewee import fn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import telegram

# Constants
USDT_CONTRACT_ADDRESS = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
USDT_DECIMALS = 6

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Decorators for authorization ---
def owner_only(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if str(user_id) == str(OWNER_ID):
            return await func(update, context, *args, **kwargs)
        else:
            lang = get_user_language(user_id)
            await update.message.reply_text(get_text("error_owner_only", lang))
    return wrapped

def admin_only(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        db.connect(reuse_if_open=True)
        try:
            is_admin_user = Admin.select().where(Admin.user_id == user_id).exists()
        finally:
            if not db.is_closed():
                db.close()

        if is_admin_user:
            return await func(update, context, *args, **kwargs)
        else:
            lang = get_user_language(user_id)
            await update.message.reply_text(get_text("error_admin_only", lang))
    return wrapped

# --- Helper Functions ---
def get_user_language(user_id: int) -> str:
    """Gets the user's language from the database."""
    db.connect(reuse_if_open=True)
    try:
        user_settings = UserSettings.get_or_none(UserSettings.user_id == user_id)
        return user_settings.language if user_settings else "en"
    finally:
        if not db.is_closed():
            db.close()

def set_user_language(user_id: int, lang_code: str):
    """Sets or updates the user's language in the database."""
    db.connect(reuse_if_open=True)
    try:
        UserSettings.replace(user_id=user_id, language=lang_code).execute()
    finally:
        if not db.is_closed():
            db.close()

# --- Basic Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /start command."""
    user_id = update.effective_user.id
    db.connect(reuse_if_open=True)
    try:
        user_settings = UserSettings.get_or_none(UserSettings.user_id == user_id)

        if not user_settings:
            # New user, ask for language
            keyboard = [
                [InlineKeyboardButton("🇬🇧 English", callback_data='set_lang_en')],
                [InlineKeyboardButton("🇷🇺 Русский", callback_data='set_lang_ru')],
                [InlineKeyboardButton("🇪🇸 Español", callback_data='set_lang_es')],
                [InlineKeyboardButton("🇮🇳 हिन्दी", callback_data='set_lang_hi')],
                [InlineKeyboardButton("🇨🇳 中文", callback_data='set_lang_zh')],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(get_text("lang_select_prompt", "en"), reply_markup=reply_markup)
        else:
            # Existing user, show welcome message in their language
            lang = user_settings.language
            await update.message.reply_text(get_text("welcome_message", lang))

    finally:
        if not db.is_closed():
            db.close()

async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles language selection from the inline keyboard."""
    query = update.callback_query
    await query.answer()

    lang_code = query.data.split('_')[-1]
    user_id = query.from_user.id

    set_user_language(user_id, lang_code)

    # Edit the message to show the welcome text in the new language.
    await query.edit_message_text(text=get_text("welcome_message", lang_code))

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    user_id = update.effective_user.id
    lang = get_user_language(user_id)

    db.connect(reuse_if_open=True)
    try:
        is_admin = Admin.select().where(Admin.user_id == user_id).exists()
    finally:
        if not db.is_closed():
            db.close()

    user_commands = (
        f"*{get_text('help_user_commands_header', lang)}*\n"
        f"/start - {get_text('help_start', lang)}\n"
        f"/help - {get_text('help_help', lang)}\n"
        f"/pay <chat_id> - {get_text('help_pay', lang)}\n"
        f"/status - {get_text('help_status', lang)}"
    )

    admin_commands = (
        f"\n\n*{get_text('help_admin_commands_header', lang)}*\n"
        f"/addchat - {get_text('help_addchat', lang)}\n"
        f"/delchat <chat_id> - {get_text('help_delchat', lang)}\n"
        f"/chats - {get_text('help_chats', lang)}"
    )

    owner_commands = (
        f"\n\n*{get_text('help_owner_commands_header', lang)}*\n"
        f"/addadmin <user_id> - {get_text('help_addadmin', lang)}"
    )

    message = user_commands
    if is_admin:
        message += admin_commands
    if str(user_id) == str(OWNER_ID):
        message += owner_commands

    await update.message.reply_text(message, parse_mode='Markdown')

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Checks the user's subscription status for a chat."""
    user_id = update.effective_user.id
    lang = get_user_language(user_id)

    db.connect(reuse_if_open=True)
    try:
        subscriptions = User.select().where((User.user_id == user_id) & (User.expires_at > datetime.datetime.now()))

        if not subscriptions.exists():
            await update.message.reply_text(get_text("status_no_subscriptions", lang))
            return

        message = f"{get_text('status_header', lang)}\n\n"
        for sub in subscriptions:
            chat = sub.chat
            status_line = get_text('status_line', lang)
            message += status_line.format(
                chat_title=chat.title,
                date=sub.expires_at.strftime('%Y-%m-%d %H:%M UTC')
            )

        await update.message.reply_text(message, parse_mode='Markdown')

    finally:
        if not db.is_closed():
            db.close()

# --- Admin Commands ---
@owner_only
async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add a new admin."""
    user_id = update.effective_user.id
    lang = get_user_language(user_id)

    if not context.args:
        await update.message.reply_text(get_text("addadmin_usage", lang))
        return

    try:
        new_admin_id = int(context.args[0])
    except (ValueError, IndexError):
        await update.message.reply_text(get_text("addadmin_invalid_id", lang))
        return

    db.connect(reuse_if_open=True)
    try:
        if Admin.select().where(Admin.user_id == new_admin_id).exists():
            await update.message.reply_text(get_text("addadmin_already_admin", lang))
            return

        Admin.create(user_id=new_admin_id)
        await update.message.reply_text(get_text("addadmin_success", lang).format(user_id=new_admin_id))
        logger.info(f"User {new_admin_id} added as admin by {update.effective_user.id}")
    finally:
        if not db.is_closed():
            db.close()

@admin_only
async def list_chats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lists all managed chats."""
    user_id = update.effective_user.id
    lang = get_user_language(user_id)

    db.connect(reuse_if_open=True)
    try:
        chats = Chat.select()
        if not chats:
            await update.message.reply_text(get_text("list_chats_no_chats", lang))
            return

        message = f"{get_text('list_chats_header', lang)}\n\n"
        chat_line_template = get_text('list_chats_line', lang)
        for chat in chats:
            message += chat_line_template.format(
                title=chat.title,
                chat_id=chat.chat_id,
                amount=chat.amount,
                currency=chat.currency,
                duration=chat.duration_days
            )
        await update.message.reply_text(message)
    finally:
        if not db.is_closed():
            db.close()

@admin_only
async def delete_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Deletes a chat from management."""
    user_id = update.effective_user.id
    lang = get_user_language(user_id)

    chat_id_to_delete = None
    if context.args:
        try:
            chat_id_to_delete = int(context.args[0])
        except ValueError:
            await update.message.reply_text(get_text("delchat_invalid_id", lang))
            return
    else:
        if update.effective_chat.type == 'private':
            await update.message.reply_text(get_text("delchat_private_chat_error", lang))
            return
        chat_id_to_delete = update.effective_chat.id

    db.connect(reuse_if_open=True)
    try:
        query = Chat.delete().where(Chat.chat_id == chat_id_to_delete)
        deleted_rows = query.execute()

        if deleted_rows > 0:
            User.delete().where(User.chat_id == chat_id_to_delete).execute()
            await update.message.reply_text(get_text("delchat_success", lang).format(chat_id=chat_id_to_delete))
            logger.info(f"Chat {chat_id_to_delete} deleted by {update.effective_user.id}")
        else:
            await update.message.reply_text(get_text("delchat_not_managed", lang))
    finally:
        if not db.is_closed():
            db.close()

# --- /addchat Conversation ---
(ASK_AMOUNT, ASK_DURATION) = range(2)

@admin_only
async def add_chat_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the conversation to add a new chat."""
    user_id = update.effective_user.id
    lang = get_user_language(user_id)

    chat = update.effective_chat
    if chat.type == 'private':
        await update.message.reply_text(get_text("addchat_private_chat_error", lang))
        return ConversationHandler.END

    db.connect(reuse_if_open=True)
    try:
        if Chat.select().where(Chat.chat_id == chat.id).exists():
            await update.message.reply_text(get_text("addchat_already_managed", lang))
            return ConversationHandler.END
    finally:
        if not db.is_closed():
            db.close()

    context.user_data['chat_id'] = chat.id
    context.user_data['chat_title'] = chat.title
    context.user_data['lang'] = lang

    await update.message.reply_text(get_text("addchat_ask_amount", lang))
    return ASK_AMOUNT

async def ask_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the amount and asks for the duration."""
    lang = context.user_data.get('lang', 'en')
    try:
        amount = float(update.message.text)
        if amount <= 0:
             await update.message.reply_text(get_text("addchat_invalid_amount", lang))
             return ASK_AMOUNT
    except ValueError:
        await update.message.reply_text(get_text("addchat_invalid_amount", lang))
        return ASK_AMOUNT

    context.user_data['amount'] = amount
    await update.message.reply_text(get_text("addchat_ask_duration", lang))
    return ASK_DURATION

async def ask_duration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the duration and saves the chat."""
    lang = context.user_data.get('lang', 'en')
    try:
        duration = int(update.message.text)
        if duration <= 0:
            await update.message.reply_text(get_text("addchat_invalid_duration", lang))
            return ASK_DURATION
    except ValueError:
        await update.message.reply_text(get_text("addchat_invalid_duration", lang))
        return ASK_DURATION

    chat_id = context.user_data['chat_id']
    chat_title = context.user_data['chat_title']
    amount = context.user_data['amount']

    db.connect(reuse_if_open=True)
    try:
        Chat.create(
            chat_id=chat_id,
            title=chat_title,
            amount=amount,
            duration_days=duration
        )
        success_message = get_text("addchat_success", lang).format(
            chat_title=chat_title,
            amount=amount,
            duration=duration
        )
        await update.message.reply_text(success_message)
        logger.info(f"Chat {chat_id} ({chat_title}) added by {update.effective_user.id}")
    finally:
        if not db.is_closed():
            db.close()

    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    await update.message.reply_text(get_text("cancel_operation", lang))
    context.user_data.clear()
    return ConversationHandler.END

# --- User Payment Flow ---
async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows payment instructions to the user."""
    user_id = update.effective_user.id
    lang = get_user_language(user_id)

    chat_id_to_pay_for = None
    if context.args:
        try:
            chat_id_to_pay_for = int(context.args[0])
        except (ValueError, IndexError):
            await update.message.reply_text(get_text("pay_invalid_id", lang))
            return
    elif update.effective_chat.type != 'private':
        chat_id_to_pay_for = update.effective_chat.id
    else:
        await update.message.reply_text(get_text("pay_private_chat_error", lang))
        return

    db.connect(reuse_if_open=True)
    try:
        chat_to_pay = Chat.get_or_none(Chat.chat_id == chat_id_to_pay_for)
    finally:
        if not db.is_closed():
            db.close()

    if not chat_to_pay:
        await update.message.reply_text(get_text("pay_chat_not_managed", lang))
        return

    db.connect(reuse_if_open=True)
    try:
        user_subscription = User.get_or_none((User.user_id == user_id) & (User.chat_id == chat_to_pay.id) & (User.expires_at > datetime.datetime.now()))
    finally:
        if not db.is_closed():
            db.close()

    if user_subscription:
        await update.message.reply_text(get_text("pay_already_active", lang).format(date=user_subscription.expires_at.strftime('%Y-%m-%d %H:%M')))
        return

    payment_message = get_text("pay_instructions", lang).format(
        chat_title=chat_to_pay.title,
        duration=chat_to_pay.duration_days,
        amount=chat_to_pay.amount,
        currency=chat_to_pay.currency,
        wallet=PAYMENT_WALLET
    )

    await update.message.reply_text(payment_message, parse_mode='MarkdownV2')
    context.user_data['payment_chat_id'] = chat_to_pay.id

async def handle_transaction_hash(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles a potential transaction hash sent by the user."""
    user_id = update.effective_user.id
    lang = get_user_language(user_id)

    if 'payment_chat_id' not in context.user_data:
        return

    tx_hash = update.message.text.strip()

    if not (len(tx_hash) == 64 and all(c in '0123456789abcdefABCDEF' for c in tx_hash)):
        await update.message.reply_text(get_text("handle_tx_invalid_hash", lang))
        return

    chat_id = context.user_data.pop('payment_chat_id')

    await update.message.reply_text(get_text("handle_tx_verifying", lang))
    logger.info(f"Received transaction hash {tx_hash} from user {user_id} for chat {chat_id}. Passing to verification.")

    await verify_and_grant_access(update, context, tx_hash, user_id, chat_id)

async def verify_and_grant_access(update: Update, context: ContextTypes.DEFAULT_TYPE, tx_hash: str, user_id: int, chat_id: int):
    """Verify a transaction and grant access to the user if valid."""
    lang = get_user_language(user_id)
    db.connect(reuse_if_open=True)
    try:
        chat_to_join = Chat.get_or_none(Chat.chat_id == chat_id)
        if not chat_to_join:
            await update.message.reply_text(get_text("verify_chat_not_found", lang))
            return

        if Payment.select().where(Payment.tx_hash == tx_hash).exists():
            await update.message.reply_text(get_text("verify_tx_used", lang))
            return

        try:
            info_url = f"{TRONGRID_API_URL}/wallet/gettransactionbyid?value={tx_hash}"
            info_response = requests.get(info_url, timeout=15)
            info_response.raise_for_status()
            tx_info = info_response.json()

            tx_timestamp = tx_info.get('raw_data', {}).get('timestamp', 0)
            if tx_timestamp == 0:
                await update.message.reply_text(get_text("verify_tx_not_found_on_chain", lang))
                return

            time_diff_minutes = (datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000 - tx_timestamp) / (1000 * 60)
            if time_diff_minutes > TRANSACTION_CONFIRMATION_WINDOW:
                await update.message.reply_text(get_text("verify_tx_too_old", lang).format(minutes=TRANSACTION_CONFIRMATION_WINDOW))
                return
        except requests.exceptions.RequestException as e:
            logger.error(f"Error calling TronGrid for tx info: {e}")
            await update.message.reply_text(get_text("verify_explorer_connection_error", lang))
            return

        try:
            events_url = f"{TRONGRID_API_URL}/v1/transactions/{tx_hash}/events"
            events_response = requests.get(events_url, timeout=15)
            events_response.raise_for_status()
            events_data = events_response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error calling TronGrid for tx events: {e}")
            await update.message.reply_text(get_text("verify_explorer_connection_error_details", lang))
            return

        if not events_data.get('data') or not events_data.get('success', False):
            await update.message.reply_text(get_text("verify_no_transfer_events", lang))
            return

        payment_verified = False
        paid_amount = 0.0
        for event in events_data['data']:
            if (event.get('event_name') == 'Transfer' and
                event.get('contract_address') == USDT_CONTRACT_ADDRESS):
                result = event.get('result', {})
                to_address = result.get('to')
                value_str = result.get('value')
                if not to_address or not value_str:
                    continue
                if to_address == PAYMENT_WALLET:
                    amount_in_sats = int(value_str)
                    paid_amount = amount_in_sats / (10**USDT_DECIMALS)
                    if paid_amount >= chat_to_join.amount:
                        payment_verified = True
                        break

        if not payment_verified:
            await update.message.reply_text(get_text("verify_payment_not_confirmed", lang).format(amount=chat_to_join.amount, currency=chat_to_join.currency, wallet=PAYMENT_WALLET), parse_mode='MarkdownV2')
            return

        now = datetime.datetime.now(datetime.timezone.utc)
        expiry_date = now + datetime.timedelta(days=chat_to_join.duration_days)
        user, created = User.get_or_create(user_id=user_id, chat=chat_to_join, defaults={'expires_at': now})
        if user.expires_at and user.expires_at > now:
            user.expires_at += datetime.timedelta(days=chat_to_join.duration_days)
        else:
            user.expires_at = expiry_date
        user.save()
        Payment.create(tx_hash=tx_hash, user=user, amount=paid_amount)

        success_message = get_text("verify_payment_confirmed", lang).format(
            chat_title=chat_to_join.title,
            date=user.expires_at.strftime('%Y-%m-%d %H:%M')
        )

        try:
            expire_date = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
            invite_link = await context.bot.create_chat_invite_link(chat_id=chat_to_join.chat_id, member_limit=1, expire_date=expire_date)
            success_message += get_text("verify_invite_link_generated", lang).format(invite_link=invite_link.invite_link)
            logger.info(f"Created invite link for user {user_id} for chat {chat_id}")
        except Exception as e:
            logger.error(f"Failed to create invite link for chat {chat_to_join.chat_id}: {e}")
            success_message += get_text("verify_invite_link_failed", lang)

        await update.message.reply_text(success_message, parse_mode='MarkdownV2')
        logger.info(f"Access granted for user {user_id} to chat {chat_id} via tx {tx_hash}")

    except Exception as e:
        logger.error(f"An error occurred during payment verification: {e}")
        await update.message.reply_text(get_text("verify_internal_error", lang))
    finally:
        if not db.is_closed():
            db.close()

# --- Scheduled Tasks ---
async def send_renewal_reminders(bot: telegram.Bot):
    """Sends renewal reminders to users whose subscriptions are about to expire."""
    logger.info("Running scheduled job: send_renewal_reminders")
    db.connect(reuse_if_open=True)
    try:
        reminder_date = datetime.date.today() + datetime.timedelta(days=RENEWAL_REMINDER_DAYS)

        expiring_users = User.select().where(fn.date(User.expires_at) == reminder_date)

        for user_sub in expiring_users:
            try:
                user_id = user_sub.user_id
                lang = get_user_language(user_id)
                chat = user_sub.chat
                message = get_text("renewal_reminder", lang).format(
                    chat_title=chat.title,
                    days=RENEWAL_REMINDER_DAYS,
                    chat_id=chat.chat_id
                )
                await bot.send_message(chat_id=user_id, text=message)
                logger.info(f"Sent renewal reminder to user {user_id} for chat {chat.chat_id}")
            except Exception as e:
                logger.error(f"Failed to send renewal reminder to user {user_sub.user_id}: {e}")
    finally:
        if not db.is_closed():
            db.close()

async def remove_expired_users(bot: telegram.Bot):
    """Removes users whose subscriptions have expired."""
    logger.info("Running scheduled job: remove_expired_users")
    db.connect(reuse_if_open=True)
    try:
        expired_users = User.select().where(User.expires_at < datetime.datetime.now(datetime.timezone.utc))

        for user_sub in expired_users:
            try:
                user_id = user_sub.user_id
                lang = get_user_language(user_id)
                chat = user_sub.chat

                await bot.ban_chat_member(chat_id=chat.chat_id, user_id=user_id)
                await bot.unban_chat_member(chat_id=chat.chat_id, user_id=user_id)

                logger.info(f"Removed expired user {user_id} from chat {chat.chat_id}")

                try:
                    message = get_text("removal_notification", lang).format(
                        chat_title=chat.title,
                        chat_id=chat.chat_id
                    )
                    await bot.send_message(chat_id=user_id, text=message)
                except Exception:
                    pass # User may have blocked the bot

                user_sub.delete_instance()

            except Exception as e:
                logger.error(f"Failed to remove expired user {user_sub.user_id} from chat {user_sub.chat.chat_id}: {e}")
    finally:
        if not db.is_closed():
            db.close()

# --- Bot Setup and Main Loop ---
def setup_owner():
    """Ensures the owner is set in the database."""
    if not OWNER_ID or OWNER_ID == "YOUR_TELEGRAM_USER_ID":
        logger.error("OWNER_ID is not set in config.py. Please set it to your Telegram User ID.")
        sys.exit(1)

    try:
        owner_id_int = int(OWNER_ID)
    except (ValueError, TypeError):
        logger.error("OWNER_ID is not a valid integer. Please set it to your Telegram User ID.")
        sys.exit(1)

    db.connect(reuse_if_open=True)
    try:
        # Check if there are any admins
        if Admin.select().where(Admin.user_id == owner_id_int).count() == 0:
            Admin.create(user_id=owner_id_int)
            logger.info(f"OWNER_ID {owner_id_int} has been added as the first admin.")
    finally:
        if not db.is_closed():
            db.close()

def main() -> None:
    """Start the bot."""
    # Initialize the database tables
    initialize_db()

    # Set up the owner
    setup_owner()

    # Load translations from JSON files
    load_translations()

    # Create the Application and pass it your bot's token.
    application = Application.builder().token(BOT_TOKEN).build()

    # Initialize and start the scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_renewal_reminders, 'cron', hour=9, minute=0, args=[application.bot]) # Daily at 9:00 AM
    scheduler.add_job(remove_expired_users, 'cron', hour='*', minute='*/30', args=[application.bot]) # Every 30 minutes
    scheduler.start()

    # Add conversation handler for /addchat
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("addchat", add_chat_start)],
        states={
            ASK_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_amount)],
            ASK_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_duration)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(conv_handler)

    # Callback handler for language selection
    application.add_handler(CallbackQueryHandler(set_language, pattern='^set_lang_'))

    # Add other command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("addadmin", add_admin))
    application.add_handler(CommandHandler("chats", list_chats))
    application.add_handler(CommandHandler("delchat", delete_chat))
    application.add_handler(CommandHandler("pay", pay))
    application.add_handler(CommandHandler("status", status))

    # Add handler for transaction hashes in private chats
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_transaction_hash))

    # Run the bot until the user presses Ctrl-C
    application.run_polling()

if __name__ == "__main__":
    main()
