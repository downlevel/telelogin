"""
Telegram bot handler
Manages registration and login confirmation via Telegram
"""
import asyncio
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from src.config import settings
from src.services.auth_service import AuthService
from src.services.token_service import TokenService
from src.database.sqlite import SQLiteDatabase
from src.services.user_service import UserService

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
        
        # Debug: print configuration
        print(f"INFO: Bot username configured as: {settings.BOT_USERNAME}")
        print(f"INFO: API base URL: {self.api_base_url}")
        print(f"INFO: Database URL: {settings.DB_URL}")
        
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command with registration token"""
        # Debug logging
        print(f"\n{'='*50}")
        print(f"DEBUG: /start command received")
        print(f"DEBUG: Update object: {update}")
        print(f"DEBUG: Message text: {update.message.text if update.message else 'No message'}")
        print(f"DEBUG: context.args = {context.args}")
        print(f"DEBUG: Number of args = {len(context.args) if context.args else 0}")
        
        # Additional debug - check if args are empty or contain empty strings
        if context.args:
            for i, arg in enumerate(context.args):
                print(f"DEBUG: arg[{i}] = '{arg}' (length={len(arg)})")
        print(f"{'='*50}\n")
        
        if context.args and len(context.args) > 0 and context.args[0].strip():
            # Registration flow
            token = context.args[0].strip()
            telegram_id = update.effective_user.id
            username = update.effective_user.username or update.effective_user.first_name
            
            print(f"INFO: Processing registration for telegram_id={telegram_id}, username={username}")
            print(f"INFO: Token received (first 50 chars): {token[:50]}...")
            print(f"INFO: Token length={len(token)}")
            print(f"INFO: Calling API at: {self.api_base_url}/auth/link-telegram")
            
            try:
                # Call API to link telegram account
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{self.api_base_url}/auth/link-telegram",
                        json={
                            "token": token,
                            "telegram_id": telegram_id
                        },
                        timeout=10.0
                    )
                    
                    print(f"DEBUG: API response status={response.status_code}")
                    
                    if response.status_code == 200:
                        await update.message.reply_text(
                            f"✅ Registration successful, {username}!\n\n"
                            "Your Telegram account is now linked to TeleLogin.\n"
                            "You can now use Telegram to confirm your logins."
                        )
                    else:
                        data = response.json()
                        error_detail = data.get('detail', 'Unknown error')
                        print(f"DEBUG: API error={error_detail}")
                        await update.message.reply_text(
                            f"❌ Registration failed: {error_detail}"
                        )
            except Exception as e:
                print(f"DEBUG: Exception={str(e)}")
                import traceback
                traceback.print_exc()
                await update.message.reply_text(
                    f"❌ Error during registration: {str(e)}\n"
                    "Please try again or contact support."
                )
        else:
            # Welcome message
            print(f"DEBUG: No args, sending welcome message")
            await update.message.reply_text(
                "👋 Welcome to TeleLogin!\n\n"
                "This bot is used to confirm login requests.\n"
                "To get started, register on the TeleLogin platform and click the registration link."
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
                     f"Username: {username}\n"
                     f"Time: {asyncio.get_event_loop().time()}\n\n"
                     f"Do you want to confirm this login?",
                reply_markup=reply_markup
            )
        except Exception as e:
            print(f"Failed to send notification: {e}")
    
    async def confirm_login(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle login confirmation callback"""
        # TODO: Implement login confirmation logic
        pass
    
    async def start(self):
        """Initialize and start the bot"""
        # Initialize database
        await self.db.init_db()
        
        # Add handlers
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CallbackQueryHandler(self.button_callback))
        
        # Start polling
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
        
        # Run until stopped
        await asyncio.Event().wait()

if __name__ == "__main__":
    bot = TeleLoginBot()
    asyncio.run(bot.start())
