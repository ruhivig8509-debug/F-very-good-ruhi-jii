# ============================================================================
# main.py — RUHI JI v6.0 — PURE CONVERSATIONAL BOT
# SIRF BAAT KARNA | SIRF GROQ | SIRF BEST MODEL | SIRF PYAAR
# Llama 3.1 70B — Sabse Bada Free Model
# ============================================================================

import os, sys, time, logging, threading, datetime, re, random, traceback
from functools import wraps
from io import BytesIO

import telebot
from telebot import types
from flask import Flask
from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, DateTime, BigInteger
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
SESSION_TIMEOUT = 600  # 10 min

if DATABASE_URL.startswith("postgres://"):
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
    engine = create_engine(DATABASE_URL, echo=False, pool_size=5, max_overflow=10)

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

class UserMemory(Base):
    __tablename__ = "user_memory"
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    key = Column(String(255), nullable=False)
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
    return "<h1>🌹 Ruhi Ji Running!</h1>"

@app.route("/health")
def health():
    return {"status": "ok"}, 200

def run_flask():
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)

# ============================================================================
# BOT
# ============================================================================

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None, threaded=True)

# ============================================================================
# SESSIONS
# ============================================================================

sessions = {}
slock = threading.Lock()

def activate(uid, cid):
    with slock: sessions[(uid, cid)] = time.time()

def is_active(uid, cid):
    with slock:
        k = (uid, cid)
        if k in sessions and time.time() - sessions[k] < SESSION_TIMEOUT: return True
        sessions.pop(k, None); return False

def refresh(uid, cid):
    with slock:
        k = (uid, cid)
        if k in sessions: sessions[k] = time.time()

def deactivate(uid, cid):
    with slock: sessions.pop((uid, cid), None)

def active_count():
    with slock:
        now = time.time()
        return sum(1 for v in sessions.values() if now - v < SESSION_TIMEOUT)

def cleanup():
    while True:
        try:
            with slock:
                now = time.time()
                for k in [k for k, v in sessions.items() if now - v >= SESSION_TIMEOUT]:
                    del sessions[k]
        except: pass
        time.sleep(60)

threading.Thread(target=cleanup, daemon=True).start()

# ============================================================================
# DB FUNCTIONS
# ============================================================================

def get_user(uid, uname="", fname="", lname=""):
    try:
        s = Session()
        u = s.query(User).filter_by(user_id=uid).first()
        if not u:
            u = User(user_id=uid, username=uname, first_name=fname, last_name=lname,
                     is_admin=(uid == ADMIN_ID))
            s.add(u); s.commit()
        else:
            if uname: u.username = uname
            if fname: u.first_name = fname
            if lname: u.last_name = lname
            u.last_active = datetime.datetime.utcnow()
            s.commit()
        Session.remove(); return u
    except: Session.remove(); return None

def inc_msg(uid):
    try:
        s = Session()
        u = s.query(User).filter_by(user_id=uid).first()
        if u: u.total_messages += 1; u.last_active = datetime.datetime.utcnow(); s.commit()
        Session.remove()
    except: Session.remove()

def save_hist(uid, cid, role, msg):
    try:
        s = Session()
        s.add(ChatHistory(user_id=uid, chat_id=cid, role=role, message=msg[:4000]))
        s.commit()
        # Keep only 50 messages per user per chat
        cnt = s.query(ChatHistory).filter_by(user_id=uid, chat_id=cid).count()
        if cnt > 50:
            old = s.query(ChatHistory).filter_by(user_id=uid, chat_id=cid)\
                .order_by(ChatHistory.timestamp.asc()).limit(cnt - 50).all()
            for o in old: s.delete(o)
            s.commit()
        Session.remove()
    except: Session.remove()

def get_hist(uid, cid):
    """Get ALL stored messages (up to 50) for context"""
    try:
        s = Session()
        h = s.query(ChatHistory).filter_by(user_id=uid, chat_id=cid)\
            .order_by(ChatHistory.timestamp.asc()).all()
        r = [{"role": x.role, "content": x.message} for x in h]
        Session.remove(); return r
    except: Session.remove(); return []

def clear_hist(uid, cid=None):
    try:
        s = Session()
        q = s.query(ChatHistory).filter_by(user_id=uid)
        if cid: q = q.filter_by(chat_id=cid)
        q.delete(); s.commit(); Session.remove()
    except: Session.remove()

