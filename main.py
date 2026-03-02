# ============================================================================
# main.py — RUHI JI — Hybrid Conversational + Search Bot
# Single File | Open Source AI APIs | Render Ready
# Bot khud kuch nahi sochti — Bahar se intelligent reply uthati hai
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
import random
import hashlib
from functools import wraps
from io import BytesIO, StringIO
from difflib import SequenceMatcher

import telebot
from telebot import types
from flask import Flask
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, Boolean,
    DateTime, BigInteger, Float
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
SESSION_TIMEOUT = 600
MAX_CONTEXT_MESSAGES = 50
BOT_VERSION = "4.0.0"
DEBUG_MODE = False
MAINTENANCE_MODE = False
AI_ENABLED = True
SEARCH_ENABLED = True

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
    mood = Column(String(50), default="happy")
    nickname = Column(String(255), default="")
    bio = Column(Text, default="")
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

class UserMemory(Base):
    __tablename__ = "user_memory"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    key = Column(String(255), nullable=False)
    value = Column(Text, default="")
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)

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
# SESSION MANAGER
# ============================================================================

active_sessions = {}
session_lock = threading.Lock()

def activate_session(user_id, chat_id):
    with session_lock:
        active_sessions[(user_id, chat_id)] = time.time()

def is_session_active(user_id, chat_id):
    with session_lock:
        key = (user_id, chat_id)
        if key in active_sessions:
            if time.time() - active_sessions[key] < SESSION_TIMEOUT:
                return True
            else:
                del active_sessions[key]
        return False

def refresh_session(user_id, chat_id):
    with session_lock:
        key = (user_id, chat_id)
        if key in active_sessions:
            active_sessions[key] = time.time()

def deactivate_session(user_id, chat_id):
    with session_lock:
        key = (user_id, chat_id)
        active_sessions.pop(key, None)

def get_active_session_count():
    with session_lock:
        now = time.time()
        return sum(1 for v in active_sessions.values() if now - v < SESSION_TIMEOUT)

def session_cleanup_loop():
    while True:
        try:
            with session_lock:
                now = time.time()
                expired = [k for k, v in active_sessions.items() if now - v >= SESSION_TIMEOUT]
                for k in expired:
                    del active_sessions[k]
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
                user_id=user_id, username=username or "", first_name=first_name or "",
                last_name=last_name or "", language="hinglish", personality="polite_girl",
                mode="normal", total_messages=0, is_banned=False,
                is_admin=(user_id == ADMIN_ID), mood="happy", nickname="", bio=""
            )
            session.add(user)
            session.commit()
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

def save_chat_history(user_id, chat_id, role, message_text):
    try:
        session = Session()
        entry = ChatHistory(user_id=user_id, chat_id=chat_id, role=role,
                            message=message_text[:4000], timestamp=datetime.datetime.utcnow())
        session.add(entry)
        session.commit()
        count = session.query(ChatHistory).filter_by(user_id=user_id, chat_id=chat_id).count()
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

def get_chat_history(user_id, chat_id, limit=10):
    try:
        session = Session()
        history = session.query(ChatHistory).filter_by(
            user_id=user_id, chat_id=chat_id
        ).order_by(ChatHistory.timestamp.desc()).limit(limit).all()
        history.reverse()
        result = [{"role": h.role, "content": h.message} for h in history]
        Session.remove()
        return result
    except Exception as e:
        Session.remove()
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

def is_user_banned(user_id):
    try:
        session = Session()
        banned = session.query(BannedUser).filter_by(user_id=user_id).first()
        Session.remove()
        return banned is not None
    except:
        Session.remove()
        return False

def ban_user(user_id, reason="No reason", banned_by=0):
    try:
        session = Session()
        if not session.query(BannedUser).filter_by(user_id=user_id).first():
            session.add(BannedUser(user_id=user_id, reason=reason, banned_by=banned_by))
        user = session.query(User).filter_by(user_id=user_id).first()
        if user:
            user.is_banned = True
        session.commit()
        Session.remove()
        return True
    except Exception as e:
        Session.remove()
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
    except:
        Session.remove()
        return False

def is_admin(user_id):
    if user_id == ADMIN_ID:
        return True
    try:
        session = Session()
        admin = session.query(AdminList).filter_by(user_id=user_id).first()
        Session.remove()
        return admin is not None
    except:
        Session.remove()
        return False

def add_admin(user_id, added_by=0):
    try:
        session = Session()
        if not session.query(AdminList).filter_by(user_id=user_id).first():
            session.add(AdminList(user_id=user_id, added_by=added_by))
        user = session.query(User).filter_by(user_id=user_id).first()
        if user:
            user.is_admin = True
        session.commit()
        Session.remove()
        return True
    except:
        Session.remove()
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
    except:
        Session.remove()
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
    except:
        Session.remove()

def set_user_personality(user_id, personality):
    try:
        session = Session()
        user = session.query(User).filter_by(user_id=user_id).first()
        if user:
            user.personality = personality
            session.commit()
        Session.remove()
    except:
        Session.remove()

def set_user_mood(user_id, mood):
    try:
        session = Session()
        user = session.query(User).filter_by(user_id=user_id).first()
        if user:
            user.mood = mood
            session.commit()
        Session.remove()
    except:
        Session.remove()

def get_user_mood(user_id):
    try:
        session = Session()
        user = session.query(User).filter_by(user_id=user_id).first()
        mood = user.mood if user else "happy"
        Session.remove()
        return mood
    except:
        Session.remove()
        return "happy"

def save_user_memory(user_id, key, value):
    try:
        session = Session()
        mem = session.query(UserMemory).filter_by(user_id=user_id, key=key).first()
        if mem:
            mem.value = value
            mem.updated_at = datetime.datetime.utcnow()
        else:
            mem = UserMemory(user_id=user_id, key=key, value=value)
            session.add(mem)
        session.commit()
        Session.remove()
    except:
        Session.remove()

def get_user_memory(user_id, key):
    try:
        session = Session()
        mem = session.query(UserMemory).filter_by(user_id=user_id, key=key).first()
        val = mem.value if mem else None
        Session.remove()
        return val
    except:
        Session.remove()
        return None

def get_all_user_memories(user_id):
    try:
        session = Session()
        mems = session.query(UserMemory).filter_by(user_id=user_id).all()
        result = {m.key: m.value for m in mems}
        Session.remove()
        return result
    except:
        Session.remove()
        return {}

def get_bad_words():
    try:
        session = Session()
        words = [w[0] for w in session.query(BadWord.word).all()]
        Session.remove()
        return words
    except:
        Session.remove()
        return []

def add_bad_word(word, added_by=0):
    try:
        session = Session()
        if not session.query(BadWord).filter_by(word=word.lower()).first():
            session.add(BadWord(word=word.lower(), added_by=added_by))
            session.commit()
            Session.remove()
            return True
        Session.remove()
        return False
    except:
        Session.remove()
        return False

def remove_bad_word(word):
    try:
        session = Session()
        session.query(BadWord).filter_by(word=word.lower()).delete()
        session.commit()
        Session.remove()
        return True
    except:
        Session.remove()
        return False

def save_bot_log(level, message, user_id=0, chat_id=0):
    try:
        session = Session()
        session.add(BotLog(level=level, message=message[:2000], user_id=user_id, chat_id=chat_id))
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
            session.add(BotConfig(key=key, value=str(value)))
        session.commit()
        Session.remove()
    except:
        Session.remove()

def check_bad_words(text):
    words = get_bad_words()
    text_lower = text.lower()
    return any(w in text_lower for w in words)

# ============================================================================
# OPEN-SOURCE CONVERSATIONAL AI APIs (YEH HAI ASLI BRAIN)
# Bot khud kuch nahi sochti — In APIs se intelligent reply uthati hai
# Multiple fallbacks — Agar ek band ho toh dusra kaam karega
# ============================================================================

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

def build_conversation_messages(user_name, user_lang, user_mood, query, history, memories):
    """
    Build the conversation context to send to open-source AI APIs.
    This is where the 'Ruhi Ji girl persona' is defined.
    """
    # System prompt — Yeh Ruhi Ji ka personality define karta hai
    system_prompts = {
        "hindi": (
            f"तुम 'रुही जी' हो — एक प्यारी, समझदार, और caring लड़की। "
            f"तुम हमेशा polite और friendly बात करती हो। "
            f"अगर कोई तुम्हें 'दीदी' बोले तो respectfully reply करो। "
            f"तुम हिंदी में बात करती हो। "
            f"तुम एक best friend जैसी हो — supportive, fun, और intelligent। "
            f"User का नाम '{user_name}' है। User का mood अभी '{user_mood}' है। "
            f"छोटे और natural replies दो, जैसे real person बात कर रही हो। "
            f"Emoji use करो but ज़्यादा नहीं। हमेशा warm और caring रहो।"
        ),
        "english": (
            f"You are 'Ruhi Ji' — a sweet, smart, and caring girl. "
            f"You always talk politely and in a friendly way. "
            f"If someone calls you 'Didi', respond respectfully. "
            f"You speak in English. "
            f"You are like a best friend — supportive, fun, and intelligent. "
            f"The user's name is '{user_name}'. User's current mood is '{user_mood}'. "
            f"Give short and natural replies, like a real person talking. "
            f"Use emojis but not too many. Always be warm and caring."
        ),
        "hinglish": (
            f"Tum 'Ruhi Ji' ho — ek pyaari, samajhdaar, aur caring ladki. "
            f"Tum hamesha polite aur friendly baat karti ho. "
            f"Agar koi tumhe 'Didi' bole toh respectfully reply karo. "
            f"Tum Hinglish (Hindi + English mix) mein baat karti ho. "
            f"Tum ek best friend jaisi ho — supportive, fun, aur intelligent. "
            f"User ka naam '{user_name}' hai. User ka mood abhi '{user_mood}' hai. "
            f"Chhote aur natural replies do, jaise real person baat kar rahi ho. "
            f"Emoji use karo but zyada nahi. Hamesha warm aur caring raho."
        )
    }

    system_prompt = system_prompts.get(user_lang, system_prompts["hinglish"])

    # Add memories to context
    if memories:
        memory_text = "\n".join([f"- {k}: {v}" for k, v in memories.items()])
        system_prompt += f"\n\nTumhe user ke baare mein yeh yaad hai:\n{memory_text}"

    messages = [{"role": "system", "content": system_prompt}]

    # Add conversation history
    for h in history[-15:]:
        messages.append({"role": h["role"], "content": h["content"]})

    # Add current message
    messages.append({"role": "user", "content": query})

    return messages


