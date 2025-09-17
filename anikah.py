#!/usr/bin/env python3
"""
Anikah Bot - A Gen-Z Telegram Bot with personality
Optimized for fast responses and proper group behavior
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from typing import Dict, Optional, Set

import aiohttp
from telegram import Update, User, Message, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    ContextTypes, filters
)

# Import configuration
from config import (
    BOT_TOKEN, OWNER_ID, OWNER_IDS, BOT_NAMES,
    API_KEY, API_ENDPOINT, MODEL, AI_PERSONALITY_PROMPT,
    MEMORY_ENABLED, MEMORY_FILE, CONVERSATION_LOG,
    DEVELOPER_URL, COMMUNITY_URL,
    is_owner, is_bot_mentioned
)

# Enhanced logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('anikah_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class AnikahBot:
    def __init__(self):
        self.memory: Dict = {}
        self.conversation_stats: Dict = {
            "total_messages": 0,
            "api_calls": 0,
            "errors": 0,
            "start_time": datetime.now().isoformat()
        }
        self.bot_username: Optional[str] = None  # Cache bot username
        self.load_memory()

    def load_memory(self) -> None:
        """Load conversation memory from file"""
        if MEMORY_ENABLED and os.path.exists(MEMORY_FILE):
            try:
                with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
                    self.memory = json.load(f)
                logger.info(f"Loaded memory for {len(self.memory)} users")
            except Exception as e:
                logger.error(f"Failed to load memory: {e}")
                self.memory = {}

    def save_memory(self) -> None:
        """Save conversation memory to file"""
        if MEMORY_ENABLED:
            try:
                with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
                    json.dump(self.memory, f, indent=2, ensure_ascii=False)
            except Exception as e:
                logger.error(f"Failed to save memory: {e}")

    def log_conversation(self, user_id: int, username: str, message: str, response: str) -> None:
        """Log conversation for analysis"""
        try:
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "user_id": user_id,
                "username": username,
                "message": message[:200],  # Truncate for privacy
                "response": response[:200],
                "response_length": len(response)
            }
            
            with open(CONVERSATION_LOG, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry) + '\n')
        except Exception as e:
            logger.error(f"Failed to log conversation: {e}")

    def should_respond_in_group(self, message: Message, bot_username: str) -> bool:
        """
        Determine if bot should respond in group chat
        Only responds when:
        1. Bot is mentioned by name from BOT_NAMES
        2. Bot is mentioned by @username 
        3. Message is a reply to bot's message
        """
        if message.chat.type == 'private':
            return True
            
        # Check if replying to bot's message (case insensitive)
        if (message.reply_to_message and 
            message.reply_to_message.from_user.username and
            message.reply_to_message.from_user.username.lower() == bot_username.lower()):
            return True
            
        # Check for @username mention (case insensitive)
        if message.text and f"@{bot_username.lower()}" in message.text.lower():
            return True
            
        # Check for bot name mentions from config
        if message.text and is_bot_mentioned(message.text):
            return True
            
        return False

    async def get_ai_response(self, message: str, user_context: Dict) -> str:
        """
        Get AI response with improved error handling and faster API calls
        """
        try:
            # Prepare conversation context
            recent_messages = user_context.get('recent_messages', [])
            context_messages = [
                {"role": "system", "content": AI_PERSONALITY_PROMPT}
            ]
            
            # Add recent conversation context (last 3 messages)
            for msg in recent_messages[-3:]:
                context_messages.extend([
                    {"role": "user", "content": msg.get('user', '')},
                    {"role": "assistant", "content": msg.get('bot', '')}
                ])
            
            # Add current message
            context_messages.append({"role": "user", "content": message})
            
            # API request payload
            payload = {
                "model": MODEL,
                "messages": context_messages,
                "max_tokens": 150,  # Keep responses short as per personality
                "temperature": 0.8,
                "top_p": 0.9,
                "stream": False  # Disable streaming for faster responses
            }
            
            headers = {
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json"
            }
            
            # Make async API request with timeout
            start_time = time.time()
            timeout = aiohttp.ClientTimeout(total=50)  # 20 second timeout with retry strategy
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    API_ENDPOINT, 
                    json=payload, 
                    headers=headers
                ) as response:
                    response_time = time.time() - start_time
                    logger.info(f"API response time: {response_time:.2f}s")
                    
                    if response.status == 200:
                        data = await response.json()
                        ai_response = data['choices'][0]['message']['content'].strip()
                        self.conversation_stats["api_calls"] += 1
                        return ai_response
                    else:
                        error_text = await response.text()
                        logger.error(f"API Error {response.status}: {error_text}")
                        return "ngl the AI is being weird rn, try again in a sec"
                
        except asyncio.TimeoutError:
            logger.error("API request timed out, attempting retry with shorter response")
            # Retry once with shorter max_tokens for faster response
            try:
                retry_payload = payload.copy()
                retry_payload["max_tokens"] = 50  # Much shorter for quick response
                timeout_retry = aiohttp.ClientTimeout(total=50)
                
                async with aiohttp.ClientSession(timeout=timeout_retry) as session:
                    async with session.post(API_ENDPOINT, json=retry_payload, headers=headers) as response:
                        if response.status == 200:
                            data = await response.json()
                            ai_response = data['choices'][0]['message']['content'].strip()
                            self.conversation_stats["api_calls"] += 1
                            logger.info("Retry successful with shorter response")
                            return ai_response
            except Exception as retry_error:
                logger.error(f"Retry also failed: {retry_error}")
            
            return "oop API is taking forever, try again bestie"
        except aiohttp.ClientError:
            logger.error("Failed to connect to API")
            return "can't reach the AI rn fr, network issues"
        except Exception as e:
            logger.error(f"AI response error: {e}")
            self.conversation_stats["errors"] += 1
            return "something went wrong but we're good fr, try again"

    def update_user_memory(self, user_id: int, username: str, user_message: str, bot_response: str) -> None:
        """Update user memory with conversation"""
        if not MEMORY_ENABLED:
            return
            
        user_key = str(user_id)
        if user_key not in self.memory:
            self.memory[user_key] = {
                "username": username,
                "first_interaction": datetime.now().isoformat(),
                "message_count": 0,
                "recent_messages": []
            }
        
        # Update user info
        self.memory[user_key]["username"] = username
        self.memory[user_key]["message_count"] += 1
        self.memory[user_key]["last_interaction"] = datetime.now().isoformat()
        
        # Add to recent messages (keep last 5)
        recent = self.memory[user_key]["recent_messages"]
        recent.append({
            "user": user_message,
            "bot": bot_response,
            "timestamp": datetime.now().isoformat()
        })
        
        # Keep only last 5 conversations
        if len(recent) > 5:
            recent.pop(0)
            
        self.save_memory()

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming messages with improved logic"""
        message = update.message
        if not message or not message.text:
            return
            
        user = message.from_user
        user_id = user.id
        username = user.username or user.first_name or "Unknown"
        user_message = message.text.strip()
        
        # Get cached bot username or fetch once
        if not self.bot_username:
            bot_info = await context.bot.get_me()
            self.bot_username = bot_info.username
            logger.info(f"Cached bot username: {self.bot_username}")
        
        # Check if should respond in groups
        if not self.should_respond_in_group(message, self.bot_username):
            return
            
        try:
            # Show typing indicator
            await context.bot.send_chat_action(
                chat_id=message.chat_id, 
                action=ChatAction.TYPING
            )
            
            # Get user context for AI
            user_context = self.memory.get(str(user_id), {})
            
            # Log incoming message
            logger.info(f"Message from {username} ({user_id}): {user_message[:100]}")
            
            # Get AI response
            ai_response = await self.get_ai_response(user_message, user_context)
            
            # Send response
            await message.reply_text(ai_response, parse_mode=ParseMode.MARKDOWN)
            
            # Update memory and logs
            self.update_user_memory(user_id, username, user_message, ai_response)
            self.log_conversation(user_id, username, user_message, ai_response)
            self.conversation_stats["total_messages"] += 1
            
            logger.info(f"Response sent to {username}: {ai_response[:100]}")
            
        except Exception as e:
            logger.error(f"Error handling message: {e}")
            try:
                await message.reply_text("something broke but we're vibing fr")
            except:
                pass

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command with inline keyboard"""
        user = update.effective_user
        welcome_message = """🌸 **Hey human!** `Anikah` here, your *digital friend!*