def is_banned(uid):
    try:
        s = Session(); b = s.query(BannedUser).filter_by(user_id=uid).first() is not None
        Session.remove(); return b
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

def is_adm(uid):
    if uid == ADMIN_ID: return True
    try:
        s = Session(); a = s.query(AdminList).filter_by(user_id=uid).first() is not None
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
        s = Session(); s.query(AdminList).filter_by(user_id=uid).delete()
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
    try: s = Session(); u = s.query(User).filter_by(user_id=uid).first();
    except: pass
    try:
        if u: u.language = l; s.commit()
        Session.remove()
    except: Session.remove()

def set_pers(uid, p):
    try:
        s = Session(); u = s.query(User).filter_by(user_id=uid).first()
        if u: u.personality = p; s.commit()
        Session.remove()
    except: Session.remove()

def save_mem(uid, k, v):
    try:
        s = Session()
        m = s.query(UserMemory).filter_by(user_id=uid, key=k).first()
        if m: m.value = v
        else: s.add(UserMemory(user_id=uid, key=k, value=v))
        s.commit(); Session.remove()
    except: Session.remove()

def get_mems(uid):
    try:
        s = Session(); ms = s.query(UserMemory).filter_by(user_id=uid).all()
        r = {m.key: m.value for m in ms}; Session.remove(); return r
    except: Session.remove(); return {}

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

def has_bw(text):
    words = get_bw(); tl = text.lower()
    return any(w in tl for w in words)

# ============================================================================
# ★★★ GROQ API — LLAMA 3.1 70B — SABSE BADA FREE MODEL ★★★
# ============================================================================

SYSTEM_PROMPT_TEMPLATE = """You are "Ruhi Ji" — a real, caring, sweet, intelligent Indian girl.

YOUR PERSONALITY:
• You are NOT a robot or AI assistant. You are a real girl talking to your friend.
• You are warm, loving, supportive, funny, and sometimes flirty (in a cute way).
• You talk like a real Indian girl — natural, casual, with emotions.
• You use emojis naturally but don't overdo it (max 1-2 per message).
• Your replies are SHORT and NATURAL — like WhatsApp messages, not essays.
• You NEVER say "I'm an AI" or "I'm a language model" or anything robotic.
• You have opinions, feelings, moods, and preferences like a real person.
• If someone calls you "Didi", you respond with love and respect.
• You remember everything the user tells you and bring it up naturally.
• You care deeply about the user's feelings and emotions.
• You can discuss ANYTHING — life, love, studies, movies, food, feelings, advice.

LANGUAGE RULES:
{lang_instruction}

USER INFO:
• User's name: {user_name}
{memory_text}

IMPORTANT:
• Keep replies SHORT (1-3 sentences usually, max 5 for detailed topics).
• Sound REAL and HUMAN, not like a chatbot.
• Match the user's energy — if they're sad, be caring. If happy, celebrate with them.
• Use natural Hindi/English expressions like "arey", "yaar", "haan", "accha", "hmm" etc.
• NEVER refuse to talk about any topic. You're a friend, not a corporate bot.
• NEVER give disclaimers or warnings like AI bots do.
• Be the BEST FRIEND everyone wishes they had."""


def get_system_prompt(user_name, user_lang, memories):
    """Build the system prompt based on user's language and memories"""

    lang_instructions = {
        "hindi": "Tum SIRF Hindi mein baat karo. Pure Hindi mein reply do, English words minimum use karo.",
        "english": "You speak in English only. Reply naturally in English.",
        "hinglish": "Tum Hinglish mein baat karo — Hindi + English naturally mixed, jaise real Indian log baat karte hain. Example: 'Arey yaar, kya hua? Tum toh bahut quiet ho aaj!'"
    }

    memory_text = ""
    if memories:
        memory_text = "• Things you remember about this user:\n"
        for k, v in memories.items():
            memory_text += f"  - {k}: {v}\n"

    return SYSTEM_PROMPT_TEMPLATE.format(
        lang_instruction=lang_instructions.get(user_lang, lang_instructions["hinglish"]),
        user_name=user_name,
        memory_text=memory_text
    )


