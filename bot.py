"""
ULP Searcher Bot - Daily Reset Version (3 CREDITS)
Complete ULP search bot with local engine and daily credits
"""

import os
import logging
import sqlite3
import threading
import io
import zipfile
import re
from datetime import datetime, time, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import glob

from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    ContextTypes, CallbackQueryHandler, filters,
    ConversationHandler, JobQueue
)

# ============================================================================
# CONFIGURATION
# ============================================================================

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_IDS = [int(id.strip()) for id in os.getenv('ADMIN_IDS', '').split(',') if id.strip()]
BOT_OWNER = "@iberic_owner"
BOT_NAME = "🔍 ULP Searcher Bot"
BOT_VERSION = "4.5 ENGLISH"
MAX_FREE_CREDITS = 3
RESET_HOUR = 0

PORT = int(os.getenv('PORT', 10000))

BASE_DIR = "bot_data"
DATA_DIR = os.path.join(BASE_DIR, "ulp_files")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
DB_PATH = os.path.join(BASE_DIR, "bot.db")

for directory in [BASE_DIR, DATA_DIR, UPLOAD_DIR]:
    os.makedirs(directory, exist_ok=True)

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(BASE_DIR, 'bot.log'), encoding='utf-8', mode='a')
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# FLASK APP
# ============================================================================

app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({"status": "online", "bot": BOT_NAME})

@app.route('/health')
def health():
    return jsonify({"status": "healthy"})

# ============================================================================
# SEARCH ENGINE - CON EXTRACCIÓN DE EMAIL:PASS
# ============================================================================

class SearchEngine:
    def __init__(self, data_dir: str = DATA_DIR):
        self.data_dir = data_dir
        self.data_files = []
        self.load_all_data()
    
    def load_all_data(self):
        self.data_files = glob.glob(os.path.join(self.data_dir, "*.txt"))
        logger.info(f"📂 Loaded {len(self.data_files)} files")
    
    def search_domain(self, domain: str, max_results: int = 5000) -> Tuple[int, List[str]]:
        """Search for domain - returns ALL lines including URLs"""
        results = []
        domain_lower = domain.lower()
        
        for file_path in self.data_files:
            if len(results) >= max_results:
                break
            
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        
                        # Search domain anywhere in the line
                        if domain_lower in line.lower():
                            results.append(line)
                        
                        if len(results) >= max_results:
                        break
            
            except Exception as e:
                logger.error(f"Error in {file_path}: {e}")
                continue
        
        return len(results), results
    
    def search_email_clean(self, email_or_domain: str, max_results: int = 1000) -> Tuple[int, List[str]]:
        """
        Search for email and return CLEAN email:pass format
        Removes URLs from lines like: url:email:pass
        """
        results = []
        search_term = email_or_domain.lower().strip()
        
        # Remove @ symbol if user included it
        if search_term.startswith('@'):
            search_term = search_term[1:]
        
        for file_path in self.data_files:
            if len(results) >= max_results:
                break
            
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        
                        line_lower = line.lower()
                        
                        # Check if search term is in the line
                        if search_term in line_lower:
                            # Extract clean email:pass from the line
                            clean_result = self.extract_clean_email_pass(line, search_term)
                            if clean_result:
                                results.append(clean_result)
                        
                        if len(results) >= max_results:
                            break
            
            except Exception as e:
                logger.error(f"Error in {file_path}: {e}")
                continue
        
        # Remove duplicates
        unique_results = []
        seen = set()
        for result in results:
            if result not in seen:
                seen.add(result)
                unique_results.append(result)
        
        return len(unique_results), unique_results[:max_results]
    
    def extract_clean_email_pass(self, line: str, search_term: str) -> Optional[str]:
        """
        Extract clean email:password from a line
        Handles formats like:
        - url:email:pass
        - http://site.com:email:pass
        - email:pass
        - email|pass
        Returns: email:password (cleaned) or None
        """
        # First, try to find email:password patterns
        email_patterns = [
            # Pattern for email:pass (with optional spaces)
            r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\s*[:|;]\s*([^\s]+)',
            # Pattern for email:pass after URL
            r'[a-zA-Z0-9.-]+\.(com|net|org|edu|gov|io|co|uk|de|fr|es|it|ru|br|ca|au|in|jp|cn)\s*[:|;]\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\s*[:|;]\s*([^\s]+)',
            # Pattern for URL:email:pass
            r'(?:https?://)?(?:www\.)?[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/\S*)?\s*[:|;]\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\s*[:|;]\s*([^\s]+)',
        ]
        
        for pattern in email_patterns:
            matches = re.findall(pattern, line, re.IGNORECASE)
            for match in matches:
                if len(match) == 2:
                    email, password = match
                elif len(match) == 3:
                    # For patterns that capture domain, email, password
                    _, email, password = match
                else:
                    continue
                
                # Check if search term matches email or domain
                email_lower = email.lower()
                if search_term in email_lower or f"@{search_term}" in email_lower:
                    return f"{email}:{password}"
        
        # If no pattern matched, try simple splitting
        parts = re.split(r'[:|;]', line)
        if len(parts) >= 3:
            # Likely format: something:email:pass
            for i in range(len(parts) - 1):
                # Check if this part looks like an email
                if '@' in parts[i] and '.' in parts[i]:
                    email = parts[i].strip()
                    password = parts[i + 1].strip()
                    email_lower = email.lower()
                    
                    if search_term in email_lower or f"@{search_term}" in email_lower:
                        return f"{email}:{password}"
        
        return None
    
    def get_stats(self) -> Dict:
        return {
            "total_files": len(self.data_files),
            "recent_files": []
        }
    
    def add_data_file(self, file_path: str) -> Tuple[bool, str]:
        try:
            import shutil
            filename = os.path.basename(file_path)
            dest_path = os.path.join(self.data_dir, filename)
            shutil.copy2(file_path, dest_path)
            self.load_all_data()
            return True, filename
        except Exception as e:
            return False, str(e)