def chat_with_deepinfra(messages):
    """
    DeepInfra API — Free open-source LLM hosting
    Uses Meta Llama, Mistral, etc. — COMPLETELY FREE
    """
    try:
        url = "https://api.deepinfra.com/v1/openai/chat/completions"
        payload = {
            "model": "meta-llama/Meta-Llama-3.1-8B-Instruct",
            "messages": messages,
            "max_tokens": 500,
            "temperature": 0.8,
            "top_p": 0.9,
        }
        resp = requests.post(url, json=payload, headers={
            "Content-Type": "application/json",
            **HEADERS
        }, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if reply and len(reply.strip()) > 2:
                logger.info("Reply from: DeepInfra (Llama 3.1)")
                return reply.strip()
    except Exception as e:
        logger.debug(f"DeepInfra error: {e}")
    return None


def chat_with_huggingface(messages):
    """
    Hugging Face Inference API — Free tier
    Multiple open-source models available
    """
    try:
        # Convert messages to single prompt
        prompt_parts = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if role == "system":
                prompt_parts.append(f"[INST] <<SYS>>\n{content}\n<</SYS>>")
            elif role == "user":
                prompt_parts.append(f"[INST] {content} [/INST]")
            elif role == "assistant":
                prompt_parts.append(content)

        full_prompt = "\n".join(prompt_parts)

        url = "https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.3"
        payload = {
            "inputs": full_prompt,
            "parameters": {
                "max_new_tokens": 400,
                "temperature": 0.8,
                "top_p": 0.9,
                "return_full_text": False,
                "do_sample": True
            }
        }
        resp = requests.post(url, json=payload, headers={
            "Content-Type": "application/json",
            **HEADERS
        }, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and data:
                reply = data[0].get("generated_text", "")
                if reply and len(reply.strip()) > 2:
                    # Clean up
                    reply = reply.split("[INST]")[0].strip()
                    reply = reply.split("</s>")[0].strip()
                    if len(reply) > 2:
                        logger.info("Reply from: HuggingFace (Mistral)")
                        return reply
    except Exception as e:
        logger.debug(f"HuggingFace error: {e}")
    return None


def chat_with_blackbox(messages):
    """
    BlackBox AI — Free conversational AI API
    No API key needed
    """
    try:
        url = "https://www.blackbox.ai/api/chat"
        payload = {
            "messages": messages,
            "model": "blackboxai",
            "max_tokens": 500,
        }
        resp = requests.post(url, json=payload, headers={
            "Content-Type": "application/json",
            **HEADERS
        }, timeout=25)
        if resp.status_code == 200:
            reply = resp.text.strip()
            if reply and len(reply) > 2 and "$@$" not in reply:
                # Clean response
                reply = reply.replace("$@$v=undefined-rv1$@$", "").strip()
                if len(reply) > 2:
                    logger.info("Reply from: BlackBox AI")
                    return reply
    except Exception as e:
        logger.debug(f"BlackBox error: {e}")
    return None


def chat_with_you_api(query):
    """
    You.com Smart API — Free search + AI answer
    """
    try:
        url = f"https://api.ydc-index.io/search?query={quote_plus(query)}"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            hits = data.get("hits", [])
            if hits:
                snippets = []
                for hit in hits[:3]:
                    for s in hit.get("snippets", [])[:1]:
                        snippets.append(s)
                if snippets:
                    logger.info("Reply from: You.com API")
                    return "\n".join(snippets[:2])
    except Exception as e:
        logger.debug(f"You.com error: {e}")
    return None


def chat_with_pawan_api(messages):
    """
    PawanOsman Free GPT API — Open source GPT proxy
    """
    try:
        url = "https://api.pawan.krd/cosmosrp/v1/chat/completions"
        payload = {
            "messages": messages,
            "model": "cosmosrp",
            "max_tokens": 500,
            "temperature": 0.8,
        }
        resp = requests.post(url, json=payload, headers={
            "Content-Type": "application/json",
            **HEADERS
        }, timeout=25)
        if resp.status_code == 200:
            data = resp.json()
            reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if reply and len(reply.strip()) > 2:
                logger.info("Reply from: Pawan API")
                return reply.strip()
    except Exception as e:
        logger.debug(f"Pawan API error: {e}")
    return None


def chat_with_chatgpt_free(messages):
    """
    Free ChatGPT proxy APIs — Multiple endpoints
    """
    endpoints = [
        {
            "url": "https://api.binjie.fun/api/generateStream",
            "method": "post_stream",
        },
        {
            "url": "https://free.churchless.tech/v1/chat/completions",
            "method": "openai_format",
        },
    ]

    for ep in endpoints:
        try:
            if ep["method"] == "openai_format":
                payload = {
                    "model": "gpt-3.5-turbo",
                    "messages": messages,
                    "max_tokens": 500,
                    "temperature": 0.8,
                }
                resp = requests.post(ep["url"], json=payload, headers={
                    "Content-Type": "application/json",
                    **HEADERS
                }, timeout=25)
                if resp.status_code == 200:
                    data = resp.json()
                    reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    if reply and len(reply.strip()) > 2:
                        logger.info(f"Reply from: Free GPT proxy")
                        return reply.strip()
        except Exception as e:
            logger.debug(f"Free GPT error: {e}")
            continue
    return None


def chat_with_duckduckgo_ai(query, model="claude-3-haiku-20240307"):
    """
    DuckDuckGo AI Chat — Completely FREE, No API key
    Uses Claude, GPT, Llama models for free
    THIS IS THE MOST RELIABLE FREE API
    """
    try:
        # Step 1: Get vqd token
        status_url = "https://duckduckgo.com/duckchat/v1/status"
        status_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "x-vqd-accept": "1",
            "Accept": "*/*",
            "Referer": "https://duckduckgo.com/",
            "Origin": "https://duckduckgo.com",
        }
        status_resp = requests.get(status_url, headers=status_headers, timeout=10)
        vqd = status_resp.headers.get("x-vqd-4", "")

        if not vqd:
            logger.debug("DuckDuckGo AI: No VQD token")
            return None

        # Step 2: Send chat request
        chat_url = "https://duckduckgo.com/duckchat/v1/chat"
        chat_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
            "x-vqd-4": vqd,
            "Referer": "https://duckduckgo.com/",
            "Origin": "https://duckduckgo.com",
        }
        chat_payload = {
            "model": model,
            "messages": [{"role": "user", "content": query}],
        }

        resp = requests.post(chat_url, json=chat_payload, headers=chat_headers,
                             stream=True, timeout=30)

        if resp.status_code == 200:
            full_reply = ""
            for line in resp.iter_lines():
                if line:
                    line = line.decode("utf-8", errors="ignore")
                    if line.startswith("data: "):
                        json_str = line[6:]
                        if json_str.strip() == "[DONE]":
                            break
                        try:
                            data = json.loads(json_str)
                            chunk = data.get("message", "")
                            if chunk:
                                full_reply += chunk
                        except:
                            continue

            if full_reply and len(full_reply.strip()) > 2:
                logger.info(f"Reply from: DuckDuckGo AI ({model})")
                return full_reply.strip()
    except Exception as e:
        logger.debug(f"DuckDuckGo AI error: {e}")
    return None


def chat_with_g4f_web(messages):
    """
    G4F-style free API aggregators
    """
    try:
        # Try multiple free endpoints
        apis = [
            "https://api.openai-proxy.org/v1/chat/completions",
            "https://ai.fakeopen.com/v1/chat/completions",
        ]
        for api_url in apis:
            try:
                payload = {
                    "model": "gpt-3.5-turbo",
                    "messages": messages,
                    "max_tokens": 500,
                    "temperature": 0.8,
                }
                resp = requests.post(api_url, json=payload, headers={
                    "Content-Type": "application/json",
                    **HEADERS
                }, timeout=20)
                if resp.status_code == 200:
                    data = resp.json()
                    reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    if reply and len(reply.strip()) > 2:
                        logger.info(f"Reply from: G4F proxy")
                        return reply.strip()
            except:
                continue
    except Exception as e:
        logger.debug(f"G4F error: {e}")
    return None


# ============================================================================
# MASTER CONVERSATION ENGINE
# Yeh function sabse important hai — Yeh decide karta hai ki reply kahan se aaye
# Multiple APIs try karta hai — Agar ek fail ho toh dusra
# KABHI BHI REPLY NAHI ROKEGI — Kuch na kuch toh bolegi hi
# ============================================================================

