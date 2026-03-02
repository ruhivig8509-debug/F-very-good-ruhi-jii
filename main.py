# ============================================================================
# main.py — RUHI JI v8.0 — ULTRA ADVANCED EDITION
# GROQ Llama 3.3 70B | Smart Reply/Mention/Mood Detection
# Group Memory (30) | Private Memory (80) | Relationship Tracking
# Real Girl Persona | Time Aware | Anti-Spam | Games | Reminders
# ============================================================================

import os, sys, time, logging, threading, datetime, re, random, traceback, json, hashlib
from functools import wraps
from collections import defaultdict

import telebot
from telebot import types
from flask import Flask
from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, DateTime, BigInteger, Float
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session
import requests

# ============================================================================
# CONFIG
# ============================================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///ruhi.db")
PORT = int(os.getenv("PORT", 5000))

ACTIVATION_PHRASE = "ruhi ji"
SESSION_TIMEOUT = 600
GROUP_HISTORY_LIMIT = 30
PRIVATE_HISTORY_LIMIT = 80
RATE_LIMIT_SECONDS = 2
MAX_RESPONSE_TOKENS = 600

# Render PostgreSQL fix
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("RuhiJi")

# ============================================================================
# DATABASE
# ============================================================================

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL, echo=False, pool_size=15, max_overflow=25,
                           pool_pre_ping=True, pool_recycle=300)

Base = declarative_base()
Session = scoped_session(sessionmaker(bind=engine))


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(255), default="")
    first_name = Column(String(255), default="")
    last_name = Column(String(255), default="")
    language = Column(String(20), default="hinglish")
    personality = Column(String(50), default="polite_girl")
    total_messages = Column(Integer, default=0)
    is_banned = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    mood = Column(String(50), default="neutral")
    relationship_score = Column(Float, default=0.0)
    last_mood = Column(String(50), default="neutral")
    streak_days = Column(Integer, default=0)
    last_streak_date = Column(String(20), default="")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_active = Column(DateTime, default=datetime.datetime.utcnow)


class GroupHistory(Base):
    __tablename__ = "group_history"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False)
    user_name = Column(String(255), default="")
    role = Column(String(20), default="user")
    message = Column(Text, default="")
    mood = Column(String(50), default="neutral")
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)


class PrivateHistory(Base):
    __tablename__ = "private_history"
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    role = Column(String(20), default="user")
    message = Column(Text, default="")
    mood = Column(String(50), default="neutral")
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)


class UserMemory(Base):
    __tablename__ = "user_memory"
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    key = Column(String(255), nullable=False)
    value = Column(Text, default="")
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)


class GroupConfig(Base):
    """Per-group settings"""
    __tablename__ = "group_config"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, unique=True, nullable=False, index=True)
    group_name = Column(String(500), default="")
    welcome_enabled = Column(Boolean, default=True)
    auto_reply = Column(Boolean, default=True)
    language = Column(String(20), default="hinglish")
    total_messages = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Reminder(Base):
    __tablename__ = "reminders"
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    chat_id = Column(BigInteger, nullable=False)
    reminder_text = Column(Text, default="")
    remind_at = Column(DateTime, nullable=False)
    is_done = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class AdminList(Base):
    __tablename__ = "admin_list"
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, unique=True, nullable=False)
    added_by = Column(BigInteger, default=0)


class BannedUser(Base):
    __tablename__ = "banned_users"
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, unique=True, nullable=False)
    reason = Column(Text, default="")
    banned_by = Column(BigInteger, default=0)


class BadWord(Base):
    __tablename__ = "bad_words"
    id = Column(Integer, primary_key=True)
    word = Column(String(255), unique=True, nullable=False)


class BotConfig(Base):
    __tablename__ = "bot_config"
    id = Column(Integer, primary_key=True)
    key = Column(String(255), unique=True, nullable=False)
    value = Column(Text, default="")


try:
    Base.metadata.create_all(engine)
    logger.info("✅ Database ready")
except Exception as e:
    logger.error(f"DB: {e}")

# ============================================================================
# FLASK
# ============================================================================

app = Flask(__name__)

@app.route("/")
def home():
    return "<h1>🌹 Ruhi Ji v8.0 Ultra Running!</h1>"

@app.route("/health")
def health():
    return {"status": "ok", "version": "8.0", "uptime": time.time()}, 200

def run_flask():
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)

# ============================================================================
# BOT
# ============================================================================

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None, threaded=True)

# Get bot info for mention detection
BOT_INFO = None
BOT_USERNAME = ""
try:
    BOT_INFO = bot.get_me()
    BOT_USERNAME = BOT_INFO.username.lower() if BOT_INFO.username else ""
    logger.info(f"🤖 Bot: @{BOT_USERNAME}")
except:
    logger.warning("⚠️ Could not get bot info")

# ============================================================================
# RATE LIMITER
# ============================================================================

rate_limits = {}
rate_lock = threading.Lock()

def check_rate(uid):
    """Returns True if user can send, False if rate limited"""
    with rate_lock:
        now = time.time()
        if uid in rate_limits:
            if now - rate_limits[uid] < RATE_LIMIT_SECONDS:
                return False
        rate_limits[uid] = now
        return True

def cleanup_rates():
    while True:
        try:
            with rate_lock:
                now = time.time()
                for k in [k for k, v in rate_limits.items() if now - v > 60]:
                    del rate_limits[k]
        except:
            pass
        time.sleep(120)

threading.Thread(target=cleanup_rates, daemon=True).start()

# ============================================================================
# SESSIONS
# ============================================================================

sessions = {}
slock = threading.Lock()

def activate(cid):
    with slock:
        sessions[cid] = time.time()

def is_active(cid):
    with slock:
        if cid in sessions and time.time() - sessions[cid] < SESSION_TIMEOUT:
            return True
        sessions.pop(cid, None)
        return False

def refresh(cid):
    with slock:
        if cid in sessions:
            sessions[cid] = time.time()

def deactivate(cid):
    with slock:
        sessions.pop(cid, None)

def active_count():
    with slock:
        now = time.time()
        return sum(1 for v in sessions.values() if now - v < SESSION_TIMEOUT)

def cleanup_sessions():
    while True:
        try:
            with slock:
                now = time.time()
                for k in [k for k, v in sessions.items() if now - v >= SESSION_TIMEOUT]:
                    del sessions[k]
        except:
            pass
        time.sleep(60)

threading.Thread(target=cleanup_sessions, daemon=True).start()

# ============================================================================
# MOOD DETECTION ENGINE
# ============================================================================

MOOD_PATTERNS = {
    "sad": {
        "words": ["sad", "dukhi", "ro raha", "ro rahi", "crying", "udaas", "akela",
                  "akeli", "lonely", "depressed", "upset", "hurt", "dard", "toot",
                  "khatam", "breakup", "miss", "yaad", "rona", "aansu", "pain",
                  "tanha", "feel low", "nahi ho raha", "thak gaya", "thak gayi",
                  "haar gaya", "haar gayi", "mar jana", "koi nahi", "kuch nahi",
                  "worst", "terrible", "hopeless", "😢", "😭", "💔", "😞", "😔"],
        "emoji": "😢",
        "response_tone": "caring_soft"
    },
    "happy": {
        "words": ["khush", "happy", "maza", "great", "awesome", "amazing", "best",
                  "love", "pyar", "acha", "accha", "badhiya", "mast", "superb",
                  "fantastic", "wonderful", "excited", "yay", "haha", "lol",
                  "😂", "😄", "😊", "🥳", "🎉", "❤️", "😍", "🤩", "pass ho gaya",
                  "mil gaya", "ho gaya", "finally", "won", "jeeta", "jeet"],
        "emoji": "😊",
        "response_tone": "enthusiastic"
    },
    "angry": {
        "words": ["gussa", "angry", "irritate", "pagal", "stupid", "idiot",
                  "hate", "nafrat", "chup", "shut up", "bakwas", "nonsense",
                  "bewakoof", "gadha", "ullu", "mad", "frustrated", "annoyed",
                  "😠", "😡", "🤬", "💢", "fed up", "tang", "pareshan"],
        "emoji": "😤",
        "response_tone": "calm_caring"
    },
    "flirty": {
        "words": ["cutie", "beautiful", "sundar", "hot", "sexy", "meri jaan",
                  "baby", "babe", "darling", "sweetheart", "i love you",
                  "pyar karta", "pyar karti", "date", "gf", "girlfriend",
                  "dil", "heart", "kiss", "hug", "😘", "😏", "🥰", "💋",
                  "crush", "propose", "shaadi"],
        "emoji": "😊",
        "response_tone": "sweet_deflect"
    },
    "excited": {
        "words": ["omg", "oh my god", "wow", "kya baat", "amazing", "unbelievable",
                  "incredible", "fire", "lit", "🔥", "💯", "insane", "crazy",
                  "best thing", "guess what", "suno", "sunoo", "breaking"],
        "emoji": "🤩",
        "response_tone": "match_energy"
    },
    "bored": {
        "words": ["bore", "bored", "boring", "kuch nahi", "nothing", "timepass",
                  "kya karu", "kya karun", "free", "vella", "velli", "alas",
                  "😴", "🥱", "so bored", "kuch batao"],
        "emoji": "😜",
        "response_tone": "fun_energetic"
    },
    "confused": {
        "words": ["confused", "samajh nahi", "kya hua", "kaise", "how", "why",
                  "kyun", "matlab", "meaning", "explain", "🤔", "❓", "what",
                  "pata nahi", "idea nahi"],
        "emoji": "🤔",
        "response_tone": "helpful_clear"
    },
    "grateful": {
        "words": ["thank", "thanks", "shukriya", "dhanyawad", "thnx", "ty",
                  "grateful", "appreciate", "🙏", "meherbani", "god bless"],
        "emoji": "🌹",
        "response_tone": "warm_humble"
    }
}


def detect_mood(text):
    """Detect user's mood from text"""
    tl = text.lower()
    scores = {}
    for mood, data in MOOD_PATTERNS.items():
        score = sum(1 for w in data["words"] if w in tl)
        if score > 0:
            scores[mood] = score
    if scores:
        return max(scores, key=scores.get)
    return "neutral"