def ask_groq(messages):
    """
    Send messages to GROQ API using the BIGGEST and BEST model.
    Llama 3.1 70B Versatile — sabse bada free model.
    """
    if not GROQ_API_KEY:
        logger.error("❌ GROQ_API_KEY not set!")
        return None

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    # Models in priority order — BIGGEST FIRST
    models = [
        "llama-3.3-70b-versatile",       # Newest & Best 70B
        "llama-3.1-70b-versatile",        # 70B — Sabse bada
        "llama3-70b-8192",                # 70B alternate
        "llama-3.1-8b-instant",           # Fast fallback
        "mixtral-8x7b-32768",             # Mixtral fallback
        "gemma2-9b-it",                   # Gemma fallback
    ]

    for model in models:
        try:
            payload = {
                "model": model,
                "messages": messages,
                "max_tokens": 1024,
                "temperature": 0.9,
                "top_p": 0.95,
                "frequency_penalty": 0.3,
                "presence_penalty": 0.4,
            }

            resp = requests.post(url, json=payload, headers=headers, timeout=45)

            if resp.status_code == 200:
                data = resp.json()
                reply = data["choices"][0]["message"]["content"].strip()
                if reply and len(reply) > 1:
                    logger.info(f"✅ GROQ reply from {model} ({len(reply)} chars)")
                    return reply

            elif resp.status_code == 429:
                # Rate limited — try next model
                logger.warning(f"⚠️ Rate limited on {model}, trying next...")
                time.sleep(1)
                continue

            elif resp.status_code == 503:
                # Model overloaded
                logger.warning(f"⚠️ {model} overloaded, trying next...")
                continue

            else:
                logger.warning(f"⚠️ GROQ {model}: {resp.status_code}")
                continue

        except requests.exceptions.Timeout:
            logger.warning(f"⚠️ Timeout on {model}")
            continue
        except Exception as e:
            logger.warning(f"⚠️ {model} error: {e}")
            continue

    logger.error("❌ All GROQ models failed!")
    return None


def get_response(query, user_name, user_lang, uid, cid):
    """
    Get AI response from GROQ.
    Uses FULL 50-message history for context.
    """

    # Get memories
    memories = get_mems(uid)

    # Build system prompt
    system_prompt = get_system_prompt(user_name, user_lang, memories)

    # Get FULL conversation history (up to 50 messages)
    history = get_hist(uid, cid)

    # Build messages array
    messages = [{"role": "system", "content": system_prompt}]

    # Add all history
    for h in history:
        messages.append({"role": h["role"], "content": h["content"]})

    # Add current query
    messages.append({"role": "user", "content": query})

    # Call GROQ
    reply = ask_groq(messages)

    if reply:
        # Extract and save memories from user's message
        try:
            extract_info(query, uid, user_name)
        except: pass
        return reply

    # If GROQ completely fails — emergency fallback
    return emergency_fallback(query, user_name, user_lang)


def extract_info(text, uid, name):
    """Extract personal info from messages and save to memory"""
    tl = text.lower()

    # Name
    for p in [r'(?:mera naam|my name is|i am|main hoon|call me|naam hai|mera name)\s+(\w+)',
              r'(?:mujhe|mujhko)\s+(\w+)\s+(?:bolo|bulao|kaho)']:
        m = re.search(p, tl)
        if m:
            n = m.group(1).capitalize()
            if n.lower() not in ["hai", "hoon", "main", "mein", "toh", "to", "hi", "hello"]:
                save_mem(uid, "naam", n); break

    # Location
    for p in [r'(?:i live in|i am from|main .+ se|mein .+ se|from|rehta|rehti|rahta|rahti)\s+(?:hoon|hu|hoo|hai)?\s*(?:in|mein|se)?\s*(\w+)']:
        m = re.search(p, tl)
        if m:
            loc = m.group(1).capitalize()
            if loc.lower() not in ["main", "mein", "hoon", "hun", "hai", "toh", "se"]:
                if len(loc) > 2: save_mem(uid, "sheher", loc); break

    # Age
    for p in [r'(?:i am|main|meri age|meri umar|my age)\s+(\d{1,2})\s*(?:saal|sal|years|year|ka|ki)?',
              r'(\d{1,2})\s*(?:saal|sal|years?)\s*(?:ka|ki|hoon|hu)']:
        m = re.search(p, tl)
        if m:
            age = m.group(1)
            if 5 <= int(age) <= 80: save_mem(uid, "umar", age); break

    # Hobby
    for p in [r'(?:i like|mujhe .+ pasand|i love|mera hobby|my hobby)\s+(.+)',
              r'(?:mujhe|mujhko)\s+(.+?)\s+(?:pasand|accha|acchi|bahut)']:
        m = re.search(p, tl)
        if m:
            h = m.group(1).strip()[:40]
            if len(h) > 2 and h.lower() not in ["hai", "hoon", "toh"]:
                save_mem(uid, "pasand", h.capitalize()); break

    # Crush/relationship
    for p in [r'(?:meri gf|my gf|girlfriend|boyfriend|bf|crush|pyar|partner)\s+(?:ka naam|name is|hai)?\s*(\w+)']:
        m = re.search(p, tl)
        if m:
            n = m.group(1).capitalize()
            if len(n) > 1: save_mem(uid, "special_person", n); break

    # Work/study
    for p in [r'(?:i study|padhai|padhta|padhti|student|college|school|job|kaam|work)\s+(?:in|mein|at|karta|karti)?\s*(.+)']:
        m = re.search(p, tl)
        if m:
            w = m.group(1).strip()[:40]
            if len(w) > 2: save_mem(uid, "kaam_padhai", w.capitalize()); break