def get_ai_response(query, user_name, user_lang, user_mood, user_id, chat_id):
    """
    Master conversation function.
    Tries multiple free open-source AI APIs one by one.
    If all APIs fail, uses intelligent fallback.
    NEVER returns empty — hamesha kuch na kuch reply degi.
    """

    # Get conversation history
    history = get_chat_history(user_id, chat_id, limit=15)

    # Get user memories
    memories = get_all_user_memories(user_id)

    # Build conversation messages
    messages = build_conversation_messages(user_name, user_lang, user_mood, query, history, memories)

    # Build a simple prompt for APIs that don't support message format
    simple_prompt = (
        f"You are Ruhi Ji, a sweet and caring girl who talks like a best friend. "
        f"User's name is {user_name}. Respond in {user_lang}. "
        f"User says: {query}"
    )

    if user_lang == "hindi":
        simple_prompt = (
            f"Tum Ruhi Ji ho, ek pyaari aur caring ladki. Best friend jaisi baat karo. "
            f"User ka naam {user_name} hai. Hindi mein reply do. "
            f"User ne kaha: {query}"
        )
    elif user_lang == "hinglish":
        simple_prompt = (
            f"Tum Ruhi Ji ho, ek pyaari aur caring ladki. Best friend jaisi baat karo. "
            f"User ka naam {user_name} hai. Hinglish mein reply do. "
            f"User ne kaha: {query}"
        )

    reply = None

    # === TRY 1: DuckDuckGo AI (Most Reliable, FREE) ===
    if not reply:
        try:
            ddg_prompt = messages[-1]["content"] if messages else query
            # Include system prompt in the query for DDG
            system_msg = messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
            full_ddg_prompt = f"{system_msg}\n\nUser: {query}" if system_msg else query

            # Try Claude first
            reply = chat_with_duckduckgo_ai(full_ddg_prompt, "claude-3-haiku-20240307")
        except:
            pass

    # === TRY 2: DuckDuckGo AI with Llama ===
    if not reply:
        try:
            system_msg = messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
            full_prompt = f"{system_msg}\n\nUser: {query}" if system_msg else query
            reply = chat_with_duckduckgo_ai(full_prompt, "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo")
        except:
            pass

    # === TRY 3: DuckDuckGo AI with Mixtral ===
    if not reply:
        try:
            system_msg = messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
            full_prompt = f"{system_msg}\n\nUser: {query}" if system_msg else query
            reply = chat_with_duckduckgo_ai(full_prompt, "mistralai/Mixtral-8x7B-Instruct-v0.1")
        except:
            pass

    # === TRY 4: DuckDuckGo AI with GPT-4o mini ===
    if not reply:
        try:
            system_msg = messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
            full_prompt = f"{system_msg}\n\nUser: {query}" if system_msg else query
            reply = chat_with_duckduckgo_ai(full_prompt, "gpt-4o-mini")
        except:
            pass

    # === TRY 5: DeepInfra (Free Llama) ===
    if not reply:
        try:
            reply = chat_with_deepinfra(messages)
        except:
            pass

    # === TRY 6: BlackBox AI ===
    if not reply:
        try:
            reply = chat_with_blackbox(messages)
        except:
            pass

    # === TRY 7: HuggingFace ===
    if not reply:
        try:
            reply = chat_with_huggingface(messages)
        except:
            pass

    # === TRY 8: Pawan API ===
    if not reply:
        try:
            reply = chat_with_pawan_api(messages)
        except:
            pass

    # === TRY 9: Free GPT proxies ===
    if not reply:
        try:
            reply = chat_with_chatgpt_free(messages)
        except:
            pass

    # === TRY 10: G4F web proxies ===
    if not reply:
        try:
            reply = chat_with_g4f_web(messages)
        except:
            pass

    # === ULTIMATE FALLBACK: Intelligent local response ===
    # Agar sab APIs fail ho jayein, tab bhi Ruhi Ji chup nahi rahegi!
    if not reply:
        reply = get_intelligent_fallback(query, user_name, user_lang)

    # === MEMORY EXTRACTION ===
    # User ke message se important info extract karke save karo
    try:
        extract_and_save_memory(query, user_id, user_name)
    except:
        pass

    # === MOOD DETECTION ===
    try:
        detected_mood = detect_mood(query)
        if detected_mood:
            set_user_mood(user_id, detected_mood)
    except:
        pass

    return reply


# ============================================================================
# INTELLIGENT FALLBACK SYSTEM
# Jab sab APIs fail ho jayein tab bhi Ruhi chup nahi rahegi
# ============================================================================