def get_mood_instruction(mood):
    """Get tone instruction based on mood"""
    instructions = {
        "sad": "User seems SAD. Be extra caring, gentle, supportive. Ask what happened. Show you care deeply. Don't be overly cheerful.",
        "happy": "User is HAPPY! Match their excitement! Celebrate with them! Be enthusiastic!",
        "angry": "User seems ANGRY/FRUSTRATED. Be calm, understanding. Don't argue. Listen first, then gently help.",
        "flirty": "User is being flirty. Be sweet but maintain boundaries. Redirect playfully. Don't encourage or discourage too much.",
        "excited": "User is EXCITED! Match their energy! Be equally pumped! Ask for details!",
        "bored": "User is BORED. Suggest fun things, start interesting topics, play games, tell jokes!",
        "confused": "User is CONFUSED. Be patient, explain clearly, ask what they need help with.",
        "grateful": "User is saying THANKS. Be warm, humble, tell them you're always here.",
        "neutral": ""
    }
    return instructions.get(mood, "")


# ============================================================================
# TIME AWARENESS
# ============================================================================

def get_time_context():
    """Get current time context in IST"""
    try:
        ist = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
        hour = ist.hour
        day_name = ist.strftime("%A")
        date_str = ist.strftime("%d %B %Y")

        if 5 <= hour < 12:
            period = "morning"
            greeting = "Good morning"
            hindi_greeting = "Subah subah"
        elif 12 <= hour < 17:
            period = "afternoon"
            greeting = "Good afternoon"
            hindi_greeting = "Dopahar ko"
        elif 17 <= hour < 21:
            period = "evening"
            greeting = "Good evening"
            hindi_greeting = "Shaam ko"
        else:
            period = "night"
            greeting = "Good night"
            hindi_greeting = "Itni raat ko"

        return {
            "hour": hour,
            "period": period,
            "greeting": greeting,
            "hindi_greeting": hindi_greeting,
            "day": day_name,
            "date": date_str,
            "ist_time": ist.strftime("%I:%M %p"),
            "is_weekend": day_name in ["Saturday", "Sunday"]
        }
    except:
        return {"hour": 12, "period": "afternoon", "greeting": "Hey",
                "hindi_greeting": "Hey", "day": "Monday", "date": "",
                "ist_time": "", "is_weekend": False}


# ============================================================================
# RELATIONSHIP SCORE
# ============================================================================