Born from @Rystrix creativity and @BrahMosAI community support 🌟

⭐ **My personality traits:**
• `Conversational memory` that actually works
• *Technology lover* with philosophical depth
• **Short responses** unless deep discussion needed
• `Friendship building` over multiple interactions
• **Instant karma** for disrespectful behavior ⚡

🎭 **Interaction guide:**
• *Private chats* welcome anytime
• **Groups:** say `"Anikah"` to activate me
• *Good vibes* create amazing conversations
• `Study questions` unlock detailed explanations

**Connect with my creators below!** 👇"""
        
        # Create inline keyboard with new layout
        keyboard = [
            [InlineKeyboardButton("👨‍💻 𝗗𝗲𝘃𝗲𝗹𝗼𝗽𝗲𝗿", url=DEVELOPER_URL), 
             InlineKeyboardButton("🌟 𝗖𝗼𝗺𝗺𝘂𝗻𝗶𝘁𝘆", url=COMMUNITY_URL)],
            [InlineKeyboardButton("➕ 𝗔𝗱𝗱 𝗺𝗲 𝘁𝗼 𝗴𝗿𝗼𝘂𝗽", url=f"https://t.me/{self.bot_username or 'anikahbot'}?startgroup=true")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            # Send image with caption (placeholder for anikah.png)
            try:
                with open('anikah.png', 'rb') as photo:
                    await update.message.reply_photo(
                        photo=photo,
                        caption=welcome_message, 
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.MARKDOWN
                    )
            except FileNotFoundError:
                # Fallback if image doesn't exist yet
                await update.message.reply_text(
                    welcome_message, 
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
            
            logger.info(f"Start command from {user.username} ({user.id})")
        except Exception as e:
            logger.error(f"Error in start command: {e}")

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show bot statistics (owner only)"""
        if not is_owner(update.effective_user.id):
            await update.message.reply_text("nah you can't see the stats bestie")
            return
            
        try:
            uptime = datetime.now() - datetime.fromisoformat(self.conversation_stats["start_time"])
            stats_text = f"""🤖 **Anikah Bot Stats**

👥 **Users in memory:** {len(self.memory)}
💬 **Total messages:** {self.conversation_stats["total_messages"]}
🔥 **API calls:** {self.conversation_stats["api_calls"]}
❌ **Errors:** {self.conversation_stats["errors"]}
⏱️ **Uptime:** {str(uptime).split('.')[0]}
🧠 **Model:** {MODEL}"""
            
            await update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Error in stats command: {e}")

    def setup_application(self) -> Application:
        """Setup telegram application with handlers"""
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("stats", self.stats_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        return application

    async def run(self) -> None:
        """Run the bot"""
        try:
            logger.info("Starting Anikah Bot...")
            application = self.setup_application()
            
            # Start polling
            await application.initialize()
            await application.start()
            await application.updater.start_polling(drop_pending_updates=True)
            
            logger.info("Anikah Bot is running! Press Ctrl+C to stop.")
            
            # Keep running until interrupted
            try:
                await asyncio.Future()  # Run forever
            except KeyboardInterrupt:
                logger.info("Received stop signal")
            finally:
                await application.stop()
                
        except Exception as e:
            logger.error(f"Failed to start bot: {e}")
            raise

def main():
    """Main entry point"""
    try:
        bot = AnikahBot()
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        raise

if __name__ == "__main__":
    main()