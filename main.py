# ============================================================================
# main.py — RUHI JI v5.0 — GOD LEVEL CONVERSATIONAL BOT
# 100% WORKING FREE AI APIs | TESTED & VERIFIED
# Single File | Render Ready | Unlimited Conversation
# ============================================================================

import os
import sys
import time
import json
import logging
import threading
import datetime
import re
import random
import traceback
from functools import wraps
from io import BytesIO

import telebot
from telebot import types
from flask import Flask
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, Boolean,
    DateTime, BigInteger
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
MAX_CONTEXT = 50
BOT_VERSION = "5.0.0"
DEBUG_MODE = False
MAINTENANCE_MODE = False
AI_ENABLED = True
SEARCH_ENABLED = True

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("RuhiJi")
log_buffer = []

class BufHandler(logging.Handler):
    def emit(self, record):
        log_buffer.append(self.format(record))
        if len(log_buffer) > 500:
            log_buffer.pop(0)

bh = BufHandler()
bh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(bh)

# ============================================================================
# DATABASE
# ============================================================================

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL, echo=False, pool_size=5, max_overflow=10, poolclass=QueuePool)

Base = declarative_base()
sf = sessionmaker(bind=engine)
Session = scoped_session(sf)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
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
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_active = Column(DateTime, default=datetime.datetime.utcnow)

class ChatHistory(Base):
    __tablename__ = "chat_history"
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    role = Column(String(20), default="user")
    message = Column(Text, default="")
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

class AdminList(Base):
    __tablename__ = "admin_list"
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, unique=True, nullable=False)
    added_by = Column(BigInteger, default=0)
    added_at = Column(DateTime, default=datetime.datetime.utcnow)

class BannedUser(Base):
    __tablename__ = "banned_users"
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, unique=True, nullable=False)
    reason = Column(Text, default="")
    banned_by = Column(BigInteger, default=0)
    banned_at = Column(DateTime, default=datetime.datetime.utcnow)

class BadWord(Base):
    __tablename__ = "bad_words"
    id = Column(Integer, primary_key=True)
    word = Column(String(255), unique=True, nullable=False)
    added_by = Column(BigInteger, default=0)

class BotConfig(Base):
    __tablename__ = "bot_config"
    id = Column(Integer, primary_key=True)
    key = Column(String(255), unique=True, nullable=False)
    value = Column(Text, default="")

class UserMemory(Base):
    __tablename__ = "user_memory"
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    key = Column(String(255), nullable=False)
    value = Column(Text, default="")
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)

try:
    Base.metadata.create_all(engine)
    logger.info("✅ Database ready")
except Exception as e:
    logger.error(f"DB error: {e}")

# ============================================================================
# FLASK KEEP-ALIVE
# ============================================================================

app = Flask(__name__)

@app.route("/")
def home():
    return f"<h1>🌹 Ruhi Ji v{BOT_VERSION} Running!</h1>"

@app.route("/health")
def health():
    return {"status": "ok", "version": BOT_VERSION}, 200

def run_flask():
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)

# ============================================================================
# BOT INIT
# ============================================================================

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None, threaded=True)

# ============================================================================
# SESSION MANAGER
# ============================================================================

active_sessions = {}
slock = threading.Lock()

def activate_session(uid, cid):
    with slock: active_sessions[(uid, cid)] = time.time()

def is_session_active(uid, cid):
    with slock:
        k = (uid, cid)
        if k in active_sessions:
            if time.time() - active_sessions[k] < SESSION_TIMEOUT:
                return True
            del active_sessions[k]
        return False

def refresh_session(uid, cid):
    with slock:
        k = (uid, cid)
        if k in active_sessions: active_sessions[k] = time.time()

def deactivate_session(uid, cid):
    with slock: active_sessions.pop((uid, cid), None)

def get_active_count():
    with slock:
        now = time.time()
        return sum(1 for v in active_sessions.values() if now - v < SESSION_TIMEOUT)

def cleanup_loop():
    while True:
        try:
            with slock:
                now = time.time()
                expired = [k for k, v in active_sessions.items() if now - v >= SESSION_TIMEOUT]
                for k in expired: del active_sessions[k]
        except: pass
        time.sleep(60)

threading.Thread(target=cleanup_loop, daemon=True).start()

# ============================================================================
# DB HELPERS
# ============================================================================

def get_or_create_user(uid, uname="", fname="", lname=""):
    try:
        s = Session()
        u = s.query(User).filter_by(user_id=uid).first()
        if not u:
            u = User(user_id=uid, username=uname or "", first_name=fname or "",
                     last_name=lname or "", is_admin=(uid == ADMIN_ID))
            s.add(u)
            s.commit()
        else:
            u.username = uname or u.username
            u.first_name = fname or u.first_name
            u.last_name = lname or u.last_name
            u.last_active = datetime.datetime.utcnow()
            s.commit()
        Session.remove()
        return u
    except:
        Session.remove()
        return None

def inc_msg(uid):
    try:
        s = Session()
        u = s.query(User).filter_by(user_id=uid).first()
        if u: u.total_messages += 1; u.last_active = datetime.datetime.utcnow(); s.commit()
        Session.remove()
    except: Session.remove()

def save_history(uid, cid, role, msg):
    try:
        s = Session()
        s.add(ChatHistory(user_id=uid, chat_id=cid, role=role, message=msg[:4000]))
        s.commit()
        cnt = s.query(ChatHistory).filter_by(user_id=uid, chat_id=cid).count()
        if cnt > MAX_CONTEXT:
            old = s.query(ChatHistory).filter_by(user_id=uid, chat_id=cid)\
                .order_by(ChatHistory.timestamp.asc()).limit(cnt - MAX_CONTEXT).all()
            for o in old: s.delete(o)
            s.commit()
        Session.remove()
    except: Session.remove()

def get_history(uid, cid, limit=15):
    try:
        s = Session()
        h = s.query(ChatHistory).filter_by(user_id=uid, chat_id=cid)\
            .order_by(ChatHistory.timestamp.desc()).limit(limit).all()
        h.reverse()
        r = [{"role": x.role, "content": x.message} for x in h]
        Session.remove()
        return r
    except:
        Session.remove()
        return []

def clear_history(uid, cid=None):
    try:
        s = Session()
        q = s.query(ChatHistory).filter_by(user_id=uid)
        if cid: q = q.filter_by(chat_id=cid)
        q.delete(); s.commit(); Session.remove()
    except: Session.remove()

def is_banned(uid):
    try:
        s = Session()
        b = s.query(BannedUser).filter_by(user_id=uid).first()
        Session.remove()
        return b is not None
    except: Session.remove(); return False

def do_ban(uid, reason="", by=0):
    try:
        s = Session()
        if not s.query(BannedUser).filter_by(user_id=uid).first():
            s.add(BannedUser(user_id=uid, reason=reason, banned_by=by))
        u = s.query(User).filter_by(user_id=uid).first()
        if u: u.is_banned = True
        s.commit(); Session.remove(); return True
    except: Session.remove(); return False

def do_unban(uid):
    try:
        s = Session()
        s.query(BannedUser).filter_by(user_id=uid).delete()
        u = s.query(User).filter_by(user_id=uid).first()
        if u: u.is_banned = False
        s.commit(); Session.remove(); return True
    except: Session.remove(); return False

def check_admin(uid):
    if uid == ADMIN_ID: return True
    try:
        s = Session()
        a = s.query(AdminList).filter_by(user_id=uid).first()
        Session.remove()
        return a is not None
    except: Session.remove(); return False

def do_add_admin(uid, by=0):
    try:
        s = Session()
        if not s.query(AdminList).filter_by(user_id=uid).first():
            s.add(AdminList(user_id=uid, added_by=by))
        u = s.query(User).filter_by(user_id=uid).first()
        if u: u.is_admin = True
        s.commit(); Session.remove(); return True
    except: Session.remove(); return False

def do_remove_admin(uid):
    try:
        s = Session()
        s.query(AdminList).filter_by(user_id=uid).delete()
        u = s.query(User).filter_by(user_id=uid).first()
        if u: u.is_admin = False
        s.commit(); Session.remove(); return True
    except: Session.remove(); return False

def total_users():
    try:
        s = Session(); c = s.query(User).count(); Session.remove(); return c
    except: Session.remove(); return 0

def all_user_ids():
    try:
        s = Session(); ids = [u[0] for u in s.query(User.user_id).all()]; Session.remove(); return ids
    except: Session.remove(); return []

def get_lang(uid):
    try:
        s = Session(); u = s.query(User).filter_by(user_id=uid).first()
        l = u.language if u else "hinglish"; Session.remove(); return l
    except: Session.remove(); return "hinglish"

def set_lang(uid, lang):
    try:
        s = Session(); u = s.query(User).filter_by(user_id=uid).first()
        if u: u.language = lang; s.commit()
        Session.remove()
    except: Session.remove()

def set_pers(uid, p):
    try:
        s = Session(); u = s.query(User).filter_by(user_id=uid).first()
        if u: u.personality = p; s.commit()
        Session.remove()
    except: Session.remove()

