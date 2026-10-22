"""Telegram bot handler
Manages registration and login confirmation via Telegram
"""
import asyncio
import hashlib
import secrets
import sys
import logging
import httpx
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, filters
from src.config import settings
from src.web.security import valid_internal_key
from uuid import UUID

# Configure logging with immediate flush
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
# python-telegram-bot logs whole updates (including /start tokens) at DEBUG
logging.getLogger("telegram").setLevel(logging.INFO)
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger(__name__)


def log_ref(login_id) -> str:
    """Correlation reference for logs; a login_id unlocks /status, so never log it"""
    return hashlib.sha256(str(login_id).encode()).hexdigest()[:12]

class TeleLoginBot:
    def __init__(self):
        self.app = Application.builder().token(settings.BOT_TOKEN).build()
        self.api_base_url = settings.API_BASE_URL.rstrip("/")

        # HTTP server for receiving notifications
        self.web_app = web.Application()
        self.web_app.router.add_post('/notify-login', self.handle_login_notification)
        self.web_app.router.add_get('/health', self.health)

        # Debug: print configuration
        logger.info(f"Bot username configured as: {settings.BOT_USERNAME}")
        logger.info(f"API base URL: {self.api_base_url}")
        logger.info(f"Database URL: {settings.DB_URL}")
        sys.stderr.flush()

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command with registration token"""
        # Debug logging
        logger.info("="*50)
        logger.info("/start command received")
        logger.info(f"Update user: {update.effective_user.id if update.effective_user else 'None'}")
        logger.info(f"Number of args = {len(context.args) if context.args else 0}")

        logger.info("="*50)
        sys.stderr.flush()

        if context.args and len(context.args) > 0 and context.args[0].strip():
            # Registration flow
            await self.link_account(update, context.args[0].strip())
        else:
            # Welcome message
            logger.info("No args received, sending welcome message")
            sys.stderr.flush()
            await update.message.reply_text(
                "👋 Welcome to TeleLogin!\n\n"
                "This bot is used to confirm login requests.\n\n"
                "📝 To register:\n"
                "1. Register on the TeleLogin platform\n"
                "2. You'll receive a registration link\n"
                "3. Click the link, then click the START button\n\n"
                "⚠️ If you've already started this bot before, you need to:\n"
                "- Delete this chat\n"
                "- Click the registration link again\n"
                "- Click the START button that appears\n\n"
                "Or use the /link command with your registration token."
            )

    async def link_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /link command with registration token as alternative to deep link"""
        logger.info("/link command received")
        sys.stderr.flush()

        if not context.args or len(context.args) == 0:
            await update.message.reply_text(
                "❌ Please provide your registration token:\n"
                "/link YOUR_TOKEN_HERE"
            )
            return

        await self.link_account(update, context.args[0].strip())

    async def link_account(self, update: Update, token: str):
        """Link the sender's Telegram account using a registration token"""
        telegram_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name

        logger.info(f"Processing registration for telegram_id={telegram_id}")
        sys.stderr.flush()

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_base_url}/auth/link-telegram",
                    headers={"X-Internal-Key": settings.INTERNAL_API_KEY},
                    json={
                        "token": token,
                        "telegram_id": telegram_id
                    },
                    timeout=10.0
                )
        except Exception as e:
            logger.warning(f"link-telegram request failed: {type(e).__name__}")
            await update.message.reply_text(
                "❌ Error during registration.\n"
                "Please try again or contact support."
            )
            return

        if response.status_code == 200:
            await update.message.reply_text(
                f"✅ Registration successful, {username}!\n\n"
                "Your Telegram account is now linked to TeleLogin.\n"
                "You can now use Telegram to confirm your logins."
            )
            return

        logger.warning(f"link-telegram failed: status={response.status_code}")
        await update.message.reply_text(self.registration_error_message(response))

    @staticmethod
    def registration_error_message(response) -> str:
        """Map known API errors to fixed user messages; never echo API text"""
        detail = None
        if response.status_code == 400:
            try:
                detail = response.json().get("detail")
            except Exception:
                detail = None
        if detail == "Telegram already linked to another account":
            return "❌ This Telegram account is already linked to another TeleLogin account."
        if detail == "Invalid or expired token":
            return "❌ This registration link is invalid or expired. Please request a new one."
        return "❌ Registration failed. Please try again or contact support."

    async def internal_request(self, path, telegram_id, **data):
        async with httpx.AsyncClient(timeout=10) as client:
            return await client.post(f"{self.api_base_url}{path}", headers={"X-Internal-Key": settings.INTERNAL_API_KEY}, json={"telegram_id": telegram_id, **data})

    async def status_command(self, update, context):
        try:
            response = await self.internal_request('/internal/account', update.effective_user.id)
            if response.status_code != 200:
                await update.message.reply_text('No linked account' if response.status_code == 404 else 'Unable to process request')
                return
            data = response.json()
            text = f"Account: {data['username']}\nLinked: {data['linked_at']}\nActive sessions: {data['active_sessions']}"
            for row in data['recent_logins']:
                text += f"\n{row['created_at']} {row['status']} IP: {row['ip']} Browser: {row['user_agent']}"
            await update.message.reply_text(text)
        except Exception:
            await update.message.reply_text('Unable to process request')

    async def sessions_command(self, update, context):
        try:
            response = await self.internal_request('/internal/sessions', update.effective_user.id)
            if response.status_code != 200:
                await update.message.reply_text('No linked account' if response.status_code == 404 else 'Unable to process request')
                return
            sessions = sorted(response.json()['sessions'], key=lambda row: (row['last_used_at'] if row['last_used_at'] is not None else row['created_at'], row['created_at'], row['id']), reverse=True)
            for row in sessions[:10]:
                await update.message.reply_text(f"Created: {row['created_at']}\nLast used: {row['last_used_at']}\nIP: {row['ip']}\nBrowser: {row['user_agent']}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Revoke', callback_data=f"revoke_session:{row['id']}")]]))
            summary = f'{len(sessions) - 10} more not shown' if len(sessions) > 10 else 'Sessions'
            await update.message.reply_text(summary, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Revoke all', callback_data='revoke_all')]]))
        except Exception:
            await update.message.reply_text('Unable to process request')

    async def unlink_command(self, update, context):
        await update.message.reply_text('Delete your account and all data?', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Yes, delete my account', callback_data='unlink_confirm'), InlineKeyboardButton('Cancel', callback_data='unlink_cancel')]]))

    async def private_only_command(self, update, context):
        await update.message.reply_text("Please use this command in a private chat with the bot.")

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        try:
            parts = query.data.split(':')
            action = parts[0]
            lengths = {'login_confirm':3,'login_deny':2,'revoke_session':2,'revoke_all':1,'unlink_confirm':1,'unlink_cancel':1}
            if action not in lengths or len(parts) != lengths[action]:
                raise ValueError
            if len(parts) > 1:
                if str(UUID(parts[1])) != parts[1]:
                    raise ValueError
            if action == 'login_confirm' and (len(parts[2]) != 2 or not parts[2].isascii() or not parts[2].isdigit() or not 10 <= int(parts[2]) <= 99):
                raise ValueError
        except (AttributeError, TypeError, ValueError):
            await query.edit_message_text('Invalid request')
            return
        account_action = action in ('revoke_session', 'revoke_all', 'unlink_confirm', 'unlink_cancel')
        if account_action and getattr(update.effective_chat, 'type', 'private') != 'private':
            await query.edit_message_text('Please use this command in a private chat with the bot.')
            return
        if action == 'unlink_cancel':
            await query.edit_message_text('Cancelled')
            return
        data = {}
        if action.startswith('login_'):
            path = '/auth/confirm-login' if action == 'login_confirm' else '/auth/deny-login'
            data['login_id'] = parts[1]
            if action == 'login_confirm':
                data['verification_code'] = int(parts[2])
        elif action == 'unlink_confirm':
            path = '/internal/account/delete'
        else:
            path = '/internal/sessions/revoke'
            data['session_id'] = parts[1] if action == 'revoke_session' else None
        try:
            response = await self.internal_request(path, update.effective_user.id, **data)
            text = {'login_confirm':'✅ Login confirmed successfully!', 'login_deny':'🚫 Login request denied.', 'unlink_confirm':'Account deleted', 'revoke_session':'Session revoked', 'revoke_all':'Sessions revoked'}[action]
            if response.status_code != 200:
                text = 'Request already handled, expired or invalid'
                if response.status_code == 400 and response.json().get('detail') == 'Wrong verification code':
                    text = 'Wrong code: request denied'
            await query.edit_message_text(text)
        except Exception:
            await query.edit_message_text('Unable to process request')

    async def send_login_notification(self, telegram_id: int, login_id: str, username: str, verification_code: int, requested_at: str, ip: str, user_agent: str):
        """Send login confirmation request to user"""
        logger.info(f"Sending login notification to telegram_id={telegram_id}, login_ref={log_ref(login_id)}")
        sys.stderr.flush()

        codes = {verification_code}
        while len(codes) < 3:
            codes.add(secrets.randbelow(90) + 10)
        codes = list(codes)
        secrets.SystemRandom().shuffle(codes)
        keyboard = [[InlineKeyboardButton(str(code), callback_data=f"login_confirm:{login_id}:{code}") for code in codes], [InlineKeyboardButton("🚫 Deny", callback_data=f"login_deny:{login_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            await self.app.bot.send_message(
                chat_id=telegram_id,
                text=f"🔐 Login Request\n\n"
                     f"Username: {username}\n\n"
                     f"Time UTC: {requested_at}\nIP: {ip}\nBrowser: {user_agent[:100]}\nTap the code shown in your browser; if this was not you, press Deny",
                reply_markup=reply_markup
            )
            logger.info("Login notification sent successfully")
        except Exception as e:
            logger.warning(f"Telegram notification failed: {type(e).__name__}")
        sys.stderr.flush()

    async def handle_login_notification(self, request):
        """Handle HTTP POST requests to send login notifications"""
        if not valid_internal_key(request.headers.get("X-Internal-Key")):
            return web.json_response({"error": "Unauthorized"}, status=401)
        try:
            data = await request.json()
            telegram_id = data.get('telegram_id')
            login_id = data.get('login_id')
            username = data.get('username')

            logger.info(f"Received login notification request: telegram_id={telegram_id}, login_ref={log_ref(login_id)}")

            code = data.get('verification_code')
            if (not all([telegram_id, login_id, username])
                    or type(code) is not int or not 10 <= code <= 99
                    or not isinstance(data.get('requested_at'), str) or not data['requested_at']
                    or not isinstance(data.get('ip'), str)
                    or not isinstance(data.get('user_agent'), str)):
                return web.json_response({'error': 'Missing required fields'}, status=400)

            # Send notification via Telegram
            await self.send_login_notification(telegram_id, login_id, username, data["verification_code"], data["requested_at"], data["ip"], data["user_agent"])

            return web.json_response({'success': True})
        except Exception as e:
            logger.warning(f"Login notification request failed: {type(e).__name__}")
            return web.json_response({'error': 'Notification failed'}, status=500)

    async def health(self, request):
        healthy = self.app.running
        return web.json_response({"status": "ok" if healthy else "starting"}, status=200 if healthy else 503)

    async def start(self):
        """Initialize and start the bot"""
        logger.info("Initializing bot...")
        sys.stderr.flush()

        # Add handlers
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("link", self.link_command))
        # Account data (IPs, browsers) must never be shown in group chats
        private = filters.ChatType.PRIVATE
        self.app.add_handler(CommandHandler("status", self.status_command, filters=private))
        self.app.add_handler(CommandHandler("sessions", self.sessions_command, filters=private))
        self.app.add_handler(CommandHandler("unlink", self.unlink_command, filters=private))
        self.app.add_handler(CommandHandler(["status", "sessions", "unlink"], self.private_only_command, filters=~private))
        self.app.add_handler(CallbackQueryHandler(self.button_callback))
        logger.info("Handlers registered")
        sys.stderr.flush()

        # Start polling
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()

        logger.info("Bot is now running and polling for updates...")
        sys.stderr.flush()

        # Start HTTP server for notifications
        runner = web.AppRunner(self.web_app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', 8001)
        await site.start()
        logger.info("HTTP notification server started on port 8001")
        sys.stderr.flush()

        # Run until stopped
        await asyncio.Event().wait()

if __name__ == "__main__":
    bot = TeleLoginBot()
    asyncio.run(bot.start())