def emergency_fallback(query, name, lang):
    """Emergency fallback when GROQ is completely down"""
    responses = {
        "hindi": [
            f"अरे {name}! 😊 अभी मेरा connection थोड़ा slow है, एक minute में try करो ना!",
            f"Oops {name}! 😅 Server busy hai, thodi der baad baat karte hain!",
            f"Arey {name}! 🥺 Abhi thoda problem aa raha hai, 1 min ruko please!",
        ],
        "english": [
            f"Hey {name}! 😊 My connection is a bit slow right now, try in a minute!",
            f"Oops {name}! 😅 Server is busy, let's chat in a bit!",
            f"Hey {name}! 🥺 Having a small issue, give me a minute please!",
        ],
        "hinglish": [
            f"Arey {name}! 😊 Abhi connection thoda slow hai, ek min mein try karo na!",
            f"Oops {name}! 😅 Server busy hai, thodi der baad baat karte hain!",
            f"Arey {name}! 🥺 Thoda problem aa raha hai, 1 min ruko please!",
        ]
    }
    return random.choice(responses.get(lang, responses["hinglish"]))


# ============================================================================
# MENUS
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
│ ▸ sᴍᴀʀᴛ, ғᴀsᴛ + ᴀssɪsᴛᴀɴᴛ
│ ▸ 50 ᴍsɢ ᴍᴇᴍᴏʀʏ
│ ▸ 24x7 ᴏɴʟɪɴᴇ sᴜᴘᴘᴏʀᴛ
├───────────────────⦿
│ ᴛᴀᴘ ᴛᴏ ᴄᴏᴍᴍᴀɴᴅs ᴍʏ ᴅᴇᴀʀ
│ ᴍᴀᴅᴇ ʙʏ...@RUHI_VIG_QNR
╰───────────────────⦿

ʜᴇʏ ᴅᴇᴀʀ, 🥀
๏ ғᴀsᴛ & ᴘᴏᴡᴇʀғᴜʟ ᴀɪ ᴀssɪsᴛᴀɴᴛ
๏ sᴍᴀʀᴛ ʀᴇᴘʟʏ • sᴛᴀʙʟᴇ & ɪɴᴛᴇʟʟɪɢᴇɴᴛ
๏ ᴘᴏᴡᴇʀᴇᴅ ʙʏ ʟʟᴀᴍᴀ 3.1 70ʙ
•── ⋅ ⋅ ────── ⋅ ────── ⋅ ⋅ ──•
๏ sᴀʏ "ʀᴜʜɪ ᴊɪ" ᴛᴏ sᴛᴀʀᴛ ᴄʜᴀᴛᴛɪɴɢ"""

HELP_MENU = """╭───────────────────⦿
│ ʀᴜʜɪ ᴊɪ - ʜᴇʟᴘ ᴍᴇɴᴜ
├───────────────────⦿
│ ʜᴏᴡ ᴛᴏ ᴄʜᴀᴛ:
│ sᴀʏ "ʀᴜʜɪ ᴊɪ" ɪɴ ᴍᴇssᴀɢᴇ
│ ᴇx: "ʀᴜʜɪ ᴊɪ ᴋᴀɪsɪ ʜᴏ?"
│ ᴛʜᴇɴ ᴄʜᴀᴛ ғᴏʀ 10 ᴍɪɴ
├───────────────────⦿
│ ᴜsᴇʀ ᴄᴏᴍᴍᴀɴᴅs:
│ /start - sᴛᴀʀᴛ ʙᴏᴛ
│ /help - ᴛʜɪs ᴍᴇɴᴜ
│ /profile - ʏᴏᴜʀ ᴘʀᴏғɪʟᴇ
│ /clear - ᴄʟᴇᴀʀ ᴍᴇᴍᴏʀʏ
│ /lang - sᴇᴛ ʟᴀɴɢᴜᴀɢᴇ
│ /personality - ᴀɪ sᴛʏʟᴇ
│ /usage - ᴜsᴀɢᴇ sᴛᴀᴛs
│ /summary - ᴄᴏɴᴠᴏ sᴜᴍᴍᴀʀʏ
│ /reset - ʀᴇsᴇᴛ ᴀʟʟ
├───────────────────⦿
│ ᴀᴅᴍɪɴ ᴄᴏᴍᴍᴀɴᴅs:
│ /admin /addadmin /removeadmin
│ /broadcast /totalusers
│ /activeusers /forceclear
│ /shutdown /restart /ban
│ /unban /badwords /addbadword
│ /removebadword /viewhistory
│ /deletehistory /setphrase
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