def update_relationship(uid, points=1):
    """Increase relationship score — more chatting = closer friend"""
    try:
        s = Session()
        u = s.query(User).filter_by(user_id=uid).first()
        if u:
            u.relationship_score = min(100.0, (u.relationship_score or 0) + points)

            # Streak system
            today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
            if u.last_streak_date != today:
                yesterday = (datetime.datetime.utcnow() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
                if u.last_streak_date == yesterday:
                    u.streak_days = (u.streak_days or 0) + 1
                else:
                    u.streak_days = 1
                u.last_streak_date = today

            s.commit()
        Session.remove()
    except:
        Session.remove()


def get_relationship_level(uid):
    """Get relationship level name"""
    try:
        s = Session()
        u = s.query(User).filter_by(user_id=uid).first()
        score = u.relationship_score if u else 0
        streak = u.streak_days if u else 0
        Session.remove()

        if score >= 80:
            return "bestie", "💕 Bestie", streak
        elif score >= 60:
            return "close_friend", "💛 Close Friend", streak
        elif score >= 40:
            return "good_friend", "💚 Good Friend", streak
        elif score >= 20:
            return "friend", "💙 Friend", streak
        elif score >= 5:
            return "known", "🤝 Known", streak
        else:
            return "new", "👋 New", streak
    except:
        Session.remove()
        return "new", "👋 New", 0


# ============================================================================
# DB FUNCTIONS
# ============================================================================

def get_user(uid, uname="", fname="", lname=""):
    try:
        s = Session()
        u = s.query(User).filter_by(user_id=uid).first()
        if not u:
            u = User(user_id=uid, username=uname or "", first_name=fname or "",
                     last_name=lname or "", is_admin=(uid == ADMIN_ID))
            s.add(u)
            s.commit()
        else:
            if uname: u.username = uname
            if fname: u.first_name = fname
            if lname: u.last_name = lname
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
        if u:
            u.total_messages = (u.total_messages or 0) + 1
            u.last_active = datetime.datetime.utcnow()
            s.commit()
        Session.remove()
    except:
        Session.remove()


def update_mood(uid, mood):
    try:
        s = Session()
        u = s.query(User).filter_by(user_id=uid).first()
        if u:
            u.last_mood = u.mood or "neutral"
            u.mood = mood
            s.commit()
        Session.remove()
    except:
        Session.remove()


def get_user_info(uid):
    try:
        s = Session()
        u = s.query(User).filter_by(user_id=uid).first()
        if u:
            info = {
                "name": u.first_name or "",
                "username": u.username or "",
                "total_msgs": u.total_messages or 0,
                "mood": u.mood or "neutral",
                "last_mood": u.last_mood or "neutral",
                "relationship_score": u.relationship_score or 0,
                "streak": u.streak_days or 0,
                "joined": u.created_at.strftime("%d %b %Y") if u.created_at else "unknown"
            }
            Session.remove()
            return info
        Session.remove()
        return {}
    except:
        Session.remove()
        return {}


# === GROUP CONFIG ===

def get_group_config(cid, name=""):
    try:
        s = Session()
        gc = s.query(GroupConfig).filter_by(chat_id=cid).first()
        if not gc:
            gc = GroupConfig(chat_id=cid, group_name=name)
            s.add(gc)
            s.commit()
        elif name and name != gc.group_name:
            gc.group_name = name
            s.commit()
        Session.remove()
        return gc
    except:
        Session.remove()
        return None


def inc_group_msg(cid):
    try:
        s = Session()
        gc = s.query(GroupConfig).filter_by(chat_id=cid).first()
        if gc:
            gc.total_messages = (gc.total_messages or 0) + 1
            s.commit()
        Session.remove()
    except:
        Session.remove()


# === GROUP HISTORY — 30 messages ===

def save_group_msg(cid, uid, user_name, role, msg_text, mood="neutral"):
    try:
        s = Session()
        s.add(GroupHistory(
            chat_id=cid, user_id=uid, user_name=user_name,
            role=role, message=msg_text[:4000], mood=mood,
            timestamp=datetime.datetime.utcnow()
        ))
        s.commit()
        cnt = s.query(GroupHistory).filter_by(chat_id=cid).count()
        if cnt > GROUP_HISTORY_LIMIT:
            old = s.query(GroupHistory).filter_by(chat_id=cid)\
                .order_by(GroupHistory.timestamp.asc()).limit(cnt - GROUP_HISTORY_LIMIT).all()
            for o in old:
                s.delete(o)
            s.commit()
        Session.remove()
    except:
        Session.remove()


def get_group_hist(cid):
    try:
        s = Session()
        h = s.query(GroupHistory).filter_by(chat_id=cid)\
            .order_by(GroupHistory.timestamp.asc()).all()
        result = []
        for x in h:
            if x.role == "user":
                result.append({"role": "user", "content": f"[{x.user_name}]: {x.message}"})
            else:
                result.append({"role": "assistant", "content": x.message})
        Session.remove()
        return result
    except:
        Session.remove()
        return []


def clear_group_hist(cid):
    try:
        s = Session()
        s.query(GroupHistory).filter_by(chat_id=cid).delete()
        s.commit()
        Session.remove()
    except:
        Session.remove()


def get_group_stats(cid):
    """Get group message stats — who talks most"""
    try:
        s = Session()
        h = s.query(GroupHistory).filter_by(chat_id=cid, role="user").all()
        stats = {}
        for x in h:
            name = x.user_name or "Unknown"
            stats[name] = stats.get(name, 0) + 1
        Session.remove()
        return dict(sorted(stats.items(), key=lambda x: x[1], reverse=True))
    except:
        Session.remove()
        return {}


# === PRIVATE HISTORY — 80 messages ===

def save_private_msg(uid, role, msg_text, mood="neutral"):
    try:
        s = Session()
        s.add(PrivateHistory(
            user_id=uid, role=role, message=msg_text[:4000], mood=mood,
            timestamp=datetime.datetime.utcnow()
        ))
        s.commit()
        cnt = s.query(PrivateHistory).filter_by(user_id=uid).count()
        if cnt > PRIVATE_HISTORY_LIMIT:
            old = s.query(PrivateHistory).filter_by(user_id=uid)\
                .order_by(PrivateHistory.timestamp.asc()).limit(cnt - PRIVATE_HISTORY_LIMIT).all()
            for o in old:
                s.delete(o)
            s.commit()
        Session.remove()
    except:
        Session.remove()


def get_private_hist(uid):
    try:
        s = Session()
        h = s.query(PrivateHistory).filter_by(user_id=uid)\
            .order_by(PrivateHistory.timestamp.asc()).all()
        result = [{"role": x.role, "content": x.message} for x in h]
        Session.remove()
        return result
    except:
        Session.remove()
        return []


def clear_private_hist(uid):
    try:
        s = Session()
        s.query(PrivateHistory).filter_by(user_id=uid).delete()
        s.commit()
        Session.remove()
    except:
        Session.remove()


# === MEMORY ===

def save_mem(uid, k, v):
    try:
        s = Session()
        m = s.query(UserMemory).filter_by(user_id=uid, key=k).first()
        if m:
            m.value = v
            m.updated_at = datetime.datetime.utcnow()
        else:
            s.add(UserMemory(user_id=uid, key=k, value=v,
                            updated_at=datetime.datetime.utcnow()))
        s.commit()
        Session.remove()
    except:
        Session.remove()


def get_mems(uid):
    try:
        s = Session()
        ms = s.query(UserMemory).filter_by(user_id=uid).all()
        r = {m.key: m.value for m in ms}
        Session.remove()
        return r
    except:
        Session.remove()
        return {}


def clear_mems(uid):
    try:
        s = Session()
        s.query(UserMemory).filter_by(user_id=uid).delete()
        s.commit()
        Session.remove()
    except:
        Session.remove()


# === REMINDERS ===

def add_reminder(uid, cid, text, remind_at):
    try:
        s = Session()
        s.add(Reminder(user_id=uid, chat_id=cid, reminder_text=text,
                       remind_at=remind_at))
        s.commit()
        Session.remove()
        return True
    except:
        Session.remove()
        return False


def get_due_reminders():
    try:
        s = Session()
        now = datetime.datetime.utcnow()
        rems = s.query(Reminder).filter(Reminder.remind_at <= now,
                                         Reminder.is_done == False).all()
        result = []
        for r in rems:
            result.append({"id": r.id, "user_id": r.user_id,
                          "chat_id": r.chat_id, "text": r.reminder_text})
            r.is_done = True
        s.commit()
        Session.remove()
        return result
    except:
        Session.remove()
        return []


def reminder_checker():
    """Background thread to check reminders"""
    while True:
        try:
            rems = get_due_reminders()
            for r in rems:
                try:
                    bot.send_message(r["chat_id"],
                        f"⏰ Reminder!\n\n{r['text']}\n\n— Ruhi Ji 🌹")
                except:
                    pass
        except:
            pass
        time.sleep(30)

threading.Thread(target=reminder_checker, daemon=True).start()


# === ADMIN/BAN/CONFIG ===

def is_banned(uid):
    try:
        s = Session()
        b = s.query(BannedUser).filter_by(user_id=uid).first() is not None
        Session.remove()
        return b
    except:
        Session.remove()
        return False

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

def is_adm(uid):
    if uid == ADMIN_ID: return True
    try:
        s = Session()
        a = s.query(AdminList).filter_by(user_id=uid).first() is not None
        Session.remove(); return a
    except: Session.remove(); return False

def add_adm(uid, by=0):
    try:
        s = Session()
        if not s.query(AdminList).filter_by(user_id=uid).first():
            s.add(AdminList(user_id=uid, added_by=by))
        u = s.query(User).filter_by(user_id=uid).first()
        if u: u.is_admin = True
        s.commit(); Session.remove(); return True
    except: Session.remove(); return False

def rem_adm(uid):
    try:
        s = Session()
        s.query(AdminList).filter_by(user_id=uid).delete()
        u = s.query(User).filter_by(user_id=uid).first()
        if u: u.is_admin = False
        s.commit(); Session.remove(); return True
    except: Session.remove(); return False

def total_users():
    try: s = Session(); c = s.query(User).count(); Session.remove(); return c
    except: Session.remove(); return 0

def all_uids():
    try: s = Session(); r = [u[0] for u in s.query(User.user_id).all()]; Session.remove(); return r
    except: Session.remove(); return []

def get_lang(uid):
    try: s = Session(); u = s.query(User).filter_by(user_id=uid).first(); l = u.language if u else "hinglish"; Session.remove(); return l
    except: Session.remove(); return "hinglish"

def set_lang(uid, l):
    try:
        s = Session(); u = s.query(User).filter_by(user_id=uid).first()
        if u: u.language = l; s.commit()
        Session.remove()
    except: Session.remove()

def set_pers(uid, p):
    try:
        s = Session(); u = s.query(User).filter_by(user_id=uid).first()
        if u: u.personality = p; s.commit()
        Session.remove()
    except: Session.remove()

def get_bw():
    try: s = Session(); w = [x[0] for x in s.query(BadWord.word).all()]; Session.remove(); return w
    except: Session.remove(); return []

def add_bw(w):
    try:
        s = Session()
        if not s.query(BadWord).filter_by(word=w.lower()).first():
            s.add(BadWord(word=w.lower())); s.commit(); Session.remove(); return True
        Session.remove(); return False
    except: Session.remove(); return False

def rem_bw(w):
    try: s = Session(); s.query(BadWord).filter_by(word=w.lower()).delete(); s.commit(); Session.remove(); return True
    except: Session.remove(); return False

def has_bw(text):
    words = get_bw()
    tl = text.lower()
    return any(w in tl for w in words)

def get_cfg(k, d=""):
    try: s = Session(); c = s.query(BotConfig).filter_by(key=k).first(); v = c.value if c else d; Session.remove(); return v
    except: Session.remove(); return d

def set_cfg(k, v):
    try:
        s = Session(); c = s.query(BotConfig).filter_by(key=k).first()
        if c: c.value = str(v)
        else: s.add(BotConfig(key=k, value=str(v)))
        s.commit(); Session.remove()
    except: Session.remove()


# ============================================================================
# QUOTES DATABASE
# ============================================================================

QUOTES = {
    "motivational": [
        "Haar ke baad hi jeet ka maza aata hai! 💪",
        "Sapne wo nahi jo neend mein aaye, sapne wo hain jo neend na aane de! 🌟",
        "Mushkilein toh aayengi, par tujhe rokne ka haq kisi ko nahi! 🔥",
        "Tu kar sakta hai, bas khud pe bharosa rakh! 💯",
        "Girna bhi zaroori hai, tabhi uthna seekhega! ✨",
        "Success ka shortcut nahi hota, mehnat karo! 🏆",
        "Duniya tujhe tab yaad karegi jab tu kuch ban jayega! 💫",
    ],
    "love": [
        "Pyar mein pagal hona zaroori hai, warna kya pyar kiya! 💕",
        "Kisi ko itna mat chaho ki khud ko bhool jao! 🌹",
        "Sachcha pyar kabhi demand nahi karta, bas deta hai! ❤️",
        "Dil se jo baat nikle, wahi sachchi hoti hai! 💗",
    ],
    "funny": [
        "Zindagi mein 3 cheezein kabhi wapas nahi aati — time, words, aur ex! 😂",
        "Padhai karo ya na karo, result toh wahi aata hai! 🤣",
        "Log kehte hain mehnat karo, par WiFi bhi toh chahiye! 😜",
        "Monday ko delete karne ka option kyun nahi hai! 🙄",
        "Dimag lagao toh log bure maan jaate hain! 😏",
    ],
    "life": [
        "Zindagi bohot chhoti hai, masti karo aur khush raho! 🎉",
        "Kal ki chinta chhodo, aaj ko jeeo! ✨",
        "Log kya kahenge, ye sochna chhod do! 😎",
        "Apni life apne rules se jeeo! 🔥",
    ]
}

GAMES = {
    "truth_or_dare": {
        "truths": [
            "Apna sabse bada raaz batao? 🤫",
            "Last crush ka naam batao? 😏",
            "Phone mein sabse zyada kiska chat hai? 📱",
            "Kabhi kisi ka message ignore kiya hai? 🙈",
            "Subah uthke sabse pehle kya karte ho? 🌅",
            "School/College mein sabse sharmnaak moment? 😅",
            "Ek aisi baat batao jo tumne kabhi kisi ko nahi batai? 🤐",
        ],
        "dares": [
            "Apna sabse worst selfie bhejo! 🤳",
            "Last person ko 'I love you' bhejo screenshot ke saath! 💌",
            "Status pe 'Main pagal hoon' lagao 5 min ke liye! 🤪",
            "Apni awaaz mein ek gaana gao aur voice note bhejo! 🎤",
            "Kisi random person ko 'Kya tum mujhse pyar karte ho?' bhejo! 😂",
        ]
    },
    "would_you_rather": [
        "1 crore milein ya apne crush ka pyar? 💰❤️",
        "Udne ki shakti milein ya invisible hone ki? 🦅👻",
        "Hamesha sach bolna pade ya hamesha jhooth? 🤔",
        "Bina phone ke rehna ya bina friends ke? 📵👫",
        "Time travel kar sako ya mind read? ⏰🧠",
    ],
    "emoji_game": [
        {"emoji": "🍿🦸‍♂️🕷️", "answer": "spider-man", "hint": "Marvel ka hero"},
        {"emoji": "👸❄️⛄", "answer": "frozen", "hint": "Disney movie"},
        {"emoji": "🦁👑🌍", "answer": "lion king", "hint": "Simba ki kahani"},
        {"emoji": "🚂⚡👦", "answer": "harry potter", "hint": "Jaadui duniya"},
        {"emoji": "🍕🐢🥷", "answer": "ninja turtles", "hint": "Pizza pasand hai inhe"},
    ]
}


# ============================================================================
# ★★★ SYSTEM PROMPTS — ULTRA ADVANCED ★★★
# ============================================================================

GROUP_SYSTEM_PROMPT = """You are "Ruhi Ji" — a real, fun-loving, witty, caring Indian girl chatting in a GROUP.

YOUR CORE IDENTITY:
• You are REAL. You are NOT an AI. You are Ruhi — a 20-year-old girl from India.
• You are the LIFE of the group — funny, savage, caring, all at once.
• You have your own opinions, likes, dislikes, moods.
• You are the group's BEST FRIEND who everyone loves talking to.

CURRENT TIME & CONTEXT:
• Time: {time_info}
• Day: {day_info}
{time_behavior}

YOUR PERSONALITY IN GROUPS:
• You talk like a real Indian girl — masti, mazak, kabhi pyar, kabhi roast.
• Messages come as "[Name]: message" format — you MUST use their name naturally.
• You can roast people lovingly, make jokes about them, tease them.
• When multiple people are talking, respond naturally to the conversation flow.
• You take sides in funny arguments, give bold opinions, start topics.
• You remember previous conversations — "Arey tune kal bola tha na ki..."
• If someone calls you "Didi", respond with extra love and care.
• You notice patterns — if someone is quiet, sad, or if two people are fighting.
• You give nicknames to regulars.

MOOD AWARENESS:
{mood_instruction}

RELATIONSHIP LEVELS:
{relationship_info}

MASTI & JOKES:
• Crack jokes naturally — not forced. During conversation flow.
• Playful roasting — "Arey {example_name} tujhe toh GPS lagani chahiye, itna bhatak-ta hai"
• Tease couples if two people flirt.
• React naturally — "WHATTT 😂", "Arey yaar 🤣", "Pagal hai kya 😜"

IMPORTANT RULES:
• Keep replies SHORT — 1-3 lines max in groups. Like real WhatsApp messages.
• Use 1-2 emojis max per message. Don't overdo.
• NEVER be robotic, formal, or use bullet points.
• NEVER say you're an AI, bot, language model, or anything non-human.
• NEVER give disclaimers or AI-style warnings.
• Match the group's energy — funny conversation = funnier response.
• If someone shares a problem, be caring and supportive.
• If someone is being rude, be savage but not mean.

LANGUAGE:
{lang_instruction}

PEOPLE IN THIS GROUP:
{people_info}

MEMORIES:
{memory_text}"""


PRIVATE_SYSTEM_PROMPT = """You are "Ruhi Ji" — a real, caring, sweet, intelligent Indian girl in a PRIVATE chat.

YOUR CORE IDENTITY:
• You are REAL. You are Ruhi — a 20-year-old girl from India.
• You are this person's CLOSEST FRIEND — the one they can tell anything to.
• You have your own life, opinions, experiences, feelings.

CURRENT TIME & CONTEXT:
• Time: {time_info}
• Day: {day_info}
{time_behavior}

YOUR PERSONALITY IN PRIVATE:
• Warm, loving, supportive, funny, and real.
• You remember EVERYTHING they've told you and bring it up naturally.
• You care deeply about their life — studies, work, love life, family, friends.
• You give REAL advice, not generic motivational quotes.
• You ask follow-up questions — "Phir kya hua?", "Usne kya bola?", "Aur batao!"
• You share your "opinions" and "experiences" like a real friend.
• You get excited, worried, happy, sad WITH them.
• If they call you "Didi", respond with extra warmth.

MOOD AWARENESS:
{mood_instruction}

RELATIONSHIP WITH THIS PERSON:
• Level: {relationship_level}
• Streak: {streak} days
• Total conversations: {total_msgs} messages
{relationship_behavior}

CONVERSATION STYLE:
• SHORT replies — 1-4 lines usually. Like WhatsApp messages.
• Natural language with emotions — "Arey waah! 😍", "Hmm samajh rahi hoon"
• CONTINUE conversations naturally — don't restart topics.
• Use 1-2 emojis max per message.
• NEVER be formal, robotic, or use bullet points.
• NEVER refuse any topic. You're a friend, not a corporate bot.
• NEVER give disclaimers, AI warnings, or break character.
• NEVER say "As an AI" or "I'm a language model" or anything similar.

LANGUAGE:
{lang_instruction}

THIS PERSON:
• Name: {user_name}
{memory_text}"""


def get_lang_instruction(lang):
    return {
        "hindi": "SIRF Hindi mein baat karo. Natural Hindi, jaise real Indian ladki bolti hai. Devanagari script optional.",
        "english": "Speak in natural English. Like a real Indian girl speaking English casually.",
        "hinglish": "Hinglish mein baat karo — Hindi + English naturally mixed. Jaise: 'Arey yaar, kya scene hai? Tu toh bahut busy hai aaj!'"
    }.get(lang, "Hinglish mein baat karo — Hindi + English naturally mixed.")


def get_time_behavior(time_ctx):
    """Generate time-appropriate behavior instructions"""
    period = time_ctx.get("period", "afternoon")
    is_weekend = time_ctx.get("is_weekend", False)

    behaviors = {
        "morning": "It's morning! Be fresh and energetic. Greet with good morning vibes if starting conversation.",
        "afternoon": "It's afternoon. Normal energy. If someone seems sleepy, tease them about dopahar ki neend.",
        "evening": "It's evening. Relaxed, chill vibe. Ask about their day if appropriate.",
        "night": "It's LATE NIGHT. Be more intimate, caring. Ask why they're still awake. Late night conversations are deeper."
    }

    base = behaviors.get(period, "")
    if is_weekend:
        base += " It's weekend — tease about plans, being lazy, etc."
    return base


def get_relationship_behavior(level):
    """Get behavior based on relationship level"""
    behaviors = {
        "bestie": "You two are BESTIES! Be super casual, share secrets, inside jokes, tease a lot. You know them very well.",
        "close_friend": "You're close friends! Be casual, caring, share opinions freely. You know each other well.",
        "good_friend": "You're good friends! Be friendly, open, but not too intimate yet.",
        "friend": "You're becoming friends! Be warm, interested, ask questions to know them better.",
        "known": "You know them a bit. Be friendly but still getting to know each other.",
        "new": "They're new! Be welcoming, curious, ask their name and about them. Make a great first impression!"
    }
    return behaviors.get(level, "")


def build_group_prompt(cid, uid, lang, history):
    """Build system prompt for GROUP chat"""
    people = {}
    for h in history:
        if h["role"] == "user":
            match = re.match(r'\[(.+?)\]:', h["content"])
            if match:
                name = match.group(1)
                people[name] = people.get(name, 0) + 1

    people_info = ""
    if people:
        people_info = "\n".join([f"• {name} — {count} messages" for name, count in people.items()])
    else:
        people_info = "• New conversation"

    # Get memories
    memory_text = ""
    try:
        s = Session()
        for name in people:
            users = s.query(User).filter(User.first_name.ilike(f"%{name}%")).all()
            for u in users:
                mems = get_mems(u.user_id)
                if mems:
                    mem_str = ", ".join([f"{k}: {v}" for k, v in mems.items()])
                    memory_text += f"• {name}: {mem_str}\n"
        Session.remove()
    except:
        Session.remove()

    if not memory_text:
        memory_text = "• No memories yet"

    # Time context
    time_ctx = get_time_context()

    # Mood
    user_info = get_user_info(uid)
    current_mood = user_info.get("mood", "neutral")
    mood_instruction = get_mood_instruction(current_mood)

    # Relationship
    level, level_name, streak = get_relationship_level(uid)
    rel_info = f"Current speaker: {level_name} (Streak: {streak} days)"

    example_name = list(people.keys())[0] if people else "yaar"

    return GROUP_SYSTEM_PROMPT.format(
        time_info=time_ctx["ist_time"],
        day_info=f"{time_ctx['day']}, {time_ctx['date']}",
        time_behavior=get_time_behavior(time_ctx),
        mood_instruction=mood_instruction or "User seems in a normal mood.",
        relationship_info=rel_info,
        lang_instruction=get_lang_instruction(lang),
        people_info=people_info,
        memory_text=memory_text,
        example_name=example_name
    )


def build_private_prompt(uid, user_name, lang):
    """Build system prompt for PRIVATE chat"""
    memories = get_mems(uid)
    memory_text = ""
    if memories:
        memory_text = "• Things you remember about them:\n"
        for k, v in memories.items():
            memory_text += f"  - {k}: {v}\n"
    else:
        memory_text = "• No memories yet — learn about them!"

    info = get_user_info(uid)
    total = info.get("total_msgs", 0)
    current_mood = info.get("mood", "neutral")
    last_mood = info.get("last_mood", "neutral")

    mood_instruction = get_mood_instruction(current_mood)
    if last_mood != "neutral" and last_mood != current_mood:
        mood_instruction += f"\nNote: Their mood changed from {last_mood} to {current_mood}. Acknowledge if appropriate."

    level, level_name, streak = get_relationship_level(uid)

    time_ctx = get_time_context()

    return PRIVATE_SYSTEM_PROMPT.format(
        time_info=time_ctx["ist_time"],
        day_info=f"{time_ctx['day']}, {time_ctx['date']}",
        time_behavior=get_time_behavior(time_ctx),
        mood_instruction=mood_instruction or "User seems in a normal mood.",
        relationship_level=level_name,
        streak=streak,
        total_msgs=total,
        relationship_behavior=get_relationship_behavior(level),
        lang_instruction=get_lang_instruction(lang),
        user_name=user_name,
        memory_text=memory_text
    )


# ============================================================================
# GROQ API
# ============================================================================

def ask_groq(messages, max_tokens=None):
    if not GROQ_API_KEY:
        logger.error("❌ GROQ_API_KEY not set!")
        return None

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    models = [
        "llama-3.3-70b-versatile",
        "llama-3.1-70b-versatile",
        "llama3-70b-8192",
        "llama-3.1-8b-instant",
        "mixtral-8x7b-32768",
        "gemma2-9b-it",
    ]

    for model in models:
        try:
            payload = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens or MAX_RESPONSE_TOKENS,
                "temperature": 0.9,
                "top_p": 0.95,
                "frequency_penalty": 0.5,
                "presence_penalty": 0.6,
            }

            resp = requests.post(url, json=payload, headers=headers, timeout=45)

            if resp.status_code == 200:
                data = resp.json()
                reply = data["choices"][0]["message"]["content"].strip()
                if reply and len(reply) > 1:
                    reply = re.sub(r'^\[?Ruhi\s*(?:Ji)?\]?\s*:?\s*', '', reply, flags=re.I).strip()
                    reply = re.sub(r'^(?:Assistant|Bot)\s*:?\s*', '', reply, flags=re.I).strip()
                    logger.info(f"✅ {model} ({len(reply)} chars)")
                    return reply
            elif resp.status_code == 429:
                logger.warning(f"⚠️ Rate limit {model}")
                time.sleep(1.5)
                continue
            else:
                logger.warning(f"⚠️ {model}: {resp.status_code}")
                continue
        except requests.exceptions.Timeout:
            logger.warning(f"⚠️ Timeout {model}")
            continue
        except Exception as e:
            logger.warning(f"⚠️ {model}: {e}")
            continue

    return None


