"""Telegram bot handler
Manages registration and login confirmation via Telegram
"""
import asyncio
import sys
import logging
import httpx
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from src.config import settings
from src.services.auth_service import AuthService
from src.services.token_service import TokenService
from src.database.sqlite import SQLiteDatabase
from src.services.user_service import UserService

# Configure logging with immediate flush
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger(__name__)

class TeleLoginBot:
    def __init__(self):
        self.app = Application.builder().token(settings.BOT_TOKEN).build()
        self.db = SQLiteDatabase()
        self.auth_service = AuthService(self.db)
        self.user_service = UserService(self.db)
        self.token_service = TokenService()
        # Use 'api' hostname for Docker network communication
        api_port = getattr(settings, 'API_PORT', 8000)
        self.api_base_url = f"http://api:{api_port}"
        
        # HTTP server for receiving notifications
        self.web_app = web.Application()
        self.web_app.router.add_post('/notify-login', self.handle_login_notification)
        
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
        logger.info(f"Message text: {update.message.text if update.message else 'No message'}")
        logger.info(f"context.args = {context.args}")
        logger.info(f"Number of args = {len(context.args) if context.args else 0}")
        
        # Additional debug - check if args are empty or contain empty strings
        if context.args:
            for i, arg in enumerate(context.args):
                logger.info(f"arg[{i}] = '{arg}' (length={len(arg)})")
        logger.info("="*50)
        sys.stderr.flush()
        
        if context.args and len(context.args) > 0 and context.args[0].strip():
            # Registration flow
            token = context.args[0].strip()
            telegram_id = update.effective_user.id
            username = update.effective_user.username or update.effective_user.first_name
            
            logger.info(f"Processing registration for telegram_id={telegram_id}, username={username}")
            logger.info(f"Token received (first 50 chars): {token[:50]}...")
            logger.info(f"Token length={len(token)}")
            logger.info(f"Calling API at: {self.api_base_url}/auth/link-telegram")
            sys.stderr.flush()
            
            try:
                # Call API to link telegram account
                logger.info("Making API call to link telegram account")
                sys.stderr.flush()
                
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{self.api_base_url}/auth/link-telegram",
                        json={
                            "token": token,
                            "telegram_id": telegram_id
                        },
                        timeout=10.0
                    )
                    
                    logger.info(f"API response status={response.status_code}")
                    sys.stderr.flush()
                    
                    if response.status_code == 200:
                        await update.message.reply_text(
                            f"✅ Registration successful, {username}!\n\n"
                            "Your Telegram account is now linked to TeleLogin.\n"
                            "You can now use Telegram to confirm your logins."
                        )
                    else:
                        data = response.json()
                        error_detail = data.get('detail', 'Unknown error')
                        logger.error(f"API error={error_detail}")
                        sys.stderr.flush()
                        await update.message.reply_text(
                            f"❌ Registration failed: {error_detail}"
                        )
            except Exception as e:
                logger.error(f"Exception during registration: {str(e)}", exc_info=True)
                sys.stderr.flush()
                await update.message.reply_text(
                    f"❌ Error during registration: {str(e)}\n"
                    "Please try again or contact support."
                )
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
        
        # Use same logic as start_command
        token = context.args[0].strip()
        telegram_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name
        
        logger.info(f"Processing /link registration for telegram_id={telegram_id}, username={username}")
        logger.info(f"Token length={len(token)}")
        sys.stderr.flush()
        
        try:
            # Call API to link telegram account
            logger.info("Making API call to link telegram account")
            sys.stderr.flush()
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_base_url}/auth/link-telegram",
                    json={
                        "token": token,
                        "telegram_id": telegram_id
                    },
                    timeout=10.0
                )
                
                logger.info(f"API response status={response.status_code}")
                sys.stderr.flush()
                
                if response.status_code == 200:
                    await update.message.reply_text(
                        f"✅ Registration successful, {username}!\n\n"
                        "Your Telegram account is now linked to TeleLogin.\n"
                        "You can now use Telegram to confirm your logins."
                    )
                else:
                    data = response.json()
                    error_detail = data.get('detail', 'Unknown error')
                    logger.error(f"API error={error_detail}")
                    sys.stderr.flush()
                    await update.message.reply_text(
                        f"❌ Registration failed: {error_detail}"
                    )
        except Exception as e:
            logger.error(f"Exception during /link registration: {str(e)}", exc_info=True)
            sys.stderr.flush()
            await update.message.reply_text(
                f"❌ Error during registration: {str(e)}\n"
                "Please try again or contact support."
            )
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button callbacks for login confirmation"""
        query = update.callback_query
        await query.answer()
        
        # Parse callback data: "login_confirm:LOGIN_ID" or "login_deny:LOGIN_ID"
        action, login_id = query.data.split(":", 1)
        telegram_id = update.effective_user.id
        
        if action == "login_confirm":
            try:
                # Call API to confirm login
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{self.api_base_url}/auth/confirm-login",
                        json={
                            "login_id": login_id,
                            "telegram_id": telegram_id
                        },
                        timeout=10.0
                    )
                    
                    if response.status_code == 200:
                        await query.edit_message_text(
                            "✅ Login confirmed successfully!\n"
                            "You can now access your account."
                        )
                    else:
                        await query.edit_message_text(
                            "❌ Login confirmation failed.\n"
                            "The request may have expired or is invalid."
                        )
            except Exception as e:
                await query.edit_message_text(
                    f"❌ Error: {str(e)}"
                )
        
        elif action == "login_deny":
            try:
                # Update login status to denied
                login_request = await self.db.get_login_request(login_id)
                if login_request:
                    await self.db.update_login_status(login_id, "denied")
                    await query.edit_message_text(
                        "🚫 Login request denied.\n"
                        "If this wasn't you, your account is secure."
                    )
                else:
                    await query.edit_message_text("❌ Login request not found.")
            except Exception as e:
                await query.edit_message_text(f"❌ Error: {str(e)}")
    
    async def send_login_notification(self, telegram_id: int, login_id: str, username: str):
        """Send login confirmation request to user"""
        logger.info(f"Sending login notification to telegram_id={telegram_id}, login_id={login_id}")
        sys.stderr.flush()
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Confirm", callback_data=f"login_confirm:{login_id}"),
                InlineKeyboardButton("🚫 Deny", callback_data=f"login_deny:{login_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await self.app.bot.send_message(
                chat_id=telegram_id,
                text=f"🔐 Login Request\n\n"
                     f"Username: {username}\n\n"
                     f"Do you want to confirm this login?",
                reply_markup=reply_markup
            )
            logger.info("Login notification sent successfully")
        except Exception as e:
            logger.error(f"Failed to send notification: {e}", exc_info=True)
        sys.stderr.flush()
    
    async def handle_login_notification(self, request):
        """Handle HTTP POST requests to send login notifications"""
        try:
            data = await request.json()
            telegram_id = data.get('telegram_id')
            login_id = data.get('login_id')
            username = data.get('username')
            
            logger.info(f"Received login notification request: telegram_id={telegram_id}, login_id={login_id}")
            
            if not all([telegram_id, login_id, username]):
                return web.json_response({'error': 'Missing required fields'}, status=400)
            
            # Send notification via Telegram
            await self.send_login_notification(telegram_id, login_id, username)
            
            return web.json_response({'success': True})
        except Exception as e:
            logger.error(f"Error handling login notification: {e}", exc_info=True)
            return web.json_response({'error': str(e)}, status=500)
    
    async def confirm_login(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle login confirmation callback"""
        # TODO: Implement login confirmation logic
        pass
    
    async def start(self):
        """Initialize and start the bot"""
        logger.info("Initializing bot...")
        sys.stderr.flush()
        
        # Initialize database
        await self.db.init_db()
        logger.info("Database initialized")
        sys.stderr.flush()
        
        # Add handlers
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("link", self.link_command))
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
