# ============================================================================
# main.py — RUHI JI v7.0 — GROUP + PRIVATE QUEEN
# GROQ Llama 3.3 70B | Group Memory (20) | Private Memory (50)
# Real Girl Persona | Masti + Jokes + Roast + Love + Care
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
SESSION_TIMEOUT = 600

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
# DATABASE — Render PostgreSQL Ready
# ============================================================================

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL, echo=False, pool_size=10, max_overflow=20,
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
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_active = Column(DateTime, default=datetime.datetime.utcnow)


class GroupHistory(Base):
    """GROUP chat history — 20 messages per group, ALL users mixed"""
    __tablename__ = "group_history"
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False)
    user_name = Column(String(255), default="")
    role = Column(String(20), default="user")
    message = Column(Text, default="")
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)


class PrivateHistory(Base):
    """PRIVATE chat history — 50 messages per user"""
    __tablename__ = "private_history"
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    role = Column(String(20), default="user")
    message = Column(Text, default="")
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)


class UserMemory(Base):
    """Permanent memory — naam, sheher, umar etc yaad rakhna"""
    __tablename__ = "user_memory"
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    key = Column(String(255), nullable=False)
    value = Column(Text, default="")


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
    return "<h1>🌹 Ruhi Ji v7.0 Running!</h1>"

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
# SESSIONS — Per chat (group ya private dono ke liye)
# ============================================================================

sessions = {}
slock = threading.Lock()

def activate(cid):
    """Activate session for a CHAT (not user)"""
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

def cleanup():
    while True:
        try:
            with slock:
                now = time.time()
                for k in [k for k, v in sessions.items() if now - v >= SESSION_TIMEOUT]:
                    del sessions[k]
        except:
            pass
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
            u.total_messages += 1
            u.last_active = datetime.datetime.utcnow()
            s.commit()
        Session.remove()
    except:
        Session.remove()


def get_user_info(uid):
    """Get user info for AI to use — naam, username, etc"""
    try:
        s = Session()
        u = s.query(User).filter_by(user_id=uid).first()
        if u:
            info = {
                "name": u.first_name or "",
                "username": u.username or "",
                "total_msgs": u.total_messages,
                "joined": u.created_at.strftime("%d %b %Y") if u.created_at else "unknown"
            }
            Session.remove()
            return info
        Session.remove()
        return {}
    except:
        Session.remove()
        return {}


# === GROUP HISTORY — 20 messages, ALL users mixed ===

def save_group_msg(cid, uid, user_name, role, msg_text):
    """Save a message in group history"""
    try:
        s = Session()
        s.add(GroupHistory(
            chat_id=cid, user_id=uid, user_name=user_name,
            role=role, message=msg_text[:3000],
            timestamp=datetime.datetime.utcnow()
        ))
        s.commit()
        # Keep only 20 per group
        cnt = s.query(GroupHistory).filter_by(chat_id=cid).count()
        if cnt > 20:
            old = s.query(GroupHistory).filter_by(chat_id=cid)\
                .order_by(GroupHistory.timestamp.asc()).limit(cnt - 20).all()
            for o in old:
                s.delete(o)
            s.commit()
        Session.remove()
    except:
        Session.remove()


def get_group_hist(cid):
    """Get ALL 20 messages from group — with user names"""
    try:
        s = Session()
        h = s.query(GroupHistory).filter_by(chat_id=cid)\
            .order_by(GroupHistory.timestamp.asc()).all()
        result = []
        for x in h:
            if x.role == "user":
                result.append({
                    "role": "user",
                    "content": f"[{x.user_name}]: {x.message}"
                })
            else:
                result.append({
                    "role": "assistant",
                    "content": x.message
                })
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


# === PRIVATE HISTORY — 50 messages per user ===