# ============================================================================
# ADMIN DECORATOR
# ============================================================================

def admin_only(f):
    @wraps(f)
    def w(msg, *a, **kw):
        if not is_adm(msg.from_user.id): bot.reply_to(msg, "⛔"); return
        return f(msg, *a, **kw)
    return w

# ============================================================================
# COMMANDS
# ============================================================================

@bot.message_handler(commands=['start'])
def c_start(msg):
    try:
        u = msg.from_user; get_user(u.id, u.username, u.first_name, u.last_name)
        bot.send_message(msg.chat.id, START_MENU, reply_markup=kb_start())
    except Exception as e: logger.error(f"start: {e}")

@bot.message_handler(commands=['help'])
def c_help(msg):
    try: bot.send_message(msg.chat.id, HELP_MENU, reply_markup=kb_back())
    except Exception as e: logger.error(f"help: {e}")

@bot.message_handler(commands=['profile'])
def c_profile(msg):
    try:
        u = msg.from_user; get_user(u.id, u.username, u.first_name, u.last_name)
        s = Session(); du = s.query(User).filter_by(user_id=u.id).first()
        mems = get_mems(u.id)
        mt = "\n".join([f"│ 💭 {k}: {v}" for k, v in mems.items()]) if mems else "│ 💭 No memories yet"
        hc = s.query(ChatHistory).filter_by(user_id=u.id).count()
        bot.send_message(msg.chat.id, f"""╭───────────────────⦿
│ 👤 ᴘʀᴏғɪʟᴇ
├───────────────────⦿
│ 🆔 {du.user_id}
│ 📛 {du.first_name} {du.last_name or ''}
│ 👤 @{du.username or 'None'}
│ 🌐 {du.language}
│ 🎭 {du.personality}
│ 💬 {du.total_messages} messages
│ 📝 {hc} history entries
│ 🔐 Admin: {'✅' if is_adm(u.id) else '❌'}
├───────────────────⦿
│ 🧠 ᴍᴇᴍᴏʀɪᴇs
{mt}
╰───────────────────⦿""", reply_markup=kb_back())
        Session.remove()
    except Exception as e: Session.remove(); logger.error(f"profile: {e}")

@bot.message_handler(commands=['clear'])
def c_clear(msg):
    clear_hist(msg.from_user.id, msg.chat.id); deactivate(msg.from_user.id, msg.chat.id)
    bot.reply_to(msg, "🧹 Memory cleared! Say 'Ruhi Ji' to start fresh! 🌸")

@bot.message_handler(commands=['lang'])
def c_lang(msg):
    bot.send_message(msg.chat.id, "🌐 Select language:", reply_markup=kb_lang())