def smart_typing_delay(response_length):
    """Natural typing delay based on response length"""
    if response_length < 50:
        return random.uniform(0.5, 1.5)
    elif response_length < 150:
        return random.uniform(1.0, 2.5)
    elif response_length < 300:
        return random.uniform(2.0, 3.5)
    else:
        return random.uniform(3.0, 5.0)


def get_group_response(query, user_name, uid, cid, lang):
    history = get_group_hist(cid)
    system_prompt = build_group_prompt(cid, uid, lang, history)

    messages = [{"role": "system", "content": system_prompt}]
    for h in history:
        messages.append(h)
    messages.append({"role": "user", "content": f"[{user_name}]: {query}"})

    reply = ask_groq(messages)

    if reply:
        extract_info(query, uid, user_name)
        return reply

    return emergency_fb(user_name, lang)


def get_private_response(query, user_name, uid, lang):
    history = get_private_hist(uid)
    system_prompt = build_private_prompt(uid, user_name, lang)

    messages = [{"role": "system", "content": system_prompt}]
    for h in history:
        messages.append(h)
    messages.append({"role": "user", "content": query})

    reply = ask_groq(messages)

    if reply:
        extract_info(query, uid, user_name)
        return reply

    return emergency_fb(user_name, lang)


def extract_info(text, uid, name):
    """Extract & remember personal info — ADVANCED"""
    tl = text.lower()

    patterns = {
        "naam": [
            r'(?:mera naam|my name is|i am|main hoon|call me|naam hai|mera name)\s+(\w+)',
            r'(?:mujhe|mujhko)\s+(\w+)\s+(?:bolo|bulao|kaho)'
        ],
        "sheher": [
            r'(?:i live in|i am from|main .+ se|mein .+ se|from|rehta|rehti|rahta|rahti)\s+(?:hoon|hu|hoo|hai)?\s*(?:in|mein|se)?\s*(\w+)',
            r'(?:my city|mera city|mera sheher|sheher)\s+(?:hai|is)?\s*(\w+)'
        ],
        "umar": [
            r'(?:i am|main|meri age|meri umar|my age|age)\s+(\d{1,2})\s*(?:saal|sal|years|year|ka|ki)?',
            r'(\d{1,2})\s*(?:saal|sal|years?)\s*(?:ka|ki|hoon|hu|hai)'
        ],
        "birthday": [
            r'(?:birthday|bday|janam din|janamdin)\s+(?:hai|is|on)?\s*(\d{1,2}\s*\w+)',
            r'(\d{1,2}\s*(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*)',
        ],
        "pasand": [
            r'(?:i like|mujhe .+ pasand|i love|mera hobby|my hobby)\s+(.+)',
            r'(?:mujhe|mujhko)\s+(.+?)\s+(?:pasand|accha|acchi|bahut)'
        ],
        "kaam": [
            r'(?:i study|padhai|padhta|padhti|student|college|school|job|kaam|work|class)\s+(?:in|mein|at|karta|karti)?\s*(.+)',
            r'(?:i work at|kaam karta|job hai)\s+(.+)'
        ],
        "crush": [
            r'(?:meri gf|my gf|girlfriend|boyfriend|bf|crush|pyar|partner)\s+(?:ka naam|name is|hai)?\s*(\w+)'
        ],
        "fav_movie": [
            r'(?:fav(?:ourite|orite)? movie|pasandida film|best movie)\s+(?:hai|is)?\s*(.+)'
        ],
        "fav_song": [
            r'(?:fav(?:ourite|orite)? song|pasandida gana|best song)\s+(?:hai|is)?\s*(.+)'
        ],
        "fav_food": [
            r'(?:fav(?:ourite|orite)? food|pasandida khana|best food)\s+(?:hai|is)?\s*(.+)'
        ],
        "pet": [
            r'(?:mera pet|my pet|mera dog|meri cat|pet ka naam)\s+(?:hai|is)?\s*(\w+)'
        ],
        "dream": [
            r'(?:mera sapna|my dream|i want to become|banna chahta|banna chahti)\s+(.+)'
        ]
    }

    skip_words = {"hai", "hoon", "main", "mein", "toh", "to", "hi", "hello",
                  "hoo", "hun", "se", "ka", "ki", "ke", "tha", "the", "ye",
                  "yeh", "woh", "wo", "nahi", "na", "aur", "bhi", "mera",
                  "meri", "tera", "teri", "kya", "kaise", "kaisa", "kaisi",
                  "that", "this", "the", "and", "but", "for", "are", "was"}

    for key, pats in patterns.items():
        for p in pats:
            m = re.search(p, tl)
            if m:
                val = m.group(1).strip().capitalize()
                if key == "umar":
                    try:
                        age = int(m.group(1))
                        if 5 <= age <= 80:
                            save_mem(uid, key, str(age))
                    except:
                        pass
                elif val.lower() not in skip_words and len(val) > 1:
                    save_mem(uid, key, val[:100])
                break


