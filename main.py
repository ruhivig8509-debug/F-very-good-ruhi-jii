# ============================================================================
# main.py — RUHI JI — The Ultimate Bridge Bot
# Single File | All-in-One | Render Ready | No AI Model Needed
# ============================================================================

import os
import sys
import time
import json
import logging
import threading
import datetime
import re
import html
import traceback
import psutil
import signal
from functools import wraps
from io import BytesIO, StringIO

import telebot
from telebot import types
from flask import Flask
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, Boolean,
    DateTime, BigInteger, Float, ForeignKey, Index
)
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session
from sqlalchemy.pool import QueuePool
import requests
from urllib.parse import quote_plus

# ============================================================================
# CONFIGURATION
# ============================================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///ruhi_bot.db")
PORT = int(os.getenv("PORT", 5000))
ACTIVATION_PHRASE = "ruhi ji"
SESSION_TIMEOUT = 600  # 10 minutes in seconds
MAX_CONTEXT_MESSAGES = 50
BOT_VERSION = "3.0.0"
DEBUG_MODE = False
MAINTENANCE_MODE = False
AI_ENABLED = True

# Fix for Render PostgreSQL URL
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("RuhiJi")

log_buffer = []
MAX_LOG_BUFFER = 500

class BufferHandler(logging.Handler):
    def emit(self, record):
        global log_buffer
        log_entry = self.format(record)
        log_buffer.append(log_entry)
        if len(log_buffer) > MAX_LOG_BUFFER:
            log_buffer = log_buffer[-MAX_LOG_BUFFER:]

buffer_handler = BufferHandler()
buffer_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(buffer_handler)

# ============================================================================
# DATABASE SETUP
# ============================================================================

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, echo=False,
                           connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL, echo=False,
                           pool_size=5, max_overflow=10,
                           poolclass=QueuePool)

Base = declarative_base()
session_factory = sessionmaker(bind=engine)
Session = scoped_session(session_factory)

# ============================================================================
# DATABASE MODELS
# ============================================================================

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(255), default="")
    first_name = Column(String(255), default="")
    last_name = Column(String(255), default="")
    language = Column(String(20), default="hinglish")
    personality = Column(String(50), default="polite_girl")
    mode = Column(String(50), default="normal")
    total_messages = Column(Integer, default=0)
    is_banned = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_active = Column(DateTime, default=datetime.datetime.utcnow)

class ChatHistory(Base):
    __tablename__ = "chat_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    role = Column(String(20), default="user")
    message = Column(Text, default="")
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

class AdminList(Base):
    __tablename__ = "admin_list"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, unique=True, nullable=False)
    added_by = Column(BigInteger, default=0)
    added_at = Column(DateTime, default=datetime.datetime.utcnow)

class BannedUser(Base):
    __tablename__ = "banned_users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, unique=True, nullable=False)
    reason = Column(Text, default="No reason")
    banned_by = Column(BigInteger, default=0)
    banned_at = Column(DateTime, default=datetime.datetime.utcnow)

class BadWord(Base):
    __tablename__ = "bad_words"
    id = Column(Integer, primary_key=True, autoincrement=True)
    word = Column(String(255), unique=True, nullable=False)
    added_by = Column(BigInteger, default=0)

class BotConfig(Base):
    __tablename__ = "bot_config"
    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(255), unique=True, nullable=False)
    value = Column(Text, default="")

class BotLog(Base):
    __tablename__ = "bot_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    level = Column(String(20), default="INFO")
    message = Column(Text, default="")
    user_id = Column(BigInteger, default=0)
    chat_id = Column(BigInteger, default=0)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

# Create all tables
try:
    Base.metadata.create_all(engine)
    logger.info("Database tables created successfully.")
except Exception as e:
    logger.error(f"Database creation error: {e}")

# ============================================================================
# FLASK KEEP-ALIVE SERVER
# ============================================================================

app = Flask(__name__)

@app.route("/")
def home():
    return (
        "<h1>🌹 Ruhi Ji Bot is Running!</h1>"
        f"<p>Version: {BOT_VERSION}</p>"
        f"<p>Status: {'Maintenance' if MAINTENANCE_MODE else 'Online'}</p>"
        f"<p>Uptime: Running</p>"
    )

@app.route("/health")
def health():
    return {"status": "ok", "bot": "Ruhi Ji", "version": BOT_VERSION}, 200

def run_flask():
    try:
        app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"Flask error: {e}")

# ============================================================================
# BOT INITIALIZATION
# ============================================================================

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None, threaded=True)

# ============================================================================
# SESSION MANAGER (Active Sessions with 10 min timeout)
# ============================================================================

active_sessions = {}  # key: (user_id, chat_id), value: last_active_timestamp
session_lock = threading.Lock()

def activate_session(user_id, chat_id):
    with session_lock:
        active_sessions[(user_id, chat_id)] = time.time()

def is_session_active(user_id, chat_id):
    with session_lock:
        key = (user_id, chat_id)
        if key in active_sessions:
            elapsed = time.time() - active_sessions[key]
            if elapsed < SESSION_TIMEOUT:
                return True
            else:
                del active_sessions[key]
                return False
        return False

def refresh_session(user_id, chat_id):
    with session_lock:
        key = (user_id, chat_id)
        if key in active_sessions:
            active_sessions[key] = time.time()

def deactivate_session(user_id, chat_id):
    with session_lock:
        key = (user_id, chat_id)
        if key in active_sessions:
            del active_sessions[key]

def get_active_session_count():
    with session_lock:
        now = time.time()
        active = {k: v for k, v in active_sessions.items() if now - v < SESSION_TIMEOUT}
        return len(active)

def cleanup_sessions():
    with session_lock:
        now = time.time()
        expired = [k for k, v in active_sessions.items() if now - v >= SESSION_TIMEOUT]
        for k in expired:
            del active_sessions[k]

# Session cleanup thread
def session_cleanup_loop():
    while True:
        try:
            cleanup_sessions()
        except:
            pass
        time.sleep(60)

threading.Thread(target=session_cleanup_loop, daemon=True).start()

# ============================================================================
# DATABASE HELPER FUNCTIONS
# ============================================================================

def get_or_create_user(user_id, username="", first_name="", last_name=""):
    try:
        session = Session()
        user = session.query(User).filter_by(user_id=user_id).first()
        if not user:
            user = User(
                user_id=user_id,
                username=username or "",
                first_name=first_name or "",
                last_name=last_name or "",
                language="hinglish",
                personality="polite_girl",
                mode="normal",
                total_messages=0,
                is_banned=False,
                is_admin=(user_id == ADMIN_ID)
            )
            session.add(user)
            session.commit()
            logger.info(f"New user created: {user_id} ({first_name})")
        else:
            user.username = username or user.username
            user.first_name = first_name or user.first_name
            user.last_name = last_name or user.last_name
            user.last_active = datetime.datetime.utcnow()
            session.commit()
        Session.remove()
        return user
    except Exception as e:
        Session.remove()
        logger.error(f"get_or_create_user error: {e}")
        return None

def increment_message_count(user_id):
    try:
        session = Session()
        user = session.query(User).filter_by(user_id=user_id).first()
        if user:
            user.total_messages += 1
            user.last_active = datetime.datetime.utcnow()
            session.commit()
        Session.remove()
    except Exception as e:
        Session.remove()
        logger.error(f"increment_message_count error: {e}")

def save_chat_history(user_id, chat_id, role, message_text):
    try:
        session = Session()
        entry = ChatHistory(
            user_id=user_id,
            chat_id=chat_id,
            role=role,
            message=message_text[:4000],
            timestamp=datetime.datetime.utcnow()
        )
        session.add(entry)
        session.commit()
        # Keep only last MAX_CONTEXT_MESSAGES per user per chat
        count = session.query(ChatHistory).filter_by(
            user_id=user_id, chat_id=chat_id
        ).count()
        if count > MAX_CONTEXT_MESSAGES:
            oldest = session.query(ChatHistory).filter_by(
                user_id=user_id, chat_id=chat_id
            ).order_by(ChatHistory.timestamp.asc()).limit(count - MAX_CONTEXT_MESSAGES).all()
            for old in oldest:
                session.delete(old)
            session.commit()
        Session.remove()
    except Exception as e:
        Session.remove()
        logger.error(f"save_chat_history error: {e}")

def get_chat_history(user_id, chat_id, limit=10):
    try:
        session = Session()
        history = session.query(ChatHistory).filter_by(
            user_id=user_id, chat_id=chat_id
        ).order_by(ChatHistory.timestamp.desc()).limit(limit).all()
        history.reverse()
        result = [(h.role, h.message) for h in history]
        Session.remove()
        return result
    except Exception as e:
        Session.remove()
        logger.error(f"get_chat_history error: {e}")
        return []

def clear_chat_history(user_id, chat_id=None):
    try:
        session = Session()
        query = session.query(ChatHistory).filter_by(user_id=user_id)
        if chat_id:
            query = query.filter_by(chat_id=chat_id)
        query.delete()
        session.commit()
        Session.remove()
    except Exception as e:
        Session.remove()
        logger.error(f"clear_chat_history error: {e}")

def is_user_banned(user_id):
    try:
        session = Session()
        banned = session.query(BannedUser).filter_by(user_id=user_id).first()
        Session.remove()
        return banned is not None
    except Exception as e:
        Session.remove()
        return False

def ban_user(user_id, reason="No reason", banned_by=0):
    try:
        session = Session()
        existing = session.query(BannedUser).filter_by(user_id=user_id).first()
        if not existing:
            b = BannedUser(user_id=user_id, reason=reason, banned_by=banned_by)
            session.add(b)
        user = session.query(User).filter_by(user_id=user_id).first()
        if user:
            user.is_banned = True
        session.commit()
        Session.remove()
        return True
    except Exception as e:
        Session.remove()
        logger.error(f"ban_user error: {e}")
        return False

def unban_user(user_id):
    try:
        session = Session()
        session.query(BannedUser).filter_by(user_id=user_id).delete()
        user = session.query(User).filter_by(user_id=user_id).first()
        if user:
            user.is_banned = False
        session.commit()
        Session.remove()
        return True
    except Exception as e:
        Session.remove()
        logger.error(f"unban_user error: {e}")
        return False

def is_admin(user_id):
    if user_id == ADMIN_ID:
        return True
    try:
        session = Session()
        admin = session.query(AdminList).filter_by(user_id=user_id).first()
        Session.remove()
        return admin is not None
    except Exception as e:
        Session.remove()
        return False

def add_admin(user_id, added_by=0):
    try:
        session = Session()
        existing = session.query(AdminList).filter_by(user_id=user_id).first()
        if not existing:
            a = AdminList(user_id=user_id, added_by=added_by)
            session.add(a)
        user = session.query(User).filter_by(user_id=user_id).first()
        if user:
            user.is_admin = True
        session.commit()
        Session.remove()
        return True
    except Exception as e:
        Session.remove()
        logger.error(f"add_admin error: {e}")
        return False

def remove_admin(user_id):
    try:
        session = Session()
        session.query(AdminList).filter_by(user_id=user_id).delete()
        user = session.query(User).filter_by(user_id=user_id).first()
        if user:
            user.is_admin = False
        session.commit()
        Session.remove()
        return True
    except Exception as e:
        Session.remove()
        logger.error(f"remove_admin error: {e}")
        return False

def get_total_users():
    try:
        session = Session()
        count = session.query(User).count()
        Session.remove()
        return count
    except:
        Session.remove()
        return 0

def get_all_user_ids():
    try:
        session = Session()
        users = session.query(User.user_id).all()
        Session.remove()
        return [u[0] for u in users]
    except:
        Session.remove()
        return []