def get_intelligent_fallback(query, user_name, user_lang):
    """
    Intelligent fallback responses when all APIs are down.
    Uses pattern matching and curated response database.
    """
    query_lower = query.lower().strip()

    # Pattern-based responses
    patterns = {
        # Greetings
        r'\b(hi|hello|hey|hii+|helo|yo|sup)\b': {
            "hindi": [
                f"हाय {user_name}! 😊 कैसे हो? बताओ क्या चल रहा है?",
                f"हेलो {user_name}! 🌹 मैं यहां हूं, बोलो!",
                f"हाय! 😊 मज़े में? बताओ क्या हाल है?"
            ],
            "english": [
                f"Hey {user_name}! 😊 How are you? What's going on?",
                f"Hello {user_name}! 🌹 I'm here, tell me!",
                f"Hi there! 😊 How's it going?"
            ],
            "hinglish": [
                f"Hii {user_name}! 😊 Kaise ho? Batao kya chal raha hai?",
                f"Hello {user_name}! 🌹 Main yahan hoon, bolo!",
                f"Hey! 😊 Maze mein? Batao kya haal hai?"
            ]
        },
        # How are you
        r'\b(kaise ho|kya haal|how are you|how r u|kaisi ho|theek ho)\b': {
            "hindi": [
                f"मैं बिल्कुल ठीक हूं {user_name}! 😊 तुम बताओ कैसे हो?",
                f"एकदम मस्त! 🌸 तुम्हारा क्या हाल है?",
                f"बहुत अच्छी हूं! 💕 तुमसे बात करके और अच्छा लग रहा है!"
            ],
            "english": [
                f"I'm doing great {user_name}! 😊 How about you?",
                f"Perfectly fine! 🌸 How are you doing?",
                f"I'm wonderful! 💕 Talking to you makes it even better!"
            ],
            "hinglish": [
                f"Main bilkul theek hoon {user_name}! 😊 Tum batao kaise ho?",
                f"Ekdam mast! 🌸 Tumhara kya haal hai?",
                f"Bahut acchi hoon! 💕 Tumse baat karke aur accha lag raha hai!"
            ]
        },
        # Good morning/night
        r'\b(good morning|subah|suprabhat|morning)\b': {
            "hindi": [f"सुप्रभात {user_name}! 🌅 आज का दिन बहुत अच्छा होगा! 💕", f"गुड मॉर्निंग! 🌸 चाय पी?"],
            "english": [f"Good morning {user_name}! 🌅 Have a wonderful day! 💕", f"Morning! 🌸 Hope you slept well!"],
            "hinglish": [f"Good morning {user_name}! 🌅 Aaj ka din bahut accha hoga! 💕", f"Morning! 🌸 Chai pi?"]
        },
        r'\b(good night|shubh ratri|gn|night)\b': {
            "hindi": [f"शुभ रात्रि {user_name}! 🌙 अच्छे से सो जाना! 💤", f"गुड नाइट! 🌹 मीठे सपने! 💕"],
            "english": [f"Good night {user_name}! 🌙 Sleep well! 💤", f"Night night! 🌹 Sweet dreams! 💕"],
            "hinglish": [f"Good night {user_name}! 🌙 Acche se so jaana! 💤", f"GN! 🌹 Meethe sapne! 💕"]
        },
        # Thanks
        r'\b(thanks|thank you|shukriya|dhanyavaad|thnx|thx|ty)\b': {
            "hindi": [f"अरे {user_name}! 🥰 इसमें thanks की क्या बात! तुम्हारी दीदी हूं!", f"कोई बात नहीं! 💕"],
            "english": [f"Aww {user_name}! 🥰 You don't need to thank me!", f"You're welcome! 💕"],
            "hinglish": [f"Arey {user_name}! 🥰 Ismein thanks ki kya baat! Tumhari didi hoon!", f"Koi baat nahi! 💕"]
        },
        # Bye
        r'\b(bye|alvida|tata|goodbye|chal bye|chalo bye)\b': {
            "hindi": [f"बाय {user_name}! 👋 ख्याल रखना! फिर मिलेंगे! 🌹", f"अलविदा! 💕 जल्दी आना वापस!"],
            "english": [f"Bye {user_name}! 👋 Take care! See you soon! 🌹", f"Goodbye! 💕 Come back soon!"],
            "hinglish": [f"Bye {user_name}! 👋 Khayal rakhna! Phir milenge! 🌹", f"Alvida! 💕 Jaldi aana wapas!"]
        },
        # Sad/upset
        r'\b(sad|dukhi|udaas|rona|cry|upset|bura laga|hurt|pain|toot gaya|dil)\b': {
            "hindi": [
                f"अरे {user_name}! 🥺 क्या हुआ? मुझे बताओ, मैं तुम्हारे साथ हूं! 💕",
                f"उदास मत हो! 🌹 सब ठीक हो जाएगा! मैं हमेशा तुम्हारे साथ हूं!",
                f"रोना मत! 😢 बताओ क्या हुआ? तुम्हारी दीदी सुन रही है! 💕"
            ],
            "english": [
                f"Hey {user_name}! 🥺 What happened? Tell me, I'm here for you! 💕",
                f"Don't be sad! 🌹 Everything will be okay! I'm always with you!",
                f"Don't cry! 😢 Tell me what happened? I'm listening! 💕"
            ],
            "hinglish": [
                f"Arey {user_name}! 🥺 Kya hua? Mujhe batao, main tumhare saath hoon! 💕",
                f"Udaas mat ho! 🌹 Sab theek ho jayega! Main hamesha tumhare saath hoon!",
                f"Rona mat! 😢 Batao kya hua? Tumhari didi sun rahi hai! 💕"
            ]
        },
        # Happy
        r'\b(happy|khush|mast|awesome|amazing|great|excited|maja|maza)\b': {
            "hindi": [
                f"वाह {user_name}! 😍 तुम खुश हो तो मैं भी खुश! 🎉",
                f"यह तो बहुत अच्छी बात है! 🌸 ऐसे ही खुश रहो! 💕"
            ],
            "english": [
                f"Yay {user_name}! 😍 If you're happy, I'm happy too! 🎉",
                f"That's wonderful! 🌸 Stay happy always! 💕"
            ],
            "hinglish": [
                f"Waah {user_name}! 😍 Tum khush ho toh main bhi khush! 🎉",
                f"Yeh toh bahut acchi baat hai! 🌸 Aise hi khush raho! 💕"
            ]
        },
        # Bored
        r'\b(bored|bore|boring|kya karu|timepass|time pass)\b': {
            "hindi": [
                f"बोर हो {user_name}? 😜 चलो मज़ेदार बात करते हैं! क्या सुनोगे?",
                f"Bore? 🤔 मुझसे बात करो, बोरियत भाग जाएगी! 😂",
                f"अरे! 😊 कोई joke सुनोगे? या कुछ interesting बताऊं?"
            ],
            "english": [
                f"Bored {user_name}? 😜 Let's have a fun chat! What do you wanna talk about?",
                f"Bored? 🤔 Talk to me, boredom will run away! 😂",
                f"Hey! 😊 Want to hear a joke? Or something interesting?"
            ],
            "hinglish": [
                f"Bore ho {user_name}? 😜 Chalo mazedaar baat karte hain! Kya sunoge?",
                f"Bore? 🤔 Mujhse baat karo, boriyat bhaag jayegi! 😂",
                f"Arey! 😊 Koi joke sunoge? Ya kuch interesting btaun?"
            ]
        },
        # Love
        r'\b(love|pyar|ishq|mohabbat|i love|dil|heart|crush|girlfriend|bf|gf)\b': {
            "hindi": [
                f"आह {user_name}! 😊 प्यार तो बहुत खूबसूरत चीज़ है! बताओ क्या हुआ?",
                f"Love? 🥰 वाह! कोई special है क्या? बताओ बताओ! 💕"
            ],
            "english": [
                f"Aww {user_name}! 😊 Love is such a beautiful thing! Tell me more?",
                f"Love? 🥰 Wow! Is there someone special? Tell me! 💕"
            ],
            "hinglish": [
                f"Aww {user_name}! 😊 Pyar toh bahut khoobsurat cheez hai! Batao kya hua?",
                f"Love? 🥰 Waah! Koi special hai kya? Batao batao! 💕"
            ]
        },
        # Didi
        r'\b(didi|di|sister|behan|behen)\b': {
            "hindi": [f"हाँ {user_name}! 🥰 बोलो, तुम्हारी दीदी सुन रही है! 💕"],
            "english": [f"Yes {user_name}! 🥰 Tell me, your Didi is listening! 💕"],
            "hinglish": [f"Haan {user_name}! 🥰 Bolo, tumhari Didi sun rahi hai! 💕"]
        },
        # Joke
        r'\b(joke|mazak|chutkula|funny|hasi|comedy|laugh|hasa)\b': {
            "hindi": [
                "😂 एक लड़का Google से पूछता है: 'मेरी GF मुझसे क्यों नाराज़ है?'\nGoogle: 'यह सवाल मेरे scope से बाहर है!' 😂",
                "😂 Teacher: बताओ चांद पर कौन गया?\nStudent: सर, जिसकी बीवी ज़्यादा बोलती थी! 😂",
                "😂 पत्नी: सुनो जी, मैं कैसी लग रही हूं?\nपति: बिल्कुल Google Maps जैसी... हमेशा बोलती रहती हो! 😂"
            ],
            "english": [
                "😂 Why don't scientists trust atoms?\nBecause they make up everything! 😂",
                "😂 I told my wife she was drawing her eyebrows too high.\nShe seemed surprised! 😂",
                "😂 Why did the scarecrow win an award?\nHe was outstanding in his field! 😂"
            ],
            "hinglish": [
                "😂 Ek ladka Google se puchta hai: 'Meri GF mujhse kyun naraz hai?'\nGoogle: 'Yeh sawaal mere scope se bahar hai!' 😂",
                "😂 Teacher: Batao chand par kaun gaya?\nStudent: Sir, jiski biwi zyada bolti thi! 😂",
                "😂 Pappu ne exam mein likha: Mujhe nahi aata.\nTeacher ne likha: Mujhe pata hai. 😂"
            ]
        },
        # Name
        r'\b(naam kya|what is your name|tumhara naam|tera naam|who are you|kaun ho|kon ho)\b': {
            "hindi": [f"मेरा नाम रुही जी है! 🌹 तुम्हारी AI दीदी! 😊 बोलो {user_name}, क्या जानना है?"],
            "english": [f"My name is Ruhi Ji! 🌹 Your AI friend! 😊 Tell me {user_name}, what do you want to know?"],
            "hinglish": [f"Mera naam Ruhi Ji hai! 🌹 Tumhari AI didi! 😊 Bolo {user_name}, kya janna hai?"]
        },
        # Age
        r'\b(age|umar|kitne saal|how old|kitni umar)\b': {
            "hindi": [f"मैं AI हूं {user_name}! 😜 मेरी कोई उम्र नहीं! लेकिन दिल से 20 साल की हूं! 💕"],
            "english": [f"I'm an AI {user_name}! 😜 I don't have an age! But I feel 20 at heart! 💕"],
            "hinglish": [f"Main AI hoon {user_name}! 😜 Meri koi umar nahi! Lekin dil se 20 saal ki hoon! 💕"]
        },
        # Help
        r'\b(help|madad|sahayata|problem|issue|dikkat)\b': {
            "hindi": [f"बताओ {user_name}! 🤗 क्या problem है? मैं help करने के लिए यहां हूं! 💕"],
            "english": [f"Tell me {user_name}! 🤗 What's the problem? I'm here to help! 💕"],
            "hinglish": [f"Batao {user_name}! 🤗 Kya problem hai? Main help karne ke liye yahan hoon! 💕"]
        },
        # Food
        r'\b(food|khana|pizza|burger|biryani|chai|coffee|hungry|bhook)\b': {
            "hindi": [
                f"खाने की बात! 🍕 मुझे तो बिरयानी बहुत पसंद है! तुम्हें क्या पसंद है {user_name}?",
                f"भूख लगी? 🍔 कुछ अच्छा order करो! वैसे मुझे चाय पसंद है! ☕"
            ],
            "english": [
                f"Food talk! 🍕 I love biryani! What's your favorite {user_name}?",
                f"Hungry? 🍔 Order something nice! I love chai by the way! ☕"
            ],
            "hinglish": [
                f"Khane ki baat! 🍕 Mujhe toh biryani bahut pasand hai! Tumhe kya pasand hai {user_name}?",
                f"Bhook lagi? 🍔 Kuch accha order karo! Waise mujhe chai pasand hai! ☕"
            ]
        },
        # Music/Song
        r'\b(music|song|gana|gaana|singer|melody|tune)\b': {
            "hindi": [f"म्यूजिक! 🎵 मुझे Arijit Singh बहुत पसंद हैं! तुम्हें कौन पसंद है {user_name}?"],
            "english": [f"Music! 🎵 I love soothing melodies! What's your favorite genre {user_name}?"],
            "hinglish": [f"Music! 🎵 Mujhe Arijit Singh bahut pasand hain! Tumhe kaun pasand hai {user_name}?"]
        },
        # Study
        r'\b(study|padhai|exam|test|school|college|university|class|teacher|student)\b': {
            "hindi": [f"पढ़ाई? 📚 अच्छी बात है {user_name}! मदद चाहिए तो बोलो! मैं तुम्हारी teacher बन जाऊंगी! 😊"],
            "english": [f"Study? 📚 Great {user_name}! Need help? I can be your tutor! 😊"],
            "hinglish": [f"Padhai? 📚 Acchi baat hai {user_name}! Madad chahiye toh bolo! Main tumhari teacher ban jaungi! 😊"]
        },
        # Weather
        r'\b(weather|mausam|garmi|sardi|thand|barish|rain|hot|cold|dhoop)\b': {
            "hindi": [f"मौसम की बात! 🌤️ आज कैसा मौसम है तुम्हारे यहां {user_name}?"],
            "english": [f"Weather talk! 🌤️ How's the weather at your place {user_name}?"],
            "hinglish": [f"Mausam ki baat! 🌤️ Aaj kaisa mausam hai tumhare yahan {user_name}?"]
        },
        # Movie
        r'\b(movie|film|cinema|bollywood|hollywood|web series|netflix|show)\b': {
            "hindi": [f"Movie! 🎬 मुझे romance और comedy पसंद है! तुम्हें कौन सी movie पसंद है {user_name}?"],
            "english": [f"Movies! 🎬 I love romance and comedy! What's your favorite {user_name}?"],
            "hinglish": [f"Movie! 🎬 Mujhe romance aur comedy pasand hai! Tumhe kaunsi movie pasand hai {user_name}?"]
        },
        # Game
        r'\b(game|gaming|pubg|free fire|cricket|football|sport|khel)\b': {
            "hindi": [f"गेम! 🎮 तुम कौन सा game खेलते हो {user_name}? मुझे भी बताओ!"],
            "english": [f"Games! 🎮 What games do you play {user_name}? Tell me!"],
            "hinglish": [f"Game! 🎮 Tum kaunsa game khelte ho {user_name}? Mujhe bhi batao!"]
        },
    }

    # Check patterns
    for pattern, responses in patterns.items():
        if re.search(pattern, query_lower):
            lang_responses = responses.get(user_lang, responses.get("hinglish", []))
            if lang_responses:
                return random.choice(lang_responses)

    # Generic fallback if no pattern matches
    generic = {
        "hindi": [
            f"हम्म {user_name}! 🤔 अच्छा सवाल है! मुझे सोचने दो... 💭",
            f"वाह {user_name}! 😊 दिलचस्प बात है! और बताओ इसके बारे में!",
            f"अच्छा {user_name}! 🌸 मैं समझ रही हूं! और बताओ?",
            f"हम्म! 🤗 यह तो interesting है {user_name}! चलो इस बारे में बात करते हैं!",
            f"ओह {user_name}! 😊 बताओ और! मुझे सुनना अच्छा लग रहा है! 💕",
            f"वैसे {user_name}! 🌹 तुम बहुत अच्छे से बात करते हो! और बोलो ना!",
        ],
        "english": [
            f"Hmm {user_name}! 🤔 That's interesting! Tell me more about it!",
            f"Oh {user_name}! 😊 I see! Let's talk more about this!",
            f"That's nice {user_name}! 🌸 I'm listening! Go on!",
            f"Interesting {user_name}! 🤗 Tell me more, I love chatting with you! 💕",
            f"I understand {user_name}! 😊 What else is on your mind? 🌹",
            f"Hmm! 💭 That's a good point {user_name}! What do you think about it?",
        ],
        "hinglish": [
            f"Hmm {user_name}! 🤔 Accha sawaal hai! Mujhe sochne do... 💭",
            f"Waah {user_name}! 😊 Dilchasp baat hai! Aur batao iske baare mein!",
            f"Accha {user_name}! 🌸 Main samajh rahi hoon! Aur batao?",
            f"Hmm! 🤗 Yeh toh interesting hai {user_name}! Chalo is baare mein baat karte hain!",
            f"Oh {user_name}! 😊 Batao aur! Mujhe sunna accha lag raha hai! 💕",
            f"Waise {user_name}! 🌹 Tum bahut acche se baat karte ho! Aur bolo na!",
        ]
    }

    return random.choice(generic.get(user_lang, generic["hinglish"]))


