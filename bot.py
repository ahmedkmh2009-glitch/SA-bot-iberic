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
BOT_OWNER = "@iberic_owner"  # ✅ CHANGED TO YOUR USERNAME
BOT_NAME = "🔍 ULP Searcher Bot"
BOT_VERSION = "4.3 ENGLISH"
MAX_FREE_CREDITS = 3  # ✅ 3 daily credits per user
RESET_HOUR = 0  # Reset hour (0 = midnight)

PORT = int(os.getenv('PORT', 10000))

BASE_DIR = "bot_data"
DATA_DIR = os.path.join(BASE_DIR, "ulp_files")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
DB_PATH = os.path.join(BASE_DIR, "bot.db")

for directory in [BASE_DIR, DATA_DIR, UPLOAD_DIR]:
    os.makedirs(directory, exist_ok=True)

CHOOSING_FORMAT, ADMIN_ADD_CREDITS = range(2)

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
# SEARCH ENGINE - MEJORADO
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
        """Search for domain anywhere in the line"""
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
    
    def search_email(self, email: str, max_results: int = 1000) -> Tuple[int, List[str]]:
        """
        Search for email and return results in email:pass format
        
        Supports formats like:
        - email:pass
        - email|pass
        - email;pass
        - email pass
        - email\tpass
        """
        results = []
        email_lower = email.lower().strip()
        
        # Remove @ symbol if user included it
        if email_lower.startswith('@'):
            email_lower = email_lower[1:]
        
        for file_path in self.data_files:
            if len(results) >= max_results:
                break
            
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        
                        # Normalize line to handle different separators
                        normalized_line = self.normalize_credentials_line(line)
                        
                        # Check if email is in the line
                        if email_lower in normalized_line.lower():
                            # Extract email:pass format
                            email_pass_line = self.extract_email_pass(line, email_lower)
                            if email_pass_line:
                                results.append(email_pass_line)
                        
                        if len(results) >= max_results:
                            break
            
            except Exception as e:
                logger.error(f"Error in {file_path}: {e}")
                continue
        
        return len(results), results
    
    def normalize_credentials_line(self, line: str) -> str:
        """Normalize different credential formats to email:pass format"""
        # Replace common separators with colon
        line = line.replace('|', ':')
        line = line.replace(';', ':')
        line = line.replace('\t', ':')
        
        # Replace multiple spaces with colon
        if ' ' in line and ':' not in line:
            parts = line.split()
            if len(parts) >= 2:
                line = f"{parts[0]}:{parts[1]}"
        
        return line
    
    def extract_email_pass(self, original_line: str, search_email: str) -> str:
        """
        Extract email:password from a line
        Returns formatted string or empty if not found
        """
        # Try to find email and password in the line
        line_lower = original_line.lower()
        
        # Check different formats
        formats_to_try = [':', '|', ';', '\t', ' ']
        
        for separator in formats_to_try:
            if separator in original_line:
                parts = original_line.split(separator)
                if len(parts) >= 2:
                    # Check if first part contains the email
                    if search_email in parts[0].lower():
                        return f"{parts[0].strip()}:{parts[1].strip()}"
                    # Check if email is in any part
                    for i in range(len(parts)):
                        if search_email in parts[i].lower() and i < len(parts) - 1:
                            return f"{parts[i].strip()}:{parts[i+1].strip()}"
        
        # If no separator found, try to extract email pattern
        email_pattern = r'[\w\.-]+@[\w\.-]+\.\w+'
        emails = re.findall(email_pattern, original_line, re.IGNORECASE)
        
        if emails:
            # Take the first email that matches
            for email in emails:
                if search_email in email.lower():
                    # Try to extract password after email
                    idx = original_line.lower().find(email.lower())
                    if idx != -1:
                        remaining = original_line[idx + len(email):].strip()
                        # Take first word after email as password
                        if remaining:
                            # Remove any separators
                            password = re.split(r'[:|;\s\t]', remaining)[0]
                            return f"{email.strip()}:{password.strip()}"
        
        return original_line.strip()
    
    def search_dni(self, dni: str, max_results: int = 1000) -> Tuple[int, List[str]]:
        results = []
        dni_lower = dni.lower()
        
        for file_path in self.data_files:
            if len(results) >= max_results:
                break
            
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        
                        # Search DNI anywhere
                        if dni_lower in line.lower():
                            results.append(line)
                        
                        if len(results) >= max_results:
                            break
            
            except Exception as e:
                logger.error(f"Error in {file_path}: {e}")
                continue
        
        return len(results), results
    
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
# CREDIT SYSTEM WITH DAILY RESET (3 CREDITS) - SIN CAMBIOS
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
# MAIN BOT - MEJORADO PARA EMAIL:PASS
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
            [InlineKeyboardButton("🔍 Search Domain", callback_data="menu_search")],
            [InlineKeyboardButton("📧 Search Email (email:pass)", callback_data="menu_email")],  # ✅ Actualizado
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
            f"<b>Email search returns results in email:password format!</b>"
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
            "/domain <domain> - Search for domain\n"
            "/email <email> - Search for email (returns email:password)\n\n"
            
            "<b>How to Search:</b>\n"
            "1. Use /domain <domain> to search for a domain\n"
            "2. Use /email <email> to search for an email\n"
            "   • Returns results in email:password format\n"
            "   • Supports: email:pass, email|pass, email;pass\n"
            "3. Or use the buttons in the main menu\n\n"
            
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
            await update.message.reply_html("Please provide an email to search. Example: /email user@example.com")
            return
        
        email = ' '.join(context.args)
        await self.perform_search(update, user.id, 'email', email, email)
    
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
            # Perform search
            if search_type == 'domain':
                count, results = self.search_engine.search_domain(query)
                result_type = "domain matches"
            elif search_type == 'email':
                count, results = self.search_engine.search_email(query)
                result_type = "email:password pairs"
            elif search_type == 'dni':
                count, results = self.search_engine.search_dni(query)
                result_type = "DNI matches"
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
                    f"<b>Results:</b> 0 {result_type}\n\n"
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
                    f"<b>Results:</b> {count} {result_type}\n\n"
                    f"<pre>{results_text}</pre>\n\n"
                    f"<i>Daily credits remaining: {daily_credits}/3</i>"
                )
            else:
                # Send as file
                results_text = "\n".join(results[:1000])
                file_content = f"Query: {query}\nTotal Results: {count}\nType: {result_type}\n\n{results_text}"
                
                file_obj = io.BytesIO(file_content.encode('utf-8'))
                filename = f"{search_type}_{query.replace('@', '_at_').replace('.', '_dot_')}_{count}_results.txt"
                file_obj.name = filename
                
                await update.message.reply_document(
                    document=file_obj,
                    caption=(
                        f"🔍 <b>Search Results</b>\n\n"
                        f"<b>Query:</b> <code>{self.escape_html(display_query)}</code>\n"
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
        
        if query.data == "menu_search":
            await query.edit_message_text(
                "🔍 <b>Domain Search</b>\n\n"
                "Send me a domain to search for.\n\n"
                "<i>Examples:</i>\n"
                "<code>example.com</code>\n"
                "<code>gmail.com</code>\n"
                "<code>@hotmail.com</code>",
                parse_mode='HTML'
            )
            context.user_data['awaiting_search'] = 'domain'
            
        elif query.data == "menu_email":
            await query.edit_message_text(
                "📧 <b>Email Search</b>\n\n"
                "Send me an email address to search for.\n\n"
                "<b>Returns results in email:password format!</b>\n\n"
                "<i>Examples:</i>\n"
                "<code>user@example.com</code>\n"
                "<code>name@gmail.com</code>\n"
                "<code>@hotmail.com</code> (for all hotmail)\n\n"
                "<i>Supports: email:pass, email|pass, email;pass</i>",
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