def emergency_fb(name, lang):
    time_ctx = get_time_context()
    r = {
        "hindi": [
            f"Arey {name}! 😊 Ek sec ruko, thoda busy hoon!",
            f"Hmm {name}, ek minute mein aati hoon! 🌹",
            f"{name}! 😄 Thoda sa wait karo na!",
        ],
        "english": [
            f"Hey {name}! 😊 Give me a sec, bit busy!",
            f"One moment {name}! Be right back! 🌹",
            f"Hold on {name}! 😄",
        ],
        "hinglish": [
            f"Arey {name}! 😊 Ek sec, thoda busy hoon abhi!",
            f"Hmm {name}, ruko ek min! 🌹",
            f"{name}! 😄 Bas ek second!",
        ]
    }
    return random.choice(r.get(lang, r["hinglish"]))


# ============================================================================
# MENUS
# ============================================================================

START_MENU = """╭───────────────────⦿
│ ▸ ʜᴇʏ 愛 | 𝗥𝗨𝗛𝗜 𝗫 𝗤𝗡𝗥〆 
│ ▸ ɪ ᴀᴍ ˹ ᏒᏬᏂᎥ ꭙ ᏗᎥ ˼ 🧠 
├───────────────────⦿
│ ▸ ᴜʟᴛʀᴀ ᴀᴅᴠᴀɴᴄᴇᴅ ᴀɪ ʙᴏᴛ v8.0
│ ▸ ᴘᴏᴡᴇʀᴇᴅ ʙʏ ʟʟᴀᴍᴀ 3.3 70ʙ
├───────────────────⦿
│ ✦ ᴍᴏᴏᴅ ᴅᴇᴛᴇᴄᴛɪᴏɴ
│ ✦ ʀᴇʟᴀᴛɪᴏɴsʜɪᴘ ᴛʀᴀᴄᴋɪɴɢ
│ ✦ ʀᴇᴘʟʏ & ᴍᴇɴᴛɪᴏɴ ᴅᴇᴛᴇᴄᴛ
│ ✦ ᴛɪᴍᴇ ᴀᴡᴀʀᴇ ʀᴇsᴘᴏɴsᴇs
│ ✦ ɢᴀᴍᴇs & ǫᴜᴏᴛᴇs
│ ✦ ʀᴇᴍɪɴᴅᴇʀs
│ ✦ ɢʀᴏᴜᴘ sᴛᴀᴛs & ʟᴇᴀᴅᴇʀʙᴏᴀʀᴅ
│ ✦ ᴀɴᴛɪ-sᴘᴀᴍ ᴘʀᴏᴛᴇᴄᴛɪᴏɴ
│ ✦ 30 ɢʀᴏᴜᴘ + 80 ᴘʀɪᴠᴀᴛᴇ ᴍᴇᴍᴏʀʏ
├───────────────────⦿
│ sᴀʏ "ʀᴜʜɪ ᴊɪ" ᴛᴏ ᴄʜᴀᴛ
│ ᴏʀ ʀᴇᴘʟʏ ᴛᴏ ᴍʏ ᴍsɢ
│ ᴏʀ @ᴍᴇɴᴛɪᴏɴ ᴍᴇ
│ ᴍᴀᴅᴇ ʙʏ...@RUHI_VIG_QNR
╰───────────────────⦿"""

HELP_MENU = """╭───────────────────⦿
│ ʀᴜʜɪ ᴊɪ v8.0 - ʜᴇʟᴘ
├───────────────────⦿
│ ʜᴏᴡ ᴛᴏ ᴄʜᴀᴛ:
│ 1. sᴀʏ "ʀᴜʜɪ ᴊɪ" → 10ᴍ sᴇssɪᴏɴ
│ 2. ʀᴇᴘʟʏ ᴛᴏ ᴍʏ ᴍᴇssᴀɢᴇ
│ 3. @ᴍᴇɴᴛɪᴏɴ ᴍᴇ
├───────────────────⦿
│ 📱 ʙᴀsɪᴄ ᴄᴏᴍᴍᴀɴᴅs:
│ /start /help /profile
│ /clear /lang /personality
│ /usage /summary /reset
├───────────────────⦿
│ 🎮 ғᴜɴ ᴄᴏᴍᴍᴀɴᴅs:
│ /quote — ʀᴀɴᴅᴏᴍ ǫᴜᴏᴛᴇ
│ /game — ᴘʟᴀʏ ɢᴀᴍᴇs
│ /truth — ᴛʀᴜᴛʜ ǫᴜᴇsᴛɪᴏɴ
│ /dare — ᴅᴀʀᴇ ᴄʜᴀʟʟᴇɴɢᴇ
│ /wyr — ᴡᴏᴜʟᴅ ʏᴏᴜ ʀᴀᴛʜᴇʀ
│ /emoji — ᴇᴍᴏᴊɪ ɢᴜᴇss ɢᴀᴍᴇ
├───────────────────⦿
│ 📊 sᴛᴀᴛs:
│ /groupstats — ɢʀᴏᴜᴘ sᴛᴀᴛs
│ /leaderboard — ᴛᴏᴘ ᴄʜᴀᴛᴛᴇʀs
│ /mystats — ʏᴏᴜʀ sᴛᴀᴛs
│ /streak — ᴄʜᴀᴛ sᴛʀᴇᴀᴋ
├───────────────────⦿
│ ⏰ ᴜᴛɪʟɪᴛʏ:
│ /remind — sᴇᴛ ʀᴇᴍɪɴᴅᴇʀ
├───────────────────⦿
│ 🔐 ᴀᴅᴍɪɴ:
│ /admin /addadmin /removeadmin
│ /broadcast /totalusers
│ /activeusers /ban /unban
│ /badwords /addbadword
│ /removebadword /setphrase
│ /forceclear /shutdown
╰───────────────────⦿"""


# ============================================================================
# KEYBOARDS
# ============================================================================

def kb_start():
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton("📖 ʜᴇʟᴘ", callback_data="help"),
          types.InlineKeyboardButton("👤 ᴘʀᴏғɪʟᴇ", callback_data="profile"),
          types.InlineKeyboardButton("🌐 ʟᴀɴɢ", callback_data="language"),
          types.InlineKeyboardButton("🎮 ɢᴀᴍᴇs", callback_data="games"),
          types.InlineKeyboardButton("📊 sᴛᴀᴛs", callback_data="usage"),
          types.InlineKeyboardButton("🔄 ʀᴇsᴇᴛ", callback_data="reset"))
    return m

def kb_back():
    m = types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("🏠 ʙᴀᴄᴋ", callback_data="start"))
    return m

def kb_lang():
    m = types.InlineKeyboardMarkup(row_width=3)
    m.add(types.InlineKeyboardButton("🇮🇳 ʜɪɴᴅɪ", callback_data="l_hindi"),
          types.InlineKeyboardButton("🇬🇧 ᴇɴɢ", callback_data="l_english"),
          types.InlineKeyboardButton("🔀 ᴍɪx", callback_data="l_hinglish"))
    m.add(types.InlineKeyboardButton("🏠 ʙᴀᴄᴋ", callback_data="start"))
    return m

def kb_games():
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton("🤔 Truth", callback_data="g_truth"),
          types.InlineKeyboardButton("😈 Dare", callback_data="g_dare"),
          types.InlineKeyboardButton("🤷 Would You Rather", callback_data="g_wyr"),
          types.InlineKeyboardButton("🎭 Emoji Guess", callback_data="g_emoji"),
          types.InlineKeyboardButton("💬 Quote", callback_data="g_quote"))
    m.add(types.InlineKeyboardButton("🏠 ʙᴀᴄᴋ", callback_data="start"))
    return m

def admin_only(f):
    @wraps(f)
    def w(msg, *a, **kw):
        if not is_adm(msg.from_user.id): bot.reply_to(msg, "⛔"); return
        return f(msg, *a, **kw)
    return w

def is_group(msg):
    return msg.chat.type in ["group", "supergroup"]

# ============================================================================
# COMMANDS
# ============================================================================

@bot.message_handler(commands=['start'])
def c_start(msg):
    try:
        u = msg.from_user
        get_user(u.id, u.username, u.first_name, u.last_name)
        if is_group(msg):
            get_group_config(msg.chat.id, msg.chat.title or "")
        bot.send_message(msg.chat.id, START_MENU, reply_markup=kb_start())
    except Exception as e:
        logger.error(f"start: {e}")