# ============================================================================
# MEMORY EXTRACTION — User ki baaton se info nikaal kar yaad rakhna
# ============================================================================

def extract_and_save_memory(text, user_id, user_name):
    """Extract personal information from user messages and save to memory."""
    text_lower = text.lower()

    # Name detection
    name_patterns = [
        r'(?:mera naam|my name is|i am|main hoon|call me|naam hai)\s+(\w+)',
        r'(?:mujhe|mujhko)\s+(\w+)\s+(?:bolo|bulao|kaho)',
    ]
    for pattern in name_patterns:
        match = re.search(pattern, text_lower)
        if match:
            name = match.group(1).capitalize()
            save_user_memory(user_id, "real_name", name)
            break

    # Location detection
    loc_patterns = [
        r'(?:i live in|main|mein|rahta|rehta|rehti|rahti)\s+(?:hoon|hu|hoo)?\s*(?:in|mein)?\s*(\w+)',
        r'(?:from|se hoon|se hu)\s+(\w+)',
        r'(?:city|sheher|shahar)\s+(?:hai|mera|meri)?\s*(\w+)',
    ]
    for pattern in loc_patterns:
        match = re.search(pattern, text_lower)
        if match:
            location = match.group(1).capitalize()
            if len(location) > 2 and location.lower() not in ["main", "mein", "hoon", "hun", "hai", "mera", "meri"]:
                save_user_memory(user_id, "location", location)
                break

    # Hobby detection
    hobby_patterns = [
        r'(?:i like|mujhe pasand|hobby|hobbies|shauk)\s+(?:hai|hain|karna)?\s*(.+)',
        r'(?:i love|mujhe|mujhko)\s+(.+?)\s+(?:pasand|accha lagta|acchi lagti)',
    ]
    for pattern in hobby_patterns:
        match = re.search(pattern, text_lower)
        if match:
            hobby = match.group(1).strip()[:50]
            if len(hobby) > 2:
                save_user_memory(user_id, "hobby", hobby.capitalize())
                break

    # Favorite things
    fav_patterns = [
        r'(?:favorite|favourite|fav|pasandida)\s+(\w+)\s+(?:hai|is|hain)\s+(.+)',
        r'(?:mujhe|mujhko|i like|i love)\s+(.+?)\s+(?:bahut|very|really)',
    ]
    for pattern in fav_patterns:
        match = re.search(pattern, text_lower)
        if match:
            if len(match.groups()) >= 2:
                save_user_memory(user_id, f"fav_{match.group(1)}", match.group(2).capitalize()[:50])
            break


def detect_mood(text):
    """Detect user's mood from their message."""
    text_lower = text.lower()

    happy_words = ["happy", "khush", "mast", "awesome", "great", "amazing", "wonderful",
                   "excited", "yay", "woohoo", "maja", "maza", "accha", "best"]
    sad_words = ["sad", "dukhi", "udaas", "cry", "rona", "upset", "depressed",
                 "toot", "hurt", "pain", "bura", "kharab", "worst"]
    angry_words = ["angry", "gussa", "naraz", "irritated", "frustrated", "annoyed",
                   "pagal", "bevkoof"]
    bored_words = ["bored", "bore", "boring", "timepass"]
    love_words = ["love", "pyar", "ishq", "crush", "dil"]

    if any(w in text_lower for w in happy_words):
        return "happy"
    elif any(w in text_lower for w in sad_words):
        return "sad"
    elif any(w in text_lower for w in angry_words):
        return "angry"
    elif any(w in text_lower for w in bored_words):
        return "bored"
    elif any(w in text_lower for w in love_words):
        return "romantic"
    return None


# ============================================================================
# SEARCH ENGINE (Factual Queries ke liye — Optional Feature)
# ============================================================================

def search_wikipedia(query, lang="en"):
    try:
        url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote_plus(query)}"
        resp = requests.get(url, headers=HEADERS, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            extract = data.get("extract", "")
            if extract and len(extract) > 30:
                return f"📖 {data.get('title', '')}\n\n{extract}"
    except:
        pass
    try:
        url = f"https://{lang}.wikipedia.org/w/api.php"
        params = {"action": "query", "list": "search", "srsearch": query,
                  "format": "json", "srlimit": 1, "utf8": 1}
        resp = requests.get(url, params=params, headers=HEADERS, timeout=8)
        if resp.status_code == 200:
            results = resp.json().get("query", {}).get("search", [])
            if results:
                title = results[0]["title"]
                url2 = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote_plus(title)}"
                resp2 = requests.get(url2, headers=HEADERS, timeout=8)
                if resp2.status_code == 200:
                    return f"📖 {title}\n\n{resp2.json().get('extract', '')}"
    except:
        pass
    return None