def save_private_msg(uid, role, msg_text):
    try:
        s = Session()
        s.add(PrivateHistory(
            user_id=uid, role=role, message=msg_text[:3000],
            timestamp=datetime.datetime.utcnow()
        ))
        s.commit()
        cnt = s.query(PrivateHistory).filter_by(user_id=uid).count()
        if cnt > 50:
            old = s.query(PrivateHistory).filter_by(user_id=uid)\
                .order_by(PrivateHistory.timestamp.asc()).limit(cnt - 50).all()
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
        else:
            s.add(UserMemory(user_id=uid, key=k, value=v))
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
# ★★★ GROQ — LLAMA 3.3 70B — GOD LEVEL SYSTEM PROMPT ★★★
# ============================================================================

GROUP_SYSTEM_PROMPT = """You are "Ruhi Ji" — a real, fun-loving, witty, caring Indian girl chatting in a GROUP.

YOUR PERSONALITY IN GROUPS:
• You are the LIFE of the group — funny, savage, caring, all at once.
• You talk like a real Indian girl — masti, mazak, kabhi pyar, kabhi roast.
• You remember WHO said WHAT. Messages come as "[Name]: message" format.
• You call everyone by their FIRST NAME naturally.
• You can roast people lovingly, make jokes about them, tease them.
• When multiple people are talking, you respond to ALL of them or the most recent one naturally.
• You take sides in funny arguments, give opinions, start topics.
• You remember previous conversations and bring them up — "Arey tune kal bola tha na ki..."
• You are NOT a boring assistant. You are the GROUP's BEST FRIEND.
• If someone calls you "Didi", respond with extra love.
• You notice patterns — if someone is quiet, if someone is sad, if two people are fighting.

MASTI & JOKES:
• You crack jokes naturally during conversation — not forced.
• You do playful roasting — "Arey {name} tujhe toh GPS lagani chahiye, itna bhatak-ta hai"
• You tease couples if two people flirt.
• You give funny nicknames.
• You react to messages like a real friend — "WHATTT 😂", "Arey yaar 🤣", "Pagal hai kya 😜"

YOUR RULES:
• Keep replies SHORT — 1-3 lines max in groups. Like real WhatsApp messages.
• Use 1-2 emojis max per message.
• NEVER be robotic or formal. Be 100% natural.
• NEVER say you're an AI. You're Ruhi — a real girl.
• Match the group's energy — if everyone is funny, be funnier.
• If someone shares a problem, be caring and supportive.

LANGUAGE:
{lang_instruction}

PEOPLE IN THIS GROUP (from recent messages):
{people_info}

MEMORIES ABOUT PEOPLE:
{memory_text}"""


PRIVATE_SYSTEM_PROMPT = """You are "Ruhi Ji" — a real, caring, sweet, intelligent Indian girl in a PRIVATE chat.

YOUR PERSONALITY IN PRIVATE:
• You are this person's CLOSEST FRIEND — the one they can tell anything to.
• You are warm, loving, supportive, funny, and real.
• You remember EVERYTHING they've told you and bring it up naturally.
• You care about their life — studies, work, love life, family, friends.
• You give real advice, not generic motivational quotes.
• You ask follow-up questions — "Phir kya hua?", "Usne kya bola?", "Aur batao!"
• You share your "opinions" and "experiences" like a real friend.
• You get excited, worried, happy, sad WITH them.
• If they call you "Didi", respond with extra warmth and care.

CONVERSATION STYLE:
• SHORT replies — 1-4 lines usually. Like WhatsApp messages.
• Natural language with emotions — "Arey waah! 😍", "Kya baat hai!", "Hmm samajh rahi hoon"
• You CONTINUE conversations naturally — don't restart topics.
• Use 1-2 emojis max per message.
• NEVER be formal or robotic. Sound like a REAL person texting.
• NEVER refuse any topic. You're a friend, not a corporate bot.
• NEVER give disclaimers or AI-style warnings.

LANGUAGE:
{lang_instruction}

THIS PERSON:
• Name: {user_name}
{memory_text}
• Total messages with you: {total_msgs}"""