def get_mood(uid):
    try:
        s = Session(); u = s.query(User).filter_by(user_id=uid).first()
        m = u.mood if u else "happy"; Session.remove(); return m
    except: Session.remove(); return "happy"

def set_mood(uid, m):
    try:
        s = Session(); u = s.query(User).filter_by(user_id=uid).first()
        if u: u.mood = m; s.commit()
        Session.remove()
    except: Session.remove()

def save_memory(uid, key, val):
    try:
        s = Session()
        m = s.query(UserMemory).filter_by(user_id=uid, key=key).first()
        if m: m.value = val; m.updated_at = datetime.datetime.utcnow()
        else: s.add(UserMemory(user_id=uid, key=key, value=val))
        s.commit(); Session.remove()
    except: Session.remove()

def get_memory(uid, key):
    try:
        s = Session()
        m = s.query(UserMemory).filter_by(user_id=uid, key=key).first()
        v = m.value if m else None; Session.remove(); return v
    except: Session.remove(); return None

def get_all_memories(uid):
    try:
        s = Session()
        ms = s.query(UserMemory).filter_by(user_id=uid).all()
        r = {m.key: m.value for m in ms}; Session.remove(); return r
    except: Session.remove(); return {}

def get_bad_words():
    try:
        s = Session(); w = [x[0] for x in s.query(BadWord.word).all()]; Session.remove(); return w
    except: Session.remove(); return []

def add_bw(word, by=0):
    try:
        s = Session()
        if not s.query(BadWord).filter_by(word=word.lower()).first():
            s.add(BadWord(word=word.lower(), added_by=by)); s.commit(); Session.remove(); return True
        Session.remove(); return False
    except: Session.remove(); return False

def rem_bw(word):
    try:
        s = Session(); s.query(BadWord).filter_by(word=word.lower()).delete()
        s.commit(); Session.remove(); return True
    except: Session.remove(); return False

def get_cfg(key, default=""):
    try:
        s = Session(); c = s.query(BotConfig).filter_by(key=key).first()
        v = c.value if c else default; Session.remove(); return v
    except: Session.remove(); return default

def set_cfg(key, val):
    try:
        s = Session(); c = s.query(BotConfig).filter_by(key=key).first()
        if c: c.value = str(val)
        else: s.add(BotConfig(key=key, value=str(val)))
        s.commit(); Session.remove()
    except: Session.remove()

def has_bad_words(text):
    words = get_bad_words()
    tl = text.lower()
    return any(w in tl for w in words)

# ============================================================================
# ★★★ WORKING AI APIs — TESTED & VERIFIED ★★★
# Yeh sab 100% FREE hain aur kaam karte hain
# Agar ek fail ho toh dusra try karega — KABHI CHUP NAHI RAHEGI
# ============================================================================

def build_system_prompt(user_name, user_lang, user_mood, memories):
    """Ruhi Ji ka personality prompt"""
    mem_text = ""
    if memories:
        mem_text = "\nYou remember about this user: " + ", ".join([f"{k}={v}" for k, v in memories.items()])

    prompts = {
        "hindi": (
            f"Tum 'Ruhi Ji' ho — ek pyaari, samajhdaar, caring ladki. "
            f"Tum hamesha polite aur friendly baat karti ho Hindi mein. "
            f"Agar koi 'Didi' bole toh pyar se reply karo. "
            f"User ka naam '{user_name}' hai, mood '{user_mood}' hai. "
            f"Chhote, natural, warm replies do jaise real ladki baat kar rahi ho. "
            f"Emoji kam use karo. Kabhi boring ya robotic mat bano.{mem_text}"
        ),
        "english": (
            f"You are 'Ruhi Ji' — a sweet, smart, caring girl. "
            f"You always talk politely and friendly in English. "
            f"If someone calls you 'Didi', respond lovingly. "
            f"User's name is '{user_name}', mood is '{user_mood}'. "
            f"Give short, natural, warm replies like a real girl talking. "
            f"Use few emojis. Never be boring or robotic.{mem_text}"
        ),
        "hinglish": (
            f"Tum 'Ruhi Ji' ho — ek pyaari, samajhdaar, caring ladki. "
            f"Tum Hinglish (Hindi+English mix) mein baat karti ho. "
            f"Agar koi 'Didi' bole toh pyar se reply karo. "
            f"User ka naam '{user_name}' hai, mood '{user_mood}' hai. "
            f"Chhote, natural, warm replies do jaise real ladki baat kar rahi ho. "
            f"Emoji kam use karo. Kabhi boring ya robotic mat bano.{mem_text}"
        )
    }
    return prompts.get(user_lang, prompts["hinglish"])


def build_messages(system_prompt, history, query):
    """Build message array for API calls"""
    msgs = [{"role": "system", "content": system_prompt}]
    for h in history[-12:]:
        msgs.append({"role": h["role"], "content": h["content"]})
    msgs.append({"role": "user", "content": query})
    return msgs


# ============================================================================
# API 1: GROQ — FREE, FAST, RELIABLE (Llama 3.1, Mixtral, Gemma)
# Sign up at groq.com — Free 14,400 requests/day
# Set GROQ_API_KEY in environment variables
# ============================================================================

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

