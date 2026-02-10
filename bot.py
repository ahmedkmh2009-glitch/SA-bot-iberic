"""
ULP Searcher Bot - COMPLETE ENGLISH VERSION
Complete ULP search bot with all commands in English
"""

import os
import logging
import sqlite3
import threading
import io
import zipfile
import re
import uuid
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
BOT_OWNER = "@iberic_owner"  # ✅ Owner for support
BOT_SUPPORT = "@iberic_owner"  # ✅ Support contact
BOT_NAME = "🔍 ULP Searcher Bot"
BOT_VERSION = "6.2 ENGLISH"
MAX_FREE_CREDITS = 2  # 2 free credits
REFERRAL_CREDITS = 1  # 1 credit per referral
RESET_HOUR = 0  # Midnight UTC

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
# SEARCH ENGINE - COMPLETE WITH DNI:pass SEARCH
# ============================================================================

class SearchEngine:
    def __init__(self, data_dir: str = DATA_DIR):
        self.data_dir = data_dir
        self.data_files = []
        self.load_all_data()
    
    def load_all_data(self):
        self.data_files = glob.glob(os.path.join(self.data_dir, "*.txt"))
        logger.info(f"📂 Loaded {len(self.data_files)} files")
    
    def search_all_formats(self, query: str, max_results: int = 10000) -> Tuple[int, List[str]]:
        """Search for query - returns ALL lines (with URLs)"""
        results = []
        query_lower = query.lower()
        
        for file_path in self.data_files:
            if len(results) >= max_results:
                break
            
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        
                        if query_lower in line.lower():
                            results.append(line)
                        
                        if len(results) >= max_results:
                            break
            
            except Exception as e:
                logger.error(f"Error in {file_path}: {e}")
                continue
        
        return len(results), results
    
    def search_email_only(self, email: str, max_results: int = 1000) -> Tuple[int, List[str]]:
        """Search for specific email"""
        results = []
        email_lower = email.lower().strip()
        
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
                        
                        if email_lower in line_lower:
                            clean_result = self.extract_clean_email_pass(line, email_lower)
                            if clean_result:
                                results.append(clean_result)
                        
                        if len(results) >= max_results:
                            break
            
            except Exception as e:
                logger.error(f"Error in {file_path}: {e}")
                continue
        
        unique_results = []
        seen = set()
        for result in results:
            if result not in seen:
                seen.add(result)
                unique_results.append(result)
        
        return len(unique_results), unique_results[:max_results]
    
    def search_login(self, login: str, max_results: int = 1000) -> Tuple[int, List[str]]:
        """Search for login (username)"""
        results = []
        login_lower = login.lower().strip()
        
        for file_path in self.data_files:
            if len(results) >= max_results:
                break
            
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        
                        parts = re.split(r'[:|;]', line)
                        if len(parts) >= 2 and login_lower in parts[0].lower():
                            results.append(line)
                        
                        if len(results) >= max_results:
                            break
            
            except Exception as e:
                logger.error(f"Error in {file_path}: {e}")
                continue
        
        return len(results), results
    
    def search_password(self, password: str, max_results: int = 1000) -> Tuple[int, List[str]]:
        """Search for password"""
        results = []
        pass_lower = password.lower().strip()
        
        for file_path in self.data_files:
            if len(results) >= max_results:
                break
            
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        
                        parts = re.split(r'[:|;]', line)
                        if len(parts) >= 2 and pass_lower in parts[1].lower():
                            results.append(line)
                        
                        if len(results) >= max_results:
                            break
            
            except Exception as e:
                logger.error(f"Error in {file_path}: {e}")
                continue
        
        return len(results), results
    
    def search_dni_domain(self, domain: str, max_results: int = 1000) -> Tuple[int, List[str]]:
        """
        Search for DNI:password combos from specific domain
        Example: /dni gmail.com finds DNI:pass from @gmail.com accounts
        """
        results = []
        domain_lower = domain.lower().strip()
        
        # Clean domain (remove @ if present)
        if domain_lower.startswith('@'):
            domain_lower = domain_lower[1:]
        
        # DNI patterns (Spanish ID formats)
        dni_patterns = [
            r'\b\d{8}[A-Z]\b',                     # 12345678A
            r'\b\d{7}[A-Z]\b',                     # 1234567A
            r'\b\d{8}-[A-Z]\b',                    # 12345678-A
            r'\b\d{7}-[A-Z]\b',                    # 1234567-A
            r'\b\d{1,2}\.\d{3}\.\d{3}-[A-Z]\b',    # 12.345.678-A
            r'\b\d{8}[a-zA-Z]\b',                  # 12345678a
        ]
        
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
                        
                        # Check if domain is in the line
                        if f"@{domain_lower}" in line_lower or domain_lower in line_lower:
                            # Try to extract DNI:password combos
                            dni_combo = self.extract_dni_password(line, domain_lower)
                            if dni_combo:
                                results.append(dni_combo)
                        
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
    
    def extract_dni_password(self, line: str, domain: str) -> Optional[str]:
        """
        Extract DNI:password from a line containing the domain
        Supports formats like:
        - DNI:password
        - email@domain.com:password (extract DNI from email or password)
        - DNI|password
        - something:DNI:password
        """
        # First, try to find DNI:password pattern
        dni_pattern = r'(\b\d{7,8}[A-Za-z]?\b)\s*[:|;]\s*([^\s]+)'
        matches = re.findall(dni_pattern, line, re.IGNORECASE)
        
        for match in matches:
            dni, password = match
            # Check if line contains the domain
            if domain in line.lower():
                return f"{dni.upper()}:{password}"
        
        # If no direct DNI:pass found, try to find email:pass and check if email contains DNI
        email_pattern = r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\s*[:|;]\s*([^\s]+)'
        email_matches = re.findall(email_pattern, line, re.IGNORECASE)
        
        for email, password in email_matches:
            # Check if email contains the domain
            if domain in email.lower():
                # Try to extract DNI from email or password
                # Check if email starts with DNI
                email_local = email.split('@')[0]
                
                # Check if local part is a DNI
                if re.match(r'\d{7,8}[A-Za-z]?$', email_local):
                    return f"{email_local.upper()}:{password}"
                
                # Check if password is a DNI
                if re.match(r'\d{7,8}[A-Za-z]?$', password):
                    return f"{password.upper()}:{email}"
        
        # Try to find DNI in any position with password
        parts = re.split(r'[:|;]', line)
        if len(parts) >= 2:
            # Check each part for DNI
            for i in range(len(parts) - 1):
                current_part = parts[i].strip()
                next_part = parts[i + 1].strip() if i + 1 < len(parts) else ""
                
                # Check if current part looks like DNI
                if re.match(r'^\d{7,8}[A-Za-z]?$', current_part):
                    # Check if domain is in the line
                    if domain in line.lower():
                        return f"{current_part.upper()}:{next_part}"
                
                # Check if next part looks like DNI
                if re.match(r'^\d{7,8}[A-Za-z]?$', next_part):
                    # Check if domain is in the line
                    if domain in line.lower():
                        return f"{next_part.upper()}:{current_part}"
        
        return None
    
    def extract_clean_email_pass(self, line: str, search_term: str) -> Optional[str]:
        """Extract clean email:password from a line"""
        email_patterns = [
            r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\s*[:|;]\s*([^\s]+)',
            r'(?:https?://)?(?:www\.)?[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/\S*)?\s*[:|;]\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\s*[:|;]\s*([^\s]+)',
        ]
        
        for pattern in email_patterns:
            matches = re.findall(pattern, line, re.IGNORECASE)
            for match in matches:
                if len(match) == 2:
                    email, password = match
                elif len(match) == 3:
                    _, email, password = match
                else:
                    continue
                
                email_lower = email.lower()
                if search_term in email_lower or f"@{search_term}" in email_lower:
                    return f"{email}:{password}"
        
        parts = re.split(r'[:|;]', line)
        if len(parts) >= 3:
            for i in range(len(parts) - 1):
                if '@' in parts[i] and '.' in parts[i]:
                    email = parts[i].strip()
                    password = parts[i + 1].strip()
                    email_lower = email.lower()
                    
                    if search_term in email_lower or f"@{search_term}" in email_lower:
                        return f"{email}:{password}"
        
        return None
    
    def get_stats(self) -> Dict:
        total_lines = 0
        total_size = 0
        
        for file_path in self.data_files:
            try:
                size = os.path.getsize(file_path)
                total_size += size
                
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    total_lines += sum(1 for _ in f)
            except:
                pass
        
        return {
            "total_files": len(self.data_files),
            "total_lines": total_lines,
            "total_size_mb": total_size / (1024 * 1024)
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
# CREDIT SYSTEM WITH REFERRALS
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
                    daily_credits INTEGER DEFAULT 2,
                    extra_credits INTEGER DEFAULT 0,
                    total_searches INTEGER DEFAULT 0,
                    referrals INTEGER DEFAULT 0,
                    referral_code TEXT UNIQUE,
                    referred_by INTEGER,
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
    
    def get_or_create_user(self, user_id: int, username: str = "", first_name: str = "", referred_by: int = None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            user = cursor.fetchone()
            
            if user:
                self.check_daily_reset(user_id)
                return dict(user)
            
            referral_code = str(uuid.uuid4())[:8].upper()
            
            cursor.execute('''
                INSERT INTO users (user_id, username, first_name, daily_credits, referral_code, referred_by)
                VALUES (?, ?, ?, 2, ?, ?)
            ''', (user_id, username, first_name, referral_code, referred_by))
            
            cursor.execute('''
                INSERT INTO transactions (user_id, amount, type, description)
                VALUES (?, ?, ?, ?)
            ''', (user_id, 2, 'welcome', '2 free welcome credits'))
            
            if referred_by:
                cursor.execute('''
                    UPDATE users 
                    SET referrals = referrals + 1,
                        extra_credits = extra_credits + 1
                    WHERE user_id = ?
                ''', (referred_by,))
                
                cursor.execute('''
                    INSERT INTO transactions (user_id, amount, type, description)
                    VALUES (?, ?, ?, ?)
                ''', (referred_by, 1, 'referral', f'Referral credit for user {user_id}'))
            
            conn.commit()
            
            return {
                'user_id': user_id,
                'username': username,
                'first_name': first_name,
                'daily_credits': 2,
                'extra_credits': 0,
                'referral_code': referral_code,
                'referred_by': referred_by
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
                        SET daily_credits = 2,
                            last_reset = DATE('now')
                        WHERE user_id = ?
                    ''', (user_id,))
                    
                    cursor.execute('''
                        INSERT INTO transactions (user_id, amount, type, description)
                        VALUES (?, ?, ?, ?)
                    ''', (user_id, 2, 'daily_reset', 'Daily reset to 2 credits'))
                    
                    conn.commit()
                    logger.info(f"🔄 Credits reset to 2 for user {user_id}")
    
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
    
    def get_user_info(self, user_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            return dict(result) if result else None
    
    def get_referral_info(self, user_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT referral_code FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            
            if not result:
                return None
            
            referral_code = result['referral_code']
            
            cursor.execute('SELECT COUNT(*) as count FROM users WHERE referred_by = ?', (user_id,))
            referrals_count = cursor.fetchone()['count']
            
            return {
                'referral_code': referral_code,
                'referrals_count': referrals_count,
                'referral_link': f"https://t.me/{BOT_NAME.replace(' ', '')}?start={referral_code}"
            }
    
    def add_credits_to_user(self, user_id: int, amount: int, admin_id: int, credit_type: str = 'extra') -> Tuple[bool, str]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
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
            
            cursor.execute('SELECT SUM(referrals) as total FROM users')
            stats['total_referrals'] = cursor.fetchone()['total'] or 0
            
            cursor.execute('SELECT reset_date, users_reset FROM daily_resets ORDER BY reset_date DESC LIMIT 7')
            stats['recent_resets'] = [dict(row) for row in cursor.fetchall()]
            
            return stats

# ============================================================================
# MAIN BOT - WITH DNI DOMAIN SEARCH
# ============================================================================

class ULPBot:
    def __init__(self, search_engine: SearchEngine, credit_system: CreditSystem):
        self.search_engine = search_engine
        self.credit_system = credit_system
    
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
        args = context.args
        
        referred_by = None
        if args and len(args) > 0:
            referral_code = args[0]
            with self.credit_system.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT user_id FROM users WHERE referral_code = ?', (referral_code,))
                result = cursor.fetchone()
                if result:
                    referred_by = result['user_id']
        
        user_info = self.credit_system.get_or_create_user(
            user_id=user.id,
            username=user.username or "",
            first_name=user.first_name or "",
            referred_by=referred_by
        )
        
        total_credits = self.credit_system.get_user_credits(user.id)
        daily_credits = self.credit_system.get_daily_credits_left(user.id)
        extra_credits = total_credits - daily_credits
        stats = self.search_engine.get_stats()
        
        welcome_msg = ""
        if referred_by:
            welcome_msg = "\n🎉 You joined using a referral link! +1 credit for your friend!"
        
        keyboard = [
            [InlineKeyboardButton("🔍 /search - Search Domain", callback_data="start_search")],
            [InlineKeyboardButton("💰 /mycredits - My Credits", callback_data="menu_credits")],
            [InlineKeyboardButton("📋 /help - Help", callback_data="menu_help")],
        ]
        
        if user.id in ADMIN_IDS:
            keyboard.append([InlineKeyboardButton("👑 Admin Panel", callback_data="menu_admin")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = (
            f"<b>🔍 {BOT_NAME}</b>\n"
            f"<i>Version: {BOT_VERSION}</i>\n\n"
            f"Welcome <b>{self.escape_html(user.first_name)}</b>!{welcome_msg}\n\n"
            f"<b>Your Credits:</b>\n"
            f"• Daily: {daily_credits}/2 (reset at midnight UTC)\n"
            f"• Extra: {extra_credits}\n"
            f"• Total: {total_credits}\n\n"
            f"<b>Database Stats:</b>\n"
            f"• Files: {stats['total_files']:,}\n"
            f"• Lines: {stats['total_lines']:,}\n"
            f"• Size: {stats['total_size_mb']:,.1f} MB\n\n"
            f"Use <b>/search</b> to start searching!"
        )
        
        await update.message.reply_html(message, reply_markup=reply_markup)
    
    # ============================================================================
    # SEARCH COMMANDS
    # ============================================================================
    
    async def search_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Main search command with format options"""
        user = update.effective_user
        
        if not context.args:
            await update.message.reply_html(
                "🔍 <b>Search Command</b>\n\n"
                "Usage: <code>/search [query]</code>\n\n"
                "<i>Examples:</i>\n"
                "<code>/search example.com</code>\n"
                "<code>/search user@gmail.com</code>\n"
                "<code>/search @hotmail.com</code>\n\n"
                "Then choose your preferred format!"
            )
            return
        
        query = ' '.join(context.args)
        
        keyboard = [
            [
                InlineKeyboardButton("📧 Email:Pass Only", callback_data=f"format_clean:{query}"),
                InlineKeyboardButton("🌐 URL:Email:Pass", callback_data=f"format_full:{query}")
            ],
            [
                InlineKeyboardButton("👤 Login:Pass", callback_data=f"format_login:{query}"),
                InlineKeyboardButton("📧 Email Only", callback_data=f"format_email:{query}")
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_search")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_html(
            f"🔍 <b>Search Query:</b> <code>{self.escape_html(query)}</code>\n\n"
            f"<b>Choose result format:</b>\n"
            f"1. <b>Email:Pass Only</b> - Clean email:password\n"
            f"2. <b>URL:Email:Pass</b> - Full lines with URLs\n"
            f"3. <b>Login:Pass</b> - Username:password\n"
            f"4. <b>Email Only</b> - Email addresses only\n\n"
            f"<i>Your credits: {self.credit_system.get_user_credits(user.id)}</i>",
            reply_markup=reply_markup
        )
    
    async def email_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Search by email"""
        user = update.effective_user
        
        if not context.args:
            await update.message.reply_html(
                "📧 <b>Email Search</b>\n\n"
                "Usage: <code>/email [email]</code>\n\n"
                "<i>Examples:</i>\n"
                "<code>/email user@gmail.com</code>\n"
                "<code>/email @hotmail.com</code>\n"
                "<code>/email admin@example.com</code>"
            )
            return
        
        query = ' '.join(context.args)
        await self.perform_search(update, user.id, 'email', query)
    
    async def login_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Search by login/username"""
        user = update.effective_user
        
        if not context.args:
            await update.message.reply_html(
                "👤 <b>Login Search</b>\n\n"
                "Usage: <code>/login [username]</code>\n\n"
                "<i>Examples:</i>\n"
                "<code>/login admin</code>\n"
                "<code>/login user123</code>\n"
                "<code>/login john_doe</code>"
            )
            return
        
        query = ' '.join(context.args)
        await self.perform_search(update, user.id, 'login', query)
    
    async def pass_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Search by password"""
        user = update.effective_user
        
        if not context.args:
            await update.message.reply_html(
                "🔐 <b>Password Search</b>\n\n"
                "Usage: <code>/pass [password]</code>\n\n"
                "<i>Examples:</i>\n"
                "<code>/pass 123456</code>\n"
                "<code>/pass password123</code>\n"
                "<code>/pass qwerty</code>"
            )
            return
        
        query = ' '.join(context.args)
        await self.perform_search(update, user.id, 'password', query)
    
    async def dni_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Search for DNI:password combos from specific domain
        Example: /dni gmail.com finds DNI:pass from @gmail.com accounts
        """
        user = update.effective_user
        
        if not context.args:
            await update.message.reply_html(
                "🇪🇸 <b>DNI Search by Domain</b>\n\n"
                "Usage: <code>/dni [domain]</code>\n\n"
                "<i>Examples:</i>\n"
                "<code>/dni gmail.com</code> - Find DNI:password from Gmail accounts\n"
                "<code>/dni hotmail.com</code> - Find DNI:password from Hotmail accounts\n"
                "<code>/dni yahoo.com</code> - Find DNI:password from Yahoo accounts\n\n"
                "<i>Searches for Spanish ID (DNI) with passwords from specific email domains</i>"
            )
            return
        
        domain = ' '.join(context.args)
        await self.perform_dni_search(update, user.id, domain)
    
    # ============================================================================
    # USER COMMANDS
    # ============================================================================
    
    async def mycredits_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user credits"""
        user = update.effective_user
        total_credits = self.credit_system.get_user_credits(user.id)
        daily_credits = self.credit_system.get_daily_credits_left(user.id)
        extra_credits = total_credits - daily_credits
        user_info = self.credit_system.get_user_info(user.id)
        
        message = (
            f"💰 <b>Your Credits</b>\n\n"
            f"<b>Daily Credits:</b> {daily_credits}/2\n"
            f"<b>Extra Credits:</b> {extra_credits}\n"
            f"<b>Total Credits:</b> {total_credits}\n\n"
            f"<b>Statistics:</b>\n"
            f"• Total searches: {user_info.get('total_searches', 0) if user_info else 0}\n"
            f"• Referrals: {user_info.get('referrals', 0) if user_info else 0}\n"
            f"• Member since: {user_info.get('join_date', 'N/A')[:10] if user_info else 'N/A'}\n\n"
            f"<i>Daily credits reset at midnight UTC</i>\n"
            f"Use /referral to invite friends and get +1 credit each!"
        )
        
        await update.message.reply_html(message)
    
    async def mystats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user statistics"""
        user = update.effective_user
        user_info = self.credit_system.get_user_info(user.id)
        
        if not user_info:
            await update.message.reply_html("❌ User not found in database")
            return
        
        message = (
            f"📊 <b>Your Statistics</b>\n\n"
            f"<b>Account Info:</b>\n"
            f"• User ID: {user_info['user_id']}\n"
            f"• Username: @{user_info['username'] or 'N/A'}\n"
            f"• Name: {user_info['first_name']}\n"
            f"• Joined: {user_info['join_date'][:10]}\n\n"
            f"<b>Activity:</b>\n"
            f"• Total searches: {user_info['total_searches']}\n"
            f"• Successful referrals: {user_info['referrals']}\n\n"
            f"<b>Current Credits:</b>\n"
            f"• Daily: {user_info['daily_credits']}/2\n"
            f"• Extra: {user_info['extra_credits']}\n"
            f"• Total: {user_info['daily_credits'] + user_info['extra_credits']}"
        )
        
        await update.message.reply_html(message)
    
    async def referral_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show referral info"""
        user = update.effective_user
        referral_info = self.credit_system.get_referral_info(user.id)
        
        if not referral_info:
            await update.message.reply_html("❌ Could not generate referral info")
            return
        
        message = (
            f"🎯 <b>Referral System</b>\n\n"
            f"<b>How it works:</b>\n"
            f"1. Share your referral link\n"
            f"2. When someone joins using your link\n"
            f"3. You get <b>+1 credit</b>!\n"
            f"4. They get 2 free credits\n\n"
            f"<b>Your Referral Stats:</b>\n"
            f"• Referrals: {referral_info['referrals_count']}\n"
            f"• Your Code: <code>{referral_info['referral_code']}</code>\n\n"
            f"<b>Your Referral Link:</b>\n"
            f"<code>{referral_info['referral_link']}</code>\n\n"
            f"<i>Share this link with friends to earn free credits!</i>"
        )
        
        await update.message.reply_html(message)
    
    async def price_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show pricing information"""
        message = (
            f"💰 <b>Pricing Information</b>\n\n"
            f"<b>FREE PLAN:</b>\n"
            f"• 2 free credits per day\n"
            f"• +1 credit per referral\n"
            f"• All search features\n\n"
            f"<b>PREMIUM PLANS:</b>\n"
            f"Contact {BOT_OWNER} for premium plans:\n"
            f"• Unlimited searches\n"
            f"• Priority support\n"
            f"• Bulk search options\n\n"
            f"<b>SUPPORT:</b>\n"
            f"Contact {BOT_SUPPORT} for any questions or to purchase credits."
        )
        
        await update.message.reply_html(message)
    
    # ============================================================================
    # INFO COMMANDS
    # ============================================================================
    
    async def info_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show bot information"""
        stats = self.credit_system.get_bot_stats()
        engine_stats = self.search_engine.get_stats()
        
        message = (
            f"📚 <b>{BOT_NAME} - Information</b>\n\n"
            f"<b>Version:</b> {BOT_VERSION}\n"
            f"<b>Owner:</b> {BOT_OWNER}\n"
            f"<b>Support:</b> {BOT_SUPPORT}\n\n"
            f"<b>Database Statistics:</b>\n"
            f"• Total files: {engine_stats['total_files']:,}\n"
            f"• Total lines: {engine_stats['total_lines']:,}\n"
            f"• Database size: {engine_stats['total_size_mb']:,.1f} MB\n\n"
            f"<b>User Statistics:</b>\n"
            f"• Total users: {stats['total_users']:,}\n"
            f"• Total searches: {stats['total_searches']:,}\n"
            f"• Total referrals: {stats['total_referrals']:,}\n\n"
            f"<b>Free Credits System:</b>\n"
            f"• 2 free credits daily\n"
            f"• +1 credit per referral\n"
            f"• Resets at midnight UTC\n\n"
            f"Use /help for all available commands."
        )
        
        await update.message.reply_html(message)
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show complete help"""
        help_text = (
            f"📚 <b>{BOT_NAME} - COMPLETE HELP</b>\n\n"
            
            "<b>🎯 FREE SYSTEM:</b>\n"
            "• Maximum 2 free credits\n"
            "• 1 credit = 1 search\n"
            "• Invite friends: +1 credit per referral\n\n"
            
            "<b>🔍 SEARCH COMMANDS:</b>\n"
            "/search <domain> - Search by domain (with format options)\n"
            "/email <email> - Search by email\n"
            "/login <username> - Search by login\n"
            "/pass <password> - Search by password\n"
            "/dni <domain> - Find DNI:password from domain (e.g., /dni gmail.com)\n\n"
            
            "<b>📋 FORMATS FOR /search:</b>\n"
            "• email:pass (clean format)\n"
            "• url:email:pass (full lines)\n"
            "• login:pass\n"
            "• email only\n\n"
            
            "<b>💰 PERSONAL COMMANDS:</b>\n"
            "/mycredits - Check your credits\n"
            "/mystats - Your statistics\n"
            "/referral - Your referral link\n"
            "/price - Pricing information\n\n"
            
            "<b>📊 INFORMATION:</b>\n"
            "/info - Bot information\n"
            "/help - This help message\n"
            "/stats - Bot statistics (admin)\n\n"
            
            "<b>👑 ADMIN COMMANDS:</b>\n"
            "/stats - Bot statistics\n"
            "/userslist - List all users\n"
            "/addcredits - Add credits to user\n"
            "/userinfo - User information\n"
            "/broadcast - Send to all users\n"
            "/upload - Upload ULP file\n\n"
            
            "<b>📁 RESULT DELIVERY:</b>\n"
            "• <100 results → Message\n"
            "• 100-10,000 results → .txt file\n"
            "• >10,000 results → .zip file\n\n"
            
            "<b>💡 TIPS:</b>\n"
            "• Use specific terms for better results\n"
            "• Invite friends to earn free credits\n"
            f"• Contact {BOT_OWNER} for more credits\n\n"
            
            f"<b>Bot developed by {BOT_OWNER}</b>"
        )
        
        await update.message.reply_html(help_text)
    
    # ============================================================================
    # ADMIN COMMANDS
    # ============================================================================
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show bot statistics (admin only)"""
        user = update.effective_user
        
        if user.id not in ADMIN_IDS:
            await update.message.reply_html("❌ This command is for admins only")
            return
        
        stats = self.credit_system.get_bot_stats()
        engine_stats = self.search_engine.get_stats()
        
        today = datetime.now().date()
        
        with self.credit_system.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) as count FROM transactions WHERE type = 'search_used' AND DATE(date) = DATE(?)",
                (today,)
            )
            today_searches = cursor.fetchone()['count']
        
        message = (
            f"📊 <b>Admin Statistics</b>\n\n"
            f"<b>Users:</b> {stats['total_users']:,}\n"
            f"<b>Total Searches:</b> {stats['total_searches']:,}\n"
            f"<b>Today's Searches:</b> {today_searches:,}\n"
            f"<b>Total Credits:</b> {stats['total_credits']:,}\n"
            f"<b>Total Referrals:</b> {stats['total_referrals']:,}\n\n"
            
            f"<b>Database:</b>\n"
            f"• Files: {engine_stats['total_files']:,}\n"
            f"• Lines: {engine_stats['total_lines']:,}\n"
            f"• Size: {engine_stats['total_size_mb']:,.1f} MB\n\n"
            
            f"<b>Recent Resets:</b>\n"
        )
        
        if stats['recent_resets']:
            for reset in stats['recent_resets'][:3]:
                message += f"• {reset['reset_date']}: {reset['users_reset']} users\n"
        else:
            message += "• No resets recorded\n"
        
        await update.message.reply_html(message)
    
    async def userslist_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List all users (admin only)"""
        user = update.effective_user
        
        if user.id not in ADMIN_IDS:
            await update.message.reply_html("❌ This command is for admins only")
            return
        
        users = self.credit_system.get_all_users(limit=20)
        
        if not users:
            await update.message.reply_html("📭 No users found in database")
            return
        
        message = "<b>👥 Users List (Last 20)</b>\n\n"
        
        for i, user_data in enumerate(users, 1):
            user_id = user_data['user_id']
            username = user_data['username'] or "No username"
            first_name = user_data['first_name']
            searches = user_data['total_searches']
            credits = user_data['daily_credits'] + user_data['extra_credits']
            join_date = user_data['join_date'][:10]
            
            message += (
                f"{i}. <b>{first_name}</b> (@{username})\n"
                f"   ID: {user_id} | Searches: {searches}\n"
                f"   Credits: {credits} | Joined: {join_date}\n\n"
            )
        
        await update.message.reply_html(message)
    
    # ============================================================================
    # SEARCH FUNCTIONALITY
    # ============================================================================
    
    async def perform_search(self, update: Update, user_id: int, search_type: str, query: str):
        """Perform a search and deliver results"""
        if not self.credit_system.has_enough_credits(user_id):
            await self.send_no_credits_message(update, user_id)
            return
        
        msg = await update.message.reply_html(
            f"🔍 Searching for: <code>{self.escape_html(query)}</code>\n"
            f"Type: {search_type.capitalize()}\n"
            f"⏳ Please wait..."
        )
        
        try:
            if search_type == 'email':
                count, results = self.search_engine.search_email_only(query)
                result_type = "email:password pairs"
            elif search_type == 'login':
                count, results = self.search_engine.search_login(query)
                result_type = "login:password pairs"
            elif search_type == 'password':
                count, results = self.search_engine.search_password(query)
                result_type = "password matches"
            else:
                await msg.edit_text("❌ Invalid search type")
                return
            
            success = self.credit_system.use_credits(user_id, search_type, query, count)
            
            if not success:
                await msg.edit_text("❌ Error using credits")
                return
            
            daily_credits = self.credit_system.get_daily_credits_left(user_id)
            
            if count == 0:
                await msg.edit_text(
                    f"🔍 <b>Search Results</b>\n\n"
                    f"<b>Query:</b> <code>{self.escape_html(query)}</code>\n"
                    f"<b>Type:</b> {search_type.capitalize()}\n"
                    f"<b>Results:</b> 0\n\n"
                    f"No results found for your search.\n\n"
                    f"<i>Daily credits remaining: {daily_credits}/2</i>"
                )
                return
            
            if count <= 100:
                results_text = "\n".join([self.escape_html(r) for r in results[:100]])
                await msg.edit_text(
                    f"🔍 <b>Search Results</b>\n\n"
                    f"<b>Query:</b> <code>{self.escape_html(query)}</code>\n"
                    f"<b>Type:</b> {search_type.capitalize()}\n"
                    f"<b>Results:</b> {count:,} {result_type}\n\n"
                    f"<pre>{results_text}</pre>\n\n"
                    f"<i>Daily credits remaining: {daily_credits}/2</i>"
                )
            elif count <= 10000:
                results_text = "\n".join(results[:10000])
                file_content = f"Query: {query}\nType: {search_type}\nTotal Results: {count}\n\n{results_text}"
                
                file_obj = io.BytesIO(file_content.encode('utf-8'))
                filename = f"{search_type}_{query.replace('@', '_at_').replace('.', '_dot_')}_{count}_results.txt"
                file_obj.name = filename
                
                await update.message.reply_document(
                    document=file_obj,
                    caption=(
                        f"🔍 <b>Search Results</b>\n\n"
                        f"<b>Query:</b> <code>{self.escape_html(query)}</code>\n"
                        f"<b>Type:</b> {search_type.capitalize()}\n"
                        f"<b>Results:</b> {count:,} {result_type}\n\n"
                        f"<i>Daily credits remaining: {daily_credits}/2</i>"
                    ),
                    parse_mode='HTML'
                )
                await msg.delete()
            else:
                results_text = "\n".join(results[:50000])
                file_content = f"Query: {query}\nType: {search_type}\nTotal Results: {count}\n\n{results_text}"
                
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                    zip_file.writestr(f"results_{query}_{count}.txt", file_content)
                
                zip_buffer.seek(0)
                zip_buffer.name = f"{search_type}_{query}_{count}_results.zip"
                
                await update.message.reply_document(
                    document=zip_buffer,
                    caption=(
                        f"🔍 <b>Search Results (ZIP)</b>\n\n"
                        f"<b>Query:</b> <code>{self.escape_html(query)}</code>\n"
                        f"<b>Type:</b> {search_type.capitalize()}\n"
                        f"<b>Results:</b> {count:,} {result_type}\n"
                        f"<i>File contains first 50,000 results</i>\n\n"
                        f"<i>Daily credits remaining: {daily_credits}/2</i>"
                    ),
                    parse_mode='HTML'
                )
                await msg.delete()
                
        except Exception as e:
            logger.error(f"Search error: {e}")
            await msg.edit_text(f"❌ Error during search: {str(e)}")
    
    async def perform_dni_search(self, update: Update, user_id: int, domain: str):
        """Search for DNI:password combos from specific domain"""
        if not self.credit_system.has_enough_credits(user_id):
            await self.send_no_credits_message(update, user_id)
            return
        
        msg = await update.message.reply_html(
            f"🔍 Searching DNI:password from: <code>{self.escape_html(domain)}</code>\n"
            f"⏳ Looking for Spanish ID combos..."
        )
        
        try:
            count, results = self.search_engine.search_dni_domain(domain)
            result_type = "DNI:password combos"
            
            success = self.credit_system.use_credits(user_id, 'dni', domain, count)
            
            if not success:
                await msg.edit_text("❌ Error using credits")
                return
            
            daily_credits = self.credit_system.get_daily_credits_left(user_id)
            
            if count == 0:
                await msg.edit_text(
                    f"🔍 <b>DNI Search Results</b>\n\n"
                    f"<b>Domain:</b> <code>{self.escape_html(domain)}</code>\n"
                    f"<b>Results:</b> 0 DNI:password combos\n\n"
                    f"No Spanish ID (DNI) combos found for {domain}.\n\n"
                    f"<i>Daily credits remaining: {daily_credits}/2</i>"
                )
                return
            
            if count <= 100:
                results_text = "\n".join([self.escape_html(r) for r in results[:100]])
                await msg.edit_text(
                    f"🔍 <b>DNI Search Results</b>\n\n"
                    f"<b>Domain:</b> <code>{self.escape_html(domain)}</code>\n"
                    f"<b>Results:</b> {count:,} DNI:password combos\n\n"
                    f"<pre>{results_text}</pre>\n\n"
                    f"<i>Daily credits remaining: {daily_credits}/2</i>"
                )
            elif count <= 10000:
                results_text = "\n".join(results[:10000])
                file_content = f"Domain: {domain}\nType: DNI:password combos\nTotal Results: {count}\n\n{results_text}"
                
                file_obj = io.BytesIO(file_content.encode('utf-8'))
                filename = f"dni_{domain.replace('.', '_dot_')}_{count}_results.txt"
                file_obj.name = filename
                
                await update.message.reply_document(
                    document=file_obj,
                    caption=(
                        f"🔍 <b>DNI Search Results</b>\n\n"
                        f"<b>Domain:</b> <code>{self.escape_html(domain)}</code>\n"
                        f"<b>Results:</b> {count:,} DNI:password combos\n\n"
                        f"<i>Daily credits remaining: {daily_credits}/2</i>"
                    ),
                    parse_mode='HTML'
                )
                await msg.delete()
            else:
                results_text = "\n".join(results[:50000])
                file_content = f"Domain: {domain}\nType: DNI:password combos\nTotal Results: {count}\n\n{results_text}"
                
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                    zip_file.writestr(f"dni_results_{domain}_{count}.txt", file_content)
                
                zip_buffer.seek(0)
                zip_buffer.name = f"dni_{domain}_{count}_results.zip"
                
                await update.message.reply_document(
                    document=zip_buffer,
                    caption=(
                        f"🔍 <b>DNI Search Results (ZIP)</b>\n\n"
                        f"<b>Domain:</b> <code>{self.escape_html(domain)}</code>\n"
                        f"<b>Results:</b> {count:,} DNI:password combos\n"
                        f"<i>File contains first 50,000 results</i>\n\n"
                        f"<i>Daily credits remaining: {daily_credits}/2</i>"
                    ),
                    parse_mode='HTML'
                )
                await msg.delete()
                
        except Exception as e:
            logger.error(f"DNI search error: {e}")
            await msg.edit_text(f"❌ Error during DNI search: {str(e)}")
    
    async def perform_search_with_format(self, update: Update, user_id: int, query: str, format_type: str):
        """Perform search with specific format from button"""
        if not self.credit_system.has_enough_credits(user_id):
            await self.send_no_credits_message(update, user_id)
            return
        
        query_msg = await update.callback_query.edit_message_text(
            f"🔍 Searching: <code>{self.escape_html(query)}</code>\n"
            f"📋 Format: {format_type.replace('_', ' ').title()}\n"
            f"⏳ Please wait...",
            parse_mode='HTML'
        )
        
        try:
            if format_type == 'clean':
                count, results = self.search_engine.search_email_only(query)
                result_type = "clean email:password pairs"
                description = "URLs removed, only email:pass"
            elif format_type == 'full':
                count, results = self.search_engine.search_all_formats(query)
                result_type = "full lines with URLs"
                description = "Complete database entries"
            elif format_type == 'login':
                count, results = self.search_engine.search_login(query)
                result_type = "login:password pairs"
                description = "Login credentials"
            elif format_type == 'email':
                count, results = self.search_engine.search_email_only(query)
                email_results = []
                for result in results:
                    if ':' in result:
                        email_results.append(result.split(':')[0])
                    else:
                        email_results.append(result)
                results = email_results[:1000]
                result_type = "email addresses"
                description = "Email addresses only"
            else:
                await query_msg.edit_text("❌ Invalid format type")
                return
            
            success = self.credit_system.use_credits(user_id, format_type, query, count)
            
            if not success:
                await query_msg.edit_text("❌ Error using credits")
                return
            
            daily_credits = self.credit_system.get_daily_credits_left(user_id)
            
            if count == 0:
                await query_msg.edit_text(
                    f"🔍 <b>Search Results</b>\n\n"
                    f"<b>Query:</b> <code>{self.escape_html(query)}</code>\n"
                    f"<b>Format:</b> {format_type.replace('_', ' ').title()}\n"
                    f"<b>Results:</b> 0\n\n"
                    f"No results found for your search.\n\n"
                    f"<i>Daily credits remaining: {daily_credits}/2</i>"
                )
                return
            
            if count <= 100:
                results_text = "\n".join([self.escape_html(r) for r in results[:100]])
                await query_msg.edit_text(
                    f"🔍 <b>Search Results</b>\n\n"
                    f"<b>Query:</b> <code>{self.escape_html(query)}</code>\n"
                    f"<b>Format:</b> {format_type.replace('_', ' ').title()}\n"
                    f"<b>Results:</b> {count:,} {result_type}\n\n"
                    f"<pre>{results_text}</pre>\n\n"
                    f"<i>Daily credits remaining: {daily_credits}/2</i>"
                )
            else:
                results_text = "\n".join(results[:10000])
                file_content = f"Query: {query}\nFormat: {description}\nTotal Results: {count}\n\n{results_text}"
                
                file_obj = io.BytesIO(file_content.encode('utf-8'))
                filename = f"{query.replace('@', '_at_').replace('.', '_dot_')}_{format_type}_{count}_results.txt"
                file_obj.name = filename
                
                await update.callback_query.message.reply_document(
                    document=file_obj,
                    caption=(
                        f"🔍 <b>Search Results</b>\n\n"
                        f"<b>Query:</b> <code>{self.escape_html(query)}</code>\n"
                        f"<b>Format:</b> {format_type.replace('_', ' ').title()}\n"
                        f"<b>Results:</b> {count:,} {result_type}\n\n"
                        f"<i>Daily credits remaining: {daily_credits}/2</i>"
                    ),
                    parse_mode='HTML'
                )
                await query_msg.delete()
                
        except Exception as e:
            logger.error(f"Search error: {e}")
            await query_msg.edit_text(f"❌ Error during search: {str(e)}")
    
    async def send_no_credits_message(self, update: Update, user_id: int):
        """Send message when user has no credits"""
        daily_credits = self.credit_system.get_daily_credits_left(user_id)
        
        message = (
            f"❌ <b>No Credits Available</b>\n\n"
            f"You have used all your credits.\n\n"
            f"<b>Daily Credits:</b> {daily_credits}/2\n\n"
            f"Credits reset at midnight UTC.\n"
            f"Use /referral to invite friends and get +1 credit each!\n"
            f"Contact {BOT_OWNER} for premium credits."
        )
        
        if update.callback_query:
            await update.callback_query.edit_message_text(message, parse_mode='HTML')
        else:
            await update.message.reply_html(message)
    
    # ============================================================================
    # BUTTON HANDLER
    # ============================================================================
    
    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        user = update.effective_user
        data = query.data
        
        if data == "start_search":
            await query.edit_message_text(
                "🔍 <b>Search Command</b>\n\n"
                "Usage: <code>/search [query]</code>\n\n"
                "<i>Examples:</i>\n"
                "<code>/search example.com</code>\n"
                "<code>/search user@gmail.com</code>\n"
                "<code>/search @hotmail.com</code>\n\n"
                "Then choose your preferred format!",
                parse_mode='HTML'
            )
            
        elif data.startswith("format_"):
            parts = data.split(":", 1)
            if len(parts) == 2:
                format_type = parts[0].replace("format_", "")
                search_query = parts[1]
                await self.perform_search_with_format(update, user.id, search_query, format_type)
        
        elif data == "cancel_search":
            await query.edit_message_text(
                "❌ <b>Search Cancelled</b>\n\n"
                "Use /search to start a new search.",
                parse_mode='HTML'
            )
            
        elif data == "menu_credits":
            await self.mycredits_command(update, context)
            
        elif data == "menu_help":
            await self.help_command(update, context)
            
        elif data == "menu_admin" and user.id in ADMIN_IDS:
            keyboard = [
                [InlineKeyboardButton("📊 /stats - Statistics", callback_data="admin_stats")],
                [InlineKeyboardButton("👥 /userslist - Users List", callback_data="admin_users")],
                [InlineKeyboardButton("➕ Add Credits", callback_data="admin_add")],
                [InlineKeyboardButton("📁 Upload Data", callback_data="admin_data")],
                [InlineKeyboardButton("⬅️ Back", callback_data="menu_back")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "👑 <b>Admin Panel</b>\n\n"
                "Select an option:",
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
            
        elif data == "admin_stats" and user.id in ADMIN_IDS:
            await self.stats_command(update, context)
            
        elif data == "admin_users" and user.id in ADMIN_IDS:
            await self.userslist_command(update, context)
            
        elif data == "menu_back":
            await self.start(update, context)

# ============================================================================
# INITIALIZATION
# ============================================================================

def setup_application():
    """Setup and return the Telegram application"""
    
    search_engine = SearchEngine()
    credit_system = CreditSystem()
    bot = ULPBot(search_engine, credit_system)
    
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("search", bot.search_command))
    application.add_handler(CommandHandler("email", bot.email_command))
    application.add_handler(CommandHandler("login", bot.login_command))
    application.add_handler(CommandHandler("pass", bot.pass_command))
    application.add_handler(CommandHandler("dni", bot.dni_command))
    
    application.add_handler(CommandHandler("mycredits", bot.mycredits_command))
    application.add_handler(CommandHandler("mystats", bot.mystats_command))
    application.add_handler(CommandHandler("referral", bot.referral_command))
    application.add_handler(CommandHandler("price", bot.price_command))
    
    application.add_handler(CommandHandler("info", bot.info_command))
    application.add_handler(CommandHandler("help", bot.help_command))
    application.add_handler(CommandHandler("stats", bot.stats_command))
    application.add_handler(CommandHandler("userslist", bot.userslist_command))
    
    application.add_handler(CallbackQueryHandler(bot.button_handler))
    
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
    
    application, bot = setup_application()
    application.bot_data['ulp_bot'] = bot
    
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_daily(
            daily_reset_job,
            time(hour=RESET_HOUR, minute=0, second=0),
            days=(0, 1, 2, 3, 4, 5, 6),
            name="daily_credit_reset"
        )
        logger.info(f"⏰ Daily reset scheduled for {RESET_HOUR}:00 UTC")
    
    def run_flask():
        app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)
    
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info(f"🌐 Flask server started on port {PORT}")
    
    logger.info("🤖 Starting ULP Search Bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    run()