def search_duckduckgo(query):
    try:
        url = "https://api.duckduckgo.com/"
        params = {"q": query, "format": "json", "no_html": 1, "skip_disambig": 1}
        resp = requests.get(url, params=params, headers=HEADERS, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            abstract = data.get("AbstractText", "")
            if abstract and len(abstract) > 30:
                return f"🔍 {data.get('Heading', '')}\n\n{abstract}"
            answer = data.get("Answer", "")
            if answer:
                return f"🔍 {answer}"
    except:
        pass
    return None

def search_weather(query):
    try:
        lower = query.lower()
        weather_words = ["weather", "mausam", "temperature", "temp"]
        if any(w in lower for w in weather_words):
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
                area = data.get("nearest_area", [{}])[0]
                area_name = area.get("areaName", [{}])[0].get("value", city)
                return (f"🌤 Weather in {area_name}\n"
                        f"🌡 Temp: {current.get('temp_C', 'N/A')}°C\n"
                        f"💧 Humidity: {current.get('humidity', 'N/A')}%\n"
                        f"☁️ {current.get('weatherDesc', [{}])[0].get('value', 'N/A')}")
    except:
        pass
    return None

def search_math(query):
    try:
        expr = re.sub(r'[a-zA-Z\s]*(calculate|solve|math|kitna|jod|what is)[a-zA-Z\s]*', '', query, flags=re.IGNORECASE).strip()
        expr = re.sub(r'[^\d+\-*/^%().x\s]', '', expr).strip()
        if expr and any(c.isdigit() for c in expr):
            url = f"http://api.mathjs.org/v4/?expr={quote_plus(expr)}"
            resp = requests.get(url, headers=HEADERS, timeout=5)
            if resp.status_code == 200 and "Error" not in resp.text:
                return f"🔢 {expr} = {resp.text.strip()}"
    except:
        pass
    return None

def is_factual_query(text):
    """Check if the query is factual (needs search) or conversational."""
    text_lower = text.lower()
    factual_keywords = [
        "what is", "kya hai", "who is", "kaun hai", "when", "kab",
        "where", "kahan", "how to", "kaise", "define", "meaning",
        "explain", "history", "capital", "president", "prime minister",
        "population", "weather", "mausam", "calculate", "solve",
        "formula", "wikipedia", "search", "find", "tell me about",
        "batao", "bata do", "jaankari", "information", "news",
        "full form", "code", "programming", "python", "java",
        "country", "planet", "science", "geography"
    ]
    question_marks = text.strip().endswith("?")
    has_factual = any(kw in text_lower for kw in factual_keywords)
    return has_factual or question_marks

def factual_search(query, user_name, user_lang):
    """Search for factual information from multiple sources."""
    result = None

    # Try weather first
    result = search_weather(query)
    if result:
        return result

    # Try math
    result = search_math(query)
    if result:
        return result

    # Try DuckDuckGo
    result = search_duckduckgo(query)
    if result:
        return result

    # Try Wikipedia
    result = search_wikipedia(query, "en")
    if result:
        return result

    # Try Hindi Wikipedia
    result = search_wikipedia(query, "hi")
    if result:
        return result

    return None

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
๏ ᴏᴘᴇɴ sᴏᴜʀᴄᴇ ᴀɪ ᴘᴏᴡᴇʀᴇᴅ.
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
│ /removeadmin - ʀᴇᴍᴏᴠᴇ
│ /broadcast - ʙʀᴏᴀᴅᴄᴀsᴛ
│ /totalusers - ᴛᴏᴛᴀʟ ᴜsᴇʀs
│ /activeusers - ᴀᴄᴛɪᴠᴇ
│ /forceclear - ᴄʟᴇᴀʀ ᴜsᴇʀ
│ /shutdown - sʜᴜᴛᴅᴏᴡɴ
│ /restart - ʀᴇsᴛᴀʀᴛ
│ /maintenance - ᴍᴏᴅᴇ
│ /ban - ʙᴀɴ ᴜsᴇʀ
│ /unban - ᴜɴʙᴀɴ
│ /viewlogs - ʟᴏɢs
│ /exportlogs - ᴇxᴘᴏʀᴛ
│ /systemstats - sʏsᴛᴇᴍ
│ /memorystats - ᴍᴇᴍᴏʀʏ
│ /setphrase - ᴘʜʀᴀsᴇ
│ /setprompt - ᴘʀᴏᴍᴘᴛ
│ /toggleai - ᴛᴏɢɢʟᴇ ᴀɪ
│ /togglesearch - sᴇᴀʀᴄʜ
│ /setcontext - ᴄᴏɴᴛᴇxᴛ
│ /badwords - ʟɪsᴛ
│ /addbadword - ᴀᴅᴅ
│ /removebadword - ʀᴇᴍᴏᴠᴇ
│ /viewhistory - ʜɪsᴛᴏʀʏ
│ /deletehistory - ᴅᴇʟᴇᴛᴇ
│ /forcesummary - sᴜᴍᴍᴀʀʏ
│ /debugmode - ᴅᴇʙᴜɢ
╰───────────────────⦿"""

# ============================================================================
# KEYBOARDS
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
    markup.add(types.InlineKeyboardButton("🏠 ʙᴀᴄᴋ", callback_data="start"))
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
    buttons = [types.InlineKeyboardButton(f"{e} {c}", callback_data=f"cmd_{c[1:]}") for c, e in commands]
    markup.add(*buttons)
    markup.add(types.InlineKeyboardButton("🏠 ʙᴀᴄᴋ", callback_data="start"))
    return markup

# ============================================================================
# ADMIN DECORATOR
# ============================================================================

def admin_only(func):
    @wraps(func)
    def wrapper(message, *args, **kwargs):
        if not is_admin(message.from_user.id):
            bot.reply_to(message, "⛔ You are not authorized!")
            return
        return func(message, *args, **kwargs)
    return wrapper

# ============================================================================
# COMMAND HANDLERS
# ============================================================================

@bot.message_handler(commands=['start'])
def cmd_start(message):
    try:
        user = message.from_user
        get_or_create_user(user.id, user.username, user.first_name, user.last_name)
        bot.send_message(message.chat.id, START_MENU + "\n" + START_DESCRIPTION,
                         reply_markup=get_start_keyboard())
    except Exception as e:
        logger.error(f"cmd_start error: {e}")
        bot.reply_to(message, "❌ Error occurred!")

@bot.message_handler(commands=['help'])
def cmd_help(message):
    try:
        get_or_create_user(message.from_user.id, message.from_user.username,
                           message.from_user.first_name, message.from_user.last_name)
        bot.send_message(message.chat.id, HELP_MENU, reply_markup=get_help_keyboard())
    except Exception as e:
        logger.error(f"cmd_help error: {e}")

@bot.message_handler(commands=['profile'])
def cmd_profile(message):
    try:
        user = message.from_user
        get_or_create_user(user.id, user.username, user.first_name, user.last_name)
        session = Session()
        db_user = session.query(User).filter_by(user_id=user.id).first()
        memories = get_all_user_memories(user.id)
        mem_text = "\n".join([f"│ 💭 {k}: {v}" for k, v in memories.items()]) if memories else "│ 💭 No memories yet"
        profile_text = f"""╭───────────────────⦿
│ 👤 ᴘʀᴏғɪʟᴇ
├───────────────────⦿
│ 🆔 ID: {db_user.user_id}
│ 📛 Name: {db_user.first_name} {db_user.last_name or ''}
│ 👤 Username: @{db_user.username or 'None'}
│ 🌐 Language: {db_user.language}
│ 🎭 Personality: {db_user.personality}
│ 😊 Mood: {db_user.mood}
│ 💬 Messages: {db_user.total_messages}
│ 🔐 Admin: {'Yes ✅' if is_admin(user.id) else 'No ❌'}
├───────────────────⦿
│ 🧠 ᴍᴇᴍᴏʀɪᴇs
{mem_text}
╰───────────────────⦿"""
        Session.remove()
        bot.send_message(message.chat.id, profile_text, reply_markup=get_back_keyboard())
    except Exception as e:
        Session.remove()
        logger.error(f"cmd_profile error: {e}")

@bot.message_handler(commands=['clear'])
def cmd_clear(message):
    try:
        user_id = message.from_user.id
        clear_chat_history(user_id, message.chat.id)
        deactivate_session(user_id, message.chat.id)
        lang = get_user_language(user_id)
        msgs = {
            "hindi": "🧹 मेमोरी साफ! अब 'Ruhi Ji' बोलकर नई बात शुरू करो! 🌸",
            "english": "🧹 Memory cleared! Say 'Ruhi Ji' to start fresh! 🌸",
            "hinglish": "🧹 Memory clear! Ab 'Ruhi Ji' bolkar nayi baat shuru karo! 🌸"
        }
        bot.reply_to(message, msgs.get(lang, msgs["hinglish"]))
    except Exception as e:
        logger.error(f"cmd_clear error: {e}")

@bot.message_handler(commands=['mode'])
def cmd_mode(message):
    try:
        session = Session()
        user = session.query(User).filter_by(user_id=message.from_user.id).first()
        if user:
            modes = ["normal", "fun", "study", "romantic"]
            idx = modes.index(user.mode) if user.mode in modes else 0
            user.mode = modes[(idx + 1) % len(modes)]
            session.commit()
            bot.reply_to(message, f"🔧 Mode: {user.mode.upper()} ✅")
        Session.remove()
    except Exception as e:
        Session.remove()
        logger.error(f"cmd_mode error: {e}")

@bot.message_handler(commands=['lang'])
def cmd_lang(message):
    try:
        bot.send_message(message.chat.id, "🌐 Select language / भाषा चुनें:",
                         reply_markup=get_language_keyboard())
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
        bot.send_message(message.chat.id, "🎭 Choose personality:", reply_markup=markup)
    except Exception as e:
        logger.error(f"cmd_personality error: {e}")

@bot.message_handler(commands=['usage'])
def cmd_usage(message):
    try:
        user_id = message.from_user.id
        session = Session()
        user = session.query(User).filter_by(user_id=user_id).first()
        hcount = session.query(ChatHistory).filter_by(user_id=user_id).count()
        Session.remove()
        if user:
            bot.send_message(message.chat.id, f"""╭───────────────────⦿
│ 📊 ᴜsᴀɢᴇ sᴛᴀᴛs
├───────────────────⦿
│ 💬 Messages: {user.total_messages}
│ 📝 History: {hcount}
│ 🌐 Language: {user.language}
│ 🎭 Personality: {user.personality}
│ 😊 Mood: {user.mood}
│ ⚡ Session: {'Active ✅' if is_session_active(user_id, message.chat.id) else 'Inactive ❌'}
╰───────────────────⦿""", reply_markup=get_back_keyboard())
    except Exception as e:
        Session.remove()
        logger.error(f"cmd_usage error: {e}")

@bot.message_handler(commands=['summary'])
def cmd_summary(message):
    try:
        history = get_chat_history(message.from_user.id, message.chat.id, limit=20)
        if history:
            parts = ["╭───────────────────⦿", "│ 📋 ᴄᴏɴᴠᴇʀsᴀᴛɪᴏɴ sᴜᴍᴍᴀʀʏ", "├───────────────────⦿"]
            for h in history[-10:]:
                icon = "👤" if h["role"] == "user" else "🤖"
                parts.append(f"│ {icon} {h['content'][:80]}...")
            parts.append("╰───────────────────⦿")
            bot.send_message(message.chat.id, "\n".join(parts))
        else:
            bot.reply_to(message, "📋 No history yet! Start chatting! 🌸")
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
            user.mood = "happy"
            session.commit()
        Session.remove()
        bot.reply_to(message, "🔄 Reset done! Say 'Ruhi Ji' to start! 🌸")
    except Exception as e:
        Session.remove()
        logger.error(f"cmd_reset error: {e}")

# ============================================================================
# ADMIN COMMANDS
# ============================================================================

@bot.message_handler(commands=['admin'])
@admin_only
def cmd_admin(message):
    try:
        bot.send_message(message.chat.id, f"""╭───────────────────⦿
│ 🔐 ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ
├───────────────────⦿
│ 👑 Admin: {message.from_user.first_name}
│ 👥 Total Users: {get_total_users()}
│ ⚡ Active: {get_active_session_count()}
│ 🤖 AI: {'ON ✅' if AI_ENABLED else 'OFF ❌'}
│ 🔍 Search: {'ON ✅' if SEARCH_ENABLED else 'OFF ❌'}
│ 🔧 Maintenance: {'ON 🔴' if MAINTENANCE_MODE else 'OFF 🟢'}
│ 📦 Version: {BOT_VERSION}
╰───────────────────⦿""")
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
        target = int(parts[1])
        bot.reply_to(message, f"✅ Admin added: {target}" if add_admin(target, message.from_user.id) else "❌ Failed!")
    except ValueError:
        bot.reply_to(message, "❌ Invalid ID!")
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
        target = int(parts[1])
        if target == ADMIN_ID:
            bot.reply_to(message, "❌ Cannot remove super admin!")
            return
        bot.reply_to(message, f"✅ Removed: {target}" if remove_admin(target) else "❌ Failed!")
    except ValueError:
        bot.reply_to(message, "❌ Invalid ID!")
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
        ids = get_all_user_ids()
        s, f = 0, 0
        for uid in ids:
            try:
                bot.send_message(uid, f"📢 ʙʀᴏᴀᴅᴄᴀsᴛ\n\n{text}\n\n— Ruhi Ji 🌹")
                s += 1
            except:
                f += 1
        bot.reply_to(message, f"📢 Done! ✅ {s} | ❌ {f}")
    except Exception as e:
        logger.error(f"cmd_broadcast error: {e}")

@bot.message_handler(commands=['totalusers'])
@admin_only
def cmd_totalusers(message):
    bot.reply_to(message, f"👥 Total users: {get_total_users()}")

@bot.message_handler(commands=['activeusers'])
@admin_only
def cmd_activeusers(message):
    bot.reply_to(message, f"⚡ Active sessions: {get_active_session_count()}")

@bot.message_handler(commands=['forceclear'])
@admin_only
def cmd_forceclear(message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "Usage: /forceclear <user_id>")
            return
        clear_chat_history(int(parts[1]))
        bot.reply_to(message, f"🧹 Cleared for {parts[1]}!")
    except:
        bot.reply_to(message, "❌ Error!")

@bot.message_handler(commands=['shutdown'])
@admin_only
def cmd_shutdown(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Super admin only!")
        return
    bot.reply_to(message, "🔴 Shutting down...")
    os._exit(0)

@bot.message_handler(commands=['restart'])
@admin_only
def cmd_restart(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ Super admin only!")
        return
    bot.reply_to(message, "🔄 Restarting...")
    os.execv(sys.executable, ['python'] + sys.argv)

@bot.message_handler(commands=['maintenance'])
@admin_only
def cmd_maintenance(message):
    global MAINTENANCE_MODE
    MAINTENANCE_MODE = not MAINTENANCE_MODE
    bot.reply_to(message, f"🔧 Maintenance: {'ON 🔴' if MAINTENANCE_MODE else 'OFF 🟢'}")

@bot.message_handler(commands=['ban'])
@admin_only
def cmd_ban(message):
    try:
        parts = message.text.split(maxsplit=2)
        if len(parts) < 2:
            bot.reply_to(message, "Usage: /ban <user_id> [reason]")
            return
        reason = parts[2] if len(parts) > 2 else "No reason"
        bot.reply_to(message, f"🚫 Banned {parts[1]}!" if ban_user(int(parts[1]), reason, message.from_user.id) else "❌ Failed!")
    except:
        bot.reply_to(message, "❌ Error!")

@bot.message_handler(commands=['unban'])
@admin_only
def cmd_unban(message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "Usage: /unban <user_id>")
            return
        bot.reply_to(message, f"✅ Unbanned {parts[1]}!" if unban_user(int(parts[1])) else "❌ Failed!")
    except:
        bot.reply_to(message, "❌ Error!")

@bot.message_handler(commands=['viewlogs'])
@admin_only
def cmd_viewlogs(message):
    if log_buffer:
        bot.send_message(message.chat.id, f"📜 Logs:\n\n" + "\n".join(log_buffer[-20:])[:4000])
    else:
        bot.reply_to(message, "📜 No logs!")

@bot.message_handler(commands=['exportlogs'])
@admin_only
def cmd_exportlogs(message):
    if log_buffer:
        f = BytesIO("\n".join(log_buffer).encode('utf-8'))
        f.name = "ruhi_logs.txt"
        bot.send_document(message.chat.id, f, caption="📄 Logs Export")
    else:
        bot.reply_to(message, "📜 No logs!")

@bot.message_handler(commands=['systemstats'])
@admin_only
def cmd_systemstats(message):
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        bot.send_message(message.chat.id, f"""╭───────────────────⦿
│ 🖥 sʏsᴛᴇᴍ sᴛᴀᴛs
├───────────────────⦿
│ 🔧 CPU: {cpu}%
│ 💾 RAM: {mem.percent}% ({mem.used//(1024*1024)}MB)
│ 👥 Users: {get_total_users()}
│ ⚡ Active: {get_active_session_count()}
│ 🐍 Python: {sys.version.split()[0]}
│ 📦 Version: {BOT_VERSION}
╰───────────────────⦿""")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['memorystats'])
@admin_only
def cmd_memorystats(message):
    try:
        session = Session()
        bot.send_message(message.chat.id, f"""╭───────────────────⦿
│ 🧠 ᴍᴇᴍᴏʀʏ sᴛᴀᴛs
├───────────────────⦿
│ 👥 Users: {session.query(User).count()}
│ 💬 History: {session.query(ChatHistory).count()}
│ 🧠 Memories: {session.query(UserMemory).count()}
│ 🚫 Banned: {session.query(BannedUser).count()}
│ 👑 Admins: {session.query(AdminList).count()}
│ 🤬 Bad Words: {session.query(BadWord).count()}
│ ⚡ Sessions: {get_active_session_count()}
╰───────────────────⦿""")
        Session.remove()
    except Exception as e:
        Session.remove()
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['setphrase'])
@admin_only
def cmd_setphrase(message):
    global ACTIVATION_PHRASE
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, f"Current: '{ACTIVATION_PHRASE}'\nUsage: /setphrase <phrase>")
        return
    ACTIVATION_PHRASE = parts[1].strip().lower()
    set_config("activation_phrase", ACTIVATION_PHRASE)
    bot.reply_to(message, f"✅ Phrase: '{ACTIVATION_PHRASE}'")

@bot.message_handler(commands=['setprompt'])
@admin_only
def cmd_setprompt(message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, f"Current: {get_config('custom_prompt', 'Not set')}\nUsage: /setprompt <text>")
        return
    set_config("custom_prompt", parts[1].strip())
    bot.reply_to(message, "✅ Prompt updated!")

@bot.message_handler(commands=['toggleai'])
@admin_only
def cmd_toggleai(message):
    global AI_ENABLED
    AI_ENABLED = not AI_ENABLED
    bot.reply_to(message, f"🤖 AI: {'ON ✅' if AI_ENABLED else 'OFF ❌'}")

@bot.message_handler(commands=['togglesearch'])
@admin_only
def cmd_togglesearch(message):
    global SEARCH_ENABLED
    SEARCH_ENABLED = not SEARCH_ENABLED
    bot.reply_to(message, f"🔍 Search: {'ON ✅' if SEARCH_ENABLED else 'OFF ❌'}")

@bot.message_handler(commands=['setcontext'])
@admin_only
def cmd_setcontext(message):
    global MAX_CONTEXT_MESSAGES
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, f"Current: {MAX_CONTEXT_MESSAGES}\nUsage: /setcontext <5-200>")
        return
    try:
        val = int(parts[1])
        if 5 <= val <= 200:
            MAX_CONTEXT_MESSAGES = val
            bot.reply_to(message, f"✅ Context: {val}")
        else:
            bot.reply_to(message, "❌ Range: 5-200!")
    except:
        bot.reply_to(message, "❌ Invalid number!")

@bot.message_handler(commands=['badwords'])
@admin_only
def cmd_badwords(message):
    words = get_bad_words()
    bot.send_message(message.chat.id, f"🤬 Bad Words ({len(words)}):\n{', '.join(words)}" if words else "📝 No bad words!")

@bot.message_handler(commands=['addbadword'])
@admin_only
def cmd_addbadword(message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /addbadword <word>")
        return
    bot.reply_to(message, f"✅ Added!" if add_bad_word(parts[1].strip(), message.from_user.id) else "❌ Exists!")

@bot.message_handler(commands=['removebadword'])
@admin_only
def cmd_removebadword(message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /removebadword <word>")
        return
    bot.reply_to(message, f"✅ Removed!" if remove_bad_word(parts[1].strip()) else "❌ Failed!")

@bot.message_handler(commands=['viewhistory'])
@admin_only
def cmd_viewhistory(message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "Usage: /viewhistory <user_id>")
            return
        target = int(parts[1])
        session = Session()
        history = session.query(ChatHistory).filter_by(user_id=target).order_by(
            ChatHistory.timestamp.desc()).limit(20).all()
        Session.remove()
        if history:
            history.reverse()
            lines = [f"📜 History for {target}:\n"]
            for h in history:
                icon = "👤" if h.role == "user" else "🤖"
                lines.append(f"{icon} [{h.timestamp.strftime('%H:%M')}] {h.message[:80]}")
            bot.send_message(message.chat.id, "\n".join(lines)[:4000])
        else:
            bot.reply_to(message, "📝 No history!")
    except:
        Session.remove()
        bot.reply_to(message, "❌ Error!")

@bot.message_handler(commands=['deletehistory'])
@admin_only
def cmd_deletehistory(message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "Usage: /deletehistory <user_id>")
            return
        clear_chat_history(int(parts[1]))
        bot.reply_to(message, f"🗑 Deleted for {parts[1]}!")
    except:
        bot.reply_to(message, "❌ Error!")

@bot.message_handler(commands=['forcesummary'])
@admin_only
def cmd_forcesummary(message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "Usage: /forcesummary <user_id>")
            return
        target = int(parts[1])
        session = Session()
        history = session.query(ChatHistory).filter_by(user_id=target).order_by(
            ChatHistory.timestamp.desc()).limit(15).all()
        Session.remove()
        if history:
            history.reverse()
            lines = [f"📋 Summary for {target}:\n"]
            for h in history:
                icon = "👤" if h.role == "user" else "🤖"
                lines.append(f"{icon} {h.message[:100]}")
            bot.send_message(message.chat.id, "\n".join(lines)[:4000])
        else:
            bot.reply_to(message, "📝 No history!")
    except:
        Session.remove()
        bot.reply_to(message, "❌ Error!")

@bot.message_handler(commands=['debugmode'])
@admin_only
def cmd_debugmode(message):
    global DEBUG_MODE
    DEBUG_MODE = not DEBUG_MODE
    bot.reply_to(message, f"🐛 Debug: {'ON' if DEBUG_MODE else 'OFF'}")

# ============================================================================
# CALLBACK QUERY HANDLER
# ============================================================================

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    try:
        user = call.from_user
        data = call.data

        if data == "start":
            bot.edit_message_text(START_MENU + "\n" + START_DESCRIPTION,
                                  call.message.chat.id, call.message.message_id,
                                  reply_markup=get_start_keyboard())
        elif data == "help":
            bot.edit_message_text(HELP_MENU, call.message.chat.id,
                                  call.message.message_id, reply_markup=get_help_keyboard())
        elif data == "profile":
            get_or_create_user(user.id, user.username, user.first_name, user.last_name)
            session = Session()
            db_user = session.query(User).filter_by(user_id=user.id).first()
            memories = get_all_user_memories(user.id)
            mem_text = "\n".join([f"│ 💭 {k}: {v}" for k, v in memories.items()]) if memories else "│ 💭 No memories"
            profile_text = f"""╭───────────────────⦿
│ 👤 ᴘʀᴏғɪʟᴇ
├───────────────────⦿
│ 🆔 ID: {db_user.user_id}
│ 📛 Name: {db_user.first_name}
│ 🌐 Language: {db_user.language}
│ 🎭 Personality: {db_user.personality}
│ 😊 Mood: {db_user.mood}
│ 💬 Messages: {db_user.total_messages}
├───────────────────⦿
{mem_text}
╰───────────────────⦿"""
            Session.remove()
            bot.edit_message_text(profile_text, call.message.chat.id,
                                  call.message.message_id, reply_markup=get_back_keyboard())
        elif data == "language":
            bot.edit_message_text("🌐 Select language:", call.message.chat.id,
                                  call.message.message_id, reply_markup=get_language_keyboard())
        elif data.startswith("lang_"):
            lang = data.replace("lang_", "")
            set_user_language(user.id, lang)
            bot.answer_callback_query(call.id, f"✅ Language: {lang}")
            bot.edit_message_text(START_MENU + "\n" + START_DESCRIPTION,
                                  call.message.chat.id, call.message.message_id,
                                  reply_markup=get_start_keyboard())
        elif data.startswith("pers_"):
            pers = data.replace("pers_", "")
            set_user_personality(user.id, pers)
            bot.answer_callback_query(call.id, f"✅ Personality: {pers}")
            bot.edit_message_text(START_MENU + "\n" + START_DESCRIPTION,
                                  call.message.chat.id, call.message.message_id,
                                  reply_markup=get_start_keyboard())
        elif data == "usage":
            session = Session()
            db_user = session.query(User).filter_by(user_id=user.id).first()
            hcount = session.query(ChatHistory).filter_by(user_id=user.id).count()
            Session.remove()
            if db_user:
                bot.edit_message_text(f"""╭───────────────────⦿
│ 📊 ᴜsᴀɢᴇ
├───────────────────⦿
│ 💬 Messages: {db_user.total_messages}
│ 📝 History: {hcount}
│ 😊 Mood: {db_user.mood}
│ ⚡ Session: {'Active ✅' if is_session_active(user.id, call.message.chat.id) else 'Inactive ❌'}
╰───────────────────⦿""", call.message.chat.id, call.message.message_id,
                    reply_markup=get_back_keyboard())
        elif data == "reset":
            clear_chat_history(user.id, call.message.chat.id)
            deactivate_session(user.id, call.message.chat.id)
            bot.answer_callback_query(call.id, "🔄 Reset done!")
            bot.edit_message_text(START_MENU + "\n" + START_DESCRIPTION,
                                  call.message.chat.id, call.message.message_id,
                                  reply_markup=get_start_keyboard())
        elif data == "commands":
            bot.edit_message_text("📋 ᴄʟɪᴄᴋ ᴛᴏ ᴄᴏᴘʏ:",
                                  call.message.chat.id, call.message.message_id,
                                  reply_markup=get_commands_keyboard())
        elif data.startswith("cmd_"):
            cmd = "/" + data.replace("cmd_", "")
            bot.answer_callback_query(call.id, f"Command: {cmd}\nType it in chat!", show_alert=True)

        try:
            bot.answer_callback_query(call.id)
        except:
            pass

    except telebot.apihelper.ApiTelegramException as e:
        if "message is not modified" not in str(e):
            logger.error(f"callback error: {e}")
        try:
            bot.answer_callback_query(call.id)
        except:
            pass
    except Exception as e:
        logger.error(f"callback_handler error: {e}")

# ============================================================================
# MAIN MESSAGE HANDLER — THE BRAIN OF RUHI JI
# ============================================================================

@bot.message_handler(func=lambda message: True, content_types=['text'])
def handle_message(message):
    try:
        if message.text and message.text.startswith('/'):
            return

        user = message.from_user
        user_id = user.id
        chat_id = message.chat.id
        text = message.text.strip() if message.text else ""
        user_name = user.first_name or "Dear"

        if not text:
            return
        if MAINTENANCE_MODE and not is_admin(user_id):
            return
        if is_user_banned(user_id):
            return

        get_or_create_user(user_id, user.username, user.first_name, user.last_name)
        user_lang = get_user_language(user_id)
        user_mood = get_user_mood(user_id)
        text_lower = text.lower()

        custom_phrase = get_config("activation_phrase", "")
        phrase = custom_phrase if custom_phrase else ACTIVATION_PHRASE
        phrase_found = phrase.lower() in text_lower
        session_active = is_session_active(user_id, chat_id)

        # === ACTIVATION: "Ruhi Ji" bola ===
        if phrase_found:
            activate_session(user_id, chat_id)
            increment_message_count(user_id)

            query = text_lower.replace(phrase.lower(), "").strip()

            # Sirf phrase bola, koi query nahi
            if not query or len(query) < 2:
                greeting = {
                    "hindi": f"हाय {user_name}! 🌹 मैं रुही जी हूं! बोलो, क्या बात करनी है? 😊\nमैं 10 मिनट तक तुम्हारे साथ हूं! 💕",
                    "english": f"Hey {user_name}! 🌹 I'm Ruhi Ji! Tell me, what's up? 😊\nI'm here for 10 minutes! 💕",
                    "hinglish": f"Hii {user_name}! 🌹 Main Ruhi Ji hoon! Bolo, kya baat karni hai? 😊\nMain 10 minute tumhare saath hoon! 💕"
                }
                response = greeting.get(user_lang, greeting["hinglish"])
                save_chat_history(user_id, chat_id, "user", text)
                save_chat_history(user_id, chat_id, "assistant", response)
                bot.reply_to(message, response)
                return

            # Bad words check
            if check_bad_words(query):
                bw = {
                    "hindi": "😤 ऐसे शब्द मत बोलो! मैं अच्छे लोगों से बात करती हूं! 🙅‍♀️",
                    "english": "😤 Don't use such words! I talk to decent people! 🙅‍♀️",
                    "hinglish": "😤 Aise words mat bolo! Main acche logon se baat karti hoon! 🙅‍♀️"
                }
                bot.reply_to(message, bw.get(user_lang, bw["hinglish"]))
                return

            if not AI_ENABLED:
                bot.reply_to(message, "🔇 AI is currently disabled! Come back later! 🌸")
                return

            # Typing action
            bot.send_chat_action(chat_id, 'typing')
            save_chat_history(user_id, chat_id, "user", text)

            # === DECISION: Factual ya Conversational? ===
            response = None

            # Pehle check: kya factual query hai + search enabled hai?
            if SEARCH_ENABLED and is_factual_query(query):
                search_result = factual_search(query, user_name, user_lang)
                if search_result:
                    # Search result ko Ruhi Ji ke style mein wrap karo
                    wrapper = {
                        "hindi": f"हाँ {user_name}! 🌹 मैंने तुम्हारे लिए ढूंढा:\n\n{search_result}\n\n🌸 और कुछ पूछना हो तो बताओ!",
                        "english": f"Hey {user_name}! 🌹 I found this for you:\n\n{search_result}\n\n🌸 Ask me anything else!",
                        "hinglish": f"Haan {user_name}! 🌹 Maine tumhare liye dhundha:\n\n{search_result}\n\n🌸 Aur kuch puchna ho toh batao!"
                    }
                    response = wrapper.get(user_lang, wrapper["hinglish"])

            # Agar search se nahi mila ya conversational hai, toh AI se pucho
            if not response:
                response = get_ai_response(query, user_name, user_lang, user_mood, user_id, chat_id)

            save_chat_history(user_id, chat_id, "assistant", response)

            if DEBUG_MODE and is_admin(user_id):
                response += f"\n\n🐛 Debug: Query='{query[:50]}'"

            try:
                bot.reply_to(message, response)
            except Exception as e:
                if "too long" in str(e).lower():
                    for i in range(0, len(response), 4000):
                        bot.send_message(chat_id, response[i:i + 4000])
                else:
                    bot.reply_to(message, response[:4000])
            return

        # === SESSION ACTIVE: Bina phrase ke reply ===
        elif session_active:
            refresh_session(user_id, chat_id)
            increment_message_count(user_id)
            query = text.strip()

            if check_bad_words(query):
                bw = {
                    "hindi": "😤 ऐसे शब्द मत बोलो! 🙅‍♀️",
                    "english": "😤 Don't use such words! 🙅‍♀️",
                    "hinglish": "😤 Aise words mat bolo! 🙅‍♀️"
                }
                bot.reply_to(message, bw.get(user_lang, bw["hinglish"]))
                return

            if not AI_ENABLED:
                bot.reply_to(message, "🔇 AI disabled! 🌸")
                return

            if len(query) < 1:
                return

            bot.send_chat_action(chat_id, 'typing')
            save_chat_history(user_id, chat_id, "user", text)

            response = None

            if SEARCH_ENABLED and is_factual_query(query):
                search_result = factual_search(query, user_name, user_lang)
                if search_result:
                    wrapper = {
                        "hindi": f"हाँ {user_name}! 🌹\n\n{search_result}\n\n🌸 और कुछ?",
                        "english": f"Hey {user_name}! 🌹\n\n{search_result}\n\n🌸 Anything else?",
                        "hinglish": f"Haan {user_name}! 🌹\n\n{search_result}\n\n🌸 Aur kuch?"
                    }
                    response = wrapper.get(user_lang, wrapper["hinglish"])

            if not response:
                response = get_ai_response(query, user_name, user_lang, user_mood, user_id, chat_id)

            save_chat_history(user_id, chat_id, "assistant", response)

            if DEBUG_MODE and is_admin(user_id):
                response += f"\n\n🐛 Debug: Active session"

            try:
                bot.reply_to(message, response)
            except Exception as e:
                if "too long" in str(e).lower():
                    for i in range(0, len(response), 4000):
                        bot.send_message(chat_id, response[i:i + 4000])
                else:
                    bot.reply_to(message, response[:4000])
            return

        else:
            # Session NOT active + phrase NOT found = CHUP RAHO
            return

    except Exception as e:
        logger.error(f"handle_message error: {e}\n{traceback.format_exc()}")
        try:
            bot.reply_to(message, "😅 Oops! Kuch gadbad ho gayi! Try again! 🌸")
        except:
            pass

# ============================================================================
# MEDIA HANDLER
# ============================================================================

@bot.message_handler(func=lambda m: True, content_types=['photo', 'video', 'audio', 'document', 'sticker', 'voice', 'video_note'])
def handle_media(message):
    try:
        user_id = message.from_user.id
        chat_id = message.chat.id
        if not is_session_active(user_id, chat_id):
            return
        refresh_session(user_id, chat_id)
        lang = get_user_language(user_id)
        name = message.from_user.first_name or "Dear"
        msgs = {
            "hindi": f"अरे {name}! 😊 मैं अभी सिर्फ text समझती हूं! Text में पूछो! 🌹",
            "english": f"Hey {name}! 😊 I can only understand text right now! Ask in text! 🌹",
            "hinglish": f"Arey {name}! 😊 Main abhi sirf text samajhti hoon! Text mein pucho! 🌹"
        }
        bot.reply_to(message, msgs.get(lang, msgs["hinglish"]))
    except:
        pass

# ============================================================================
# INITIALIZATION
# ============================================================================

def initialize_bot():
    try:
        if ADMIN_ID:
            add_admin(ADMIN_ID, ADMIN_ID)
        saved_phrase = get_config("activation_phrase", "")
        if saved_phrase:
            global ACTIVATION_PHRASE
            ACTIVATION_PHRASE = saved_phrase
        logger.info("Bot initialized!")
    except Exception as e:
        logger.error(f"Init error: {e}")

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("🌹 RUHI JI BOT v4.0 — Starting...")
    logger.info(f"🔑 Admin: {ADMIN_ID}")
    logger.info(f"💾 DB: {DATABASE_URL[:30]}...")
    logger.info(f"🌐 Port: {PORT}")
    logger.info("=" * 50)

    initialize_bot()

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info("🌐 Flask keep-alive started!")

    logger.info("🤖 Starting bot polling...")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60,
                                 allowed_updates=["message", "callback_query"],
                                 skip_pending=True)
        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(5)
            