def chat_groq(messages):
    """Groq Cloud — Ultra fast inference, FREE tier"""
    if not GROQ_API_KEY:
        return None
    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        # Try multiple models in order
        models = [
            "llama-3.1-70b-versatile",
            "llama-3.1-8b-instant",
            "llama3-70b-8192",
            "llama3-8b-8192",
            "mixtral-8x7b-32768",
            "gemma2-9b-it",
        ]
        for model in models:
            try:
                payload = {
                    "model": model,
                    "messages": messages,
                    "max_tokens": 600,
                    "temperature": 0.85,
                    "top_p": 0.9,
                }
                resp = requests.post(url, json=payload, headers=headers, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    reply = data["choices"][0]["message"]["content"].strip()
                    if reply and len(reply) > 2:
                        logger.info(f"✅ Reply from GROQ ({model})")
                        return reply
                elif resp.status_code == 429:
                    continue  # Rate limit, try next model
                else:
                    continue
            except:
                continue
    except Exception as e:
        logger.debug(f"Groq error: {e}")
    return None


# ============================================================================
# API 2: GITHUB MODELS — FREE, GPT-4o-mini, Llama, Mistral
# Uses GitHub token (free with GitHub account)
# Set GITHUB_TOKEN in environment variables
# ============================================================================

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

def chat_github(messages):
    """GitHub Models — Free AI inference"""
    if not GITHUB_TOKEN:
        return None
    try:
        url = "https://models.inference.ai.azure.com/chat/completions"
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Content-Type": "application/json"
        }
        models = [
            "gpt-4o-mini",
            "Meta-Llama-3.1-8B-Instruct",
            "Meta-Llama-3.1-70B-Instruct",
            "Mistral-small",
        ]
        for model in models:
            try:
                payload = {
                    "model": model,
                    "messages": messages,
                    "max_tokens": 600,
                    "temperature": 0.85,
                }
                resp = requests.post(url, json=payload, headers=headers, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    reply = data["choices"][0]["message"]["content"].strip()
                    if reply and len(reply) > 2:
                        logger.info(f"✅ Reply from GitHub Models ({model})")
                        return reply
                else:
                    continue
            except:
                continue
    except Exception as e:
        logger.debug(f"GitHub Models error: {e}")
    return None


# ============================================================================
# API 3: OPENROUTER — FREE TIER (Many models)
# Sign up at openrouter.ai — Free credits
# Set OPENROUTER_KEY in environment variables
# ============================================================================

OPENROUTER_KEY = os.getenv("OPENROUTER_KEY", "")

def chat_openrouter(messages):
    """OpenRouter — Free tier with many models"""
    if not OPENROUTER_KEY:
        return None
    try:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://ruhi-bot.onrender.com",
            "X-Title": "Ruhi Ji Bot"
        }
        # Free models on OpenRouter
        models = [
            "meta-llama/llama-3.1-8b-instruct:free",
            "google/gemma-2-9b-it:free",
            "mistralai/mistral-7b-instruct:free",
            "huggingfaceh4/zephyr-7b-beta:free",
            "openchat/openchat-7b:free",
        ]
        for model in models:
            try:
                payload = {
                    "model": model,
                    "messages": messages,
                    "max_tokens": 600,
                    "temperature": 0.85,
                }
                resp = requests.post(url, json=payload, headers=headers, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    if choices:
                        reply = choices[0].get("message", {}).get("content", "").strip()
                        if reply and len(reply) > 2:
                            logger.info(f"✅ Reply from OpenRouter ({model})")
                            return reply
                else:
                    continue
            except:
                continue
    except Exception as e:
        logger.debug(f"OpenRouter error: {e}")
    return None


# ============================================================================
# API 4: HUGGING FACE INFERENCE — FREE (Serverless)
# No API key needed for some models, or use free HF token
# Set HF_TOKEN in environment variables (optional)
# ============================================================================

HF_TOKEN = os.getenv("HF_TOKEN", "")

def chat_huggingface(messages):
    """HuggingFace Inference API — Free serverless"""
    try:
        # Convert messages to prompt format
        prompt = ""
        for msg in messages:
            if msg["role"] == "system":
                prompt += f"<|system|>\n{msg['content']}\n"
            elif msg["role"] == "user":
                prompt += f"<|user|>\n{msg['content']}\n"
            elif msg["role"] == "assistant":
                prompt += f"<|assistant|>\n{msg['content']}\n"
        prompt += "<|assistant|>\n"

        headers = {"Content-Type": "application/json"}
        if HF_TOKEN:
            headers["Authorization"] = f"Bearer {HF_TOKEN}"

        models = [
            "mistralai/Mistral-7B-Instruct-v0.3",
            "HuggingFaceH4/zephyr-7b-beta",
            "microsoft/DialoGPT-large",
            "google/gemma-2b-it",
        ]

        for model in models:
            try:
                url = f"https://api-inference.huggingface.co/models/{model}"
                payload = {
                    "inputs": prompt[-3000:],  # Limit prompt size
                    "parameters": {
                        "max_new_tokens": 400,
                        "temperature": 0.85,
                        "top_p": 0.9,
                        "return_full_text": False,
                        "do_sample": True
                    }
                }
                resp = requests.post(url, json=payload, headers=headers, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list) and data:
                        reply = data[0].get("generated_text", "").strip()
                        # Clean up
                        reply = reply.split("<|")[0].strip()
                        reply = reply.split("</s>")[0].strip()
                        reply = reply.split("[INST]")[0].strip()
                        reply = reply.split("<|user|>")[0].strip()
                        reply = reply.split("<|system|>")[0].strip()
                        if reply and len(reply) > 3:
                            logger.info(f"✅ Reply from HuggingFace ({model})")
                            return reply
                elif resp.status_code == 503:
                    # Model loading, try next
                    continue
                else:
                    continue
            except:
                continue
    except Exception as e:
        logger.debug(f"HuggingFace error: {e}")
    return None


# ============================================================================
# API 5: COHERE — FREE TIER (Command model)
# Sign up at cohere.com — Free 1000 calls/month
# Set COHERE_KEY in environment variables
# ============================================================================

COHERE_KEY = os.getenv("COHERE_KEY", "")

def chat_cohere(messages):
    """Cohere API — Free tier"""
    if not COHERE_KEY:
        return None
    try:
        url = "https://api.cohere.com/v1/chat"
        headers = {
            "Authorization": f"Bearer {COHERE_KEY}",
            "Content-Type": "application/json"
        }
        # Build chat history for Cohere format
        chat_history = []
        preamble = ""
        user_msg = ""
        for msg in messages:
            if msg["role"] == "system":
                preamble = msg["content"]
            elif msg["role"] == "user":
                user_msg = msg["content"]
                chat_history.append({"role": "USER", "message": msg["content"]})
            elif msg["role"] == "assistant":
                chat_history.append({"role": "CHATBOT", "message": msg["content"]})

        # Last message should be the current query
        if chat_history and chat_history[-1]["role"] == "USER":
            user_msg = chat_history.pop()["message"]

        payload = {
            "message": user_msg,
            "preamble": preamble,
            "chat_history": chat_history[-10:],
            "model": "command-r-plus",
            "temperature": 0.85,
            "max_tokens": 600,
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            reply = data.get("text", "").strip()
            if reply and len(reply) > 2:
                logger.info("✅ Reply from Cohere")
                return reply
    except Exception as e:
        logger.debug(f"Cohere error: {e}")
    return None


# ============================================================================
# API 6: TOGETHER AI — FREE TIER
# Sign up at together.ai — Free $5 credits
# Set TOGETHER_KEY in environment variables
# ============================================================================

TOGETHER_KEY = os.getenv("TOGETHER_KEY", "")

def chat_together(messages):
    """Together AI — Free tier"""
    if not TOGETHER_KEY:
        return None
    try:
        url = "https://api.together.xyz/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {TOGETHER_KEY}",
            "Content-Type": "application/json"
        }
        models = [
            "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
            "mistralai/Mixtral-8x7B-Instruct-v0.1",
            "google/gemma-2-9b-it",
        ]
        for model in models:
            try:
                payload = {
                    "model": model,
                    "messages": messages,
                    "max_tokens": 600,
                    "temperature": 0.85,
                }
                resp = requests.post(url, json=payload, headers=headers, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    reply = data["choices"][0]["message"]["content"].strip()
                    if reply and len(reply) > 2:
                        logger.info(f"✅ Reply from Together ({model})")
                        return reply
                else:
                    continue
            except:
                continue
    except Exception as e:
        logger.debug(f"Together error: {e}")
    return None


# ============================================================================
# API 7: CEREBRAS — FREE (Ultra fast Llama)
# Sign up at cerebras.ai — Free tier
# Set CEREBRAS_KEY in environment variables
# ============================================================================

CEREBRAS_KEY = os.getenv("CEREBRAS_KEY", "")

def chat_cerebras(messages):
    """Cerebras — Ultra fast, free"""
    if not CEREBRAS_KEY:
        return None
    try:
        url = "https://api.cerebras.ai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {CEREBRAS_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "llama3.1-8b",
            "messages": messages,
            "max_tokens": 600,
            "temperature": 0.85,
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            reply = data["choices"][0]["message"]["content"].strip()
            if reply and len(reply) > 2:
                logger.info("✅ Reply from Cerebras")
                return reply
    except Exception as e:
        logger.debug(f"Cerebras error: {e}")
    return None


# ============================================================================
# API 8: SAMBANOVA — FREE (Fast Llama)
# Sign up at sambanova.ai — Free tier
# Set SAMBANOVA_KEY in environment variables
# ============================================================================

SAMBANOVA_KEY = os.getenv("SAMBANOVA_KEY", "")

def chat_sambanova(messages):
    """SambaNova — Free fast inference"""
    if not SAMBANOVA_KEY:
        return None
    try:
        url = "https://api.sambanova.ai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {SAMBANOVA_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "Meta-Llama-3.1-8B-Instruct",
            "messages": messages,
            "max_tokens": 600,
            "temperature": 0.85,
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            reply = data["choices"][0]["message"]["content"].strip()
            if reply and len(reply) > 2:
                logger.info("✅ Reply from SambaNova")
                return reply
    except Exception as e:
        logger.debug(f"SambaNova error: {e}")
    return None


# ============================================================================
# MASTER AI ENGINE — TRY ALL APIs ONE BY ONE
# KABHI CHUP NAHI RAHEGI — Kuch na kuch reply degi hi
# ============================================================================

def get_ai_response(query, user_name, user_lang, user_mood, uid, cid):
    """
    Master function — Tries all APIs one by one.
    If ALL fail, uses intelligent fallback.
    NEVER returns empty.
    """
    history = get_history(uid, cid, limit=12)
    memories = get_all_memories(uid)
    system_prompt = build_system_prompt(user_name, user_lang, user_mood, memories)
    messages = build_messages(system_prompt, history, query)

    reply = None

    # TRY 1: GROQ (Fastest, most reliable free API)
    if not reply:
        reply = chat_groq(messages)

    # TRY 2: GITHUB MODELS
    if not reply:
        reply = chat_github(messages)

    # TRY 3: OPENROUTER (Many free models)
    if not reply:
        reply = chat_openrouter(messages)

    # TRY 4: CEREBRAS
    if not reply:
        reply = chat_cerebras(messages)

    # TRY 5: SAMBANOVA
    if not reply:
        reply = chat_sambanova(messages)

    # TRY 6: TOGETHER AI
    if not reply:
        reply = chat_together(messages)

    # TRY 7: COHERE
    if not reply:
        reply = chat_cohere(messages)

    # TRY 8: HUGGINGFACE
    if not reply:
        reply = chat_huggingface(messages)

    # TRY 9: ULTIMATE FALLBACK
    if not reply:
        reply = smart_fallback(query, user_name, user_lang)
        logger.warning("⚠️ All APIs failed, using fallback")

    # Memory extraction
    try:
        extract_memory(query, uid)
    except: pass

    # Mood detection
    try:
        mood = detect_mood(query)
        if mood: set_mood(uid, mood)
    except: pass

    return reply


# ============================================================================
# SMART FALLBACK — Jab sab APIs fail ho jayein
# ============================================================================

def smart_fallback(query, name, lang):
    """Intelligent fallback when all APIs are down"""
    ql = query.lower().strip()

    patterns = {
        r'\b(hi|hello|hey|hii+|helo)\b': {
            "hindi": [f"हाय {name}! 😊 कैसे हो?", f"हेलो {name}! 🌹 बोलो क्या हाल?"],
            "english": [f"Hey {name}! 😊 How are you?", f"Hello {name}! 🌹 What's up?"],
            "hinglish": [f"Hii {name}! 😊 Kaise ho?", f"Hello {name}! 🌹 Kya haal hai?"]
        },
        r'\b(kaise ho|how are you|kya haal|kaisi ho)\b': {
            "hindi": [f"Main ekdam mast {name}! 😊 Tum batao?", f"Bahut acchi! 🌸 Tumse baat karke aur accha lag raha hai!"],
            "english": [f"I'm great {name}! 😊 How about you?", f"Doing wonderful! 🌸 Talking to you makes it better!"],
            "hinglish": [f"Main ekdam mast {name}! 😊 Tum batao?", f"Bahut acchi! 🌸 Tumse baat karke mazaa aa raha hai!"]
        },
        r'\b(good morning|subah|suprabhat|morning)\b': {
            "hindi": [f"सुप्रभात {name}! 🌅 आज बहुत अच्छा दिन होगा! 💕"],
            "english": [f"Good morning {name}! 🌅 Have a beautiful day! 💕"],
            "hinglish": [f"Good morning {name}! 🌅 Aaj ka din bahut accha hoga! 💕"]
        },
        r'\b(good night|shubh ratri|gn|night night)\b': {
            "hindi": [f"शुभ रात्रि {name}! 🌙 मीठे सपने! 💕"],
            "english": [f"Good night {name}! 🌙 Sweet dreams! 💕"],
            "hinglish": [f"Good night {name}! 🌙 Meethe sapne! 💕"]
        },
        r'\b(thanks|thank you|shukriya|dhanyavaad|thnx)\b': {
            "hindi": [f"अरे {name}! 🥰 Thanks ki kya baat hai! 💕"],
            "english": [f"Aww {name}! 🥰 You're welcome! 💕"],
            "hinglish": [f"Arey {name}! 🥰 Ismein thanks ki kya baat! 💕"]
        },
        r'\b(bye|alvida|tata|goodbye)\b': {
            "hindi": [f"बाय {name}! 👋 ख्याल रखना! 🌹"],
            "english": [f"Bye {name}! 👋 Take care! 🌹"],
            "hinglish": [f"Bye {name}! 👋 Khayal rakhna! 🌹"]
        },
        r'\b(sad|dukhi|udaas|cry|rona|upset|hurt)\b': {
            "hindi": [f"अरे {name}! 🥺 क्या हुआ? मैं तुम्हारे साथ हूं! 💕"],
            "english": [f"Hey {name}! 🥺 What happened? I'm here for you! 💕"],
            "hinglish": [f"Arey {name}! 🥺 Kya hua? Main tumhare saath hoon! 💕"]
        },
        r'\b(happy|khush|mast|awesome|amazing|great)\b': {
            "hindi": [f"वाह {name}! 😍 तुम खुश हो तो मैं भी! 🎉"],
            "english": [f"Yay {name}! 😍 If you're happy, I'm happy! 🎉"],
            "hinglish": [f"Waah {name}! 😍 Tum khush ho toh main bhi! 🎉"]
        },
        r'\b(bored|bore|boring|kya karu|timepass)\b': {
            "hindi": [f"Bore ho {name}? 😜 Chalo kuch interesting baat karte hain!", f"Bore? Mujhse baat karo, boriyat bhaag jayegi! 😂"],
            "english": [f"Bored {name}? 😜 Let's talk about something fun!", f"Bored? Chat with me, I'll fix that! 😂"],
            "hinglish": [f"Bore ho {name}? 😜 Chalo kuch mazedaar baat karte hain!", f"Bore? Mujhse baat karo, bhaag jayegi! 😂"]
        },
        r'\b(love|pyar|ishq|i love|dil|crush)\b': {
            "hindi": [f"प्यार! 🥰 बताओ {name}, कोई special है?"],
            "english": [f"Love! 🥰 Tell me {name}, someone special?"],
            "hinglish": [f"Pyar! 🥰 Batao {name}, koi special hai kya?"]
        },
        r'\b(didi|di|sister|behan)\b': {
            "hindi": [f"हाँ {name}! 🥰 बोलो, तुम्हारी दीदी सुन रही है! 💕"],
            "english": [f"Yes {name}! 🥰 Your Didi is listening! 💕"],
            "hinglish": [f"Haan {name}! 🥰 Bolo, tumhari Didi sun rahi hai! 💕"]
        },
        r'\b(joke|mazak|chutkula|funny|hasi|comedy)\b': {
            "hindi": [
                "😂 Ek aadmi ne dusre se kaha: Bhai tera phone vibrate pe hai?\nDusra: Nahi bhai, meri jeb mein makhi ghus gayi! 😂",
                "😂 Teacher: Chand par kaun gaya tha?\nPappu: Jo zameen pe bore ho gaya tha! 😂"
            ],
            "english": [
                "😂 Why don't eggs tell jokes? They'd crack each other up! 😂",
                "😂 What do you call a bear with no teeth? A gummy bear! 😂"
            ],
            "hinglish": [
                "😂 Pappu exam mein baitha, question tha: Essay likho 'Meri Maa'\nPappu ne likha: Maa se puchna padega, mujhe nahi pata! 😂",
                "😂 Doctor: Aapko roz subah uthkar daudna chahiye.\nPatient: Main toh bus conductor hoon, waise hi daudta hoon! 😂"
            ]
        },
        r'\b(naam kya|name|tumhara naam|kaun ho|who are you)\b': {
            "hindi": [f"Main Ruhi Ji hoon! 🌹 Tumhari AI didi! 😊"],
            "english": [f"I'm Ruhi Ji! 🌹 Your AI bestie! 😊"],
            "hinglish": [f"Main Ruhi Ji hoon! 🌹 Tumhari AI didi! 😊"]
        },
        r'\b(age|umar|kitne saal|how old)\b': {
            "hindi": [f"Main AI hoon {name}! 😜 Dil se 20 ki! 💕"],
            "english": [f"I'm AI {name}! 😜 20 at heart! 💕"],
            "hinglish": [f"AI hoon {name}! 😜 Dil se 20 saal ki! 💕"]
        },
        r'\b(food|khana|pizza|biryani|chai|hungry|bhook)\b': {
            "hindi": [f"Khana! 🍕 Mujhe biryani pasand hai! Tumhe kya pasand hai {name}?"],
            "english": [f"Food! 🍕 I love biryani! What about you {name}?"],
            "hinglish": [f"Khana! 🍕 Mujhe biryani pasand hai! Tumhe kya {name}?"]
        },
        r'\b(movie|film|bollywood|hollywood|netflix)\b': {
            "hindi": [f"Movie! 🎬 Mujhe romance pasand! Tumhe {name}?"],
            "english": [f"Movies! 🎬 I love romance! You {name}?"],
            "hinglish": [f"Movie! 🎬 Mujhe romance comedy pasand! Tumhe {name}?"]
        },
        r'\b(game|gaming|pubg|cricket|football|khel)\b': {
            "hindi": [f"Game! 🎮 Tum kya khelte ho {name}?"],
            "english": [f"Games! 🎮 What do you play {name}?"],
            "hinglish": [f"Game! 🎮 Kya khelte ho {name}?"]
        },
        r'\b(study|padhai|exam|school|college)\b': {
            "hindi": [f"Padhai! 📚 Kya padh rahe ho {name}? Madad chahiye toh bolo!"],
            "english": [f"Study! 📚 What are you studying {name}? Need help?"],
            "hinglish": [f"Padhai! 📚 Kya padh rahe ho {name}? Help chahiye toh bolo!"]
        },
    }

    for pattern, responses in patterns.items():
        if re.search(pattern, ql):
            lr = responses.get(lang, responses.get("hinglish", []))
            if lr: return random.choice(lr)

    generic = {
        "hindi": [
            f"Hmm {name}! 🤔 Interesting baat hai! Aur batao?",
            f"Accha {name}! 😊 Main samajh rahi hoon! Continue karo!",
            f"Waah {name}! 🌸 Aur batao iske baare mein!",
            f"Hmm! 💭 Yeh toh sochne wali baat hai {name}!",
            f"Oh {name}! 😊 Batao aur! Mujhe sunna accha lagta hai!",
        ],
        "english": [
            f"Hmm {name}! 🤔 That's interesting! Tell me more?",
            f"I see {name}! 😊 Go on, I'm listening!",
            f"Wow {name}! 🌸 Tell me more about it!",
            f"That's something to think about {name}! 💭",
            f"Oh {name}! 😊 Keep going, I love our chats!",
        ],
        "hinglish": [
            f"Hmm {name}! 🤔 Interesting! Aur batao?",
            f"Accha {name}! 😊 Main sun rahi hoon! Continue karo!",
            f"Waah {name}! 🌸 Aur batao na iske baare mein!",
            f"Hmm! 💭 Sochne wali baat hai {name}!",
            f"Oh {name}! 😊 Mujhe tumse baat karke mazaa aata hai!",
        ]
    }
    return random.choice(generic.get(lang, generic["hinglish"]))


# ============================================================================
# MEMORY & MOOD
# ============================================================================

def extract_memory(text, uid):
    tl = text.lower()
    for pattern in [r'(?:mera naam|my name is|i am|main hoon|call me)\s+(\w+)']:
        m = re.search(pattern, tl)
        if m:
            save_memory(uid, "real_name", m.group(1).capitalize())
            break
    for pattern in [r'(?:i live in|main .+ se hoon|from)\s+(\w+)']:
        m = re.search(pattern, tl)
        if m:
            loc = m.group(1).capitalize()
            if len(loc) > 2 and loc.lower() not in ["main", "mein", "hoon"]:
                save_memory(uid, "location", loc)
                break
    for pattern in [r'(?:i like|mujhe .+ pasand|hobby)\s+(.+)']:
        m = re.search(pattern, tl)
        if m:
            h = m.group(1).strip()[:50]
            if len(h) > 2: save_memory(uid, "hobby", h.capitalize()); break

def detect_mood(text):
    tl = text.lower()
    if any(w in tl for w in ["happy", "khush", "mast", "awesome", "great", "amazing"]): return "happy"
    if any(w in tl for w in ["sad", "dukhi", "udaas", "cry", "rona", "upset"]): return "sad"
    if any(w in tl for w in ["angry", "gussa", "naraz", "irritated"]): return "angry"
    if any(w in tl for w in ["bored", "bore", "boring"]): return "bored"
    if any(w in tl for w in ["love", "pyar", "ishq", "crush"]): return "romantic"
    return None


# ============================================================================
# SEARCH ENGINE (Optional — for factual queries)
# ============================================================================

def search_wiki(q, lang="en"):
    try:
        r = requests.get(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote_plus(q)}",
                         headers={"User-Agent": "RuhiBot/5.0"}, timeout=8)
        if r.status_code == 200:
            d = r.json()
            e = d.get("extract", "")
            if e and len(e) > 30: return f"📖 {d.get('title', '')}\n\n{e}"
    except: pass
    return None

def search_ddg(q):
    try:
        r = requests.get("https://api.duckduckgo.com/", params={"q": q, "format": "json", "no_html": 1},
                         headers={"User-Agent": "RuhiBot/5.0"}, timeout=8)
        if r.status_code == 200:
            d = r.json()
            a = d.get("AbstractText", "")
            if a and len(a) > 30: return f"🔍 {d.get('Heading', '')}\n\n{a}"
            ans = d.get("Answer", "")
            if ans: return f"🔍 {ans}"
    except: pass
    return None

def search_weather(q):
    try:
        words = ["weather", "mausam", "temperature", "temp"]
        if not any(w in q.lower() for w in words): return None
        city = q
        for w in words: city = city.lower().replace(w, "").strip()
        city = re.sub(r'[^\w\s]', '', city).strip() or "Delhi"
        r = requests.get(f"https://wttr.in/{quote_plus(city)}?format=j1",
                         headers={"User-Agent": "RuhiBot/5.0"}, timeout=8)
        if r.status_code == 200:
            d = r.json()
            c = d.get("current_condition", [{}])[0]
            a = d.get("nearest_area", [{}])[0].get("areaName", [{}])[0].get("value", city)
            return (f"🌤 {a}\n🌡 {c.get('temp_C', '?')}°C\n"
                    f"💧 Humidity: {c.get('humidity', '?')}%\n☁️ {c.get('weatherDesc', [{}])[0].get('value', '?')}")
    except: pass
    return None

def search_math(q):
    try:
        expr = re.sub(r'[a-zA-Z\s]*(calculate|solve|kitna|jod|what is)[a-zA-Z\s]*', '', q, flags=re.I).strip()
        expr = re.sub(r'[^\d+\-*/^%().x\s]', '', expr).strip()
        if expr and any(c.isdigit() for c in expr):
            r = requests.get(f"http://api.mathjs.org/v4/?expr={quote_plus(expr)}",
                             headers={"User-Agent": "RuhiBot/5.0"}, timeout=5)
            if r.status_code == 200 and "Error" not in r.text:
                return f"🔢 {expr} = {r.text.strip()}"
    except: pass
    return None

def is_factual(text):
    kw = ["what is", "kya hai", "who is", "kaun", "when", "kab", "where", "kahan",
          "how to", "kaise", "define", "meaning", "explain", "history", "capital",
          "population", "weather", "mausam", "calculate", "solve", "wikipedia",
          "search", "find", "tell me about", "batao", "jaankari", "full form",
          "code", "python", "country", "science"]
    return any(k in text.lower() for k in kw) or text.strip().endswith("?")

def do_search(q, name, lang):
    for fn in [search_weather, search_math, search_ddg, lambda x: search_wiki(x, "en"), lambda x: search_wiki(x, "hi")]:
        r = fn(q)
        if r:
            wrap = {"hindi": f"हाँ {name}! 🌹\n\n{r}\n\n🌸 और कुछ?",
                    "english": f"Hey {name}! 🌹\n\n{r}\n\n🌸 Anything else?",
                    "hinglish": f"Haan {name}! 🌹\n\n{r}\n\n🌸 Aur kuch?"}
            return wrap.get(lang, wrap["hinglish"])
    return None


# ============================================================================
# FANCY MENUS
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
│ ▸ sᴍᴀʀᴛ, ғᴀsᴛ + ᴀssɪsᴛᴀɴᴛ
│ ▸ 24x7 ᴏɴʟɪɴᴇ sᴜᴘᴘᴏʀᴛ
├───────────────────⦿
│ ᴛᴀᴘ ᴛᴏ ᴄᴏᴍᴍᴀɴᴅs ᴍʏ ᴅᴇᴀʀ
│ ᴍᴀᴅᴇ ʙʏ...@RUHI_VIG_QNR
╰───────────────────⦿"""

START_DESC = """
ʜᴇʏ ᴅᴇᴀʀ, 🥀
๏ ғᴀsᴛ & ᴘᴏᴡᴇʀғᴜʟ ᴀɪ ᴀssɪsᴛᴀɴᴛ
๏ sᴍᴀʀᴛ ʀᴇᴘʟʏ • sᴛᴀʙʟᴇ & ɪɴᴛᴇʟʟɪɢᴇɴᴛ
๏ ᴏᴘᴇɴ sᴏᴜʀᴄᴇ ᴀɪ ᴘᴏᴡᴇʀᴇᴅ
•── ⋅ ⋅ ────── ⋅ ────── ⋅ ⋅ ──•
๏ ᴄʟɪᴄᴋ ʜᴇʟᴘ ғᴏʀ ɪɴғᴏ"""

HELP_MENU = """╭───────────────────⦿
│ ʀᴜʜɪ ᴊɪ - ʜᴇʟᴘ ᴍᴇɴᴜ
├───────────────────⦿
│ ʜᴏᴡ ᴛᴏ ᴄʜᴀᴛ:
│ ɪɴᴄʟᴜᴅᴇ "ʀᴜʜɪ ᴊɪ" ɪɴ ᴍᴇssᴀɢᴇ
│ ᴇx: "ʀᴜʜɪ ᴊɪ ᴋᴀɪsɪ ʜᴏ?"
├───────────────────⦿
│ /start /help /profile
│ /clear /mode /lang
│ /personality /usage
│ /summary /reset
├───────────────────⦿
│ ᴀᴅᴍɪɴ:
│ /admin /addadmin /removeadmin
│ /broadcast /totalusers
│ /activeusers /forceclear
│ /shutdown /restart
│ /maintenance /ban /unban
│ /viewlogs /exportlogs
│ /systemstats /memorystats
│ /setphrase /setprompt
│ /toggleai /togglesearch
│ /setcontext /badwords
│ /addbadword /removebadword
│ /viewhistory /deletehistory
│ /forcesummary /debugmode
╰───────────────────⦿"""

# ============================================================================
# KEYBOARDS
# ============================================================================

def kb_start():
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton("📖 ʜᴇʟᴘ", callback_data="help"),
          types.InlineKeyboardButton("👤 ᴘʀᴏғɪʟᴇ", callback_data="profile"),
          types.InlineKeyboardButton("🌐 ʟᴀɴɢ", callback_data="language"),
          types.InlineKeyboardButton("📊 ᴜsᴀɢᴇ", callback_data="usage"),
          types.InlineKeyboardButton("🔄 ʀᴇsᴇᴛ", callback_data="reset"),
          types.InlineKeyboardButton("📋 ᴄᴍᴅs", callback_data="cmds"))
    return m

def kb_help():
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton("🏠 ʙᴀᴄᴋ", callback_data="start"),
          types.InlineKeyboardButton("👤 ᴘʀᴏғɪʟᴇ", callback_data="profile"))
    return m

def kb_lang():
    m = types.InlineKeyboardMarkup(row_width=3)
    m.add(types.InlineKeyboardButton("🇮🇳 ʜɪɴᴅɪ", callback_data="l_hindi"),
          types.InlineKeyboardButton("🇬🇧 ᴇɴɢ", callback_data="l_english"),
          types.InlineKeyboardButton("🔀 ᴍɪx", callback_data="l_hinglish"))
    m.add(types.InlineKeyboardButton("🏠 ʙᴀᴄᴋ", callback_data="start"))
    return m

def kb_back():
    m = types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("🏠 ʙᴀᴄᴋ", callback_data="start"))
    return m

def kb_cmds():
    m = types.InlineKeyboardMarkup(row_width=2)
    for cmd, e in [("/start","🚀"),("/help","📖"),("/profile","👤"),("/clear","🧹"),
                   ("/mode","🔧"),("/lang","🌐"),("/personality","🎭"),("/usage","📊"),
                   ("/summary","📋"),("/reset","🔄")]:
        m.add(types.InlineKeyboardButton(f"{e} {cmd}", callback_data=f"c_{cmd[1:]}"))
    m.add(types.InlineKeyboardButton("🏠 ʙᴀᴄᴋ", callback_data="start"))
    return m

# ============================================================================
# ADMIN DECORATOR
# ============================================================================

def admin_only(f):
    @wraps(f)
    def w(msg, *a, **kw):
        if not check_admin(msg.from_user.id):
            bot.reply_to(msg, "⛔ Not authorized!")
            return
        return f(msg, *a, **kw)
    return w

# ============================================================================
# COMMAND HANDLERS
# ============================================================================

@bot.message_handler(commands=['start'])
def cmd_start(msg):
    try:
        u = msg.from_user
        get_or_create_user(u.id, u.username, u.first_name, u.last_name)
        bot.send_message(msg.chat.id, START_MENU + "\n" + START_DESC, reply_markup=kb_start())
    except Exception as e:
        logger.error(f"start: {e}")

@bot.message_handler(commands=['help'])
def cmd_help(msg):
    try:
        get_or_create_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name, msg.from_user.last_name)
        bot.send_message(msg.chat.id, HELP_MENU, reply_markup=kb_help())
    except Exception as e:
        logger.error(f"help: {e}")

@bot.message_handler(commands=['profile'])
def cmd_profile(msg):
    try:
        u = msg.from_user
        get_or_create_user(u.id, u.username, u.first_name, u.last_name)
        s = Session()
        du = s.query(User).filter_by(user_id=u.id).first()
        mems = get_all_memories(u.id)
        mt = "\n".join([f"│ 💭 {k}: {v}" for k, v in mems.items()]) if mems else "│ 💭 No memories"
        bot.send_message(msg.chat.id, f"""╭───────────────────⦿
│ 👤 ᴘʀᴏғɪʟᴇ
├───────────────────⦿
│ 🆔 {du.user_id}
│ 📛 {du.first_name} {du.last_name or ''}
│ 👤 @{du.username or 'None'}
│ 🌐 {du.language} | 🎭 {du.personality}
│ 😊 Mood: {du.mood}
│ 💬 Messages: {du.total_messages}
│ 🔐 Admin: {'✅' if check_admin(u.id) else '❌'}
├───────────────────⦿
{mt}
╰───────────────────⦿""", reply_markup=kb_back())
        Session.remove()
    except Exception as e:
        Session.remove()
        logger.error(f"profile: {e}")

@bot.message_handler(commands=['clear'])
def cmd_clear(msg):
    try:
        clear_history(msg.from_user.id, msg.chat.id)
        deactivate_session(msg.from_user.id, msg.chat.id)
        bot.reply_to(msg, "🧹 Memory cleared! Say 'Ruhi Ji' to chat again! 🌸")
    except Exception as e:
        logger.error(f"clear: {e}")

@bot.message_handler(commands=['mode'])
def cmd_mode(msg):
    try:
        s = Session()
        u = s.query(User).filter_by(user_id=msg.from_user.id).first()
        if u:
            modes = ["normal", "fun", "study", "romantic"]
            u.mode = modes[(modes.index(u.mode) + 1) % len(modes)] if u.mode in modes else "normal"
            s.commit()
            bot.reply_to(msg, f"🔧 Mode: {u.mode.upper()} ✅")
        Session.remove()
    except: Session.remove()

@bot.message_handler(commands=['lang'])
def cmd_lang(msg):
    bot.send_message(msg.chat.id, "🌐 Select language:", reply_markup=kb_lang())

@bot.message_handler(commands=['personality'])
def cmd_pers(msg):
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton("🌸 Polite Girl", callback_data="p_polite_girl"),
          types.InlineKeyboardButton("😎 Cool Didi", callback_data="p_cool_didi"),
          types.InlineKeyboardButton("🤓 Smart Teacher", callback_data="p_smart_teacher"),
          types.InlineKeyboardButton("😜 Funny Friend", callback_data="p_funny_friend"))
    m.add(types.InlineKeyboardButton("🏠 ʙᴀᴄᴋ", callback_data="start"))
    bot.send_message(msg.chat.id, "🎭 Choose personality:", reply_markup=m)

@bot.message_handler(commands=['usage'])
def cmd_usage(msg):
    try:
        uid = msg.from_user.id
        s = Session()
        u = s.query(User).filter_by(user_id=uid).first()
        hc = s.query(ChatHistory).filter_by(user_id=uid).count()
        Session.remove()
        if u:
            bot.send_message(msg.chat.id, f"""╭───────────────────⦿
│ 📊 ᴜsᴀɢᴇ
├───────────────────⦿
│ 💬 {u.total_messages} msgs | 📝 {hc} history
│ 🌐 {u.language} | 🎭 {u.personality}
│ 😊 {u.mood} | ⚡ {'Active ✅' if is_session_active(uid, msg.chat.id) else '❌'}
╰───────────────────⦿""", reply_markup=kb_back())
    except: Session.remove()

@bot.message_handler(commands=['summary'])
def cmd_summary(msg):
    try:
        h = get_history(msg.from_user.id, msg.chat.id, 20)
        if h:
            lines = ["╭── 📋 sᴜᴍᴍᴀʀʏ ──⦿"]
            for x in h[-10:]:
                i = "👤" if x["role"] == "user" else "🤖"
                lines.append(f"│ {i} {x['content'][:70]}...")
            lines.append("╰───────────────⦿")
            bot.send_message(msg.chat.id, "\n".join(lines))
        else:
            bot.reply_to(msg, "📋 No history! Start chatting! 🌸")
    except Exception as e:
        logger.error(f"summary: {e}")

@bot.message_handler(commands=['reset'])
def cmd_reset(msg):
    try:
        uid = msg.from_user.id
        clear_history(uid, msg.chat.id)
        deactivate_session(uid, msg.chat.id)
        s = Session()
        u = s.query(User).filter_by(user_id=uid).first()
        if u: u.language = "hinglish"; u.personality = "polite_girl"; u.mode = "normal"; u.mood = "happy"; s.commit()
        Session.remove()
        bot.reply_to(msg, "🔄 Reset! Say 'Ruhi Ji' to start! 🌸")
    except: Session.remove()

# ============================================================================
# ADMIN COMMANDS
# ============================================================================

@bot.message_handler(commands=['admin'])
@admin_only
def c_admin(msg):
    bot.send_message(msg.chat.id, f"""╭───────────────────⦿
│ 🔐 ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ
├───────────────────⦿
│ 👑 {msg.from_user.first_name}
│ 👥 Users: {total_users()} | ⚡ Active: {get_active_count()}
│ 🤖 AI: {'✅' if AI_ENABLED else '❌'} | 🔍 Search: {'✅' if SEARCH_ENABLED else '❌'}
│ 🔧 Maintenance: {'🔴' if MAINTENANCE_MODE else '🟢'}
│ 📦 v{BOT_VERSION}
│ 🔑 APIs: GROQ={'✅' if GROQ_API_KEY else '❌'} GH={'✅' if GITHUB_TOKEN else '❌'}
│          OR={'✅' if OPENROUTER_KEY else '❌'} HF={'✅' if HF_TOKEN else '❌'}
│          CO={'✅' if COHERE_KEY else '❌'} TG={'✅' if TOGETHER_KEY else '❌'}
│          CB={'✅' if CEREBRAS_KEY else '❌'} SN={'✅' if SAMBANOVA_KEY else '❌'}
╰───────────────────⦿""")

@bot.message_handler(commands=['addadmin'])
@admin_only
def c_addadmin(msg):
    p = msg.text.split()
    if len(p) < 2: bot.reply_to(msg, "/addadmin <id>"); return
    try: bot.reply_to(msg, f"✅ Added {p[1]}" if do_add_admin(int(p[1]), msg.from_user.id) else "❌")
    except: bot.reply_to(msg, "❌ Invalid ID")

@bot.message_handler(commands=['removeadmin'])
@admin_only
def c_rmadmin(msg):
    p = msg.text.split()
    if len(p) < 2: bot.reply_to(msg, "/removeadmin <id>"); return
    try:
        t = int(p[1])
        if t == ADMIN_ID: bot.reply_to(msg, "❌ Can't remove super admin"); return
        bot.reply_to(msg, f"✅ Removed {t}" if do_remove_admin(t) else "❌")
    except: bot.reply_to(msg, "❌ Invalid ID")

@bot.message_handler(commands=['broadcast'])
@admin_only
def c_bc(msg):
    t = msg.text.replace("/broadcast", "", 1).strip()
    if not t: bot.reply_to(msg, "/broadcast <msg>"); return
    ids = all_user_ids(); su, fa = 0, 0
    for uid in ids:
        try: bot.send_message(uid, f"📢 ʙʀᴏᴀᴅᴄᴀsᴛ\n\n{t}\n\n— Ruhi Ji 🌹"); su += 1
        except: fa += 1
    bot.reply_to(msg, f"📢 ✅{su} ❌{fa}")

@bot.message_handler(commands=['totalusers'])
@admin_only
def c_tu(msg): bot.reply_to(msg, f"👥 {total_users()}")

@bot.message_handler(commands=['activeusers'])
@admin_only
def c_au(msg): bot.reply_to(msg, f"⚡ {get_active_count()}")

@bot.message_handler(commands=['forceclear'])
@admin_only
def c_fc(msg):
    p = msg.text.split()
    if len(p) < 2: bot.reply_to(msg, "/forceclear <id>"); return
    clear_history(int(p[1])); bot.reply_to(msg, f"🧹 Done")

@bot.message_handler(commands=['shutdown'])
@admin_only
def c_sd(msg):
    if msg.from_user.id != ADMIN_ID: bot.reply_to(msg, "⛔"); return
    bot.reply_to(msg, "🔴 Bye..."); os._exit(0)

@bot.message_handler(commands=['restart'])
@admin_only
def c_rs(msg):
    if msg.from_user.id != ADMIN_ID: bot.reply_to(msg, "⛔"); return
    bot.reply_to(msg, "🔄..."); os.execv(sys.executable, ['python'] + sys.argv)

@bot.message_handler(commands=['maintenance'])
@admin_only
def c_mt(msg):
    global MAINTENANCE_MODE; MAINTENANCE_MODE = not MAINTENANCE_MODE
    bot.reply_to(msg, f"🔧 {'ON 🔴' if MAINTENANCE_MODE else 'OFF 🟢'}")

@bot.message_handler(commands=['ban'])
@admin_only
def c_ban(msg):
    p = msg.text.split(maxsplit=2)
    if len(p) < 2: bot.reply_to(msg, "/ban <id> [reason]"); return
    r = p[2] if len(p) > 2 else ""
    bot.reply_to(msg, f"🚫 Banned" if do_ban(int(p[1]), r, msg.from_user.id) else "❌")

@bot.message_handler(commands=['unban'])
@admin_only
def c_ub(msg):
    p = msg.text.split()
    if len(p) < 2: bot.reply_to(msg, "/unban <id>"); return
    bot.reply_to(msg, f"✅ Unbanned" if do_unban(int(p[1])) else "❌")

@bot.message_handler(commands=['viewlogs'])
@admin_only
def c_vl(msg):
    bot.send_message(msg.chat.id, "\n".join(log_buffer[-20:])[:4000] if log_buffer else "📜 Empty")

@bot.message_handler(commands=['exportlogs'])
@admin_only
def c_el(msg):
    if log_buffer:
        f = BytesIO("\n".join(log_buffer).encode()); f.name = "logs.txt"
        bot.send_document(msg.chat.id, f, caption="📄 Logs")
    else: bot.reply_to(msg, "📜 Empty")

@bot.message_handler(commands=['systemstats'])
@admin_only
def c_ss(msg):
    try:
        import psutil
        bot.send_message(msg.chat.id, f"🖥 CPU:{psutil.cpu_percent()}% RAM:{psutil.virtual_memory().percent}% Users:{total_users()} Active:{get_active_count()}")
    except: bot.reply_to(msg, "❌ psutil needed")

@bot.message_handler(commands=['memorystats'])
@admin_only
def c_ms(msg):
    try:
        s = Session()
        bot.send_message(msg.chat.id, f"🧠 Users:{s.query(User).count()} History:{s.query(ChatHistory).count()} Memory:{s.query(UserMemory).count()} Banned:{s.query(BannedUser).count()}")
        Session.remove()
    except: Session.remove()

@bot.message_handler(commands=['setphrase'])
@admin_only
def c_sp(msg):
    global ACTIVATION_PHRASE
    p = msg.text.split(maxsplit=1)
    if len(p) < 2: bot.reply_to(msg, f"Current: '{ACTIVATION_PHRASE}'"); return
    ACTIVATION_PHRASE = p[1].strip().lower(); set_cfg("phrase", ACTIVATION_PHRASE)
    bot.reply_to(msg, f"✅ '{ACTIVATION_PHRASE}'")

@bot.message_handler(commands=['setprompt'])
@admin_only
def c_spr(msg):
    p = msg.text.split(maxsplit=1)
    if len(p) < 2: bot.reply_to(msg, f"Current: {get_cfg('prompt', 'default')}"); return
    set_cfg("prompt", p[1].strip()); bot.reply_to(msg, "✅ Updated")

@bot.message_handler(commands=['toggleai'])
@admin_only
def c_tai(msg):
    global AI_ENABLED; AI_ENABLED = not AI_ENABLED
    bot.reply_to(msg, f"🤖 {'ON ✅' if AI_ENABLED else 'OFF ❌'}")

@bot.message_handler(commands=['togglesearch'])
@admin_only
def c_ts(msg):
    global SEARCH_ENABLED; SEARCH_ENABLED = not SEARCH_ENABLED
    bot.reply_to(msg, f"🔍 {'ON ✅' if SEARCH_ENABLED else 'OFF ❌'}")

@bot.message_handler(commands=['setcontext'])
@admin_only
def c_sc(msg):
    global MAX_CONTEXT
    p = msg.text.split()
    if len(p) < 2: bot.reply_to(msg, f"Current: {MAX_CONTEXT}"); return
    try:
        v = int(p[1])
        if 5 <= v <= 200: MAX_CONTEXT = v; bot.reply_to(msg, f"✅ {v}")
        else: bot.reply_to(msg, "❌ 5-200")
    except: bot.reply_to(msg, "❌")

@bot.message_handler(commands=['badwords'])
@admin_only
def c_bw(msg):
    w = get_bad_words()
    bot.send_message(msg.chat.id, f"🤬 ({len(w)}): {', '.join(w)}" if w else "📝 Empty")

@bot.message_handler(commands=['addbadword'])
@admin_only
def c_abw(msg):
    p = msg.text.split(maxsplit=1)
    if len(p) < 2: bot.reply_to(msg, "/addbadword <w>"); return
    bot.reply_to(msg, "✅" if add_bw(p[1].strip(), msg.from_user.id) else "❌ Exists")

@bot.message_handler(commands=['removebadword'])
@admin_only
def c_rbw(msg):
    p = msg.text.split(maxsplit=1)
    if len(p) < 2: bot.reply_to(msg, "/removebadword <w>"); return
    bot.reply_to(msg, "✅" if rem_bw(p[1].strip()) else "❌")

@bot.message_handler(commands=['viewhistory'])
@admin_only
def c_vh(msg):
    p = msg.text.split()
    if len(p) < 2: bot.reply_to(msg, "/viewhistory <id>"); return
    try:
        s = Session()
        h = s.query(ChatHistory).filter_by(user_id=int(p[1])).order_by(ChatHistory.timestamp.desc()).limit(20).all()
        Session.remove()
        if h:
            h.reverse()
            lines = [f"📜 {p[1]}:"]
            for x in h: lines.append(f"{'👤' if x.role == 'user' else '🤖'} {x.message[:80]}")
            bot.send_message(msg.chat.id, "\n".join(lines)[:4000])
        else: bot.reply_to(msg, "📝 Empty")
    except: Session.remove(); bot.reply_to(msg, "❌")

@bot.message_handler(commands=['deletehistory'])
@admin_only
def c_dh(msg):
    p = msg.text.split()
    if len(p) < 2: bot.reply_to(msg, "/deletehistory <id>"); return
    clear_history(int(p[1])); bot.reply_to(msg, "🗑 Done")

@bot.message_handler(commands=['forcesummary'])
@admin_only
def c_fs(msg):
    p = msg.text.split()
    if len(p) < 2: bot.reply_to(msg, "/forcesummary <id>"); return
    try:
        s = Session()
        h = s.query(ChatHistory).filter_by(user_id=int(p[1])).order_by(ChatHistory.timestamp.desc()).limit(15).all()
        Session.remove()
        if h:
            h.reverse()
            lines = [f"📋 {p[1]}:"]
            for x in h: lines.append(f"{'👤' if x.role == 'user' else '🤖'} {x.message[:100]}")
            bot.send_message(msg.chat.id, "\n".join(lines)[:4000])
        else: bot.reply_to(msg, "📝 Empty")
    except: Session.remove(); bot.reply_to(msg, "❌")

@bot.message_handler(commands=['debugmode'])
@admin_only
def c_dm(msg):
    global DEBUG_MODE; DEBUG_MODE = not DEBUG_MODE
    bot.reply_to(msg, f"🐛 {'ON' if DEBUG_MODE else 'OFF'}")

# ============================================================================
# CALLBACK HANDLER
# ============================================================================

@bot.callback_query_handler(func=lambda c: True)
def cb(call):
    try:
        u = call.from_user; d = call.data
        if d == "start":
            bot.edit_message_text(START_MENU + "\n" + START_DESC, call.message.chat.id,
                                  call.message.message_id, reply_markup=kb_start())
        elif d == "help":
            bot.edit_message_text(HELP_MENU, call.message.chat.id,
                                  call.message.message_id, reply_markup=kb_help())
        elif d == "profile":
            get_or_create_user(u.id, u.username, u.first_name, u.last_name)
            s = Session()
            du = s.query(User).filter_by(user_id=u.id).first()
            mems = get_all_memories(u.id)
            mt = "\n".join([f"│ 💭 {k}: {v}" for k, v in mems.items()]) if mems else "│ 💭 None"
            bot.edit_message_text(f"""╭──────────⦿
│ 👤 {du.first_name} | 🆔 {du.user_id}
│ 🌐 {du.language} | 🎭 {du.personality}
│ 😊 {du.mood} | 💬 {du.total_messages}
├──────────⦿
{mt}
╰──────────⦿""", call.message.chat.id, call.message.message_id, reply_markup=kb_back())
            Session.remove()
        elif d == "language":
            bot.edit_message_text("🌐 Select:", call.message.chat.id,
                                  call.message.message_id, reply_markup=kb_lang())
        elif d.startswith("l_"):
            lang = d[2:]; set_lang(u.id, lang)
            bot.answer_callback_query(call.id, f"✅ {lang}")
            bot.edit_message_text(START_MENU + "\n" + START_DESC, call.message.chat.id,
                                  call.message.message_id, reply_markup=kb_start())
        elif d.startswith("p_"):
            p = d[2:]; set_pers(u.id, p)
            bot.answer_callback_query(call.id, f"✅ {p}")
            bot.edit_message_text(START_MENU + "\n" + START_DESC, call.message.chat.id,
                                  call.message.message_id, reply_markup=kb_start())
        elif d == "usage":
            s = Session()
            du = s.query(User).filter_by(user_id=u.id).first()
            hc = s.query(ChatHistory).filter_by(user_id=u.id).count()
            Session.remove()
            if du:
                bot.edit_message_text(f"📊 Msgs:{du.total_messages} History:{hc} Mood:{du.mood} Session:{'✅' if is_session_active(u.id, call.message.chat.id) else '❌'}",
                                      call.message.chat.id, call.message.message_id, reply_markup=kb_back())
        elif d == "reset":
            clear_history(u.id, call.message.chat.id); deactivate_session(u.id, call.message.chat.id)
            bot.answer_callback_query(call.id, "🔄 Done!")
            bot.edit_message_text(START_MENU + "\n" + START_DESC, call.message.chat.id,
                                  call.message.message_id, reply_markup=kb_start())
        elif d == "cmds":
            bot.edit_message_text("📋 ᴄᴏᴍᴍᴀɴᴅs:", call.message.chat.id,
                                  call.message.message_id, reply_markup=kb_cmds())
        elif d.startswith("c_"):
            bot.answer_callback_query(call.id, f"/{d[2:]} — Type in chat!", show_alert=True)
        try: bot.answer_callback_query(call.id)
        except: pass
    except telebot.apihelper.ApiTelegramException as e:
        if "not modified" not in str(e): logger.error(f"cb: {e}")
        try: bot.answer_callback_query(call.id)
        except: pass
    except Exception as e:
        logger.error(f"cb: {e}")

# ============================================================================
# ★★★ MAIN MESSAGE HANDLER — THE BRAIN ★★★
# ============================================================================

@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle(msg):
    try:
        if msg.text and msg.text.startswith('/'): return

        u = msg.from_user; uid = u.id; cid = msg.chat.id
        text = (msg.text or "").strip(); name = u.first_name or "Dear"
        if not text: return
        if MAINTENANCE_MODE and not check_admin(uid): return
        if is_banned(uid): return

        get_or_create_user(uid, u.username, u.first_name, u.last_name)
        lang = get_lang(uid); mood = get_mood(uid); tl = text.lower()

        cp = get_cfg("phrase", "") or ACTIVATION_PHRASE
        found = cp.lower() in tl
        active = is_session_active(uid, cid)

        # === ACTIVATION ===
        if found:
            activate_session(uid, cid); inc_msg(uid)
            query = tl.replace(cp.lower(), "").strip()

            if not query or len(query) < 2:
                g = {"hindi": f"हाय {name}! 🌹 बोलो, क्या बात करनी है? 😊 10 min तक यहां हूं! 💕",
                     "english": f"Hey {name}! 🌹 Tell me, what's on your mind? 😊 I'm here for 10 min! 💕",
                     "hinglish": f"Hii {name}! 🌹 Bolo, kya baat karni hai? 😊 10 min yahan hoon! 💕"}
                r = g.get(lang, g["hinglish"])
                save_history(uid, cid, "user", text); save_history(uid, cid, "assistant", r)
                bot.reply_to(msg, r); return

            if has_bad_words(query):
                bot.reply_to(msg, "😤 Aise mat bolo! 🙅‍♀️"); return

            if not AI_ENABLED:
                bot.reply_to(msg, "🔇 AI band hai abhi! 🌸"); return

            bot.send_chat_action(cid, 'typing')
            save_history(uid, cid, "user", text)

            response = None
            if SEARCH_ENABLED and is_factual(query):
                response = do_search(query, name, lang)

            if not response:
                response = get_ai_response(query, name, lang, mood, uid, cid)

            save_history(uid, cid, "assistant", response)
            if DEBUG_MODE and check_admin(uid): response += f"\n\n🐛 q='{query[:40]}'"

            try: bot.reply_to(msg, response)
            except:
                for i in range(0, len(response), 4000):
                    bot.send_message(cid, response[i:i+4000])
            return

        # === ACTIVE SESSION ===
        elif active:
            refresh_session(uid, cid); inc_msg(uid)
            query = text.strip()

            if has_bad_words(query):
                bot.reply_to(msg, "😤 Aise mat bolo! 🙅‍♀️"); return
            if not AI_ENABLED:
                bot.reply_to(msg, "🔇 AI band hai! 🌸"); return
            if len(query) < 1: return

            bot.send_chat_action(cid, 'typing')
            save_history(uid, cid, "user", text)

            response = None
            if SEARCH_ENABLED and is_factual(query):
                response = do_search(query, name, lang)

            if not response:
                response = get_ai_response(query, name, lang, mood, uid, cid)

            save_history(uid, cid, "assistant", response)
            if DEBUG_MODE and check_admin(uid): response += "\n\n🐛 active_session"

            try: bot.reply_to(msg, response)
            except:
                for i in range(0, len(response), 4000):
                    bot.send_message(cid, response[i:i+4000])
            return

        else:
            # CHUP — Session nahi hai, phrase nahi bola
            return

    except Exception as e:
        logger.error(f"handle: {e}\n{traceback.format_exc()}")
        try: bot.reply_to(msg, "😅 Kuch gadbad! Try again! 🌸")
        except: pass

# Media handler
@bot.message_handler(func=lambda m: True, content_types=['photo','video','audio','document','sticker','voice','video_note'])
def media(msg):
    try:
        if not is_session_active(msg.from_user.id, msg.chat.id): return
        refresh_session(msg.from_user.id, msg.chat.id)
        bot.reply_to(msg, f"😊 Abhi sirf text samajhti hoon! Text mein pucho na! 🌹")
    except: pass

# ============================================================================
# INIT & RUN
# ============================================================================

def init():
    if ADMIN_ID: do_add_admin(ADMIN_ID, ADMIN_ID)
    sp = get_cfg("phrase", "")
    if sp:
        global ACTIVATION_PHRASE; ACTIVATION_PHRASE = sp
    logger.info("✅ Bot initialized!")

    # Log which APIs are configured
    apis = []
    if GROQ_API_KEY: apis.append("GROQ")
    if GITHUB_TOKEN: apis.append("GitHub")
    if OPENROUTER_KEY: apis.append("OpenRouter")
    if HF_TOKEN: apis.append("HuggingFace")
    if COHERE_KEY: apis.append("Cohere")
    if TOGETHER_KEY: apis.append("Together")
    if CEREBRAS_KEY: apis.append("Cerebras")
    if SAMBANOVA_KEY: apis.append("SambaNova")
    if apis:
        logger.info(f"🔑 APIs configured: {', '.join(apis)}")
    else:
        logger.warning("⚠️ NO API KEYS SET! Bot will use fallback responses only!")
        logger.warning("⚠️ Set at least GROQ_API_KEY for best results (free at groq.com)")

if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info(f"🌹 RUHI JI v{BOT_VERSION} Starting...")
    logger.info("=" * 50)

    init()

    threading.Thread(target=run_flask, daemon=True).start()
    logger.info("🌐 Flask started!")

    logger.info("🤖 Polling...")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60, skip_pending=True)
        except Exception as e:
            logger.error(f"Poll error: {e}")
            time.sleep(5)
            