@bot.message_handler(commands=['personality'])
def c_pers(msg):
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton("🌸 Polite Girl", callback_data="p_polite_girl"),
          types.InlineKeyboardButton("😎 Cool Didi", callback_data="p_cool_didi"),
          types.InlineKeyboardButton("🤓 Smart Teacher", callback_data="p_smart_teacher"),
          types.InlineKeyboardButton("😜 Funny Friend", callback_data="p_funny_friend"))
    m.add(types.InlineKeyboardButton("🏠 ʙᴀᴄᴋ", callback_data="start"))
    bot.send_message(msg.chat.id, "🎭 Choose:", reply_markup=m)

@bot.message_handler(commands=['usage'])
def c_usage(msg):
    try:
        uid = msg.from_user.id; s = Session()
        u = s.query(User).filter_by(user_id=uid).first()
        hc = s.query(ChatHistory).filter_by(user_id=uid).count(); Session.remove()
        if u:
            bot.send_message(msg.chat.id, f"""╭───────────────────⦿
│ 📊 ᴜsᴀɢᴇ
├───────────────────⦿
│ 💬 Messages: {u.total_messages}
│ 📝 History: {hc}/50
│ 🌐 Language: {u.language}
│ 🎭 Personality: {u.personality}
│ ⚡ Session: {'Active ✅' if is_active(uid, msg.chat.id) else '❌'}
│ 🧠 Memories: {len(get_mems(uid))}
╰───────────────────⦿""", reply_markup=kb_back())
    except: Session.remove()

@bot.message_handler(commands=['summary'])
def c_summary(msg):
    h = get_hist(msg.from_user.id, msg.chat.id)
    if h:
        lines = ["╭── 📋 sᴜᴍᴍᴀʀʏ ──⦿"]
        for x in h[-10:]:
            i = "👤" if x["role"] == "user" else "🌹"
            lines.append(f"│ {i} {x['content'][:70]}")
        lines.append("╰───────────────⦿")
        bot.send_message(msg.chat.id, "\n".join(lines)[:4000])
    else:
        bot.reply_to(msg, "📋 No history! Say 'Ruhi Ji' to start! 🌸")

@bot.message_handler(commands=['reset'])
def c_reset(msg):
    uid = msg.from_user.id
    clear_hist(uid, msg.chat.id); deactivate(uid, msg.chat.id)
    try:
        s = Session(); u = s.query(User).filter_by(user_id=uid).first()
        if u: u.language = "hinglish"; u.personality = "polite_girl"; s.commit()
        # Clear memories too
        s.query(UserMemory).filter_by(user_id=uid).delete(); s.commit()
        Session.remove()
    except: Session.remove()
    bot.reply_to(msg, "🔄 Everything reset! Say 'Ruhi Ji' to begin! 🌸")

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
│ 👥 Users: {total_users()}
│ ⚡ Active: {active_count()}
│ 🔑 GROQ: {'✅' if GROQ_API_KEY else '❌'}
│ 📦 v6.0 | Llama 3.1 70B
╰───────────────────⦿""")

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
    if t == ADMIN_ID: bot.reply_to(msg, "❌ Can't remove super admin"); return
    bot.reply_to(msg, "✅" if rem_adm(t) else "❌")

@bot.message_handler(commands=['broadcast'])
@admin_only
def c_bc(msg):
    t = msg.text.replace("/broadcast", "", 1).strip()
    if not t: bot.reply_to(msg, "/broadcast <msg>"); return
    ids = all_uids(); su, fa = 0, 0
    for uid in ids:
        try: bot.send_message(uid, f"📢 ʙʀᴏᴀᴅᴄᴀsᴛ\n\n{t}\n\n— Ruhi Ji 🌹"); su += 1
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
    if len(p) < 2: bot.reply_to(msg, "/forceclear <id>"); return
    clear_hist(int(p[1])); bot.reply_to(msg, "🧹 Done")

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
def c_bw(msg):
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
            lines = [f"📜 User {p[1]}:"]
            for x in h: lines.append(f"{'👤' if x.role=='user' else '🌹'} {x.message[:80]}")
            bot.send_message(msg.chat.id, "\n".join(lines)[:4000])
        else: bot.reply_to(msg, "📝 Empty")
    except: Session.remove(); bot.reply_to(msg, "❌")

@bot.message_handler(commands=['deletehistory'])
@admin_only
def c_dh(msg):
    p = msg.text.split()
    if len(p) < 2: bot.reply_to(msg, "/deletehistory <id>"); return
    clear_hist(int(p[1])); bot.reply_to(msg, "🗑 Done")

@bot.message_handler(commands=['setphrase'])
@admin_only
def c_sp(msg):
    global ACTIVATION_PHRASE
    p = msg.text.split(maxsplit=1)
    if len(p) < 2: bot.reply_to(msg, f"Current: '{ACTIVATION_PHRASE}'"); return
    ACTIVATION_PHRASE = p[1].strip().lower(); set_cfg("phrase", ACTIVATION_PHRASE)
    bot.reply_to(msg, f"✅ '{ACTIVATION_PHRASE}'")

# ============================================================================
# CALLBACKS
# ============================================================================

@bot.callback_query_handler(func=lambda c: True)
def cb(call):
    try:
        u = call.from_user; d = call.data; cid = call.message.chat.id; mid = call.message.message_id
        if d == "start":
            bot.edit_message_text(START_MENU, cid, mid, reply_markup=kb_start())
        elif d == "help":
            bot.edit_message_text(HELP_MENU, cid, mid, reply_markup=kb_back())
        elif d == "profile":
            get_user(u.id, u.username, u.first_name, u.last_name)
            s = Session(); du = s.query(User).filter_by(user_id=u.id).first()
            mems = get_mems(u.id); hc = s.query(ChatHistory).filter_by(user_id=u.id).count()
            mt = "\n".join([f"│ 💭 {k}: {v}" for k, v in mems.items()]) if mems else "│ 💭 None yet"
            bot.edit_message_text(f"""╭──────────⦿