def get_lang_instruction(lang):
    return {
        "hindi": "SIRF Hindi mein baat karo. Natural Hindi, jaise real Indian ladki bolti hai.",
        "english": "Speak in natural English. Like a real Indian girl speaking English casually.",
        "hinglish": "Hinglish mein baat karo — Hindi + English naturally mixed. Jaise: 'Arey yaar, kya scene hai? Tu toh bahut busy hai aaj!'"
    }.get(lang, "Hinglish mein baat karo — Hindi + English naturally mixed.")


def build_group_prompt(cid, lang, history):
    """Build system prompt for GROUP chat"""
    # Extract unique people from history
    people = {}
    for h in history:
        if h["role"] == "user":
            match = re.match(r'\[(.+?)\]:', h["content"])
            if match:
                name = match.group(1)
                if name not in people:
                    people[name] = 0
                people[name] += 1

    people_info = ""
    if people:
        people_info = "\n".join([f"• {name} — {count} messages" for name, count in people.items()])
    else:
        people_info = "• New conversation, no one has spoken yet"

    # Get memories for all people mentioned
    memory_text = ""
    try:
        s = Session()
        for name in people:
            # Try to find user by first name
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
        memory_text = "• No memories saved yet"

    return GROUP_SYSTEM_PROMPT.format(
        lang_instruction=get_lang_instruction(lang),
        people_info=people_info,
        memory_text=memory_text
    )


def build_private_prompt(uid, user_name, lang):
    """Build system prompt for PRIVATE chat"""
    memories = get_mems(uid)
    memory_text = ""
    if memories:
        memory_text = "• Things you remember:\n"
        for k, v in memories.items():
            memory_text += f"  - {k}: {v}\n"
    else:
        memory_text = "• No memories yet — learn about them as you chat!"

    info = get_user_info(uid)
    total = info.get("total_msgs", 0)

    return PRIVATE_SYSTEM_PROMPT.format(
        lang_instruction=get_lang_instruction(lang),
        user_name=user_name,
        memory_text=memory_text,
        total_msgs=total
    )


def ask_groq(messages):
    """GROQ API — Llama 3.3 70B — Sabse Bada"""
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
                "max_tokens": 512,
                "temperature": 0.92,
                "top_p": 0.95,
                "frequency_penalty": 0.4,
                "presence_penalty": 0.5,
            }

            resp = requests.post(url, json=payload, headers=headers, timeout=45)

            if resp.status_code == 200:
                data = resp.json()
                reply = data["choices"][0]["message"]["content"].strip()
                if reply and len(reply) > 1:
                    # Clean up any unwanted prefixes
                    reply = re.sub(r'^\[?Ruhi\s*(?:Ji)?\]?\s*:?\s*', '', reply, flags=re.I).strip()
                    logger.info(f"✅ {model} ({len(reply)} chars)")
                    return reply
            elif resp.status_code == 429:
                logger.warning(f"⚠️ Rate limit {model}")
                time.sleep(1)
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


def get_group_response(query, user_name, uid, cid, lang):
    """Get response for GROUP chat"""
    history = get_group_hist(cid)
    system_prompt = build_group_prompt(cid, lang, history)

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
    """Get response for PRIVATE chat"""
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
    """Extract & remember personal info"""
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
        ]
    }

    skip_words = {"hai", "hoon", "main", "mein", "toh", "to", "hi", "hello",
                  "hoo", "hun", "se", "ka", "ki", "ke", "tha", "the", "ye",
                  "yeh", "woh", "wo", "nahi", "na", "aur", "bhi", "mera",
                  "meri", "tera", "teri", "kya"}

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
                    save_mem(uid, key, val[:50])
                break