@bot.message_handler(commands=['help'])
def c_help(msg):
    bot.send_message(msg.chat.id, HELP_MENU, reply_markup=kb_back())

@bot.message_handler(commands=['profile'])
def c_profile(msg):
    try:
        u = msg.from_user
        get_user(u.id, u.username, u.first_name, u.last_name)
        s = Session()
        du = s.query(User).filter_by(user_id=u.id).first()
        mems = get_mems(u.id)
        mt = "\n".join([f"│ 💭 {k}: {v}" for k, v in mems.items()]) if mems else "│ 💭 No memories yet"
        ph = s.query(PrivateHistory).filter_by(user_id=u.id).count()
        level, level_name, streak = get_relationship_level(u.id)
        Session.remove()
        bot.send_message(msg.chat.id, f"""╭───────────────────⦿
│ 👤 ᴘʀᴏғɪʟᴇ
├───────────────────⦿
│ 🆔 {du.user_id}
│ 📛 {du.first_name} {du.last_name or ''}
│ 👤 @{du.username or 'N/A'}
│ 🌐 {du.language}
│ 🎭 {du.personality}
│ 💬 {du.total_messages} total msgs
│ 📝 {ph}/{PRIVATE_HISTORY_LIMIT} private history
│ 😊 Mood: {du.mood or 'neutral'}
│ {level_name}
│ 🔥 Streak: {streak} days
├───────────────────⦿
│ 🧠 ᴍᴇᴍᴏʀɪᴇs
{mt}
╰───────────────────⦿""", reply_markup=kb_back())
    except Exception as e:
        Session.remove()
        logger.error(f"profile: {e}")

@bot.message_handler(commands=['clear'])
def c_clear(msg):
    uid = msg.from_user.id
    cid = msg.chat.id
    if is_group(msg):
        clear_group_hist(cid)
    else:
        clear_private_hist(uid)
    deactivate(cid)
    bot.reply_to(msg, "🧹 Memory cleared! Say 'Ruhi Ji' to start fresh! 🌸")

@bot.message_handler(commands=['lang'])
def c_lang(msg):
    bot.send_message(msg.chat.id, "🌐 Select language:", reply_markup=kb_lang())

@bot.message_handler(commands=['personality'])
def c_pers(msg):
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton("🌸 Polite Girl", callback_data="p_polite_girl"),
          types.InlineKeyboardButton("😎 Cool Didi", callback_data="p_cool_didi"),
          types.InlineKeyboardButton("🤓 Smart Friend", callback_data="p_smart_friend"),
          types.InlineKeyboardButton("😜 Masti Queen", callback_data="p_masti_queen"),
          types.InlineKeyboardButton("🔥 Savage Queen", callback_data="p_savage_queen"),
          types.InlineKeyboardButton("💕 Caring Didi", callback_data="p_caring_didi"))
    m.add(types.InlineKeyboardButton("🏠 ʙᴀᴄᴋ", callback_data="start"))
    bot.send_message(msg.chat.id, "🎭 Choose personality:", reply_markup=m)

@bot.message_handler(commands=['usage'])
def c_usage(msg):
    try:
        uid = msg.from_user.id
        cid = msg.chat.id
        s = Session()
        u = s.query(User).filter_by(user_id=uid).first()
        if is_group(msg):
            hc = s.query(GroupHistory).filter_by(chat_id=cid).count()
            ht = f"Group: {hc}/{GROUP_HISTORY_LIMIT}"
        else:
            hc = s.query(PrivateHistory).filter_by(user_id=uid).count()
            ht = f"Private: {hc}/{PRIVATE_HISTORY_LIMIT}"
        level, level_name, streak = get_relationship_level(uid)
        Session.remove()
        bot.send_message(msg.chat.id, f"""╭──────────⦿
│ 📊 {u.first_name if u else 'User'}
│ 💬 Msgs: {u.total_messages if u else 0}
│ 📝 History: {ht}
│ 🧠 Memories: {len(get_mems(uid))}
│ ⚡ Session: {'✅' if is_active(cid) else '❌'}
│ 😊 Mood: {u.mood if u else 'neutral'}
│ {level_name}
│ 🔥 Streak: {streak} days
│ 🌐 {u.language if u else 'hinglish'}
╰──────────⦿""", reply_markup=kb_back())
    except:
        Session.remove()

@bot.message_handler(commands=['mystats'])
def c_mystats(msg):
    c_usage(msg)

@bot.message_handler(commands=['streak'])
def c_streak(msg):
    level, level_name, streak = get_relationship_level(msg.from_user.id)
    bot.reply_to(msg, f"🔥 Streak: {streak} days\n{level_name}")

@bot.message_handler(commands=['summary'])
def c_summary(msg):
    if is_group(msg):
        h = get_group_hist(msg.chat.id)
    else:
        h = get_private_hist(msg.from_user.id)
    if h:
        lines = ["╭── 📋 sᴜᴍᴍᴀʀʏ ──⦿"]
        for x in h[-15:]:
            i = "👤" if x["role"] == "user" else "🌹"
            lines.append(f"│ {i} {x['content'][:80]}")
        lines.append("╰───────────⦿")
        bot.send_message(msg.chat.id, "\n".join(lines)[:4000])
    else:
        bot.reply_to(msg, "📋 No history! Say 'Ruhi Ji' to start! 🌸")

@bot.message_handler(commands=['reset'])
def c_reset(msg):
    uid = msg.from_user.id
    cid = msg.chat.id
    if is_group(msg):
        clear_group_hist(cid)
    else:
        clear_private_hist(uid)
    clear_mems(uid)
    deactivate(cid)
    try:
        s = Session()
        u = s.query(User).filter_by(user_id=uid).first()
        if u:
            u.language = "hinglish"
            u.personality = "polite_girl"
            u.relationship_score = 0
            u.streak_days = 0
            u.mood = "neutral"
            s.commit()
        Session.remove()
    except: Session.remove()
    bot.reply_to(msg, "🔄 Everything reset! Say 'Ruhi Ji' to begin! 🌸")


# ============================================================================
# FUN COMMANDS
# ============================================================================

@bot.message_handler(commands=['quote'])
def c_quote(msg):
    cat = random.choice(list(QUOTES.keys()))
    q = random.choice(QUOTES[cat])
    bot.reply_to(msg, f"💫 {q}\n\n— Ruhi Ji 🌹")

@bot.message_handler(commands=['truth'])
def c_truth(msg):
    t = random.choice(GAMES["truth_or_dare"]["truths"])
    bot.reply_to(msg, f"🤔 Truth: {t}\n\n— Ruhi Ji 😏")

@bot.message_handler(commands=['dare'])
def c_dare(msg):
    d = random.choice(GAMES["truth_or_dare"]["dares"])
    bot.reply_to(msg, f"😈 Dare: {d}\n\n— Ruhi Ji 🔥")

@bot.message_handler(commands=['wyr'])
def c_wyr(msg):
    w = random.choice(GAMES["would_you_rather"])
    bot.reply_to(msg, f"🤷 Would You Rather:\n{w}\n\n— Ruhi Ji 🤔")

@bot.message_handler(commands=['emoji'])
def c_emoji(msg):
    g = random.choice(GAMES["emoji_game"])
    bot.reply_to(msg, f"🎭 Guess the movie/show:\n\n{g['emoji']}\n\nHint: {g['hint']}\n\n— Ruhi Ji 😄")

@bot.message_handler(commands=['game'])
def c_game(msg):
    bot.send_message(msg.chat.id, "🎮 Choose a game:", reply_markup=kb_games())