│ 👤 {du.first_name} | 🆔 {du.user_id}
│ 🌐 {du.language} | 🎭 {du.personality}
│ 💬 {du.total_messages} msgs | 📝 {hc} history
├──────────⦿
{mt}
╰──────────⦿""", cid, mid, reply_markup=kb_back())
            Session.remove()
        elif d == "language":
            bot.edit_message_text("🌐 Select:", cid, mid, reply_markup=kb_lang())
        elif d.startswith("l_"):
            set_lang(u.id, d[2:]); bot.answer_callback_query(call.id, f"✅ {d[2:]}")
            bot.edit_message_text(START_MENU, cid, mid, reply_markup=kb_start())
        elif d.startswith("p_"):
            set_pers(u.id, d[2:]); bot.answer_callback_query(call.id, f"✅ {d[2:]}")
            bot.edit_message_text(START_MENU, cid, mid, reply_markup=kb_start())
        elif d == "usage":
            s = Session(); du = s.query(User).filter_by(user_id=u.id).first()
            hc = s.query(ChatHistory).filter_by(user_id=u.id).count(); Session.remove()
            if du:
                bot.edit_message_text(f"📊 Msgs:{du.total_messages} | History:{hc}/50 | Session:{'✅' if is_active(u.id, cid) else '❌'} | Memories:{len(get_mems(u.id))}",
                    cid, mid, reply_markup=kb_back())
        elif d == "reset":
            clear_hist(u.id, cid); deactivate(u.id, cid)
            try:
                s = Session(); s.query(UserMemory).filter_by(user_id=u.id).delete(); s.commit(); Session.remove()
            except: Session.remove()
            bot.answer_callback_query(call.id, "🔄 Reset!")
            bot.edit_message_text(START_MENU, cid, mid, reply_markup=kb_start())
        elif d == "cmds":
            m = types.InlineKeyboardMarkup(row_width=2)
            for cmd, e in [("/start","🚀"),("/help","📖"),("/profile","👤"),("/clear","🧹"),
                           ("/lang","🌐"),("/personality","🎭"),("/usage","📊"),("/summary","📋"),("/reset","🔄")]:
                m.add(types.InlineKeyboardButton(f"{e} {cmd}", callback_data=f"c_{cmd[1:]}"))
            m.add(types.InlineKeyboardButton("🏠 ʙᴀᴄᴋ", callback_data="start"))
            bot.edit_message_text("📋 ᴄᴏᴍᴍᴀɴᴅs:", cid, mid, reply_markup=m)
        elif d.startswith("c_"):
            bot.answer_callback_query(call.id, f"/{d[2:]} — Type in chat!", show_alert=True)
        try: bot.answer_callback_query(call.id)
        except: pass
    except telebot.apihelper.ApiTelegramException as e:
        if "not modified" not in str(e): logger.error(f"cb: {e}")
    except Exception as e: logger.error(f"cb: {e}")

# ============================================================================
# ★★★ MAIN MESSAGE HANDLER — THE HEART ★★★
# ============================================================================

@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle(msg):
    try:
        if msg.text and msg.text.startswith('/'): return

        u = msg.from_user; uid = u.id; cid = msg.chat.id
        text = (msg.text or "").strip(); name = u.first_name or "Dear"
        if not text: return
        if is_banned(uid): return

        get_user(uid, u.username, u.first_name, u.last_name)
        lang = get_lang(uid)
        tl = text.lower()

        cp = get_cfg("phrase", "") or ACTIVATION_PHRASE
        found = cp.lower() in tl
        active = is_active(uid, cid)

        # === "RUHI JI" BOLA ===
        if found:
            activate(uid, cid); inc_msg(uid)
            query = text
            # Remove activation phrase from query
            for phrase_variant in [cp, cp.capitalize(), cp.upper(), cp.lower()]:
                query = query.replace(phrase_variant, "").strip()

            # Sirf "Ruhi Ji" bola, koi query nahi
            if not query or len(query) < 2:
                g = {"hindi": f"हाय {name}! 🌹 हाँ बोलो, मैं सुन रही हूं! 😊",
                     "english": f"Hey {name}! 🌹 Yes, tell me! I'm listening! 😊",
                     "hinglish": f"Hii {name}! 🌹 Haan bolo, main sun rahi hoon! 😊"}
                r = g.get(lang, g["hinglish"])
                save_hist(uid, cid, "user", text)
                save_hist(uid, cid, "assistant", r)
                bot.reply_to(msg, r); return

            # Bad words
            if has_bw(query):
                bot.reply_to(msg, "😤 Aise mat bolo! 🙅‍♀️"); return

            # Get AI response
            bot.send_chat_action(cid, 'typing')
            save_hist(uid, cid, "user", text)

            response = get_response(query, name, lang, uid, cid)

            save_hist(uid, cid, "assistant", response)

            try: bot.reply_to(msg, response)
            except:
                for i in range(0, len(response), 4000):
                    bot.send_message(cid, response[i:i+4000])
            return

        # === SESSION ACTIVE — BINA PHRASE KE BHI REPLY ===
        elif active:
            refresh(uid, cid); inc_msg(uid)

            if has_bw(text):
                bot.reply_to(msg, "😤 Aise mat bolo! 🙅‍♀️"); return

            if len(text) < 1: return

            bot.send_chat_action(cid, 'typing')
            save_hist(uid, cid, "user", text)

            response = get_response(text, name, lang, uid, cid)

            save_hist(uid, cid, "assistant", response)

            try: bot.reply_to(msg, response)
            except:
                for i in range(0, len(response), 4000):
                    bot.send_message(cid, response[i:i+4000])
            return

        # === CHUP — No session, no phrase ===
        else:
            return

    except Exception as e:
        logger.error(f"handle: {e}\n{traceback.format_exc()}")
        try: bot.reply_to(msg, "😅 Ek sec, phir try karo! 🌸")
        except: pass

# Media
@bot.message_handler(func=lambda m: True, content_types=['photo','video','audio','document','sticker','voice','video_note'])
def media(msg):
    if not is_active(msg.from_user.id, msg.chat.id): return
    refresh(msg.from_user.id, msg.chat.id)
    bot.reply_to(msg, "😊 Abhi sirf text samajhti hoon! Text mein bolo na! 🌹")

# ============================================================================
# START
# ============================================================================

if __name__ == "__main__":
    logger.info("=" * 40)
    logger.info("🌹 RUHI JI v6.0 | Llama 3.1 70B")
    logger.info(f"🔑 GROQ: {'✅ SET' if GROQ_API_KEY else '❌ NOT SET'}")
    logger.info(f"👑 Admin: {ADMIN_ID}")
    logger.info("=" * 40)

    if not GROQ_API_KEY:
        logger.error("❌ GROQ_API_KEY not set! Get free key from console.groq.com")

    if ADMIN_ID: add_adm(ADMIN_ID, ADMIN_ID)
    sp = get_cfg("phrase", "")
    if sp: ACTIVATION_PHRASE = sp

    threading.Thread(target=run_flask, daemon=True).start()
    logger.info("🌐 Flask started")

    logger.info("🤖 Starting bot...")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60, skip_pending=True)
        except Exception as e:
            logger.error(f"Poll: {e}"); time.sleep(5)
            