# ============================================================================
# CREDIT SYSTEM (SAME AS BEFORE)
# ============================================================================

class CreditSystem:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.init_database()
    
    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_database(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    daily_credits INTEGER DEFAULT 3,
                    extra_credits INTEGER DEFAULT 0,
                    total_searches INTEGER DEFAULT 0,
                    join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_reset DATE DEFAULT CURRENT_DATE
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    amount INTEGER,
                    type TEXT,
                    description TEXT,
                    date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS daily_resets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reset_date DATE UNIQUE,
                    users_reset INTEGER DEFAULT 0,
                    reset_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.commit()
    
    def get_or_create_user(self, user_id: int, username: str = "", first_name: str = ""):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            user = cursor.fetchone()
            
            if user:
                self.check_daily_reset(user_id)
                return dict(user)
            
            cursor.execute('''
                INSERT INTO users (user_id, username, first_name, daily_credits, last_reset)
                VALUES (?, ?, ?, 3, DATE('now'))
            ''', (user_id, username, first_name))
            
            cursor.execute('''
                INSERT INTO transactions (user_id, amount, type, description)
                VALUES (?, ?, ?, ?)
            ''', (user_id, 3, 'daily_reset', '3 daily initial credits'))
            
            conn.commit()
            
            return {
                'user_id': user_id,
                'username': username,
                'first_name': first_name,
                'daily_credits': 3,
                'extra_credits': 0
            }
    
    def check_daily_reset(self, user_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute(
                'SELECT last_reset, daily_credits FROM users WHERE user_id = ?',
                (user_id,)
            )
            result = cursor.fetchone()
            
            if result:
                last_reset = result['last_reset']
                today = datetime.now().date()
                
                if last_reset != str(today):
                    cursor.execute('''
                        UPDATE users 
                        SET daily_credits = 3,
                            last_reset = DATE('now')
                        WHERE user_id = ?
                    ''', (user_id,))
                    
                    cursor.execute('''
                        INSERT INTO transactions (user_id, amount, type, description)
                        VALUES (?, ?, ?, ?)
                    ''', (user_id, 3, 'daily_reset', 'Daily reset to 3 credits'))
                    
                    conn.commit()
                    logger.info(f"🔄 Credits reset to 3 for user {user_id}")
    
    def get_user_credits(self, user_id: int) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT daily_credits, extra_credits FROM users WHERE user_id = ?',
                (user_id,)
            )
            result = cursor.fetchone()
            
            if result:
                self.check_daily_reset(user_id)
                
                cursor.execute(
                    'SELECT daily_credits, extra_credits FROM users WHERE user_id = ?',
                    (user_id,)
                )
                result = cursor.fetchone()
                return result['daily_credits'] + result['extra_credits']
            
            return 0
    
    def get_daily_credits_left(self, user_id: int) -> int:
        self.check_daily_reset(user_id)
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT daily_credits FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            return result['daily_credits'] if result else 0
    
    def has_enough_credits(self, user_id: int) -> bool:
        return self.get_user_credits(user_id) > 0
    
    def use_credits(self, user_id: int, search_type: str, query: str, results_count: int = 0):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            self.check_daily_reset(user_id)
            
            cursor.execute(
                'SELECT daily_credits, extra_credits FROM users WHERE user_id = ?',
                (user_id,)
            )
            result = cursor.fetchone()
            
            if not result:
                return False
            
            daily_credits = result['daily_credits']
            extra_credits = result['extra_credits']
            
            if daily_credits > 0:
                new_daily = daily_credits - 1
                new_extra = extra_credits
                credit_type = "daily"
            elif extra_credits > 0:
                new_daily = 0
                new_extra = extra_credits - 1
                credit_type = "extra"
            else:
                return False
            
            cursor.execute('''
                UPDATE users 
                SET daily_credits = ?,
                    extra_credits = ?,
                    total_searches = total_searches + 1
                WHERE user_id = ?
            ''', (new_daily, new_extra, user_id))
            
            cursor.execute('''
                INSERT INTO transactions 
                (user_id, amount, type, description)
                VALUES (?, ?, ?, ?)
            ''', (user_id, -1, 'search_used', f'{search_type}: {query} ({credit_type})'))
            
            conn.commit()
            return True
    
    def reset_all_daily_credits(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            today = datetime.now().date()
            
            cursor.execute('''
                SELECT COUNT(*) as count FROM users 
                WHERE last_reset != DATE(?) OR last_reset IS NULL
            ''', (today,))
            users_to_reset = cursor.fetchone()['count']
            
            if users_to_reset > 0:
                cursor.execute('''
                    UPDATE users 
                    SET daily_credits = 3,
                        last_reset = DATE(?)
                    WHERE last_reset != DATE(?) OR last_reset IS NULL
                ''', (today, today))
                
                cursor.execute('''
                    INSERT INTO daily_resets (reset_date, users_reset)
                    VALUES (?, ?)
                ''', (today, users_to_reset))
                
                conn.commit()
                logger.info(f"🔄 Reset daily credits for {users_to_reset} users")
                return users_to_reset
            
            return 0
    
    def add_credits_to_user(self, user_id: int, amount: int, admin_id: int, credit_type: str = 'extra') -> Tuple[bool, str]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute(
                'SELECT extra_credits FROM users WHERE user_id = ?',
                (user_id,)
            )
            result = cursor.fetchone()
            
            if not result:
                return False, "User not found"
            
            if credit_type == 'extra':
                cursor.execute(
                    'UPDATE users SET extra_credits = extra_credits + ? WHERE user_id = ?',
                    (amount, user_id)
                )
            else:
                cursor.execute(
                    'UPDATE users SET daily_credits = daily_credits + ? WHERE user_id = ?',
                    (amount, user_id)
                )
            
            cursor.execute('''
                INSERT INTO transactions 
                (user_id, amount, type, description)
                VALUES (?, ?, ?, ?)
            ''', (user_id, amount, f'admin_add_{credit_type}', f'{credit_type} credits added by admin {admin_id}'))
            
            conn.commit()
            return True, f"✅ {amount} {credit_type} credits added"
    
    def get_user_info(self, user_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            return dict(result) if result else None
    
    def get_all_users(self, limit: int = 50):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users ORDER BY join_date DESC LIMIT ?', (limit,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_bot_stats(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            stats = {}
            cursor.execute('SELECT COUNT(*) as count FROM users')
            stats['total_users'] = cursor.fetchone()['count']
            
            cursor.execute('SELECT COUNT(*) as count FROM transactions WHERE type = "search_used"')
            stats['total_searches'] = cursor.fetchone()['count']
            
            cursor.execute('SELECT SUM(daily_credits + extra_credits) as total FROM users')
            stats['total_credits'] = cursor.fetchone()['total'] or 0
            
            cursor.execute('SELECT reset_date, users_reset FROM daily_resets ORDER BY reset_date DESC LIMIT 7')
            stats['recent_resets'] = [dict(row) for row in cursor.fetchall()]
            
            return stats

# ============================================================================
# MAIN BOT - CON BÚSQUEDA LIMPIA
# ============================================================================

class ULPBot:
    def __init__(self, search_engine: SearchEngine, credit_system: CreditSystem):
        self.search_engine = search_engine
        self.credit_system = credit_system
        self.pending_searches = {}
    
    def escape_html(self, text: str) -> str:
        if not text:
            return ""
        text = str(text)
        text = text.replace('&', '&amp;')
        text = text.replace('<', '&lt;')
        text = text.replace('>', '&gt;')
        return text
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        user_info = self.credit_system.get_or_create_user(
            user_id=user.id,
            username=user.username or "",
            first_name=user.first_name or ""
        )
        
        total_credits = self.credit_system.get_user_credits(user.id)
        daily_credits = self.credit_system.get_daily_credits_left(user.id)
        extra_credits = total_credits - daily_credits
        stats = self.search_engine.get_stats()
        
        keyboard = [
            [InlineKeyboardButton("🔍 Search Domain (full lines)", callback_data="menu_search_domain")],
            [InlineKeyboardButton("📧 Search Email (clean email:pass)", callback_data="menu_search_email")],
            [InlineKeyboardButton("💰 My Credits", callback_data="menu_credits")],
            [InlineKeyboardButton("📋 /help", callback_data="menu_help")],
        ]
        
        if user.id in ADMIN_IDS:
            keyboard.append([InlineKeyboardButton("👑 Admin", callback_data="menu_admin")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = (
            f"<b>🔍 {BOT_NAME}</b>\n"
            f"<i>Version: {BOT_VERSION}</i>\n\n"
            f"Welcome <b>{self.escape_html(user.first_name)}</b>!\n\n"
            f"<b>Your Credits:</b>\n"
            f"• Daily: {daily_credits}/3 (reset at midnight UTC)\n"
            f"• Extra: {extra_credits}\n"
            f"• Total: {total_credits}\n\n"
            f"<b>Database:</b> {stats['total_files']} files loaded\n\n"
            f"<b>Two search modes:</b>\n"
            f"1. <b>Domain Search</b> - Full lines with URLs\n"
            f"2. <b>Email Search</b> - Clean email:password only"
        )
        
        await update.message.reply_html(message, reply_markup=reply_markup)
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = (
            f"<b>📖 {BOT_NAME} - HELP</b>\n\n"
            "<b>Available Commands:</b>\n"
            "/start - Start the bot\n"
            "/credits - Check your credits\n"
            "/stats - Bot statistics\n"
            "/help - This help message\n"
            "/domain <domain> - Search for domain (full lines)\n"
            "/email <email/domain> - Search for email (clean email:pass)\n\n"
            
            "<b>Two Search Types:</b>\n"
            "1. <b>Domain Search</b>\n"
            "   • Shows full lines including URLs\n"
            "   • Example: /domain example.com\n"
            "   • Shows: http://example.com:user@mail.com:pass123\n\n"
            
            "2. <b>Email Search</b>\n"
            "   • Shows ONLY clean email:password\n"
            "   • Removes URLs automatically\n"
            "   • Example: /email gmail.com\n"
            "   • Shows: user@gmail.com:password123\n\n"
            
            "<b>Credits System:</b>\n"
            f"• Every user gets {MAX_FREE_CREDITS} credits per day\n"
            "• Credits reset at midnight UTC\n"
            "• Extra credits can be added by admins\n\n"
            
            f"<b>Bot Owner:</b> {BOT_OWNER}\n"
            f"<b>Version:</b> {BOT_VERSION}"
        )
        
        await update.message.reply_html(help_text)
    
    async def credits_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        total_credits = self.credit_system.get_user_credits(user.id)
        daily_credits = self.credit_system.get_daily_credits_left(user.id)
        extra_credits = total_credits - daily_credits
        user_info = self.credit_system.get_user_info(user.id)
        
        message = (
            f"<b>💰 Your Credits</b>\n\n"
            f"<b>Daily Credits:</b> {daily_credits}/3\n"
            f"<b>Extra Credits:</b> {extra_credits}\n"
            f"<b>Total Credits:</b> {total_credits}\n\n"
            f"<b>Statistics:</b>\n"
            f"• Total searches: {user_info.get('total_searches', 0) if user_info else 0}\n"
            f"• Member since: {user_info.get('join_date', 'N/A') if user_info else 'N/A'}\n\n"
            f"<i>Daily credits reset at midnight UTC</i>"
        )
        
        await update.message.reply_html(message)
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        stats = self.credit_system.get_bot_stats()
        engine_stats = self.search_engine.get_stats()
        
        message = (
            f"<b>📊 {BOT_NAME} Statistics</b>\n\n"
            f"<b>Users:</b> {stats.get('total_users', 0)}\n"
            f"<b>Total Searches:</b> {stats.get('total_searches', 0)}\n"
            f"<b>Total Credits:</b> {stats.get('total_credits', 0)}\n"
            f"<b>Database Files:</b> {engine_stats.get('total_files', 0)}\n"
            f"<b>Bot Owner:</b> {BOT_OWNER}\n"
            f"<b>Version:</b> {BOT_VERSION}"
        )
        
        await update.message.reply_html(message)
    
    async def search_domain_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        
        if not context.args:
            await update.message.reply_html("Please provide a domain to search. Example: /domain example.com")
            return
        
        domain = ' '.join(context.args)
        await self.perform_search(update, user.id, 'domain', domain, domain)
    
    async def search_email_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        
        if not context.args:
            await update.message.reply_html("Please provide an email or domain to search. Example: /email gmail.com")
            return
        
        query = ' '.join(context.args)
        await self.perform_search(update, user.id, 'email', query, query)
    
    async def perform_search(self, update: Update, user_id: int, search_type: str, query: str, display_query: str):
        if not self.credit_system.has_enough_credits(user_id):
            await self.send_no_credits_message(update, user_id)
            return
        
        # Send initial message
        message = await update.message.reply_html(
            f"🔍 Searching for: <code>{self.escape_html(display_query)}</code>\n"
            f"⏳ Please wait..."
        )
        
        try:
            # Perform search based on type
            if search_type == 'domain':
                count, results = self.search_engine.search_domain(query)
                result_type = "domain matches"
                description = "Full lines with URLs"
            elif search_type == 'email':
                count, results = self.search_engine.search_email_clean(query)
                result_type = "clean email:password pairs"
                description = "URLs removed, only email:pass"
            else:
                await message.edit_text("❌ Invalid search type")
                return
            
            # Use credits
            success = self.credit_system.use_credits(user_id, search_type, query, count)
            
            if not success:
                await message.edit_text("❌ Error using credits")
                return
            
            # Get updated credits
            daily_credits = self.credit_system.get_daily_credits_left(user_id)
            
            if count == 0:
                await message.edit_text(
                    f"🔍 <b>Search Results</b>\n\n"
                    f"<b>Query:</b> <code>{self.escape_html(display_query)}</code>\n"
                    f"<b>Type:</b> {description}\n"
                    f"<b>Results:</b> 0\n\n"
                    f"No results found for your search.\n\n"
                    f"<i>Daily credits remaining: {daily_credits}/3</i>"
                )
                return
            
            # Prepare results
            if count <= 50:
                # Send results directly
                results_text = "\n".join([self.escape_html(r) for r in results[:50]])
                await message.edit_text(
                    f"🔍 <b>Search Results</b>\n\n"
                    f"<b>Query:</b> <code>{self.escape_html(display_query)}</code>\n"
                    f"<b>Type:</b> {description}\n"
                    f"<b>Results:</b> {count} {result_type}\n\n"
                    f"<pre>{results_text}</pre>\n\n"
                    f"<i>Daily credits remaining: {daily_credits}/3</i>"
                )
            else:
                # Send as file
                results_text = "\n".join(results[:1000])
                file_content = f"Query: {query}\nType: {description}\nTotal Results: {count}\n\n{results_text}"
                
                file_obj = io.BytesIO(file_content.encode('utf-8'))
                filename = f"{search_type}_{query.replace('@', '_at_').replace('.', '_dot_')}_{count}_results.txt"
                file_obj.name = filename
                
                await update.message.reply_document(
                    document=file_obj,
                    caption=(
                        f"🔍 <b>Search Results</b>\n\n"
                        f"<b>Query:</b> <code>{self.escape_html(display_query)}</code>\n"
                        f"<b>Type:</b> {description}\n"
                        f"<b>Results:</b> {count} {result_type}\n\n"
                        f"<i>Daily credits remaining: {daily_credits}/3</i>"
                    ),
                    parse_mode='HTML'
                )
                await message.delete()
                
        except Exception as e:
            logger.error(f"Search error: {e}")
            await message.edit_text(f"❌ Error during search: {str(e)}")
    
    async def send_no_credits_message(self, update: Update, user_id: int):
        daily_credits = self.credit_system.get_daily_credits_left(user_id)
        
        message = (
            f"❌ <b>No Credits Available</b>\n\n"
            f"You have used all your credits.\n\n"
            f"<b>Daily Credits:</b> {daily_credits}/3\n\n"
            f"Credits reset at midnight UTC.\n"
            f"Contact {BOT_OWNER} for extra credits."
        )
        
        await update.message.reply_html(message)
    
    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        user = update.effective_user
        
        if query.data == "menu_search_domain":
            await query.edit_message_text(
                "🔍 <b>Domain Search (Full Lines)</b>\n\n"
                "Send me a domain to search for.\n\n"
                "<b>Shows complete lines including URLs:</b>\n"
                "<code>http://example.com:user@mail.com:pass123</code>\n\n"
                "<i>Examples:</i>\n"
                "<code>example.com</code>\n"
                "<code>gmail.com</code>\n"
                "<code>@hotmail.com</code>\n\n"
                "<i>Use this to see complete database entries</i>",
                parse_mode='HTML'
            )
            context.user_data['awaiting_search'] = 'domain'
            
        elif query.data == "menu_search_email":
            await query.edit_message_text(
                "📧 <b>Email Search (Clean Format)</b>\n\n"
                "Send me an email or domain to search for.\n\n"
                "<b>Returns ONLY clean email:password format:</b>\n"
                "<code>user@gmail.com:password123</code>\n\n"
                "<b>Automatically removes URLs:</b>\n"
                "From: <code>http://site.com:user@gmail.com:pass123</code>\n"
                "To: <code>user@gmail.com:pass123</code>\n\n"
                "<i>Examples:</i>\n"
                "<code>user@example.com</code>\n"
                "<code>gmail.com</code> (all gmail accounts)\n"
                "<code>@hotmail.com</code>\n",
                parse_mode='HTML'
            )
            context.user_data['awaiting_search'] = 'email'
            
        elif query.data == "menu_credits":
            total_credits = self.credit_system.get_user_credits(user.id)
            daily_credits = self.credit_system.get_daily_credits_left(user.id)
            extra_credits = total_credits - daily_credits
            
            await query.edit_message_text(
                f"💰 <b>Your Credits</b>\n\n"
                f"<b>Daily Credits:</b> {daily_credits}/3\n"
                f"<b>Extra Credits:</b> {extra_credits}\n"
                f"<b>Total Credits:</b> {total_credits}\n\n"
                f"<i>Daily credits reset at midnight UTC</i>",
                parse_mode='HTML'
            )
            
        elif query.data == "menu_help":
            await self.help_command(update, context)
            
        elif query.data == "menu_admin" and user.id in ADMIN_IDS:
            keyboard = [
                [InlineKeyboardButton("📊 Bot Stats", callback_data="admin_stats")],
                [InlineKeyboardButton("👥 Users List", callback_data="admin_users")],
                [InlineKeyboardButton("➕ Add Credits", callback_data="admin_add")],
                [InlineKeyboardButton("📁 Add Data", callback_data="admin_data")],
                [InlineKeyboardButton("🔄 Reset Credits", callback_data="admin_reset")],
                [InlineKeyboardButton("⬅️ Back", callback_data="menu_back")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "👑 <b>Admin Panel</b>\n\n"
                "Select an option:",
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
            
        elif query.data == "admin_stats" and user.id in ADMIN_IDS:
            stats = self.credit_system.get_bot_stats()
            engine_stats = self.search_engine.get_stats()
            
            reset_info = ""
            if stats.get('recent_resets'):
                reset_info = "\n<b>Recent Resets:</b>\n"
                for reset in stats['recent_resets'][:3]:
                    reset_info += f"• {reset['reset_date']}: {reset['users_reset']} users\n"
            
            await query.edit_message_text(
                f"📊 <b>Admin Statistics</b>\n\n"
                f"<b>Users:</b> {stats.get('total_users', 0)}\n"
                f"<b>Total Searches:</b> {stats.get('total_searches', 0)}\n"
                f"<b>Total Credits:</b> {stats.get('total_credits', 0)}\n"
                f"<b>Database Files:</b> {engine_stats.get('total_files', 0)}\n"
                f"{reset_info}",
                parse_mode='HTML'
            )
            
        elif query.data == "menu_back":
            await self.start(update, context)
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        text = update.message.text.strip()
        
        if 'awaiting_search' in context.user_data:
            search_type = context.user_data['awaiting_search']
            del context.user_data['awaiting_search']
            
            await self.perform_search(update, user.id, search_type, text, text)
            return
        
        # Default response
        await update.message.reply_html(
            "Use /start to see the main menu or /help for instructions."
        )

# ============================================================================
# INITIALIZATION
# ============================================================================

def setup_application():
    """Setup and return the Telegram application"""
    
    # Initialize components
    search_engine = SearchEngine()
    credit_system = CreditSystem()
    bot = ULPBot(search_engine, credit_system)
    
    # Create application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("help", bot.help_command))
    application.add_handler(CommandHandler("credits", bot.credits_command))
    application.add_handler(CommandHandler("stats", bot.stats_command))
    application.add_handler(CommandHandler("domain", bot.search_domain_command))
    application.add_handler(CommandHandler("email", bot.search_email_command))
    
    application.add_handler(CallbackQueryHandler(bot.button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_message))
    
    return application, bot

# ============================================================================
# DAILY RESET FUNCTION
# ============================================================================

async def daily_reset_job(context: ContextTypes.DEFAULT_TYPE):
    """Reset daily credits for all users"""
    logger.info("🔄 Running daily credit reset...")
    
    try:
        if hasattr(context, 'bot_data') and 'ulp_bot' in context.bot_data:
            credit_system = context.bot_data['ulp_bot'].credit_system
        else:
            credit_system = CreditSystem()
        
        users_reset = credit_system.reset_all_daily_credits()
        logger.info(f"✅ Daily reset completed for {users_reset} users")
        
    except Exception as e:
        logger.error(f"❌ Error in daily reset: {e}")

# ============================================================================
# MAIN
# ============================================================================

def run():
    """Run the bot with Flask server"""
    
    # Setup Telegram bot
    application, bot = setup_application()
    
    # Store bot in application data for job access
    application.bot_data['ulp_bot'] = bot
    
    # Setup daily reset job
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_daily(
            daily_reset_job,
            time(hour=RESET_HOUR, minute=0, second=0),
            days=(0, 1, 2, 3, 4, 5, 6),
            name="daily_credit_reset"
        )
        logger.info(f"⏰ Daily reset scheduled for {RESET_HOUR}:00 UTC")
    
    # Start Flask in background
    def run_flask():
        app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)
    
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info(f"🌐 Flask server started on port {PORT}")
    
    # Start the bot
    logger.info("🤖 Starting ULP Search Bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    run()