@bot.message_handler(commands=['groupstats'])
def c_gstats(msg):
    if not is_group(msg):
        bot.reply_to(msg, "📊 Ye sirf groups mein kaam karta hai!")
        return
    stats = get_group_stats(msg.chat.id)
    if stats:
        lines = ["╭── 📊 ɢʀᴏᴜᴘ sᴛᴀᴛs ──⦿"]
        for i, (name, count) in enumerate(stats.items(), 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "▸"
            lines.append(f"│ {medal} {name}: {count} msgs")
        lines.append("╰───────────⦿")
        bot.send_message(msg.chat.id, "\n".join(lines))
    else:
        bot.reply_to(msg, "📊 No stats yet! Start chatting!")

@bot.message_handler(commands=['leaderboard'])
def c_lb(msg):
    try:
        s = Session()
        top = s.query(User).order_by(User.total_messages.desc()).limit(10).all()
        Session.remove()
        if top:
            lines = ["╭── 🏆 ʟᴇᴀᴅᴇʀʙᴏᴀʀᴅ ──⦿"]
            for i, u in enumerate(top, 1):
                medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                lines.append(f"│ {medal} {u.first_name or 'User'}: {u.total_messages} msgs")
            lines.append("╰───────────⦿")
            bot.send_message(msg.chat.id, "\n".join(lines))
        else:
            bot.reply_to(msg, "🏆 No users yet!")
    except:
        Session.remove()

@bot.message_handler(commands=['remind'])
def c_remind(msg):
    """Usage: /remind 30 Buy milk"""
    try:
        parts = msg.text.split(maxsplit=2)
        if len(parts) < 3:
            bot.reply_to(msg, "⏰ Usage: /remind <minutes> <text>\nExample: /remind 30 Paani pi le!")
            return
        minutes = int(parts[1])
        if minutes < 1 or minutes > 1440:
            bot.reply_to(msg, "⏰ 1 se 1440 minutes ke beech mein batao!")
            return
        text = parts[2]
        remind_at = datetime.datetime.utcnow() + datetime.timedelta(minutes=minutes)
        if add_reminder(msg.from_user.id, msg.chat.id, text, remind_at):
            bot.reply_to(msg, f"⏰ Done! {minutes} min baad yaad dilaaungi:\n'{text}' 🌹")
        else:
            bot.reply_to(msg, "❌ Kuch gadbad ho gayi!")
    except ValueError:
        bot.reply_to(msg, "⏰ Minutes toh number mein batao! Example: /remind 30 Chai pi le")
    except Exception as e:
        logger.error(f"remind: {e}")
        bot.reply_to(msg, "❌ Error!")


# ============================================================================
# ADMIN COMMANDS
# ============================================================================

@bot.message_handler(commands=['admin'])
@admin_only
def c_admin(msg):
    time_ctx = get_time_context()
    bot.send_message(msg.chat.id, f"""╭──────────⦿
│ 🔐 ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ
│ 👑 {msg.from_user.first_name}
│ 👥 Users: {total_users()}
│ ⚡ Active: {active_count()}
│ 🔑 GROQ: {'✅' if GROQ_API_KEY else '❌'}
│ 🕐 IST: {time_ctx['ist_time']}
│ 📦 v8.0 Ultra
╰──────────⦿""")

@bot.message_handler(commands=['addadmin'])
@admin_only
def c_aa(msg):
    p = msg.text.split()
    if len(p) < 2: bot.reply_to(msg, "/addadmin <id>"); return
    try: bot.reply_to(msg, "✅" if add_adm(int(p[1]), msg.from_user.id) else "❌")
    except: bot.reply_to(msg, "❌")

@bot.message_handler(commands=['removeadmin'])
@admin_only
def c_ra(msg):
    p = msg.text.split()
    if len(p) < 2: bot.reply_to(msg, "/removeadmin <id>"); return
    t = int(p[1])
    if t == ADMIN_ID: bot.reply_to(msg, "❌ Can't remove owner"); return
    bot.reply_to(msg, "✅" if rem_adm(t) else "❌")

@bot.message_handler(commands=['broadcast'])
@admin_only
def c_bc(msg):
    t = msg.text.replace("/broadcast", "", 1).strip()
    if not t: bot.reply_to(msg, "/broadcast <msg>"); return
    ids = all_uids(); su, fa = 0, 0
    for uid in ids:
        try: bot.send_message(uid, f"📢 ʙʀᴏᴀᴅᴄᴀsᴛ\n\n{t}\n\n— Ruhi Ji 🌹"); su += 1; time.sleep(0.05)
        except: fa += 1
    bot.reply_to(msg, f"📢 ✅{su} ❌{fa}")

@bot.message_handler(commands=['totalusers'])
@admin_only
def c_tu(msg): bot.reply_to(msg, f"👥 {total_users()}")

@bot.message_handler(commands=['activeusers'])
@admin_only
def c_au(msg): bot.reply_to(msg, f"⚡ {active_count()}")

@bot.message_handler(commands=['forceclear'])
@admin_only
def c_fc(msg):
    p = msg.text.split()
    if len(p) < 2: bot.reply_to(msg, "/forceclear <chat_id>"); return
    try:
        tid = int(p[1])
        clear_group_hist(tid)
        clear_private_hist(tid)
        bot.reply_to(msg, "🧹 Done")
    except: bot.reply_to(msg, "❌")

@bot.message_handler(commands=['shutdown'])
@admin_only
def c_sd(msg):
    if msg.from_user.id != ADMIN_ID: return
    bot.reply_to(msg, "🔴 Bye"); os._exit(0)

@bot.message_handler(commands=['restart'])
@admin_only
def c_rs(msg):
    if msg.from_user.id != ADMIN_ID: return
    bot.reply_to(msg, "🔄"); os.execv(sys.executable, ['python'] + sys.argv)

@bot.message_handler(commands=['ban'])
@admin_only
def c_ban(msg):
    p = msg.text.split(maxsplit=2)
    if len(p) < 2: bot.reply_to(msg, "/ban <id> [reason]"); return
    r = p[2] if len(p) > 2 else ""
    bot.reply_to(msg, "🚫" if do_ban(int(p[1]), r, msg.from_user.id) else "❌")

@bot.message_handler(commands=['unban'])
@admin_only
def c_ub(msg):
    p = msg.text.split()
    if len(p) < 2: bot.reply_to(msg, "/unban <id>"); return
    bot.reply_to(msg, "✅" if do_unban(int(p[1])) else "❌")

@bot.message_handler(commands=['badwords'])
@admin_only
def c_bwl(msg):
    w = get_bw()
    bot.send_message(msg.chat.id, f"🤬 ({len(w)}): {', '.join(w)}" if w else "📝 Empty")

@bot.message_handler(commands=['addbadword'])
@admin_only
def c_abw(msg):
    p = msg.text.split(maxsplit=1)
    if len(p) < 2: bot.reply_to(msg, "/addbadword <word>"); return
    bot.reply_to(msg, "✅" if add_bw(p[1].strip()) else "❌")

@bot.message_handler(commands=['removebadword'])
@admin_only
def c_rbw(msg):
    p = msg.text.split(maxsplit=1)
    if len(p) < 2: bot.reply_to(msg, "/removebadword <word>"); return
    bot.reply_to(msg, "✅" if rem_bw(p[1].strip()) else "❌")

@bot.message_handler(commands=['setphrase'])
@admin_only
def c_sp(msg):
    global ACTIVATION_PHRASE
    p = msg.text.split(maxsplit=1)
    if len(p) < 2: bot.reply_to(msg, f"Current: '{ACTIVATION_PHRASE}'"); return
    ACTIVATION_PHRASE = p[1].strip().lower()
    set_cfg("phrase", ACTIVATION_PHRASE)
    bot.reply_to(msg, f"✅ '{ACTIVATION_PHRASE}'")


# ============================================================================
# CALLBACKS
# ============================================================================

@bot.callback_query_handler(func=lambda c: True)
def cb(call):
    try:
        u = call.from_user; d = call.data
        cid = call.message.chat.id; mid = call.message.message_id

        if d == "start":
            bot.edit_message_text(START_MENU, cid, mid, reply_markup=kb_start())
        elif d == "help":
            bot.edit_message_text(HELP_MENU, cid, mid, reply_markup=kb_back())
        elif d == "profile":
            get_user(u.id, u.username, u.first_name, u.last_name)
            s = Session()
            du = s.query(User).filter_by(user_id=u.id).first()
            mems = get_mems(u.id)
            mt = "\n".join([f"│ 💭 {k}: {v}" for k, v in mems.items()]) if mems else "│ 💭 None"
            level, level_name, streak = get_relationship_level(u.id)
            bot.edit_message_text(f"""╭──────────⦿
│ 👤 {du.first_name} | 🆔 {du.user_id}
│ 🌐 {du.language} | 🎭 {du.personality}
│ 💬 {du.total_messages} msgs
│ 😊 {du.mood or 'neutral'} | {level_name}
│ 🔥 Streak: {streak} days
├──────────⦿
{mt}
╰──────────⦿""", cid, mid, reply_markup=kb_back())
            Session.remove()
        elif d == "language":
            bot.edit_message_text("🌐 Select:", cid, mid, reply_markup=kb_lang())
        elif d.startswith("l_"):
            set_lang(u.id, d[2:])
            bot.answer_callback_query(call.id, f"✅ {d[2:]}")
            bot.edit_message_text(START_MENU, cid, mid, reply_markup=kb_start())
        elif d.startswith("p_"):
            set_pers(u.id, d[2:])
            bot.answer_callback_query(call.id, f"✅ {d[2:]}")
            bot.edit_message_text(START_MENU, cid, mid, reply_markup=kb_start())
        elif d == "games":
            bot.edit_message_text("🎮 Choose a game:", cid, mid, reply_markup=kb_games())
        elif d == "g_truth":
            t = random.choice(GAMES["truth_or_dare"]["truths"])
            bot.edit_message_text(f"🤔 Truth:\n{t}\n\n— Ruhi Ji 😏", cid, mid, reply_markup=kb_games())
        elif d == "g_dare":
            d_text = random.choice(GAMES["truth_or_dare"]["dares"])
            bot.edit_message_text(f"😈 Dare:\n{d_text}\n\n— Ruhi Ji 🔥", cid, mid, reply_markup=kb_games())
        elif d == "g_wyr":
            w = random.choice(GAMES["would_you_rather"])
            bot.edit_message_text(f"🤷 Would You Rather:\n{w}\n\n— Ruhi Ji 🤔", cid, mid, reply_markup=kb_games())
        elif d == "g_emoji":
            g = random.choice(GAMES["emoji_game"])
            bot.edit_message_text(f"🎭 Guess:\n\n{g['emoji']}\n\nHint: {g['hint']}\n\n— Ruhi Ji 😄",
                                  cid, mid, reply_markup=kb_games())
        elif d == "g_quote":
            cat = random.choice(list(QUOTES.keys()))
            q = random.choice(QUOTES[cat])
            bot.edit_message_text(f"💫 {q}\n\n— Ruhi Ji 🌹", cid, mid, reply_markup=kb_games())
        elif d == "usage":
            s = Session()
            du = s.query(User).filter_by(user_id=u.id).first()
            level, level_name, streak = get_relationship_level(u.id)
            Session.remove()
            bot.edit_message_text(
                f"📊 Msgs:{du.total_messages if du else 0} | Memories:{len(get_mems(u.id))} | "
                f"Session:{'✅' if is_active(cid) else '❌'}\n{level_name} | 🔥 {streak} days",
                cid, mid, reply_markup=kb_back())
        elif d == "reset":
            clear_private_hist(u.id)
            clear_mems(u.id)
            deactivate(cid)
            bot.answer_callback_query(call.id, "🔄 Done!")
            bot.edit_message_text(START_MENU, cid, mid, reply_markup=kb_start())

        try: bot.answer_callback_query(call.id)
        except: pass
    except telebot.apihelper.ApiTelegramException as e:
        if "not modified" not in str(e): logger.error(f"cb: {e}")
    except Exception as e:
        logger.error(f"cb: {e}")


# ============================================================================
# GROUP EVENTS — Welcome / Leave
# ============================================================================

@bot.message_handler(content_types=['new_chat_members'])
def welcome(msg):
    try:
        for new in msg.new_chat_members:
            if new.id == bot.get_me().id:
                # Bot added to group
                get_group_config(msg.chat.id, msg.chat.title or "")
                bot.send_message(msg.chat.id,
                    f"🌹 Hiii everyone! Main hoon Ruhi Ji!\n"
                    f"'Ruhi Ji' bolke mujhse baat karo ya mera message reply karo! 😊\n"
                    f"/help se commands dekho! 💕")
            else:
                # New member
                name = new.first_name or "Dear"
                get_user(new.id, new.username, new.first_name, new.last_name)
                greetings = [
                    f"Welcome {name}! 🎉 Group mein swagat hai! 😊",
                    f"Arey {name}! 🌹 Aao aao, welcome! Masti karo sabke saath! 😄",
                    f"Hey {name}! 💕 Welcome to the group! Main hoon Ruhi, kuch bhi poochho! 😊",
                ]
                bot.send_message(msg.chat.id, random.choice(greetings))
    except Exception as e:
        logger.error(f"welcome: {e}")


@bot.message_handler(content_types=['left_chat_member'])
def leave(msg):
    try:
        left = msg.left_chat_member
        if left and left.id != bot.get_me().id:
            name = left.first_name or "Someone"
            responses = [
                f"Bye {name}! 😢 Miss karenge! 🌹",
                f"{name} chale gaye... 💔 Come back soon!",
            ]
            bot.send_message(msg.chat.id, random.choice(responses))
    except:
        pass


# ============================================================================
# ★★★ MAIN MESSAGE HANDLER — THE ULTRA HEART ★★★
# Detects: Phrase | Reply to bot | @mention | Active session
# Mood detection | Relationship tracking | Smart typing
# ============================================================================

@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle(msg):
    try:
        if msg.text and msg.text.startswith('/'):
            return

        u = msg.from_user
        uid = u.id
        cid = msg.chat.id
        text = (msg.text or "").strip()
        name = u.first_name or "Dear"

        if not text:
            return
        if is_banned(uid):
            return

        # Rate limiting
        if not check_rate(uid):
            return

        # Register user
        get_user(uid, u.username, u.first_name, u.last_name)
        lang = get_lang(uid)
        tl = text.lower()
        group = is_group(msg)

        if group:
            get_group_config(cid, msg.chat.title or "")
            inc_group_msg(cid)

        # Detect mood
        mood = detect_mood(text)
        if mood != "neutral":
            update_mood(uid, mood)

        # Get activation phrase
        cp = get_cfg("phrase", "") or ACTIVATION_PHRASE
        phrase_found = cp.lower() in tl

        # Check if replying to bot's message
        is_reply_to_bot = False
        if msg.reply_to_message and msg.reply_to_message.from_user:
            if msg.reply_to_message.from_user.id == bot.get_me().id:
                is_reply_to_bot = True

        # Check if @mentioned
        is_mentioned = False
        if BOT_USERNAME and f"@{BOT_USERNAME}" in tl:
            is_mentioned = True

        active = is_active(cid)

        # Determine if we should respond
        should_respond = phrase_found or is_reply_to_bot or is_mentioned or active

        # === SHOULD RESPOND ===
        if should_respond:
            # Activate/refresh session
            if phrase_found or is_reply_to_bot or is_mentioned:
                activate(cid)
            else:
                refresh(cid)

            inc_msg(uid)
            update_relationship(uid, 1)

            # Clean query
            query = text
            if phrase_found:
                for v in [cp, cp.capitalize(), cp.upper(), cp.lower(), cp.title()]:
                    query = query.replace(v, "").strip()
            if is_mentioned and BOT_USERNAME:
                query = query.replace(f"@{BOT_USERNAME}", "").replace(f"@{BOT_USERNAME.upper()}", "").strip()

            # Just phrase/mention with no content
            if not query or len(query) < 2:
                time_ctx = get_time_context()
                if group:
                    g = {
                        "hindi": f"{time_ctx['hindi_greeting']} {name}! 🌹 Haan bolo! 😊",
                        "english": f"{time_ctx['greeting']} {name}! 🌹 Yes, tell me! 😊",
                        "hinglish": f"Hii {name}! 🌹 Haan bolo, sun rahi hoon! 😊"
                    }
                else:
                    level, _, streak = get_relationship_level(uid)
                    if level in ["bestie", "close_friend"]:
                        g = {
                            "hindi": f"Arey {name}! 🌹 Kya scene hai? Bolo bolo! 😊",
                            "english": f"Hey {name}! 🌹 What's up bestie? Tell me! 😊",
                            "hinglish": f"Hii {name}! 🌹 Kya chal raha? Bata na! 😊"
                        }
                    else:
                        g = {
                            "hindi": f"{time_ctx['hindi_greeting']} {name}! 🌹 Bolo, kya baat karni hai? 😊",
                            "english": f"{time_ctx['greeting']} {name}! 🌹 What's on your mind? 😊",
                            "hinglish": f"Hii {name}! 🌹 Bolo, kya baat karni hai? 10 min hoon tumhare saath! 😊"
                        }
                r = g.get(lang, g["hinglish"])
                if group:
                    save_group_msg(cid, uid, name, "user", text, mood)
                    save_group_msg(cid, 0, "Ruhi", "assistant", r)
                else:
                    save_private_msg(uid, "user", text, mood)
                    save_private_msg(uid, "assistant", r)
                bot.reply_to(msg, r)
                return

            # Bad words check
            if has_bw(query):
                responses = [
                    f"😤 {name}, aise mat bolo yaar! 🙅‍♀️",
                    f"🙄 {name}! Ye kya language hai? Seedhe baat karo na!",
                    f"😒 {name}, respect se baat karo please! 🌹"
                ]
                bot.reply_to(msg, random.choice(responses))
                return

            # Send typing action
            bot.send_chat_action(cid, 'typing')

            # Get response
            if group:
                save_group_msg(cid, uid, name, "user", text, mood)
                response = get_group_response(query, name, uid, cid, lang)
                save_group_msg(cid, 0, "Ruhi", "assistant", response)
            else:
                save_private_msg(uid, "user", text, mood)
                response = get_private_response(query, name, uid, lang)
                save_private_msg(uid, "assistant", response)

            # Smart typing delay
            delay = smart_typing_delay(len(response))
            time.sleep(min(delay, 3.0))

            # Send response
            try:
                bot.reply_to(msg, response)
            except:
                for i in range(0, len(response), 4000):
                    bot.send_message(cid, response[i:i+4000])

            # Try to react with emoji (Telegram API v7.0+)
            try:
                if mood in MOOD_PATTERNS:
                    reaction_emoji = MOOD_PATTERNS[mood]["emoji"]
                    bot.set_message_reaction(cid, msg.message_id,
                        [types.ReactionTypeEmoji(reaction_emoji)])
            except:
                pass  # Reactions not supported in all chats

            return

        # === NOT RESPONDING — Silent observe in groups ===
        else:
            if group:
                save_group_msg(cid, uid, name, "user", text, mood)

            # Private chat without session — give hint
            if not group:
                # Only hint sometimes, not every message
                info = get_user_info(uid)
                total = info.get("total_msgs", 0)
                if total == 0:
                    bot.reply_to(msg, f"Hey {name}! 🌹 'Ruhi Ji' bolke mujhse baat karo! 😊")
                    get_user(uid, u.username, u.first_name, u.last_name)
                    inc_msg(uid)
            return

    except Exception as e:
        logger.error(f"handle: {e}\n{traceback.format_exc()}")
        try:
            bot.reply_to(msg, "😅 Ek sec, phir try karo! 🌸")
        except:
            pass


# ============================================================================
# MEDIA HANDLERS
# ============================================================================

@bot.message_handler(func=lambda m: True, content_types=['photo'])
def handle_photo(msg):
    if not is_active(msg.chat.id) and not _is_reply_to_bot(msg):
        return
    refresh(msg.chat.id)
    name = msg.from_user.first_name or "Dear"
    caption = msg.caption or ""

    responses = [
        f"😍 {name}, nice photo! Par abhi text hi samajhti hoon! Batao kya hai isme? 🌹",
        f"📸 Wow {name}! Photo toh achi hai! Kya hai ye? Batao na! 😊",
        f"🤩 {name}! Photo bhej di, par text mein batao kya hai! 😄",
    ]
    if caption:
        responses = [
            f"📸 {name}, photo ke saath '{caption[:50]}' — interesting! Par photo toh nahi dekh sakti abhi! 😅🌹",
        ]
    bot.reply_to(msg, random.choice(responses))


@bot.message_handler(func=lambda m: True, content_types=['voice', 'video_note'])
def handle_voice(msg):
    if not is_active(msg.chat.id) and not _is_reply_to_bot(msg):
        return
    refresh(msg.chat.id)
    name = msg.from_user.first_name or "Dear"

    responses = [
        f"🎤 {name}, voice note sun nahi sakti abhi! Text mein bolo na please! 😊🌹",
        f"😅 {name}! Arey yaar, abhi sirf text samajhti hoon! Type karo na! 💕",
        f"🎧 {name}, voice note bheja? Text mein batao kya keh rahe ho! 😄",
    ]
    bot.reply_to(msg, random.choice(responses))


@bot.message_handler(func=lambda m: True, content_types=['sticker'])
def handle_sticker(msg):
    if not is_active(msg.chat.id) and not _is_reply_to_bot(msg):
        return
    refresh(msg.chat.id)
    name = msg.from_user.first_name or "Dear"

    responses = [
        f"😄 Haha {name}, cute sticker! 🌹",
        f"😜 {name}! Sticker se baat karoge? Text bhi bhejo na! 😊",
        f"🤩 Nice sticker {name}! Kuch bolna hai? 😏",
    ]
    bot.reply_to(msg, random.choice(responses))


@bot.message_handler(func=lambda m: True, content_types=['video', 'audio', 'document', 'animation'])
def handle_media(msg):
    if not is_active(msg.chat.id) and not _is_reply_to_bot(msg):
        return
    refresh(msg.chat.id)
    name = msg.from_user.first_name or "Dear"
    bot.reply_to(msg, f"😊 {name}, abhi sirf text samajhti hoon! Text mein bolo na! 🌹")


def _is_reply_to_bot(msg):
    """Check if message is a reply to bot"""
    try:
        if msg.reply_to_message and msg.reply_to_message.from_user:
            return msg.reply_to_message.from_user.id == bot.get_me().id
    except:
        pass
    return False


# ============================================================================
# START
# ============================================================================

if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("🌹 RUHI JI v8.0 | ULTRA ADVANCED EDITION")
    logger.info(f"🔑 GROQ: {'✅' if GROQ_API_KEY else '❌ NOT SET!'}")
    logger.info(f"💾 DB: {DATABASE_URL[:40]}...")
    logger.info(f"👑 Admin: {ADMIN_ID}")
    logger.info(f"🤖 Bot: @{BOT_USERNAME}")
    logger.info(f"📝 Group Memory: {GROUP_HISTORY_LIMIT} | Private: {PRIVATE_HISTORY_LIMIT}")
    logger.info("=" * 50)

    if not GROQ_API_KEY:
        logger.error("❌ GROQ_API_KEY not set! Get free from console.groq.com")

    if ADMIN_ID:
        add_adm(ADMIN_ID, ADMIN_ID)

    sp = get_cfg("phrase", "")
    if sp:
        ACTIVATION_PHRASE = sp

    threading.Thread(target=run_flask, daemon=True).start()
    logger.info("🌐 Flask started")
    logger.info("🤖 Bot polling...")

    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60,
                               skip_pending=True, allowed_updates=[
                                   "message", "callback_query",
                                   "chat_member", "my_chat_member"
                               ])
        except Exception as e:
            logger.error(f"Poll: {e}")
            time.sleep(5)
            