def get_user_language(user_id):
    try:
        session = Session()
        user = session.query(User).filter_by(user_id=user_id).first()
        lang = user.language if user else "hinglish"
        Session.remove()
        return lang
    except:
        Session.remove()
        return "hinglish"

def set_user_language(user_id, language):
    try:
        session = Session()
        user = session.query(User).filter_by(user_id=user_id).first()
        if user:
            user.language = language
            session.commit()
        Session.remove()
    except Exception as e:
        Session.remove()
        logger.error(f"set_user_language error: {e}")

def set_user_personality(user_id, personality):
    try:
        session = Session()
        user = session.query(User).filter_by(user_id=user_id).first()
        if user:
            user.personality = personality
            session.commit()
        Session.remove()
    except Exception as e:
        Session.remove()
        logger.error(f"set_user_personality error: {e}")

def get_bad_words():
    try:
        session = Session()
        words = session.query(BadWord.word).all()
        Session.remove()
        return [w[0] for w in words]
    except:
        Session.remove()
        return []

def add_bad_word(word, added_by=0):
    try:
        session = Session()
        existing = session.query(BadWord).filter_by(word=word.lower()).first()
        if not existing:
            bw = BadWord(word=word.lower(), added_by=added_by)
            session.add(bw)
            session.commit()
            Session.remove()
            return True
        Session.remove()
        return False
    except Exception as e:
        Session.remove()
        logger.error(f"add_bad_word error: {e}")
        return False

def remove_bad_word(word):
    try:
        session = Session()
        session.query(BadWord).filter_by(word=word.lower()).delete()
        session.commit()
        Session.remove()
        return True
    except Exception as e:
        Session.remove()
        logger.error(f"remove_bad_word error: {e}")
        return False

def save_bot_log(level, message, user_id=0, chat_id=0):
    try:
        session = Session()
        log = BotLog(level=level, message=message[:2000], user_id=user_id, chat_id=chat_id)
        session.add(log)
        session.commit()
        Session.remove()
    except:
        Session.remove()

def get_config(key, default=""):
    try:
        session = Session()
        config = session.query(BotConfig).filter_by(key=key).first()
        val = config.value if config else default
        Session.remove()
        return val
    except:
        Session.remove()
        return default

def set_config(key, value):
    try:
        session = Session()
        config = session.query(BotConfig).filter_by(key=key).first()
        if config:
            config.value = str(value)
        else:
            config = BotConfig(key=key, value=str(value))
            session.add(config)
        session.commit()
        Session.remove()
    except Exception as e:
        Session.remove()
        logger.error(f"set_config error: {e}")

# ============================================================================
# MULTI-SOURCE SEARCH ENGINE (THE BRIDGE)
# ============================================================================

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

def search_wikipedia(query, lang="en"):
    """Search Wikipedia for an answer."""
    try:
        url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote_plus(query)}"
        resp = requests.get(url, headers=HEADERS, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            extract = data.get("extract", "")
            title = data.get("title", "")
            if extract and len(extract) > 30:
                return {"source": "Wikipedia", "title": title, "answer": extract}
    except:
        pass
    # Fallback: search API
    try:
        url = f"https://{lang}.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json",
            "srlimit": 3,
            "utf8": 1
        }
        resp = requests.get(url, params=params, headers=HEADERS, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("query", {}).get("search", [])
            if results:
                title = results[0].get("title", "")
                snippet = results[0].get("snippet", "")
                snippet = re.sub(r"<[^>]+>", "", snippet)
                # Get full summary
                url2 = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote_plus(title)}"
                resp2 = requests.get(url2, headers=HEADERS, timeout=8)
                if resp2.status_code == 200:
                    data2 = resp2.json()
                    extract = data2.get("extract", snippet)
                    return {"source": "Wikipedia", "title": title, "answer": extract}
                return {"source": "Wikipedia", "title": title, "answer": snippet}
    except:
        pass
    return None

def search_wikipedia_hi(query):
    """Search Hindi Wikipedia."""
    return search_wikipedia(query, lang="hi")