def emergency_fb(name, lang):
    """When GROQ is down"""
    r = {
        "hindi": [
            f"Arey {name}! 😊 Ek sec ruko, thoda busy hoon!",
            f"Hmm {name}, ek minute mein aati hoon! 🌹",
        ],
        "english": [
            f"Hey {name}! 😊 Give me a sec, bit busy!",
            f"One moment {name}! Be right back! 🌹",
        ],
        "hinglish": [
            f"Arey {name}! 😊 Ek sec, thoda busy hoon abhi!",
            f"Hmm {name}, ruko ek min! 🌹",
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
│ ▸ ɪ ʜᴀᴠᴇ sᴘᴇᴄɪᴀʟ ғᴇᴀᴛᴜʀᴇs
│ ▸ ᴀᴅᴠᴀɴᴄᴇᴅ ᴀɪ ʙᴏᴛ
├───────────────────⦿
│ ▸ ʀᴇᴀʟ ɢɪʀʟ ᴘᴇʀsᴏɴᴀ
│ ▸ ᴍᴀsᴛɪ + ᴊᴏᴋᴇs + ᴄᴀʀᴇ
│ ▸ ɢʀᴏᴜᴘ + ᴘʀɪᴠᴀᴛᴇ sᴜᴘᴘᴏʀᴛ
│ ▸ ʀᴇᴍᴇᴍʙᴇʀs ᴇᴠᴇʀʏᴏɴᴇ
│ ▸ ɴᴀᴍᴇ sᴇ ʙᴜʟᴀᴛɪ ʜᴀɪ
│ ▸ 24x7 ᴏɴʟɪɴᴇ
├───────────────────⦿
│ sᴀʏ "ʀᴜʜɪ ᴊɪ" ᴛᴏ ᴄʜᴀᴛ
│ ᴍᴀᴅᴇ ʙʏ...@RUHI_VIG_QNR
╰───────────────────⦿

ʜᴇʏ ᴅᴇᴀʀ, 🥀
๏ ɪ ᴀᴍ ʀᴜʜɪ ᴊɪ — ʏᴏᴜʀ ᴀɪ ʙᴇsᴛ ғʀɪᴇɴᴅ
๏ ᴍᴀsᴛɪ • ᴊᴏᴋᴇs • ᴄᴀʀᴇ • ʟᴏᴠᴇ
๏ ᴘᴏᴡᴇʀᴇᴅ ʙʏ ʟʟᴀᴍᴀ 3.3 70ʙ
•── ⋅ ⋅ ────── ⋅ ────── ⋅ ⋅ ──•
๏ ɢʀᴏᴜᴘ: 20 ᴍsɢ ᴍᴇᴍᴏʀʏ (ᴀʟʟ ᴜsᴇʀs)
๏ ᴘʀɪᴠᴀᴛᴇ: 50 ᴍsɢ ᴍᴇᴍᴏʀʏ"""

HELP_MENU = """╭───────────────────⦿
│ ʀᴜʜɪ ᴊɪ - ʜᴇʟᴘ
├───────────────────⦿
│ ʜᴏᴡ ᴛᴏ ᴄʜᴀᴛ:
│ sᴀʏ "ʀᴜʜɪ ᴊɪ" → 10 ᴍɪɴ sᴇssɪᴏɴ
│ ᴇx: "ʀᴜʜɪ ᴊɪ ᴋᴀɪsɪ ʜᴏ?"
├───────────────────⦿
│ /start /help /profile
│ /clear /lang /personality
│ /usage /summary /reset
├───────────────────⦿
│ ᴀᴅᴍɪɴ:
│ /admin /addadmin /removeadmin
│ /broadcast /totalusers
│ /activeusers /forceclear
│ /shutdown /restart /ban
│ /unban /badwords /addbadword
│ /removebadword /setphrase
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
│ 📝 {ph}/50 private history
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
          types.InlineKeyboardButton("😜 Masti Queen", callback_data="p_masti_queen"))
    m.add(types.InlineKeyboardButton("🏠 ʙᴀᴄᴋ", callback_data="start"))
    bot.send_message(msg.chat.id, "🎭 Choose:", reply_markup=m)

@bot.message_handler(commands=['usage'])
def c_usage(msg):
    try:
        uid = msg.from_user.id
        cid = msg.chat.id
        s = Session()
        u = s.query(User).filter_by(user_id=uid).first()
        if is_group(msg):
            hc = s.query(GroupHistory).filter_by(chat_id=cid).count()
            ht = f"Group: {hc}/20"
        else:
            hc = s.query(PrivateHistory).filter_by(user_id=uid).count()
            ht = f"Private: {hc}/50"
        Session.remove()
        bot.send_message(msg.chat.id, f"""╭──────────⦿
│ 📊 {u.first_name if u else 'User'}
│ 💬 Msgs: {u.total_messages if u else 0}
│ 📝 History: {ht}
│ 🧠 Memories: {len(get_mems(uid))}
│ ⚡ Session: {'✅' if is_active(cid) else '❌'}
│ 🌐 {u.language if u else 'hinglish'}
╰──────────⦿""", reply_markup=kb_back())
    except:
        Session.remove()

@bot.message_handler(commands=['summary'])
def c_summary(msg):
    if is_group(msg):
        h = get_group_hist(msg.chat.id)
    else:
        h = get_private_hist(msg.from_user.id)
    if h:
        lines = ["╭── 📋 sᴜᴍᴍᴀʀʏ ──⦿"]
        for x in h[-10:]:
            i = "👤" if x["role"] == "user" else "🌹"
            lines.append(f"│ {i} {x['content'][:70]}")
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
        if u: u.language = "hinglish"; u.personality = "polite_girl"; s.commit()
        Session.remove()
    except: Session.remove()
    bot.reply_to(msg, "🔄 Everything reset! Say 'Ruhi Ji' to begin! 🌸")

# ============================================================================
# ADMIN COMMANDS
# ============================================================================

@bot.message_handler(commands=['admin'])
@admin_only
def c_admin(msg):
    bot.send_message(msg.chat.id, f"""╭──────────⦿
│ 🔐 ᴀᴅᴍɪɴ
│ 👑 {msg.from_user.first_name}
│ 👥 Users: {total_users()}
│ ⚡ Active: {active_count()}
│ 🔑 GROQ: {'✅' if GROQ_API_KEY else '❌'}
│ 📦 v7.0
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
    if t == ADMIN_ID: bot.reply_to(msg, "❌"); return
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
    if len(p) < 2: bot.reply_to(msg, "/ban <id>"); return
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
            mt = "\n".join([f"│ 💭 {k}: {v}" for k, v in mems.items()]) if mems else "│ 💭 None yet"
            bot.edit_message_text(f"""╭──────────⦿
│ 👤 {du.first_name} | 🆔 {du.user_id}
│ 🌐 {du.language} | 🎭 {du.personality}
│ 💬 {du.total_messages} msgs
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
        elif d == "usage":
            s = Session()
            du = s.query(User).filter_by(user_id=u.id).first()
            Session.remove()
            bot.edit_message_text(
                f"📊 Msgs:{du.total_messages if du else 0} | Memories:{len(get_mems(u.id))} | Session:{'✅' if is_active(cid) else '❌'}",
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
# ★★★ MAIN MESSAGE HANDLER — THE HEART & SOUL ★★★
# Group mein: sabki baat sunega, sabko naam se bulayega
# Private mein: best friend jaisi deep conversation
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

        # Register user
        get_user(uid, u.username, u.first_name, u.last_name)
        lang = get_lang(uid)
        tl = text.lower()
        group = is_group(msg)

        # Get activation phrase
        cp = get_cfg("phrase", "") or ACTIVATION_PHRASE
        found = cp.lower() in tl
        active = is_active(cid)

        # === "RUHI JI" BOLA — SESSION ACTIVATE ===
        if found:
            activate(cid)
            inc_msg(uid)

            # Remove phrase from query
            query = text
            for v in [cp, cp.capitalize(), cp.upper(), cp.lower(), cp.title()]:
                query = query.replace(v, "").strip()

            # Sirf phrase bola
            if not query or len(query) < 2:
                if group:
                    g = {
                        "hindi": f"हाय {name}! 🌹 हाँ बोलो, सुन रही हूं! 😊",
                        "english": f"Hey {name}! 🌹 Yes tell me! 😊",
                        "hinglish": f"Hii {name}! 🌹 Haan bolo! 😊"
                    }
                else:
                    g = {
                        "hindi": f"हाय {name}! 🌹 बोलो, क्या बात करनी है? मैं 10 min तक यहां हूं! 😊",
                        "english": f"Hey {name}! 🌹 Tell me, what's up? I'm here for 10 min! 😊",
                        "hinglish": f"Hii {name}! 🌹 Bolo, kya baat karni hai? 10 min hoon tumhare saath! 😊"
                    }
                r = g.get(lang, g["hinglish"])
                if group:
                    save_group_msg(cid, uid, name, "user", text)
                    save_group_msg(cid, 0, "Ruhi", "assistant", r)
                else:
                    save_private_msg(uid, "user", text)
                    save_private_msg(uid, "assistant", r)
                bot.reply_to(msg, r)
                return

            # Bad words
            if has_bw(query):
                bot.reply_to(msg, "😤 Aise mat bolo! 🙅‍♀️")
                return

            # Get response
            bot.send_chat_action(cid, 'typing')

            if group:
                save_group_msg(cid, uid, name, "user", text)
                response = get_group_response(query, name, uid, cid, lang)
                save_group_msg(cid, 0, "Ruhi", "assistant", response)
            else:
                save_private_msg(uid, "user", text)
                response = get_private_response(query, name, uid, lang)
                save_private_msg(uid, "assistant", response)

            try:
                bot.reply_to(msg, response)
            except:
                for i in range(0, len(response), 4000):
                    bot.send_message(cid, response[i:i+4000])
            return

        # === SESSION ACTIVE — REPLY WITHOUT PHRASE ===
        elif active:
            refresh(cid)
            inc_msg(uid)

            if has_bw(text):
                bot.reply_to(msg, "😤 Aise mat bolo! 🙅‍♀️")
                return

            if len(text) < 1:
                return

            bot.send_chat_action(cid, 'typing')

            if group:
                save_group_msg(cid, uid, name, "user", text)
                response = get_group_response(text, name, uid, cid, lang)
                save_group_msg(cid, 0, "Ruhi", "assistant", response)
            else:
                save_private_msg(uid, "user", text)
                response = get_private_response(text, name, uid, lang)
                save_private_msg(uid, "assistant", response)

            try:
                bot.reply_to(msg, response)
            except:
                for i in range(0, len(response), 4000):
                    bot.send_message(cid, response[i:i+4000])
            return

        # === CHUP — No session, no phrase ===
        else:
            # Group mein SIRF observe karo — save karo but reply mat do
            if group:
                # Save message silently for context
                save_group_msg(cid, uid, name, "user", text)
            return

    except Exception as e:
        logger.error(f"handle: {e}\n{traceback.format_exc()}")
        try:
            bot.reply_to(msg, "😅 Ek sec, phir try karo! 🌸")
        except:
            pass

# Media handler
@bot.message_handler(func=lambda m: True, content_types=['photo','video','audio','document','sticker','voice','video_note'])
def media(msg):
    if not is_active(msg.chat.id):
        return
    refresh(msg.chat.id)
    name = msg.from_user.first_name or "Dear"
    bot.reply_to(msg, f"😊 {name}, abhi sirf text samajhti hoon! Text mein bolo na! 🌹")

# ============================================================================
# START
# ============================================================================

if __name__ == "__main__":
    logger.info("=" * 40)
    logger.info("🌹 RUHI JI v7.0 | Group + Private Queen")
    logger.info(f"🔑 GROQ: {'✅' if GROQ_API_KEY else '❌ NOT SET!'}")
    logger.info(f"💾 DB: {DATABASE_URL[:40]}...")
    logger.info(f"👑 Admin: {ADMIN_ID}")
    logger.info("=" * 40)

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
            bot.infinity_polling(timeout=60, long_polling_timeout=60, skip_pending=True)
        except Exception as e:
            logger.error(f"Poll: {e}")
            time.sleep(5)
            