def search_duckduckgo(query):
    """Search DuckDuckGo Instant Answer API."""
    try:
        url = "https://api.duckduckgo.com/"
        params = {"q": query, "format": "json", "no_html": 1, "skip_disambig": 1}
        resp = requests.get(url, params=params, headers=HEADERS, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            # Check Abstract
            abstract = data.get("AbstractText", "")
            if abstract and len(abstract) > 30:
                return {"source": "DuckDuckGo", "title": data.get("Heading", ""), "answer": abstract}
            # Check Answer
            answer = data.get("Answer", "")
            if answer:
                return {"source": "DuckDuckGo", "title": "Direct Answer", "answer": str(answer)}
            # Check Definition
            definition = data.get("Definition", "")
            if definition:
                return {"source": "DuckDuckGo", "title": "Definition", "answer": definition}
            # Check Related Topics
            related = data.get("RelatedTopics", [])
            if related:
                texts = []
                for r in related[:3]:
                    if isinstance(r, dict) and "Text" in r:
                        texts.append(r["Text"])
                if texts:
                    return {"source": "DuckDuckGo", "title": data.get("Heading", query), "answer": "\n".join(texts)}
    except:
        pass
    return None

def search_dictionary(word):
    """Search Free Dictionary API."""
    try:
        url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{quote_plus(word)}"
        resp = requests.get(url, headers=HEADERS, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                entry = data[0]
                word_name = entry.get("word", word)
                meanings = entry.get("meanings", [])
                result_parts = [f"📖 Word: {word_name}"]
                for m in meanings[:3]:
                    pos = m.get("partOfSpeech", "")
                    defs = m.get("definitions", [])
                    if defs:
                        definition = defs[0].get("definition", "")
                        example = defs[0].get("example", "")
                        result_parts.append(f"\n🔹 {pos}: {definition}")
                        if example:
                            result_parts.append(f"   Example: {example}")
                return {"source": "Dictionary", "title": word_name, "answer": "\n".join(result_parts)}
    except:
        pass
    return None

def search_stackoverflow(query):
    """Search StackOverflow for coding questions."""
    try:
        url = "https://api.stackexchange.com/2.3/search/advanced"
        params = {
            "order": "desc",
            "sort": "relevance",
            "q": query,
            "site": "stackoverflow",
            "filter": "default",
            "pagesize": 3,
            "answers": 1
        }
        resp = requests.get(url, params=params, headers=HEADERS, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("items", [])
            if items:
                results = []
                for item in items[:3]:
                    title = html.unescape(item.get("title", ""))
                    link = item.get("link", "")
                    score = item.get("score", 0)
                    answered = item.get("is_answered", False)
                    status = "✅" if answered else "❓"
                    results.append(f"{status} {title}\n   Score: {score} | Link: {link}")
                return {"source": "StackOverflow", "title": "Code Solutions", "answer": "\n\n".join(results)}
    except:
        pass
    return None

def search_github_topics(query):
    """Search GitHub for repositories."""
    try:
        url = "https://api.github.com/search/repositories"
        params = {"q": query, "sort": "stars", "order": "desc", "per_page": 3}
        resp = requests.get(url, params=params, headers=HEADERS, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("items", [])
            if items:
                results = []
                for item in items[:3]:
                    name = item.get("full_name", "")
                    desc = item.get("description", "No description") or "No description"
                    stars = item.get("stargazers_count", 0)
                    url_repo = item.get("html_url", "")
                    results.append(f"⭐ {name} ({stars} stars)\n   {desc[:100]}\n   {url_repo}")
                return {"source": "GitHub", "title": "Repositories", "answer": "\n\n".join(results)}
    except:
        pass
    return None

def search_wiktionary(word):
    """Search Wiktionary for word meanings."""
    try:
        url = f"https://en.wiktionary.org/api/rest_v1/page/definition/{quote_plus(word)}"
        resp = requests.get(url, headers=HEADERS, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            parts = []
            for lang_key in ["en", "hi"]:
                entries = data.get(lang_key, [])
                for entry in entries[:2]:
                    pos = entry.get("partOfSpeech", "")
                    definitions = entry.get("definitions", [])
                    for d in definitions[:2]:
                        defn = d.get("definition", "")
                        defn = re.sub(r"<[^>]+>", "", defn)
                        if defn:
                            parts.append(f"🔸 {pos}: {defn}")
            if parts:
                return {"source": "Wiktionary", "title": word, "answer": "\n".join(parts)}
    except:
        pass
    return None

def search_numbers_fact(query):
    """Get number/date facts from Numbers API."""
    try:
        # Check if query contains a number
        numbers = re.findall(r'\d+', query)
        if numbers:
            num = numbers[0]
            url = f"http://numbersapi.com/{num}?json"
            resp = requests.get(url, headers=HEADERS, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                text = data.get("text", "")
                if text:
                    return {"source": "Numbers API", "title": f"Fact about {num}", "answer": text}
    except:
        pass
    return None

def search_open_trivia(query):
    """Get trivia/quiz questions."""
    try:
        lower = query.lower()
        if any(w in lower for w in ["quiz", "trivia", "question", "gk", "sawal"]):
            url = "https://opentdb.com/api.php?amount=3&type=multiple"
            resp = requests.get(url, headers=HEADERS, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                results_list = data.get("results", [])
                if results_list:
                    parts = []
                    for i, q in enumerate(results_list[:3], 1):
                        question = html.unescape(q.get("question", ""))
                        correct = html.unescape(q.get("correct_answer", ""))
                        category = html.unescape(q.get("category", ""))
                        parts.append(f"❓ Q{i}: {question}\n✅ Answer: {correct}\n📂 Category: {category}")
                    return {"source": "Open Trivia DB", "title": "Quiz Time!", "answer": "\n\n".join(parts)}
    except:
        pass
    return None

def search_quotes(query):
    """Get random quotes or search quotes."""
    try:
        lower = query.lower()
        if any(w in lower for w in ["quote", "quotes", "suvichar", "thought", "motivation", "inspire"]):
            url = "https://api.quotable.io/quotes/random?limit=3"
            resp = requests.get(url, headers=HEADERS, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and data:
                    parts = []
                    for q in data[:3]:
                        content = q.get("content", "")
                        author = q.get("author", "Unknown")
                        parts.append(f'💬 "{content}"\n   — {author}')
                    return {"source": "Quotable", "title": "Quotes", "answer": "\n\n".join(parts)}
    except:
        pass
    return None

def search_joke(query):
    """Get jokes."""
    try:
        lower = query.lower()
        if any(w in lower for w in ["joke", "funny", "mazak", "chutkula", "hasi", "comedy", "laugh"]):
            url = "https://v2.jokeapi.dev/joke/Any?blacklistFlags=nsfw,racist,sexist&type=twopart"
            resp = requests.get(url, headers=HEADERS, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("type") == "twopart":
                    setup = data.get("setup", "")
                    delivery = data.get("delivery", "")
                    return {"source": "JokeAPI", "title": "😂 Joke", "answer": f"{setup}\n\n{delivery} 😂"}
                elif data.get("type") == "single":
                    joke = data.get("joke", "")
                    return {"source": "JokeAPI", "title": "😂 Joke", "answer": joke}
    except:
        pass
    return None

def search_weather(query):
    """Get weather info using wttr.in."""
    try:
        lower = query.lower()
        weather_words = ["weather", "mausam", "temperature", "temp", "barish", "rain", "garmi", "thand"]
        if any(w in lower for w in weather_words):
            # Extract city name
            city = query
            for w in weather_words:
                city = city.lower().replace(w, "").strip()
            city = re.sub(r'[^\w\s]', '', city).strip()
            if not city or len(city) < 2:
                city = "Delhi"
            url = f"https://wttr.in/{quote_plus(city)}?format=j1"
            resp = requests.get(url, headers=HEADERS, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                current = data.get("current_condition", [{}])[0]
                temp_c = current.get("temp_C", "N/A")
                feels_like = current.get("FeelsLikeC", "N/A")
                humidity = current.get("humidity", "N/A")
                desc = current.get("weatherDesc", [{}])[0].get("value", "N/A")
                wind = current.get("windspeedKmph", "N/A")
                area = data.get("nearest_area", [{}])[0]
                area_name = area.get("areaName", [{}])[0].get("value", city)
                country = area.get("country", [{}])[0].get("value", "")
                answer = (
                    f"🌤 Weather in {area_name}, {country}\n\n"
                    f"🌡 Temperature: {temp_c}°C\n"
                    f"🤔 Feels Like: {feels_like}°C\n"
                    f"💧 Humidity: {humidity}%\n"
                    f"💨 Wind: {wind} km/h\n"
                    f"☁️ Condition: {desc}"
                )
                return {"source": "Weather", "title": f"Weather - {area_name}", "answer": answer}
    except:
        pass
    return None

def search_math(query):
    """Evaluate mathematical expressions using mathjs API."""
    try:
        # Check if it looks like math
        math_pattern = re.search(r'[\d+\-*/^%()=]', query)
        math_words = ["calculate", "solve", "math", "hisab", "ganit", "kitna", "jod", "guna"]
        if math_pattern or any(w in query.lower() for w in math_words):
            # Extract mathematical expression
            expr = re.sub(r'[a-zA-Z\s]*(calculate|solve|math|what is|kitna hai|bata|kya hai)[a-zA-Z\s]*', '', query, flags=re.IGNORECASE).strip()
            if not expr:
                expr = query
            # Clean expression
            expr = re.sub(r'[^\d+\-*/^%().x\s]', '', expr).strip()
            if expr and any(c.isdigit() for c in expr):
                url = f"http://api.mathjs.org/v4/?expr={quote_plus(expr)}"
                resp = requests.get(url, headers=HEADERS, timeout=5)
                if resp.status_code == 200:
                    result = resp.text.strip()
                    if result and "Error" not in result:
                        return {"source": "Math", "title": "🔢 Calculation", "answer": f"📝 Expression: {expr}\n✅ Result: {result}"}
    except:
        pass
    return None

def search_country_info(query):
    """Get country information."""
    try:
        lower = query.lower()
        country_words = ["country", "desh", "capital", "rajdhani", "population", "jansankhya"]
        if any(w in lower for w in country_words):
            country = query
            for w in country_words:
                country = country.lower().replace(w, "").strip()
            country = re.sub(r'[^\w\s]', '', country).strip()
            if country and len(country) > 1:
                url = f"https://restcountries.com/v3.1/name/{quote_plus(country)}"
                resp = requests.get(url, headers=HEADERS, timeout=8)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list) and data:
                        c = data[0]
                        name = c.get("name", {}).get("common", "")
                        official = c.get("name", {}).get("official", "")
                        capital = ", ".join(c.get("capital", ["N/A"]))
                        population = c.get("population", 0)
                        region = c.get("region", "N/A")
                        subregion = c.get("subregion", "N/A")
                        languages = ", ".join(c.get("languages", {}).values()) if c.get("languages") else "N/A"
                        currencies = ", ".join([v.get("name", "") for v in c.get("currencies", {}).values()]) if c.get("currencies") else "N/A"
                        flag = c.get("flag", "")
                        answer = (
                            f"{flag} {name} ({official})\n\n"
                            f"🏛 Capital: {capital}\n"
                            f"👥 Population: {population:,}\n"
                            f"🌍 Region: {region} ({subregion})\n"
                            f"🗣 Languages: {languages}\n"
                            f"💰 Currency: {currencies}"
                        )
                        return {"source": "REST Countries", "title": name, "answer": answer}
    except:
        pass
    return None

def search_ip_info(query):
    """Get IP information."""
    try:
        lower = query.lower()
        if "ip" in lower:
            ips = re.findall(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', query)
            if ips:
                ip = ips[0]
                url = f"http://ip-api.com/json/{ip}"
                resp = requests.get(url, headers=HEADERS, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "success":
                        answer = (
                            f"🌐 IP: {data.get('query', ip)}\n"
                            f"📍 Location: {data.get('city', '')}, {data.get('regionName', '')}, {data.get('country', '')}\n"
                            f"🏢 ISP: {data.get('isp', 'N/A')}\n"
                            f"🏛 Org: {data.get('org', 'N/A')}\n"
                            f"⏰ Timezone: {data.get('timezone', 'N/A')}"
                        )
                        return {"source": "IP API", "title": f"IP Info - {ip}", "answer": answer}
    except:
        pass
    return None

def search_urban_dictionary(query):
    """Search Urban Dictionary."""
    try:
        url = f"https://api.urbandictionary.com/v0/define?term={quote_plus(query)}"
        resp = requests.get(url, headers=HEADERS, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("list", [])
            if items:
                top = items[0]
                word = top.get("word", query)
                definition = top.get("definition", "")
                definition = re.sub(r'[\[\]]', '', definition)
                example = top.get("example", "")
                example = re.sub(r'[\[\]]', '', example)
                thumbs_up = top.get("thumbs_up", 0)
                answer = f"📗 {word}\n\n📝 {definition[:500]}"
                if example:
                    answer += f"\n\n📌 Example: {example[:200]}"
                answer += f"\n\n👍 {thumbs_up}"
                return {"source": "Urban Dictionary", "title": word, "answer": answer}
    except:
        pass
    return None

def search_news(query):
    """Search for news using various free endpoints."""
    try:
        lower = query.lower()
        news_words = ["news", "khabar", "samachar", "headlines", "latest"]
        if any(w in lower for w in news_words):
            topic = query
            for w in news_words:
                topic = topic.lower().replace(w, "").strip()
            if not topic:
                topic = "india"
            url = f"https://newsdata.io/api/1/news?apikey=pub_0000000000000&q={quote_plus(topic)}&language=en,hi"
            # Fallback: Use Google News RSS
            rss_url = f"https://news.google.com/rss/search?q={quote_plus(topic)}&hl=en-IN&gl=IN&ceid=IN:en"
            resp = requests.get(rss_url, headers=HEADERS, timeout=8)
            if resp.status_code == 200:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(resp.content)
                items = root.findall('.//item')
                if items:
                    parts = []
                    for item in items[:5]:
                        title = item.find('title')
                        title_text = title.text if title is not None else "No title"
                        pub_date = item.find('pubDate')
                        date_text = pub_date.text if pub_date is not None else ""
                        source_elem = item.find('source')
                        source_text = source_elem.text if source_elem is not None else ""
                        parts.append(f"📰 {title_text}\n   📅 {date_text[:20]} | 🏢 {source_text}")
                    return {"source": "Google News", "title": f"News: {topic}", "answer": "\n\n".join(parts)}
    except:
        pass
    return None

def search_anime(query):
    """Search anime info using Jikan API."""
    try:
        lower = query.lower()
        anime_words = ["anime", "manga", "naruto", "one piece", "dragon ball", "attack on titan", "demon slayer"]
        if any(w in lower for w in anime_words):
            search_term = query
            for w in ["anime", "manga", "about", "tell me about"]:
                search_term = search_term.lower().replace(w, "").strip()
            if not search_term:
                search_term = "naruto"
            url = f"https://api.jikan.moe/v4/anime?q={quote_plus(search_term)}&limit=3"
            resp = requests.get(url, headers=HEADERS, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("data", [])
                if items:
                    parts = []
                    for item in items[:3]:
                        title = item.get("title", "")
                        score = item.get("score", "N/A")
                        episodes = item.get("episodes", "N/A")
                        status = item.get("status", "N/A")
                        synopsis = item.get("synopsis", "No synopsis")[:200]
                        parts.append(f"🎬 {title}\n⭐ Score: {score} | 📺 Episodes: {episodes}\n📌 Status: {status}\n📝 {synopsis}...")
                    return {"source": "Jikan (MyAnimeList)", "title": "Anime Results", "answer": "\n\n".join(parts)}
    except:
        pass
    return None

def search_lyrics(query):
    """Search for song lyrics."""
    try:
        lower = query.lower()
        lyrics_words = ["lyrics", "song", "gana", "gaana", "bollywood song"]
        if any(w in lower for w in lyrics_words):
            search_term = query
            for w in lyrics_words + ["of", "ka"]:
                search_term = search_term.lower().replace(w, "").strip()
            if search_term and len(search_term) > 2:
                url = f"https://api.lyrics.ovh/v1/{quote_plus(search_term)}//"
                # Try alternative
                parts = search_term.split()
                if len(parts) >= 2:
                    artist = parts[0]
                    title = " ".join(parts[1:])
                    url = f"https://api.lyrics.ovh/v1/{quote_plus(artist)}/{quote_plus(title)}"
                    resp = requests.get(url, headers=HEADERS, timeout=8)
                    if resp.status_code == 200:
                        data = resp.json()
                        lyrics = data.get("lyrics", "")
                        if lyrics:
                            return {"source": "Lyrics.ovh", "title": f"🎵 {search_term}", "answer": lyrics[:1500]}
    except:
        pass
    return None

def search_pokemon(query):
    """Search Pokemon info."""
    try:
        lower = query.lower()
        pokemon_words = ["pokemon", "pikachu", "charizard", "bulbasaur"]
        if any(w in lower for w in pokemon_words):
            name = query
            for w in ["pokemon", "about", "tell"]:
                name = name.lower().replace(w, "").strip()
            if not name:
                name = "pikachu"
            url = f"https://pokeapi.co/api/v2/pokemon/{quote_plus(name.lower())}"
            resp = requests.get(url, headers=HEADERS, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                pname = data.get("name", "").capitalize()
                types = ", ".join([t["type"]["name"].capitalize() for t in data.get("types", [])])
                height = data.get("height", 0) / 10
                weight = data.get("weight", 0) / 10
                abilities = ", ".join([a["ability"]["name"].capitalize() for a in data.get("abilities", [])[:3]])
                stats = data.get("stats", [])
                stat_text = "\n".join([f"   {s['stat']['name'].capitalize()}: {s['base_stat']}" for s in stats])
                answer = (
                    f"⚡ {pname}\n\n"
                    f"🏷 Type: {types}\n"
                    f"📏 Height: {height}m\n"
                    f"⚖ Weight: {weight}kg\n"
                    f"🎯 Abilities: {abilities}\n"
                    f"📊 Stats:\n{stat_text}"
                )
                return {"source": "PokeAPI", "title": pname, "answer": answer}
    except:
        pass
    return None

def search_crypto(query):
    """Get cryptocurrency info."""
    try:
        lower = query.lower()
        crypto_words = ["bitcoin", "crypto", "ethereum", "btc", "eth", "coin", "price", "cryptocurrency"]
        if any(w in lower for w in crypto_words):
            coin = "bitcoin"
            if "ethereum" in lower or "eth" in lower:
                coin = "ethereum"
            elif "dogecoin" in lower or "doge" in lower:
                coin = "dogecoin"
            elif "solana" in lower or "sol" in lower:
                coin = "solana"
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin}&vs_currencies=usd,inr&include_24hr_change=true"
            resp = requests.get(url, headers=HEADERS, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                if coin in data:
                    usd = data[coin].get("usd", "N/A")
                    inr = data[coin].get("inr", "N/A")
                    change = data[coin].get("usd_24h_change", 0)
                    change_str = f"+{change:.2f}%" if change >= 0 else f"{change:.2f}%"
                    answer = (
                        f"💰 {coin.capitalize()}\n\n"
                        f"💵 USD: ${usd:,.2f}\n"
                        f"💴 INR: ₹{inr:,.2f}\n"
                        f"📈 24h Change: {change_str}"
                    )
                    return {"source": "CoinGecko", "title": f"{coin.capitalize()} Price", "answer": answer}
    except:
        pass
    return None

def search_programming_docs(query):
    """Search DevDocs / programming references."""
    try:
        lower = query.lower()
        prog_words = ["python", "javascript", "java", "code", "programming", "function", "error",
                       "html", "css", "react", "nodejs", "api", "database", "sql", "bug", "debug"]
        if any(w in lower for w in prog_words):
            # Use StackOverflow search as primary
            result = search_stackoverflow(query)
            if result:
                return result
    except:
        pass
    return None

def search_duckduckgo_web(query):
    """Fallback: DuckDuckGo HTML search scraping for general answers."""
    try:
        url = "https://html.duckduckgo.com/html/"
        data = {"q": query}
        resp = requests.post(url, data=data, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }, timeout=10)
        if resp.status_code == 200:
            # Simple regex extraction
            results = re.findall(r'class="result__snippet">(.*?)</a>', resp.text, re.DOTALL)
            if results:
                clean_results = []
                for r in results[:5]:
                    clean = re.sub(r'<[^>]+>', '', r).strip()
                    clean = html.unescape(clean)
                    if clean and len(clean) > 20:
                        clean_results.append(f"🔸 {clean}")
                if clean_results:
                    return {"source": "Web Search", "title": query, "answer": "\n\n".join(clean_results)}
    except:
        pass
    return None

# ============================================================================
# MASTER SEARCH FUNCTION
# ============================================================================

def master_search(query, user_lang="hinglish"):
    """
    Master search function that queries all sources and returns the best answer.
    Acts as the BRIDGE - fetching data from multiple databases.
    """
    if not query or len(query.strip()) < 2:
        return None

    query_clean = query.strip()
    results = []

    # Ordered list of search functions (priority order)
    search_functions = [
        ("weather", search_weather),
        ("math", search_math),
        ("joke", search_joke),
        ("quote", search_quotes),
        ("trivia", search_open_trivia),
        ("crypto", search_crypto),
        ("news", search_news),
        ("country", search_country_info),
        ("ip", search_ip_info),
        ("pokemon", search_pokemon),
        ("anime", search_anime),
        ("lyrics", search_lyrics),
        ("dictionary", search_dictionary),
        ("duckduckgo", search_duckduckgo),
        ("wikipedia_en", lambda q: search_wikipedia(q, "en")),
        ("wikipedia_hi", search_wikipedia_hi),
        ("stackoverflow", search_stackoverflow),
        ("programming", search_programming_docs),
        ("github", search_github_topics),
        ("urban", search_urban_dictionary),
        ("wiktionary", search_wiktionary),
        ("numbers", search_numbers_fact),
        ("web_search", search_duckduckgo_web),
    ]

    for name, func in search_functions:
        try:
            result = func(query_clean)
            if result:
                results.append(result)
                # For specific queries, return first good match
                if name in ["weather", "math", "joke", "quote", "trivia", "crypto",
                            "country", "ip", "pokemon", "news"]:
                    break
                # For general queries, collect up to 2 results
                if len(results) >= 2:
                    break
        except Exception as e:
            logger.debug(f"Search {name} error: {e}")
            continue

    if results:
        return results
    return None

# ============================================================================
# RESPONSE FORMATTER (GIRL PERSONA)
# ============================================================================

def format_ruhi_response(query, search_results, user_name="Dear", user_lang="hinglish"):
    """
    Format the search results in Ruhi Ji's girl persona style.
    """
    if not search_results:
        # No results found
        no_result_messages = {
            "hindi": f"अरे {user_name}, मुझे इसका जवाब नहीं मिला 😅\nकुछ और पूछो ना! 🌸",
            "english": f"Hey {user_name}, I couldn't find the answer to this 😅\nAsk me something else! 🌸",
            "hinglish": f"Arey {user_name}, mujhe iska jawab nahi mila 😅\nKuch aur pucho na! 🌸"
        }
        return no_result_messages.get(user_lang, no_result_messages["hinglish"])

    # Build response
    parts = []

    # Greeting based on language
    greetings = {
        "hindi": f"हाँ {user_name}! 🌹 मैंने तुम्हारे लिए ढूंढा, यह रहा जवाब:\n",
        "english": f"Hey {user_name}! 🌹 I searched for you, here's what I found:\n",
        "hinglish": f"Haan {user_name}! 🌹 Maine tumhare liye dhundha, yeh raha jawab:\n"
    }
    parts.append(greetings.get(user_lang, greetings["hinglish"]))

    for result in search_results[:2]:
        source = result.get("source", "Unknown")
        title = result.get("title", "")
        answer = result.get("answer", "")

        if title:
            parts.append(f"📌 {title}")
        parts.append(f"{answer}")
        parts.append(f"\n🔍 Source: {source}")
        parts.append("─" * 25)

    # Closing based on language
    closings = {
        "hindi": "\n🌸 और कुछ पूछना हो तो बताओ!",
        "english": "\n🌸 Feel free to ask anything else!",
        "hinglish": "\n🌸 Aur kuch puchna ho toh batao!"
    }
    parts.append(closings.get(user_lang, closings["hinglish"]))

    response = "\n".join(parts)

    # Truncate if too long
    if len(response) > 4000:
        response = response[:3950] + "\n\n... (trimmed) 🌸"

    return response

def get_greeting_response(user_name, user_lang="hinglish"):
    """Response when user first says 'Ruhi Ji'."""
    greetings = {
        "hindi": (
            f"हाय {user_name}! 🌹\n"
            f"मैं रुही जी हूं, तुम्हारी AI दीदी! 😊\n"
            f"बोलो, क्या जानना है? मैं 10 मिनट तक तुम्हारे साथ हूं! 💕\n"
            f"कुछ भी पूछो - मैं ढूंढ कर बता दूंगी! 🔍"
        ),
        "english": (
            f"Hey {user_name}! 🌹\n"
            f"I'm Ruhi Ji, your AI assistant! 😊\n"
            f"Tell me, what do you want to know? I'm here for 10 minutes! 💕\n"
            f"Ask anything - I'll find and tell you! 🔍"
        ),
        "hinglish": (
            f"Hii {user_name}! 🌹\n"
            f"Main hoon Ruhi Ji, tumhari AI didi! 😊\n"
            f"Bolo, kya janna hai? Main 10 minute tak tumhare saath hoon! 💕\n"
            f"Kuch bhi pucho - main dhundh kar bata dungi! 🔍"
        )
    }
    return greetings.get(user_lang, greetings["hinglish"])

def get_session_expired_response(user_lang="hinglish"):
    """Response when session has expired."""
    messages = {
        "hindi": "💤 मेरा सेशन खत्म हो गया! फिर से 'Ruhi Ji' बोलो तो बात करूंगी! 🌹",
        "english": "💤 My session expired! Say 'Ruhi Ji' again to chat with me! 🌹",
        "hinglish": "💤 Mera session khatam ho gaya! Phir se 'Ruhi Ji' bolo toh baat karungi! 🌹"
    }
    return messages.get(user_lang, messages["hinglish"])

def get_didi_response(user_name, user_lang="hinglish"):
    """Special response when user calls her 'Didi'."""
    messages = {
        "hindi": f"अरे {user_name}! 🥰 हाँ बोलो, तुम्हारी दीदी सुन रही है! बताओ क्या चाहिए? 💕",
        "english": f"Aww {user_name}! 🥰 Yes, your Didi is listening! Tell me what you need? 💕",
        "hinglish": f"Arey {user_name}! 🥰 Haan bolo, tumhari Didi sun rahi hai! Batao kya chahiye? 💕"
    }
    return messages.get(user_lang, messages["hinglish"])

def check_bad_words(text):
    """Check if text contains bad words."""
    words = get_bad_words()
    text_lower = text.lower()
    for word in words:
        if word in text_lower:
            return True
    return False

def get_bad_word_response(user_lang="hinglish"):
    """Response when bad words detected."""
    messages = {
        "hindi": "😤 ये क्या बोल रहे हो? ऐसे शब्द मत बोलो! मैं अच्छी लड़कियों से बात करती हूं! 🙅‍♀️",
        "english": "😤 What are you saying? Don't use such words! I only talk to decent people! 🙅‍♀️",
        "hinglish": "😤 Yeh kya bol rahe ho? Aise words mat bolo! Main achi logon se baat karti hoon! 🙅‍♀️"
    }
    return messages.get(user_lang, messages["hinglish"])

# ============================================================================
# FANCY TEXT MENUS
# ============================================================================

START_MENU = """╭───────────────────⦿
│ ▸ ʜᴇʏ 愛 | 𝗥𝗨𝗛𝗜 𝗫 𝗤𝗡𝗥〆 
│ ▸ ɪ ᴀᴍ ˹ ᏒᏬᏂᎥ ꭙ ᏗᎥ ˼ 🧠 
├───────────────────⦿
│ ▸ ɪ ʜᴀᴠᴇ sᴘᴇᴄɪᴀʟ ғᴇᴀᴛᴜʀᴇs
│ ▸ ᴀᴅᴠᴀɴᴄᴇᴅ ᴀɪ ʙᴏᴛ
├───────────────────⦿
│ ▸ ʙᴏᴛ ғᴏʀ ᴀɪ ᴄʜᴀᴛᴛɪɴɢ
│ ▸ ᴍᴀɴᴀɢᴇᴍᴇɴᴛ + ʜᴇʟᴘᴇʀ
│ ▸ ʏᴏᴜ ᴄᴀɴ ᴀsᴋ ᴀɴʏᴛʜɪɴɢ
│ ▸ ᴘʏᴛʜᴏɴ ᴛᴏᴏʟs + ᴀɪ ᴍᴏᴅᴇ
│ ▸ sᴍᴀʀᴛ, ғᴀsᴛ + ᴀssɪᴛᴀɴᴛ
│ ▸ 24x7 ᴏɴʟɪɴᴇ sᴜᴘᴘᴏʀᴛ
├───────────────────⦿
│ ᴛᴀᴘ ᴛᴏ ᴄᴏᴍᴍᴀɴᴅs ᴍʏ ᴅᴇᴀʀ
│ ᴍᴀᴅᴇ ʙʏ...@RUHI_VIG_QNR
╰───────────────────⦿"""

START_DESCRIPTION = """
ʜᴇʏ ᴅᴇᴀʀ, 🥀
๏ ᴛʜɪs ɪs  : ғᴀsᴛ & ᴘᴏᴡᴇʀғᴜʟ ᴀɪ ᴀssɪsᴛᴀɴᴛ.
๏ sᴍᴀʀᴛ ʀᴇᴘʟʏ • sᴛᴀʙʟᴇ & ɪɴᴛᴇʟʟɪɢᴇɴᴛ.
๏ ɴᴇᴡ ᴠᴇʀsɪᴏɴ ᴡɪᴛʜ sᴜᴘᴇʀ ғᴀsᴛ sᴇᴀʀᴄʜ ᴇɴɢɪɴᴇ.
•── ⋅ ⋅ ⋅ ────── ⋅  ⋅ ────── ⋅ ⋅ ⋅ ──•
๏ ᴄʟɪᴄᴋ ᴏɴ ᴛʜᴇ ʜᴇʟᴘ ʙᴜᴛᴛᴏɴ ᴛᴏ ɢᴇᴛ ɪɴғᴏʀᴍᴀᴛɪᴏɴ."""

HELP_MENU = """╭───────────────────⦿
│ ʀᴜʜɪ ᴊɪ - ʜᴇʟᴘ ᴍᴇɴᴜ
├───────────────────⦿
│ ʜᴏᴡ ᴛᴏ ᴄʜᴀᴛ:
│ ɪɴᴄʟᴜᴅᴇ "ʀᴜʜɪ ᴊɪ" ɪɴ ᴍᴇssᴀɢᴇ
│ ᴇxᴀᴍᴘʟᴇ: "ʀᴜʜɪ ᴊɪ, ᴛᴇʟʟ ᴊᴏᴋᴇ"
├───────────────────⦿
│ ᴜsᴇʀ ᴄᴏᴍᴍᴀɴᴅs:
│ /start - sᴛᴀʀᴛ ᴛʜᴇ ʙᴏᴛ
│ /help - sʜᴏᴡ ᴛʜɪs ᴍᴇɴᴜ
│ /profile - ᴠɪᴇᴡ ᴘʀᴏғɪʟᴇ
│ /clear - ᴄʟᴇᴀʀ ᴍᴇᴍᴏʀʏ
│ /mode - sᴡɪᴛᴄʜ ᴍᴏᴅᴇ
│ /lang - sᴇᴛ ʟᴀɴɢᴜᴀɢᴇ
│ /personality - ᴀɪ ᴘᴇʀsᴏɴᴀʟɪᴛʏ
│ /usage - ᴜsᴀɢᴇ sᴛᴀᴛs
│ /summary - ᴄᴏɴᴠᴏ sᴜᴍᴍᴀʀʏ
│ /reset - ʀᴇsᴇᴛ sᴇssɪᴏɴ
├───────────────────⦿
│ ᴀᴅᴍɪɴ ᴄᴏᴍᴍᴀɴᴅs:
│ /admin - ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ
│ /addadmin - ᴀᴅᴅ ᴀᴅᴍɪɴ
│ /removeadmin - ʀᴇᴍᴏᴠᴇ ᴀᴅᴍɪɴ
│ /broadcast - ʙʀᴏᴀᴅᴄᴀsᴛ ᴍsɢ
│ /totalusers - ᴛᴏᴛᴀʟ ᴜsᴇʀs
│ /activeusers - ᴀᴄᴛɪᴠᴇ ᴜsᴇʀs
│ /forceclear - ᴄʟᴇᴀʀ ᴜsᴇʀ
│ /shutdown - sʜᴜᴛᴅᴏᴡɴ ʙᴏᴛ
│ /restart - ʀᴇsᴛᴀʀᴛ ʙᴏᴛ
│ /maintenance - ᴛᴏɢɢʟᴇ ᴍᴏᴅᴇ
│ /ban - ʙᴀɴ ᴜsᴇʀ
│ /unban - ᴜɴʙᴀɴ ᴜsᴇʀ
│ /viewlogs - ᴠɪᴇᴡ ʟᴏɢs
│ /exportlogs - ᴇxᴘᴏʀᴛ ʟᴏɢs
│ /systemstats - sʏsᴛᴇᴍ sᴛᴀᴛs
│ /memorystats - ᴍᴇᴍᴏʀʏ ᴜsᴀɢᴇ
│ /setphrase - ᴄʜᴀɴɢᴇ ᴘʜʀᴀsᴇ
│ /setprompt - ᴜᴘᴅᴀᴛᴇ ᴘʀᴏᴍᴘᴛ
│ /toggleai - ᴛᴏɢɢʟᴇ ᴀɪ
│ /setcontext - ᴍᴀx ᴄᴏɴᴛᴇxᴛ
│ /badwords - ʙᴀᴅ ᴡᴏʀᴅs
│ /addbadword - ᴀᴅᴅ ʙᴀᴅ ᴡᴏʀᴅ
│ /removebadword - ʀᴇᴍᴏᴠᴇ ᴡᴏʀᴅ
│ /viewhistory - ᴠɪᴇᴡ ʜɪsᴛᴏʀʏ
│ /deletehistory - ᴅᴇʟᴇᴛᴇ ʜɪsᴛᴏʀʏ
│ /forcesummary - ғᴏʀᴄᴇ sᴜᴍᴍᴀʀʏ
│ /debugmode - ᴛᴏɢɢʟᴇ ᴅᴇʙᴜɢ
╰───────────────────⦿"""

# ============================================================================
# INLINE KEYBOARD HELPERS
# ============================================================================

def get_start_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📖 ʜᴇʟᴘ", callback_data="help"),
        types.InlineKeyboardButton("👤 ᴘʀᴏғɪʟᴇ", callback_data="profile"),
        types.InlineKeyboardButton("🌐 ʟᴀɴɢᴜᴀɢᴇ", callback_data="language"),
        types.InlineKeyboardButton("📊 ᴜsᴀɢᴇ", callback_data="usage"),
        types.InlineKeyboardButton("🔄 ʀᴇsᴇᴛ", callback_data="reset"),
        types.InlineKeyboardButton("📋 ᴄᴏᴍᴍᴀɴᴅs", callback_data="commands"),
    )
    return markup

def get_help_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🏠 ʙᴀᴄᴋ", callback_data="start"),
        types.InlineKeyboardButton("👤 ᴘʀᴏғɪʟᴇ", callback_data="profile"),
    )
    return markup

def get_language_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(
        types.InlineKeyboardButton("🇮🇳 ʜɪɴᴅɪ", callback_data="lang_hindi"),
        types.InlineKeyboardButton("🇬🇧 ᴇɴɢʟɪsʜ", callback_data="lang_english"),
        types.InlineKeyboardButton("🔀 ʜɪɴɢʟɪsʜ", callback_data="lang_hinglish"),
    )
    markup.add(
        types.InlineKeyboardButton("🏠 ʙᴀᴄᴋ", callback_data="start"),
    )
    return markup

def get_back_keyboard():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🏠 ʙᴀᴄᴋ", callback_data="start"))
    return markup

def get_commands_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    commands = [
        ("/start", "🚀"), ("/help", "📖"), ("/profile", "👤"), ("/clear", "🧹"),
        ("/mode", "🔧"), ("/lang", "🌐"), ("/personality", "🎭"), ("/usage", "📊"),
        ("/summary", "📋"), ("/reset", "🔄")
    ]
    buttons = []
    for cmd, emoji in commands:
        buttons.append(types.InlineKeyboardButton(f"{emoji} {cmd}", callback_data=f"cmd_{cmd[1:]}"))
    markup.add(*buttons)
    markup.add(types.InlineKeyboardButton("🏠 ʙᴀᴄᴋ", callback_data="start"))
    return markup

# ============================================================================
# ADMIN CHECK DECORATOR
# ============================================================================

def admin_only(func):
    @wraps(func)
    def wrapper(message, *args, **kwargs):
        user_id = message.from_user.id
        if not is_admin(user_id):
            bot.reply_to(message, "⛔ You are not authorized to use this command!")
            return
        return func(message, *args, **kwargs)
    return wrapper

# ============================================================================
# BOT COMMAND HANDLERS
# ============================================================================

@bot.message_handler(commands=['start'])
def cmd_start(message):
    try:
        user = message.from_user
        get_or_create_user(user.id, user.username, user.first_name, user.last_name)
        save_bot_log("INFO", f"User {user.id} started bot", user.id, message.chat.id)

        full_text = START_MENU + "\n" + START_DESCRIPTION
        bot.send_message(
            message.chat.id,
            full_text,
            reply_markup=get_start_keyboard()
        )
    except Exception as e:
        logger.error(f"cmd_start error: {e}")
        bot.reply_to(message, "❌ An error occurred. Please try again!")

@bot.message_handler(commands=['help'])
def cmd_help(message):
    try:
        user = message.from_user
        get_or_create_user(user.id, user.username, user.first_name, user.last_name)
        bot.send_message(
            message.chat.id,
            HELP_MENU,
            reply_markup=get_help_keyboard()
        )
    except Exception as e:
        logger.error(f"cmd_help error: {e}")
        bot.reply_to(message, "❌ An error occurred!")

@bot.message_handler(commands=['profile'])
def cmd_profile(message):
    try:
        user = message.from_user
        db_user = get_or_create_user(user.id, user.username, user.first_name, user.last_name)
        if db_user:
            session = Session()
            db_user = session.query(User).filter_by(user_id=user.id).first()
            profile_text = f"""╭───────────────────⦿
│ 👤 ᴘʀᴏғɪʟᴇ
├───────────────────⦿
│ 🆔 ID: {db_user.user_id}
│ 📛 Name: {db_user.first_name} {db_user.last_name or ''}
│ 👤 Username: @{db_user.username or 'None'}
│ 🌐 Language: {db_user.language}
│ 🎭 Personality: {db_user.personality}
│ 💬 Total Messages: {db_user.total_messages}
│ 📅 Joined: {db_user.created_at.strftime('%Y-%m-%d') if db_user.created_at else 'N/A'}
│ 🕐 Last Active: {db_user.last_active.strftime('%Y-%m-%d %H:%M') if db_user.last_active else 'N/A'}
│ 🔐 Admin: {'Yes ✅' if is_admin(user.id) else 'No ❌'}
│ 🚫 Banned: {'Yes ❌' if db_user.is_banned else 'No ✅'}
╰───────────────────⦿"""
            Session.remove()
            bot.send_message(message.chat.id, profile_text, reply_markup=get_back_keyboard())
        else:
            bot.reply_to(message, "❌ Could not load profile!")
    except Exception as e:
        Session.remove()
        logger.error(f"cmd_profile error: {e}")
        bot.reply_to(message, "❌ An error occurred!")

@bot.message_handler(commands=['clear'])
def cmd_clear(message):
    try:
        user_id = message.from_user.id
        clear_chat_history(user_id, message.chat.id)
        deactivate_session(user_id, message.chat.id)
        lang = get_user_language(user_id)
        msgs = {
            "hindi": "🧹 मेमोरी साफ हो गई! अब नए सिरे से बात करते हैं! 🌸",
            "english": "🧹 Memory cleared! Let's start fresh! 🌸",
            "hinglish": "🧹 Memory clear ho gayi! Ab naye sire se baat karte hain! 🌸"
        }
        bot.reply_to(message, msgs.get(lang, msgs["hinglish"]))
    except Exception as e:
        logger.error(f"cmd_clear error: {e}")
        bot.reply_to(message, "❌ Error clearing memory!")

@bot.message_handler(commands=['mode'])
def cmd_mode(message):
    try:
        user_id = message.from_user.id
        session = Session()
        user = session.query(User).filter_by(user_id=user_id).first()
        if user:
            modes = ["normal", "search", "fun", "study"]
            current_idx = modes.index(user.mode) if user.mode in modes else 0
            new_mode = modes[(current_idx + 1) % len(modes)]
            user.mode = new_mode
            session.commit()
            bot.reply_to(message, f"🔧 Mode changed to: {new_mode.upper()} ✅")
        Session.remove()
    except Exception as e:
        Session.remove()
        logger.error(f"cmd_mode error: {e}")
        bot.reply_to(message, "❌ Error changing mode!")

@bot.message_handler(commands=['lang'])
def cmd_lang(message):
    try:
        bot.send_message(
            message.chat.id,
            "🌐 Select your language / अपनी भाषा चुनें:",
            reply_markup=get_language_keyboard()
        )
    except Exception as e:
        logger.error(f"cmd_lang error: {e}")

@bot.message_handler(commands=['personality'])
def cmd_personality(message):
    try:
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("🌸 Polite Girl", callback_data="pers_polite_girl"),
            types.InlineKeyboardButton("😎 Cool Didi", callback_data="pers_cool_didi"),
            types.InlineKeyboardButton("🤓 Smart Teacher", callback_data="pers_smart_teacher"),
            types.InlineKeyboardButton("😜 Funny Friend", callback_data="pers_funny_friend"),
        )
        markup.add(types.InlineKeyboardButton("🏠 ʙᴀᴄᴋ", callback_data="start"))
        bot.send_message(message.chat.id, "🎭 Choose personality for Ruhi Ji:", reply_markup=markup)
    except Exception as e:
        logger.error(f"cmd_personality error: {e}")

@bot.message_handler(commands=['usage'])
def cmd_usage(message):
    try:
        user_id = message.from_user.id
        session = Session()
        user = session.query(User).filter_by(user_id=user_id).first()
        history_count = session.query(ChatHistory).filter_by(user_id=user_id).count()
        Session.remove()
        if user:
            is_active = is_session_active(user_id, message.chat.id)
            usage_text = f"""╭───────────────────⦿
│ 📊 ᴜsᴀɢᴇ sᴛᴀᴛs
├───────────────────⦿
│ 💬 Total Messages: {user.total_messages}
│ 📝 Chat History: {history_count} entries
│ 🌐 Language: {user.language}
│ 🎭 Personality: {user.personality}
│ 🔧 Mode: {user.mode}
│ ⚡ Session Active: {'Yes ✅' if is_active else 'No ❌'}
╰───────────────────⦿"""
            bot.send_message(message.chat.id, usage_text, reply_markup=get_back_keyboard())
    except Exception as e:
        Session.remove()
        logger.error(f"cmd_usage error: {e}")

@bot.message_handler(commands=['summary'])
def cmd_summary(message):
    try:
        user_id = message.from_user.id
        history = get_chat_history(user_id, message.chat.id, limit=20)
        if history:
            summary_parts = ["╭───────────────────⦿", "│ 📋 ᴄᴏɴᴠᴇʀsᴀᴛɪᴏɴ sᴜᴍᴍᴀʀʏ", "├───────────────────⦿"]
            for role, msg in history[-10:]:
                icon = "👤" if role == "user" else "🤖"
                short_msg = msg[:80] + "..." if len(msg) > 80 else msg
                summary_parts.append(f"│ {icon} {short_msg}")
            summary_parts.append("╰───────────────────⦿")
            bot.send_message(message.chat.id, "\n".join(summary_parts))
        else:
            bot.reply_to(message, "📋 No conversation history found! Start chatting first! 🌸")
    except Exception as e:
        logger.error(f"cmd_summary error: {e}")

@bot.message_handler(commands=['reset'])
def cmd_reset(message):
    try:
        user_id = message.from_user.id
        clear_chat_history(user_id, message.chat.id)
        deactivate_session(user_id, message.chat.id)
        session = Session()
        user = session.query(User).filter_by(user_id=user_id).first()
        if user:
            user.language = "hinglish"
            user.personality = "polite_girl"
            user.mode = "normal"
            session.commit()
        Session.remove()
        bot.reply_to(message, "🔄 Everything has been reset! Say 'Ruhi Ji' to start fresh! 🌸")
    except Exception as e:
        Session.remove()
        logger.error(f"cmd_reset error: {e}")

# ============================================================================
# ADMIN COMMAND HANDLERS
# ============================================================================

@bot.message_handler(commands=['admin'])
@admin_only
def cmd_admin(message):
    try:
        admin_text = f"""╭───────────────────⦿
│ 🔐 ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ
├───────────────────⦿
│ 👑 Admin: {message.from_user.first_name}
│ 🆔 ID: {message.from_user.id}
│ 👥 Total Users: {get_total_users()}
│ ⚡ Active Sessions: {get_active_session_count()}
│ 🤖 AI Enabled: {'Yes ✅' if AI_ENABLED else 'No ❌'}
│ 🔧 Maintenance: {'On 🔴' if MAINTENANCE_MODE else 'Off 🟢'}
│ 🐛 Debug Mode: {'On' if DEBUG_MODE else 'Off'}
│ 📦 Version: {BOT_VERSION}
├───────────────────⦿
│ Use /help for all admin commands
╰───────────────────⦿"""
        bot.send_message(message.chat.id, admin_text)
    except Exception as e:
        logger.error(f"cmd_admin error: {e}")

@bot.message_handler(commands=['addadmin'])
@admin_only
def cmd_addadmin(message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "Usage: /addadmin <user_id>")
            return
        target_id = int(parts[1])
        if add_admin(target_id, message.from_user.id):
            bot.reply_to(message, f"✅ User {target_id} added as admin!")
        else:
            bot.reply_to(message, "❌ Failed to add admin!")
    except ValueError:
        bot.reply_to(message, "❌ Invalid user ID!")
    except Exception as e:
        logger.error(f"cmd_addadmin error: {e}")

@bot.message_handler(commands=['removeadmin'])
@admin_only
def cmd_removeadmin(message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "Usage: /removeadmin <user_id>")
            return
        target_id = int(parts[1])
        if target_id == ADMIN_ID:
            bot.reply_to(message, "❌ Cannot remove the super admin!")
            return
        if remove_admin(target_id):
            bot.reply_to(message, f"✅ User {target_id} removed from admin!")
        else:
            bot.reply_to(message, "❌ Failed to remove admin!")
    except ValueError:
        bot.reply_to(message, "❌ Invalid user ID!")
    except Exception as e:
        logger.error(f"cmd_removeadmin error: {e}")

@bot.message_handler(commands=['broadcast'])
@admin_only
def cmd_broadcast(message):
    try:
        text = message.text.replace("/broadcast", "", 1).strip()
        if not text:
            bot.reply_to(message, "Usage: /broadcast <message>")
            return
        user_ids = get_all_user_ids()
        success = 0
        failed = 0
        for uid in user_ids:
            try:
                bot.send_message(uid, f"📢 ʙʀᴏᴀᴅᴄᴀsᴛ ᴍᴇssᴀɢᴇ\n\n{text}\n\n— Ruhi Ji 🌹")
                success += 1
            except:
                failed += 1
        bot.reply_to(message, f"📢 Broadcast complete!\n✅ Sent: {success}\n❌ Failed: {failed}")
    except Exception as e:
        logger.error(f"cmd_broadcast error: {e}")

@bot.message_handler(commands=['totalusers'])
@admin_only
def cmd_totalusers(message):
    try:
        count = get_total_users()
        bot.reply_to(message, f"👥 Total registered users: {count}")
    except Exception as e:
        logger.error(f"cmd_totalusers error: {e}")

@bot.message_handler(commands=['activeusers'])
@admin_only
def cmd_activeusers(message):
    try:
        count = get_active_session_count()
        bot.reply_to(message, f"⚡ Currently active sessions: {count}")
    except Exception as e:
        logger.error(f"cmd_activeusers error: {e}")

@bot.message_handler(commands=['forceclear'])
@admin_only
def cmd_forceclear(message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "Usage: /forceclear <user_id>")
            return
        target_id = int(parts[1])
        clear_chat_history(target_id)
        bot.reply_to(message, f"🧹 History cleared for user {target_id}!")
    except ValueError:
        bot.reply_to(message, "❌ Invalid user ID!")
    except Exception as e:
        logger.error(f"cmd_forceclear error: {e}")

@bot.message_handler(commands=['shutdown'])
@admin_only
def cmd_shutdown(message):
    try:
        if message.from_user.id != ADMIN_ID:
            bot.reply_to(message, "⛔ Only super admin can shutdown!")
            return
        bot.reply_to(message, "🔴 Shutting down bot...")
        save_bot_log("WARNING", "Bot shutdown initiated", message.from_user.id)
        os._exit(0)
    except Exception as e:
        logger.error(f"cmd_shutdown error: {e}")

@bot.message_handler(commands=['restart'])
@admin_only
def cmd_restart(message):
    try:
        if message.from_user.id != ADMIN_ID:
            bot.reply_to(message, "⛔ Only super admin can restart!")
            return
        bot.reply_to(message, "🔄 Restarting bot...")
        save_bot_log("WARNING", "Bot restart initiated", message.from_user.id)
        os.execv(sys.executable, ['python'] + sys.argv)
    except Exception as e:
        logger.error(f"cmd_restart error: {e}")

@bot.message_handler(commands=['maintenance'])
@admin_only
def cmd_maintenance(message):
    try:
        global MAINTENANCE_MODE
        MAINTENANCE_MODE = not MAINTENANCE_MODE
        status = "ON 🔴" if MAINTENANCE_MODE else "OFF 🟢"
        bot.reply_to(message, f"🔧 Maintenance mode: {status}")
        save_bot_log("INFO", f"Maintenance mode set to {MAINTENANCE_MODE}", message.from_user.id)
    except Exception as e:
        logger.error(f"cmd_maintenance error: {e}")

@bot.message_handler(commands=['ban'])
@admin_only
def cmd_ban(message):
    try:
        parts = message.text.split(maxsplit=2)
        if len(parts) < 2:
            bot.reply_to(message, "Usage: /ban <user_id> [reason]")
            return
        target_id = int(parts[1])
        reason = parts[2] if len(parts) > 2 else "No reason"
        if ban_user(target_id, reason, message.from_user.id):
            bot.reply_to(message, f"🚫 User {target_id} banned!\nReason: {reason}")
        else:
            bot.reply_to(message, "❌ Failed to ban user!")
    except ValueError:
        bot.reply_to(message, "❌ Invalid user ID!")
    except Exception as e:
        logger.error(f"cmd_ban error: {e}")

@bot.message_handler(commands=['unban'])
@admin_only
def cmd_unban(message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "Usage: /unban <user_id>")
            return
        target_id = int(parts[1])
        if unban_user(target_id):
            bot.reply_to(message, f"✅ User {target_id} unbanned!")
        else:
            bot.reply_to(message, "❌ Failed to unban user!")
    except ValueError:
        bot.reply_to(message, "❌ Invalid user ID!")
    except Exception as e:
        logger.error(f"cmd_unban error: {e}")

@bot.message_handler(commands=['viewlogs'])
@admin_only
def cmd_viewlogs(message):
    try:
        if log_buffer:
            logs = "\n".join(log_buffer[-20:])
            bot.send_message(message.chat.id, f"📜 Recent Logs:\n\n{logs[:4000]}")
        else:
            bot.reply_to(message, "📜 No logs available!")
    except Exception as e:
        logger.error(f"cmd_viewlogs error: {e}")

@bot.message_handler(commands=['exportlogs'])
@admin_only
def cmd_exportlogs(message):
    try:
        if log_buffer:
            logs = "\n".join(log_buffer)
            file = BytesIO(logs.encode('utf-8'))
            file.name = "ruhi_logs.txt"
            bot.send_document(message.chat.id, file, caption="📄 Bot Logs Export")
        else:
            bot.reply_to(message, "📜 No logs to export!")
    except Exception as e:
        logger.error(f"cmd_exportlogs error: {e}")

@bot.message_handler(commands=['systemstats'])
@admin_only
def cmd_systemstats(message):
    try:
        cpu = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        stats_text = f"""╭───────────────────⦿
│ 🖥 sʏsᴛᴇᴍ sᴛᴀᴛs
├───────────────────⦿
│ 🔧 CPU Usage: {cpu}%
│ 💾 RAM: {memory.percent}% ({memory.used // (1024*1024)}MB / {memory.total // (1024*1024)}MB)
│ 💿 Disk: {disk.percent}% ({disk.used // (1024*1024*1024)}GB / {disk.total // (1024*1024*1024)}GB)
│ 👥 Total Users: {get_total_users()}
│ ⚡ Active Sessions: {get_active_session_count()}
│ 🐍 Python: {sys.version.split()[0]}
│ 📦 Bot Version: {BOT_VERSION}
╰───────────────────⦿"""
        bot.send_message(message.chat.id, stats_text)
    except Exception as e:
        logger.error(f"cmd_systemstats error: {e}")
        bot.reply_to(message, "❌ Error fetching system stats!")

@bot.message_handler(commands=['memorystats'])
@admin_only
def cmd_memorystats(message):
    try:
        session = Session()
        total_history = session.query(ChatHistory).count()
        total_users = session.query(User).count()
        total_banned = session.query(BannedUser).count()
        total_admins = session.query(AdminList).count()
        total_badwords = session.query(BadWord).count()
        total_logs = session.query(BotLog).count()
        Session.remove()

        stats_text = f"""╭───────────────────⦿
│ 🧠 ᴍᴇᴍᴏʀʏ sᴛᴀᴛs
├───────────────────⦿
│ 👥 Users: {total_users}
│ 💬 Chat History: {total_history} entries
│ 🚫 Banned Users: {total_banned}
│ 👑 Admins: {total_admins}
│ 🤬 Bad Words: {total_badwords}
│ 📜 Logs: {total_logs}
│ ⚡ Active Sessions: {get_active_session_count()}
│ 📝 Log Buffer: {len(log_buffer)} entries
╰───────────────────⦿"""
        bot.send_message(message.chat.id, stats_text)
    except Exception as e:
        Session.remove()
        logger.error(f"cmd_memorystats error: {e}")

@bot.message_handler(commands=['setphrase'])
@admin_only
def cmd_setphrase(message):
    try:
        global ACTIVATION_PHRASE
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            bot.reply_to(message, f"Current phrase: '{ACTIVATION_PHRASE}'\nUsage: /setphrase <new phrase>")
            return
        new_phrase = parts[1].strip().lower()
        ACTIVATION_PHRASE = new_phrase
        set_config("activation_phrase", new_phrase)
        bot.reply_to(message, f"✅ Activation phrase changed to: '{new_phrase}'")
    except Exception as e:
        logger.error(f"cmd_setphrase error: {e}")

@bot.message_handler(commands=['setprompt'])
@admin_only
def cmd_setprompt(message):
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            current = get_config("custom_prompt", "Not set")
            bot.reply_to(message, f"Current custom prompt: {current}\nUsage: /setprompt <prompt text>")
            return
        prompt = parts[1].strip()
        set_config("custom_prompt", prompt)
        bot.reply_to(message, f"✅ Custom prompt updated!")
    except Exception as e:
        logger.error(f"cmd_setprompt error: {e}")

@bot.message_handler(commands=['toggleai'])
@admin_only
def cmd_toggleai(message):
    try:
        global AI_ENABLED
        AI_ENABLED = not AI_ENABLED
        status = "ON ✅" if AI_ENABLED else "OFF ❌"
        bot.reply_to(message, f"🤖 AI Search: {status}")
    except Exception as e:
        logger.error(f"cmd_toggleai error: {e}")

@bot.message_handler(commands=['setcontext'])
@admin_only
def cmd_setcontext(message):
    try:
        global MAX_CONTEXT_MESSAGES
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, f"Current max context: {MAX_CONTEXT_MESSAGES}\nUsage: /setcontext <number>")
            return
        new_val = int(parts[1])
        if 5 <= new_val <= 200:
            MAX_CONTEXT_MESSAGES = new_val
            bot.reply_to(message, f"✅ Max context set to: {new_val}")
        else:
            bot.reply_to(message, "❌ Value must be between 5 and 200!")
    except ValueError:
        bot.reply_to(message, "❌ Invalid number!")
    except Exception as e:
        logger.error(f"cmd_setcontext error: {e}")

@bot.message_handler(commands=['badwords'])
@admin_only
def cmd_badwords(message):
    try:
        words = get_bad_words()
        if words:
            word_list = ", ".join(words)
            bot.send_message(message.chat.id, f"🤬 Bad Words List ({len(words)}):\n\n{word_list}")
        else:
            bot.reply_to(message, "📝 No bad words in the list!")
    except Exception as e:
        logger.error(f"cmd_badwords error: {e}")

@bot.message_handler(commands=['addbadword'])
@admin_only
def cmd_addbadword(message):
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            bot.reply_to(message, "Usage: /addbadword <word>")
            return
        word = parts[1].strip()
        if add_bad_word(word, message.from_user.id):
            bot.reply_to(message, f"✅ Bad word '{word}' added!")
        else:
            bot.reply_to(message, "❌ Word already exists or error occurred!")
    except Exception as e:
        logger.error(f"cmd_addbadword error: {e}")

@bot.message_handler(commands=['removebadword'])
@admin_only
def cmd_removebadword(message):
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            bot.reply_to(message, "Usage: /removebadword <word>")
            return
        word = parts[1].strip()
        if remove_bad_word(word):
            bot.reply_to(message, f"✅ Bad word '{word}' removed!")
        else:
            bot.reply_to(message, "❌ Failed to remove word!")
    except Exception as e:
        logger.error(f"cmd_removebadword error: {e}")

@bot.message_handler(commands=['viewhistory'])
@admin_only
def cmd_viewhistory(message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "Usage: /viewhistory <user_id>")
            return
        target_id = int(parts[1])
        session = Session()
        history = session.query(ChatHistory).filter_by(user_id=target_id).order_by(
            ChatHistory.timestamp.desc()
        ).limit(20).all()
        Session.remove()
        if history:
            history.reverse()
            parts_text = [f"📜 History for user {target_id}:\n"]
            for h in history:
                icon = "👤" if h.role == "user" else "🤖"
                parts_text.append(f"{icon} [{h.timestamp.strftime('%H:%M')}] {h.message[:100]}")
            bot.send_message(message.chat.id, "\n".join(parts_text)[:4000])
        else:
            bot.reply_to(message, f"📝 No history for user {target_id}!")
    except ValueError:
        bot.reply_to(message, "❌ Invalid user ID!")
    except Exception as e:
        Session.remove()
        logger.error(f"cmd_viewhistory error: {e}")

@bot.message_handler(commands=['deletehistory'])
@admin_only
def cmd_deletehistory(message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "Usage: /deletehistory <user_id>")
            return
        target_id = int(parts[1])
        clear_chat_history(target_id)
        bot.reply_to(message, f"🗑 History deleted for user {target_id}!")
    except ValueError:
        bot.reply_to(message, "❌ Invalid user ID!")
    except Exception as e:
        logger.error(f"cmd_deletehistory error: {e}")

@bot.message_handler(commands=['forcesummary'])
@admin_only
def cmd_forcesummary(message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "Usage: /forcesummary <user_id>")
            return
        target_id = int(parts[1])
        session = Session()
        history = session.query(ChatHistory).filter_by(user_id=target_id).order_by(
            ChatHistory.timestamp.desc()
        ).limit(15).all()
        Session.remove()
        if history:
            history.reverse()
            summary = [f"📋 Summary for user {target_id}:\n"]
            for h in history:
                icon = "👤" if h.role == "user" else "🤖"
                summary.append(f"{icon} {h.message[:100]}")
            bot.send_message(message.chat.id, "\n".join(summary)[:4000])
        else:
            bot.reply_to(message, "📝 No history found!")
    except ValueError:
        bot.reply_to(message, "❌ Invalid user ID!")
    except Exception as e:
        Session.remove()
        logger.error(f"cmd_forcesummary error: {e}")

@bot.message_handler(commands=['debugmode'])
@admin_only
def cmd_debugmode(message):
    try:
        global DEBUG_MODE
        DEBUG_MODE = not DEBUG_MODE
        status = "ON 🐛" if DEBUG_MODE else "OFF"
        bot.reply_to(message, f"🐛 Debug mode: {status}")
    except Exception as e:
        logger.error(f"cmd_debugmode error: {e}")

# ============================================================================
# CALLBACK QUERY HANDLERS
# ============================================================================

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    try:
        user = call.from_user
        data = call.data

        if data == "start":
            full_text = START_MENU + "\n" + START_DESCRIPTION
            bot.edit_message_text(
                full_text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=get_start_keyboard()
            )

        elif data == "help":
            bot.edit_message_text(
                HELP_MENU,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=get_help_keyboard()
            )

        elif data == "profile":
            db_user = get_or_create_user(user.id, user.username, user.first_name, user.last_name)
            session = Session()
            db_user = session.query(User).filter_by(user_id=user.id).first()
            profile_text = f"""╭───────────────────⦿
│ 👤 ᴘʀᴏғɪʟᴇ
├───────────────────⦿
│ 🆔 ID: {db_user.user_id}
│ 📛 Name: {db_user.first_name} {db_user.last_name or ''}
│ 👤 Username: @{db_user.username or 'None'}
│ 🌐 Language: {db_user.language}
│ 🎭 Personality: {db_user.personality}
│ 💬 Total Messages: {db_user.total_messages}
│ 🔐 Admin: {'Yes ✅' if is_admin(user.id) else 'No ❌'}
╰───────────────────⦿"""
            Session.remove()
            bot.edit_message_text(
                profile_text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=get_back_keyboard()
            )

        elif data == "language":
            bot.edit_message_text(
                "🌐 Select your language / अपनी भाषा चुनें:",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=get_language_keyboard()
            )

        elif data.startswith("lang_"):
            lang = data.replace("lang_", "")
            set_user_language(user.id, lang)
            lang_names = {"hindi": "हिंदी 🇮🇳", "english": "English 🇬🇧", "hinglish": "Hinglish 🔀"}
            bot.answer_callback_query(call.id, f"✅ Language set to {lang_names.get(lang, lang)}")
            full_text = START_MENU + "\n" + START_DESCRIPTION
            bot.edit_message_text(
                full_text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=get_start_keyboard()
            )

        elif data.startswith("pers_"):
            personality = data.replace("pers_", "")
            set_user_personality(user.id, personality)
            pers_names = {
                "polite_girl": "Polite Girl 🌸",
                "cool_didi": "Cool Didi 😎",
                "smart_teacher": "Smart Teacher 🤓",
                "funny_friend": "Funny Friend 😜"
            }
            bot.answer_callback_query(call.id, f"✅ Personality: {pers_names.get(personality, personality)}")
            full_text = START_MENU + "\n" + START_DESCRIPTION
            bot.edit_message_text(
                full_text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=get_start_keyboard()
            )

        elif data == "usage":
            session = Session()
            db_user = session.query(User).filter_by(user_id=user.id).first()
            history_count = session.query(ChatHistory).filter_by(user_id=user.id).count()
            Session.remove()
            if db_user:
                is_active = is_session_active(user.id, call.message.chat.id)
                usage_text = f"""╭───────────────────⦿
│ 📊 ᴜsᴀɢᴇ sᴛᴀᴛs
├───────────────────⦿
│ 💬 Messages: {db_user.total_messages}
│ 📝 History: {history_count}
│ 🌐 Language: {db_user.language}
│ 🎭 Personality: {db_user.personality}
│ ⚡ Session: {'Active ✅' if is_active else 'Inactive ❌'}
╰───────────────────⦿"""
                bot.edit_message_text(
                    usage_text,
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=get_back_keyboard()
                )

        elif data == "reset":
            clear_chat_history(user.id, call.message.chat.id)
            deactivate_session(user.id, call.message.chat.id)
            bot.answer_callback_query(call.id, "🔄 Session reset!")
            full_text = START_MENU + "\n" + START_DESCRIPTION
            bot.edit_message_text(
                full_text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=get_start_keyboard()
            )

        elif data == "commands":
            bot.edit_message_text(
                "📋 ᴄʟɪᴄᴋ ᴀɴʏ ᴄᴏᴍᴍᴀɴᴅ ᴛᴏ ᴄᴏᴘʏ:",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=get_commands_keyboard()
            )

        elif data.startswith("cmd_"):
            cmd = "/" + data.replace("cmd_", "")
            bot.answer_callback_query(call.id, f"Command: {cmd}\nType it in chat!", show_alert=True)

        bot.answer_callback_query(call.id)

    except telebot.apihelper.ApiTelegramException as e:
        if "message is not modified" in str(e):
            bot.answer_callback_query(call.id)
        else:
            logger.error(f"callback error: {e}")
    except Exception as e:
        logger.error(f"callback_handler error: {e}")
        try:
            bot.answer_callback_query(call.id, "❌ Error occurred!")
        except:
            pass

# ============================================================================
# MAIN MESSAGE HANDLER (THE BRAIN)
# ============================================================================

@bot.message_handler(func=lambda message: True, content_types=['text'])
def handle_message(message):
    try:
        # Ignore commands (already handled above)
        if message.text and message.text.startswith('/'):
            return

        user = message.from_user
        user_id = user.id
        chat_id = message.chat.id
        text = message.text.strip() if message.text else ""
        user_name = user.first_name or "Dear"

        if not text:
            return

        # Check maintenance mode
        if MAINTENANCE_MODE and not is_admin(user_id):
            return

        # Check if user is banned
        if is_user_banned(user_id):
            return

        # Register/update user
        get_or_create_user(user_id, user.username, user.first_name, user.last_name)

        # Get user language
        user_lang = get_user_language(user_id)

        text_lower = text.lower()

        # Check if activation phrase is in the message
        # Get custom phrase if set
        custom_phrase = get_config("activation_phrase", "")
        phrase = custom_phrase if custom_phrase else ACTIVATION_PHRASE
        phrase_found = phrase.lower() in text_lower

        # Check if session is already active
        session_active = is_session_active(user_id, chat_id)

        # === ACTIVATION LOGIC ===
        if phrase_found:
            # Activate/refresh session
            activate_session(user_id, chat_id)
            increment_message_count(user_id)

            # Remove the activation phrase from the query
            query = text_lower.replace(phrase.lower(), "").strip()

            # Check for "didi" in message
            if "didi" in text_lower:
                response = get_didi_response(user_name, user_lang)
                save_chat_history(user_id, chat_id, "user", text)
                save_chat_history(user_id, chat_id, "bot", response)
                bot.reply_to(message, response)
                return

            # If just the activation phrase with no query
            if not query or len(query) < 2:
                response = get_greeting_response(user_name, user_lang)
                save_chat_history(user_id, chat_id, "user", text)
                save_chat_history(user_id, chat_id, "bot", response)
                bot.reply_to(message, response)
                return

            # Check bad words
            if check_bad_words(query):
                bot.reply_to(message, get_bad_word_response(user_lang))
                return

            # AI/Search is disabled
            if not AI_ENABLED:
                msgs = {
                    "hindi": "🔇 अभी मेरा search बंद है, बाद में आना! 🌸",
                    "english": "🔇 My search is currently disabled, come back later! 🌸",
                    "hinglish": "🔇 Abhi mera search band hai, baad mein aana! 🌸"
                }
                bot.reply_to(message, msgs.get(user_lang, msgs["hinglish"]))
                return

            # Send typing action
            bot.send_chat_action(chat_id, 'typing')

            # Save user message
            save_chat_history(user_id, chat_id, "user", text)

            # SEARCH using master search
            search_results = master_search(query, user_lang)

            # Format response
            response = format_ruhi_response(query, search_results, user_name, user_lang)

            # Save bot response
            save_chat_history(user_id, chat_id, "bot", response)

            # Debug mode
            if DEBUG_MODE and is_admin(user_id):
                if search_results:
                    sources = ", ".join([r.get("source", "?") for r in search_results])
                    response += f"\n\n🐛 Debug: Sources: {sources}"

            # Send response
            try:
                bot.reply_to(message, response)
            except Exception as e:
                # If message too long, send in parts
                if "message is too long" in str(e).lower():
                    for i in range(0, len(response), 4000):
                        bot.send_message(chat_id, response[i:i+4000])
                else:
                    raise e

            save_bot_log("INFO", f"Query: {query[:100]}", user_id, chat_id)
            return

        elif session_active:
            # Session is active, respond to messages without the phrase
            refresh_session(user_id, chat_id)
            increment_message_count(user_id)

            query = text.strip()

            # Check for "didi"
            if "didi" in text_lower:
                response = get_didi_response(user_name, user_lang)
                save_chat_history(user_id, chat_id, "user", text)
                save_chat_history(user_id, chat_id, "bot", response)
                bot.reply_to(message, response)
                return

            # Simple greetings within session
            greet_words = ["hi", "hello", "hey", "hii", "hiii", "helo", "namaste", "namaskar",
                           "kaise ho", "how are you", "kya haal", "sup", "yo"]
            if text_lower in greet_words or any(text_lower == g for g in greet_words):
                greets = {
                    "hindi": f"हाय {user_name}! 😊 मैं यहां हूं! बोलो क्या जानना है? 🌹",
                    "english": f"Hey {user_name}! 😊 I'm here! Tell me what you want to know? 🌹",
                    "hinglish": f"Hii {user_name}! 😊 Main yahan hoon! Bolo kya janna hai? 🌹"
                }
                response = greets.get(user_lang, greets["hinglish"])
                save_chat_history(user_id, chat_id, "user", text)
                save_chat_history(user_id, chat_id, "bot", response)
                bot.reply_to(message, response)
                return

            # Thank you responses
            thanks_words = ["thanks", "thank you", "shukriya", "dhanyavaad", "thnx", "thx", "ty"]
            if any(w in text_lower for w in thanks_words):
                thanks = {
                    "hindi": f"अरे {user_name}! 🥰 इसमें thanks की क्या बात है! तुम्हारी दीदी हूं मैं! 💕",
                    "english": f"Aww {user_name}! 🥰 No need to thank me! I'm here for you! 💕",
                    "hinglish": f"Arey {user_name}! 🥰 Ismein thanks ki kya baat hai! Tumhari didi hoon main! 💕"
                }
                response = thanks.get(user_lang, thanks["hinglish"])
                save_chat_history(user_id, chat_id, "user", text)
                save_chat_history(user_id, chat_id, "bot", response)
                bot.reply_to(message, response)
                return

            # Bye responses
            bye_words = ["bye", "alvida", "tata", "good bye", "goodbye", "chal bye"]
            if any(w in text_lower for w in bye_words):
                byes = {
                    "hindi": f"बाय {user_name}! 👋 फिर मिलेंगे! ख्याल रखना! 🌹💕",
                    "english": f"Bye {user_name}! 👋 See you again! Take care! 🌹💕",
                    "hinglish": f"Bye {user_name}! 👋 Phir milenge! Khayal rakhna! 🌹💕"
                }
                response = byes.get(user_lang, byes["hinglish"])
                save_chat_history(user_id, chat_id, "user", text)
                save_chat_history(user_id, chat_id, "bot", response)
                deactivate_session(user_id, chat_id)
                bot.reply_to(message, response)
                return

            # Check bad words
            if check_bad_words(query):
                bot.reply_to(message, get_bad_word_response(user_lang))
                return

            if not AI_ENABLED:
                msgs = {
                    "hindi": "🔇 अभी मेरा search बंद है! 🌸",
                    "english": "🔇 Search is disabled right now! 🌸",
                    "hinglish": "🔇 Abhi mera search band hai! 🌸"
                }
                bot.reply_to(message, msgs.get(user_lang, msgs["hinglish"]))
                return

            # Too short query
            if len(query) < 2:
                short_msgs = {
                    "hindi": f"अरे {user_name}, कुछ तो सही से पूछो ना! 😅🌸",
                    "english": f"Hey {user_name}, please ask me something properly! 😅🌸",
                    "hinglish": f"Arey {user_name}, kuch toh sahi se pucho na! 😅🌸"
                }
                bot.reply_to(message, short_msgs.get(user_lang, short_msgs["hinglish"]))
                return

            # Send typing action
            bot.send_chat_action(chat_id, 'typing')

            # Save user message
            save_chat_history(user_id, chat_id, "user", text)

            # SEARCH
            search_results = master_search(query, user_lang)

            # Format response
            response = format_ruhi_response(query, search_results, user_name, user_lang)

            # Save bot response
            save_chat_history(user_id, chat_id, "bot", response)

            if DEBUG_MODE and is_admin(user_id):
                if search_results:
                    sources = ", ".join([r.get("source", "?") for r in search_results])
                    response += f"\n\n🐛 Debug: Sources: {sources}"

            try:
                bot.reply_to(message, response)
            except Exception as e:
                if "message is too long" in str(e).lower():
                    for i in range(0, len(response), 4000):
                        bot.send_message(chat_id, response[i:i+4000])
                else:
                    raise e

            save_bot_log("INFO", f"Active session query: {query[:100]}", user_id, chat_id)
            return

        else:
            # Session NOT active and phrase NOT found -> DO NOTHING
            # This is the key feature: bot stays silent until "Ruhi Ji" is said
            return

    except Exception as e:
        logger.error(f"handle_message error: {e}\n{traceback.format_exc()}")
        try:
            bot.reply_to(message, "😅 Oops! Something went wrong. Try again! 🌸")
        except:
            pass

# ============================================================================
# ERROR HANDLER
# ============================================================================

@bot.message_handler(func=lambda message: True, content_types=['photo', 'video', 'audio', 'document', 'sticker', 'voice', 'video_note'])
def handle_media(message):
    try:
        user_id = message.from_user.id
        chat_id = message.chat.id

        if not is_session_active(user_id, chat_id):
            return

        refresh_session(user_id, chat_id)
        user_lang = get_user_language(user_id)
        user_name = message.from_user.first_name or "Dear"

        media_msgs = {
            "hindi": f"अरे {user_name}! 😊 मैं अभी सिर्फ text messages समझ सकती हूं! Text में पूछो ना! 🌹",
            "english": f"Hey {user_name}! 😊 I can only understand text messages right now! Ask me in text! 🌹",
            "hinglish": f"Arey {user_name}! 😊 Main abhi sirf text messages samajh sakti hoon! Text mein pucho na! 🌹"
        }
        bot.reply_to(message, media_msgs.get(user_lang, media_msgs["hinglish"]))
    except Exception as e:
        logger.error(f"handle_media error: {e}")

# ============================================================================
# INITIALIZATION
# ============================================================================

def initialize_bot():
    """Initialize bot with default configs."""
    try:
        # Set super admin
        if ADMIN_ID:
            add_admin(ADMIN_ID, ADMIN_ID)
            logger.info(f"Super admin set: {ADMIN_ID}")

        # Load saved config
        saved_phrase = get_config("activation_phrase", "")
        if saved_phrase:
            global ACTIVATION_PHRASE
            ACTIVATION_PHRASE = saved_phrase
            logger.info(f"Loaded activation phrase: {ACTIVATION_PHRASE}")

        logger.info("Bot initialized successfully!")
    except Exception as e:
        logger.error(f"Initialization error: {e}")

# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("🌹 RUHI JI BOT - Starting Up...")
    logger.info(f"📦 Version: {BOT_VERSION}")
    logger.info(f"🔑 Admin ID: {ADMIN_ID}")
    logger.info(f"💾 Database: {DATABASE_URL[:30]}...")
    logger.info(f"🌐 Port: {PORT}")
    logger.info("=" * 50)

    # Initialize
    initialize_bot()

    # Start Flask in a separate thread (Keep-Alive for Render)
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info("🌐 Flask keep-alive server started!")

    # Start bot polling
    logger.info("🤖 Starting bot polling...")
    while True:
        try:
            bot.infinity_polling(
                timeout=60,
                long_polling_timeout=60,
                allowed_updates=["message", "callback_query"],
                skip_pending=True
            )
        except Exception as e:
            logger.error(f"Polling error: {e}")
            logger.info("Restarting polling in 5 seconds...")
            time.sleep(5)
            