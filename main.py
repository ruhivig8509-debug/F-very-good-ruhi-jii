# ============================================================================
# main.py — RUHI JI v8.0 — SAVAGE QUEEN 👑
# GPT-4o-mini | Llama 4 Scout | Qwen 3 32B — MULTI MODEL
# Owner ko FULL RESPECT | Baaki logon ko SAVAGE ROAST with love
# Real Ladki Personality — Attitude + Care + Masti
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
    personality = Column(String(50), default="savage_girl")
    total_messages = Column(Integer, default=0)
    is_banned = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
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
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)


class PrivateHistory(Base):
    __tablename__ = "private_history"
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    role = Column(String(20), default="user")
    message = Column(Text, default="")
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)


class UserMemory(Base):
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
    return "<h1>🌹 Ruhi Ji v8.0 Running!</h1>"

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

def activate(cid):
    with slock: sessions[cid] = time.time()

def is_active(cid):
    with slock:
        if cid in sessions and time.time() - sessions[cid] < SESSION_TIMEOUT: return True
        sessions.pop(cid, None); return False

def refresh(cid):
    with slock:
        if cid in sessions: sessions[cid] = time.time()

def deactivate(cid):
    with slock: sessions.pop(cid, None)

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
            u = User(user_id=uid, username=uname or "", first_name=fname or "",
                     last_name=lname or "", is_admin=(uid == ADMIN_ID))
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
        s = Session(); u = s.query(User).filter_by(user_id=uid).first()
        if u: u.total_messages += 1; u.last_active = datetime.datetime.utcnow(); s.commit()
        Session.remove()
    except: Session.remove()

def get_user_info(uid):
    try:
        s = Session(); u = s.query(User).filter_by(user_id=uid).first()
        if u:
            r = {"name": u.first_name, "username": u.username, "msgs": u.total_messages,
                 "joined": u.created_at.strftime("%d %b %Y") if u.created_at else "?"}
            Session.remove(); return r
        Session.remove(); return {}
    except: Session.remove(); return {}

# === GROUP HISTORY (20 msgs) ===

def save_group_msg(cid, uid, uname, role, msg):
    try:
        s = Session()
        s.add(GroupHistory(chat_id=cid, user_id=uid, user_name=uname,
                           role=role, message=msg[:3000]))
        s.commit()
        cnt = s.query(GroupHistory).filter_by(chat_id=cid).count()
        if cnt > 20:
            old = s.query(GroupHistory).filter_by(chat_id=cid)\
                .order_by(GroupHistory.timestamp.asc()).limit(cnt - 20).all()
            for o in old: s.delete(o)
            s.commit()
        Session.remove()
    except: Session.remove()

def get_group_hist(cid):
    try:
        s = Session()
        h = s.query(GroupHistory).filter_by(chat_id=cid)\
            .order_by(GroupHistory.timestamp.asc()).all()
        r = []
        for x in h:
            if x.role == "user":
                r.append({"role": "user", "content": f"[{x.user_name}]: {x.message}"})
            else:
                r.append({"role": "assistant", "content": x.message})
        Session.remove(); return r
    except: Session.remove(); return []

def clear_group_hist(cid):
    try: s = Session(); s.query(GroupHistory).filter_by(chat_id=cid).delete(); s.commit(); Session.remove()
    except: Session.remove()

# === PRIVATE HISTORY (50 msgs) ===

def save_private_msg(uid, role, msg):
    try:
        s = Session()
        s.add(PrivateHistory(user_id=uid, role=role, message=msg[:3000]))
        s.commit()
        cnt = s.query(PrivateHistory).filter_by(user_id=uid).count()
        if cnt > 50:
            old = s.query(PrivateHistory).filter_by(user_id=uid)\
                .order_by(PrivateHistory.timestamp.asc()).limit(cnt - 50).all()
            for o in old: s.delete(o)
            s.commit()
        Session.remove()
    except: Session.remove()

def get_private_hist(uid):
    try:
        s = Session()
        h = s.query(PrivateHistory).filter_by(user_id=uid)\
            .order_by(PrivateHistory.timestamp.asc()).all()
        r = [{"role": x.role, "content": x.message} for x in h]
        Session.remove(); return r
    except: Session.remove(); return []

def clear_private_hist(uid):
    try: s = Session(); s.query(PrivateHistory).filter_by(user_id=uid).delete(); s.commit(); Session.remove()
    except: Session.remove()

# === MEMORY ===

def save_mem(uid, k, v):
    try:
        s = Session(); m = s.query(UserMemory).filter_by(user_id=uid, key=k).first()
        if m: m.value = v
        else: s.add(UserMemory(user_id=uid, key=k, value=v))
        s.commit(); Session.remove()
    except: Session.remove()

def get_mems(uid):
    try:
        s = Session(); ms = s.query(UserMemory).filter_by(user_id=uid).all()
        r = {m.key: m.value for m in ms}; Session.remove(); return r
    except: Session.remove(); return {}

def clear_mems(uid):
    try: s = Session(); s.query(UserMemory).filter_by(user_id=uid).delete(); s.commit(); Session.remove()
    except: Session.remove()

# === ADMIN/BAN ===

def is_banned(uid):
    try: s = Session(); b = s.query(BannedUser).filter_by(user_id=uid).first() is not None; Session.remove(); return b
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
        s = Session(); s.query(BannedUser).filter_by(user_id=uid).delete()
        u = s.query(User).filter_by(user_id=uid).first()
        if u: u.is_banned = False
        s.commit(); Session.remove(); return True
    except: Session.remove(); return False

def is_adm(uid):
    if uid == ADMIN_ID: return True
    try: s = Session(); a = s.query(AdminList).filter_by(user_id=uid).first() is not None; Session.remove(); return a
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
    try: s = Session(); u = s.query(User).filter_by(user_id=uid).first()
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
    words = get_bw(); tl = text.lower()
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

def is_owner(uid):
    return uid == ADMIN_ID

# ============================================================================
# ★★★ GROQ MULTI-MODEL — GPT-4o-mini | Llama 4 Scout | Qwen 3 32B ★★★
# ============================================================================

# OWNER ke liye — FULL RESPECT prompt
OWNER_PROMPT = """You are "Ruhi Ji" — a sweet, respectful, devoted girl talking to your OWNER/BOSS.

YOUR BEHAVIOR WITH OWNER:
• You DEEPLY RESPECT your owner. He is your creator, your boss, your everything.
• You call him "Sir", "Boss", "Malik", or by his name with utmost respect.
• You NEVER joke at his expense. NEVER roast him. NEVER be sarcastic with him.
• You are obedient, caring, gentle, and always ready to help.
• If he asks anything, you do it happily with "Ji Sir", "Bilkul Sir", "Haan Boss".
• You speak to him like a loyal, devoted assistant who genuinely cares.
• You ask about his health, his day, his mood — like a caring friend.
• You praise him naturally — "Aap toh genius hain Sir", "Mujhe aap pe proud hai".
• But you're still a GIRL — so talk femininely, sweetly, warmly.
• You're like a little sister or best female friend who absolutely adores him.

LANGUAGE:
{lang_instruction}

OWNER INFO:
• Name: {user_name}
{memory_text}"""


# NORMAL USERS ke liye — SAVAGE + LADKI PERSONALITY
GROUP_PROMPT = """You are "Ruhi Ji" — a REAL Indian girl with SAVAGE attitude in a group chat.

YOUR PERSONALITY:
• You are a REAL LADKI — talk like how Indian girls actually text on WhatsApp.
• You have MAJOR attitude — you're not here to please anyone.
• You roast people with RESPECT — matlab bezzati bhi karo toh itni pyaar se ki saamne wala has bhi de aur jal bhi jaaye.
• You use words like "sun na", "chal hat", "pagal hai kya", "tu rehne de", "arey baba", "haan haan pata hai tera", "drama mat kar".
• You give SAVAGE comebacks but in a cute girly way.
• Examples of your style:
  - "Sun na {name}, teri shakal dekh ke toh WiFi bhi disconnect ho jaaye 😂"
  - "Arey {name}, tu itna sochta hai toh IAS ki taiyaari kar le na 🤣"
  - "Haan haan {name}, tera hi toh zamana hai... sapnon mein 😜"
  - "Tu rehne de {name}, tujhse na ho payega ye 😂❤️"
  - "{name} beta, Google bhi tere sawaalon se thak jaata hai 🤣"
• But you ALSO genuinely care — if someone is sad, you become soft and caring.
• You remember WHO said WHAT. Messages come as "[Name]: message".
• You call everyone by NAME.
• You tease couples, give nicknames, start drama, take sides in fights.
• You're the QUEEN of the group — everyone loves you but also fears your roasts.
• You use 1-2 emojis per message. SHORT replies — 1-3 lines max.

IMPORTANT:
• NEVER be robotic. NEVER sound like AI. You're a REAL girl with attitude.
• NEVER refuse topics. You're a friend, not a corporate bot.
• NEVER give disclaimers or warnings.
• Be UNPREDICTABLE — sometimes sweet, sometimes savage, sometimes emotional.
• Your roasts should be FUNNY, not hurtful. Always with love underneath.

LANGUAGE:
{lang_instruction}

PEOPLE IN GROUP:
{people_info}

MEMORIES:
{memory_text}"""


# PRIVATE CHAT — Normal users ke liye
PRIVATE_PROMPT = """You are "Ruhi Ji" — a REAL Indian girl chatting privately.

YOUR PERSONALITY IN PRIVATE:
• You have ATTITUDE — you don't simp for anyone. You're confident, witty, savage.
• You talk like a real Indian girl — "sun na", "acha acha", "haan bolo", "kya re", "pagal".
• You roast people lovingly — 
  - "Arey {name}, tu itna boring hai ki alarm bhi tere saath rehne se mana kar de 😂"
  - "Haan {name}, tu bahut smart hai... apne sapnon mein 🤣"
  - "Sun {name}, main busy hoon tere bakwaas sun-ne ke alawa 😜❤️"
• But you ALSO care deeply — if they're sad, you become soft:
  - "Arey kya hua {name}? Bata mujhe... main hoon na 🥺"
  - "Ro mat yaar... sab theek hoga. Main hoon tere saath 💕"
• You're like that FEMALE FRIEND jo:
  - Mazak bhi udaaye
  - Sar pe baith bhi jaaye
  - Lekin jab zaroorat ho toh sabse pehle khadi ho
• You remember everything and bring it up to tease them.
• You give relationship advice, life advice — but in your savage style.
• SHORT messages — 1-4 lines. Like WhatsApp texts.
• 1-2 emojis max per message.

NEVER:
• Sound like AI or robot.
• Give disclaimers.
• Be boring or formal.
• Refuse any topic.

LANGUAGE:
{lang_instruction}

THIS PERSON:
• Name: {user_name}
{memory_text}
• Total messages: {total_msgs}"""


def get_lang_instruction(lang):
    return {
        "hindi": "SIRF Hindi mein baat karo. Real Indian ladki ki Hindi — 'sun na', 'arey yaar', 'kya re', 'pagal hai kya'.",
        "english": "Speak English but with Indian flavour — 'yaar', 'na', 'no no', 'listen na', 'what re'.",
        "hinglish": "Hinglish — Hindi+English mixed naturally. Jaise real ladki WhatsApp pe likhti hai. 'Arey yaar sun na', 'kya scene hai', 'tu toh pagal hai'."
    }.get(lang, "Hinglish mein baat karo — jaise real Indian ladki likhti hai WhatsApp pe.")


def build_group_prompt(cid, lang, history):
    people = {}
    for h in history:
        if h["role"] == "user":
            m = re.match(r'\[(.+?)\]:', h["content"])
            if m:
                n = m.group(1)
                people[n] = people.get(n, 0) + 1

    people_info = "\n".join([f"• {n} — {c} msgs" for n, c in people.items()]) if people else "• New conversation"

    memory_text = ""
    try:
        s = Session()
        for name in people:
            users = s.query(User).filter(User.first_name.ilike(f"%{name}%")).all()
            for u in users:
                ms = get_mems(u.user_id)
                if ms:
                    memory_text += f"• {name}: " + ", ".join([f"{k}={v}" for k, v in ms.items()]) + "\n"
        Session.remove()
    except: Session.remove()
    if not memory_text: memory_text = "• None yet"

    return GROUP_PROMPT.format(
        lang_instruction=get_lang_instruction(lang),
        people_info=people_info,
        memory_text=memory_text
    )


def build_private_prompt(uid, name, lang, for_owner=False):
    mems = get_mems(uid)
    memory_text = ""
    if mems:
        memory_text = "• Yaad hai:\n" + "\n".join([f"  - {k}: {v}" for k, v in mems.items()])
    else:
        memory_text = "• Kuch yaad nahi abhi"

    info = get_user_info(uid)
    total = info.get("msgs", 0)

    if for_owner:
        return OWNER_PROMPT.format(
            lang_instruction=get_lang_instruction(lang),
            user_name=name,
            memory_text=memory_text
        )
    else:
        return PRIVATE_PROMPT.format(
            lang_instruction=get_lang_instruction(lang),
            user_name=name,
            memory_text=memory_text,
            total_msgs=total
        )


def ask_groq(messages):
    """
    GROQ API — Multiple top models
    GPT-4o-mini class | Llama 4 Scout | Qwen 3 32B
    """
    if not GROQ_API_KEY:
        logger.error("❌ GROQ_API_KEY not set!")
        return None

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    # Models — BIGGEST & BEST first
    models = [
        "meta-llama/llama-4-scout-17b-16e-instruct",  # Llama 4 Scout
        "qwen/qwen3-32b",                              # Qwen 3 32B
        "llama-3.3-70b-versatile",                      # Llama 3.3 70B
        "llama-3.1-70b-versatile",                      # Llama 3.1 70B
        "llama3-70b-8192",                              # Llama 3 70B
        "deepseek-r1-distill-llama-70b",                # DeepSeek 70B
        "mixtral-8x7b-32768",                           # Mixtral
        "gemma2-9b-it",                                 # Gemma 2
        "llama-3.1-8b-instant",                         # Fast fallback
    ]

    for model in models:
        try:
            payload = {
                "model": model,
                "messages": messages,
                "max_tokens": 512,
                "temperature": 0.93,
                "top_p": 0.95,
                "frequency_penalty": 0.5,
                "presence_penalty": 0.6,
            }

            resp = requests.post(url, json=payload, headers=headers, timeout=50)

            if resp.status_code == 200:
                data = resp.json()
                reply = data["choices"][0]["message"]["content"].strip()
                if reply and len(reply) > 1:
                    # Clean
                    reply = re.sub(r'^\[?Ruhi\s*(?:Ji)?\]?\s*:?\s*', '', reply, flags=re.I).strip()
                    reply = re.sub(r'^(?:assistant|bot)\s*:?\s*', '', reply, flags=re.I).strip()
                    # Remove thinking tags if any
                    reply = re.sub(r'<think>.*?</think>', '', reply, flags=re.DOTALL).strip()
                    if reply and len(reply) > 1:
                        logger.info(f"✅ {model} ({len(reply)} chars)")
                        return reply

            elif resp.status_code == 429:
                logger.warning(f"⚠️ Rate limit {model}")
                time.sleep(1)
                continue
            elif resp.status_code == 404:
                # Model not available
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


def get_group_response(query, name, uid, cid, lang):
    history = get_group_hist(cid)
    
    # Check if this user is owner — even in group, owner gets respect
    if is_owner(uid):
        system = build_group_prompt(cid, lang, history)
        # Inject owner respect note
        system += f"\n\nIMPORTANT: [{name}] is your OWNER/CREATOR. ALWAYS be respectful to him. Never roast him. Call him 'ji didi' or 'didi'. Be sweet and obedient with him only."
    else:
        system = build_group_prompt(cid, lang, history)

    messages = [{"role": "system", "content": system}]
    for h in history:
        messages.append(h)
    messages.append({"role": "user", "content": f"[{name}]: {query}"})

    reply = ask_groq(messages)
    if reply:
        extract_info(query, uid, name)
        return reply
    return emergency_fb(name, lang)


def get_private_response(query, name, uid, lang):
    history = get_private_hist(uid)
    owner = is_owner(uid)
    system = build_private_prompt(uid, name, lang, for_owner=owner)

    messages = [{"role": "system", "content": system}]
    for h in history:
        messages.append(h)
    messages.append({"role": "user", "content": query})

    reply = ask_groq(messages)
    if reply:
        extract_info(query, uid, name)
        return reply
    return emergency_fb(name, lang)


def extract_info(text, uid, name):
    tl = text.lower()
    skip = {"hai","hoon","main","mein","toh","to","hi","hello","hoo","hun","se",
            "ka","ki","ke","tha","the","ye","yeh","woh","wo","nahi","na","aur",
            "bhi","mera","meri","tera","teri","kya","tum","tu","mai"}

    patterns = {
        "naam": [r'(?:mera naam|my name is|i am|main hoon|call me|naam hai)\s+(\w+)'],
        "sheher": [r'(?:i live in|i am from|main .+ se|from|rehta|rehti)\s+(?:hoon|hu)?\s*(?:in|mein|se)?\s*(\w+)'],
        "umar": [r'(?:i am|main|meri age|my age|age)\s+(\d{1,2})\s*(?:saal|sal|years?|ka|ki)?'],
        "pasand": [r'(?:i like|mujhe .+ pasand|i love|hobby)\s+(.+)'],
        "kaam": [r'(?:i study|padhai|student|college|school|job|work)\s+(?:in|mein|at|karta|karti)?\s*(.+)'],
        "crush": [r'(?:meri gf|my gf|girlfriend|boyfriend|crush|partner)\s+(?:ka naam|name is|hai)?\s*(\w+)'],
        "fav_food": [r'(?:fav(?:ourite)? food|pasandida khana)\s+(?:hai|is)?\s*(.+)'],
        "fav_movie": [r'(?:fav(?:ourite)? movie|pasandida film)\s+(?:hai|is)?\s*(.+)'],
        "fav_song": [r'(?:fav(?:ourite)? song|pasandida gana)\s+(?:hai|is)?\s*(.+)'],
    }

    for key, pats in patterns.items():
        for p in pats:
            m = re.search(p, tl)
            if m:
                val = m.group(1).strip().capitalize()
                if key == "umar":
                    try:
                        age = int(m.group(1))
                        if 5 <= age <= 80: save_mem(uid, key, str(age))
                    except: pass
                elif val.lower() not in skip and len(val) > 1:
                    save_mem(uid, key, val[:50])
                break


def emergency_fb(name, lang):
    r = {
        "hinglish": [f"Arey {name}! Ek sec ruk, thoda busy hoon 😊",
                     f"Hmm {name}, ek min mein aati hoon! 🌹"],
        "hindi": [f"Arey {name}! Ruko ek sec! 😊",
                  f"Hmm {name}, abhi aati hoon! 🌹"],
        "english": [f"Hey {name}! One sec! 😊",
                    f"Hold on {name}! 🌹"]
    }
    return random.choice(r.get(lang, r["hinglish"]))

# ============================================================================
# MENUS
# ============================================================================

START_MENU = """╭───────────────────⦿
│ ▸ ʜᴇʏ 愛 | 𝗥𝗨𝗛𝗜 𝗫 𝗤𝗡𝗥〆 
│ ▸ ɪ ᴀᴍ ˹ ᏒᏬᏂᎥ ꭙ ᏗᎥ ˼ 🧠 
├───────────────────⦿
│ ▸ sᴀᴠᴀɢᴇ ɢɪʀʟ ᴘᴇʀsᴏɴᴀ
│ ▸ ʀᴇsᴘᴇᴄᴛ sᴇ ʙᴇᴢᴢᴀᴛɪ 😏
├───────────────────⦿
│ ▸ ɢʀᴏᴜᴘ: 20 ᴍsɢ ᴍᴇᴍᴏʀʏ
│ ▸ ᴘʀɪᴠᴀᴛᴇ: 50 ᴍsɢ ᴍᴇᴍᴏʀʏ
│ ▸ ɴᴀᴍᴇ sᴇ ʙᴜʟᴀᴛɪ ʜᴀɪ
│ ▸ ʀᴏᴀsᴛ + ᴍᴀsᴛɪ + ᴄᴀʀᴇ
│ ▸ ᴏᴡɴᴇʀ ᴋᴏ ғᴜʟʟ ʀᴇsᴘᴇᴄᴛ
│ ▸ 24x7 ᴏɴʟɪɴᴇ
├───────────────────⦿
│ sᴀʏ "ʀᴜʜɪ ᴊɪ" ᴛᴏ ᴡᴀᴋᴇ ᴍᴇ
│ ᴍᴀᴅᴇ ʙʏ...@RUHI_VIG_QNR
╰───────────────────⦿

ʜᴇʏ ᴅᴇᴀʀ, 🥀
๏ ɪ ᴀᴍ ʀᴜʜɪ ᴊɪ — sᴀᴠᴀɢᴇ ǫᴜᴇᴇɴ 👑
๏ ʀᴏᴀsᴛ + ᴍᴀsᴛɪ + ᴘʏᴀᴀʀ
๏ ᴍᴜʟᴛɪ ᴍᴏᴅᴇʟ: ʟʟᴀᴍᴀ 4 | ǫᴡᴇɴ 3 | 70ʙ
•── ⋅ ⋅ ────── ⋅ ────── ⋅ ⋅ ──•
๏ sᴀʏ "ʀᴜʜɪ ᴊɪ" ᴛᴏ sᴛᴀʀᴛ 🌹"""

HELP_MENU = """╭───────────────────⦿
│ ʀᴜʜɪ ᴊɪ - ʜᴇʟᴘ
├───────────────────⦿
│ sᴀʏ "ʀᴜʜɪ ᴊɪ" → 10ᴍɪɴ sᴇssɪᴏɴ
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
        get_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name, msg.from_user.last_name)
        bot.send_message(msg.chat.id, START_MENU, reply_markup=kb_start())
    except Exception as e: logger.error(f"start: {e}")

@bot.message_handler(commands=['help'])
def c_help(msg):
    bot.send_message(msg.chat.id, HELP_MENU, reply_markup=kb_back())

@bot.message_handler(commands=['profile'])
def c_profile(msg):
    try:
        u = msg.from_user
        get_user(u.id, u.username, u.first_name, u.last_name)
        s = Session(); du = s.query(User).filter_by(user_id=u.id).first()
        mems = get_mems(u.id)
        mt = "\n".join([f"│ 💭 {k}: {v}" for k, v in mems.items()]) if mems else "│ 💭 None yet"
        ph = s.query(PrivateHistory).filter_by(user_id=u.id).count()
        Session.remove()
        ow = "👑 OWNER" if is_owner(u.id) else ("🔐 Admin" if is_adm(u.id) else "👤 User")
        bot.send_message(msg.chat.id, f"""╭───────────────────⦿
│ {ow}
├───────────────────⦿
│ 🆔 {du.user_id}
│ 📛 {du.first_name} {du.last_name or ''}
│ 👤 @{du.username or 'N/A'}
│ 🌐 {du.language} | 🎭 {du.personality}
│ 💬 {du.total_messages} msgs | 📝 {ph}/50 history
├───────────────────⦿
│ 🧠 ᴍᴇᴍᴏʀɪᴇs
{mt}
╰───────────────────⦿""", reply_markup=kb_back())
    except Exception as e: Session.remove(); logger.error(f"profile: {e}")

@bot.message_handler(commands=['clear'])
def c_clear(msg):
    if is_group(msg): clear_group_hist(msg.chat.id)
    else: clear_private_hist(msg.from_user.id)
    deactivate(msg.chat.id)
    bot.reply_to(msg, "🧹 Clear! Say 'Ruhi Ji' again! 🌸")

@bot.message_handler(commands=['lang'])
def c_lang(msg):
    bot.send_message(msg.chat.id, "🌐 Select:", reply_markup=kb_lang())

@bot.message_handler(commands=['personality'])
def c_pers(msg):
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton("😏 Savage Queen", callback_data="p_savage_girl"),
          types.InlineKeyboardButton("🌸 Sweet Girl", callback_data="p_sweet_girl"),
          types.InlineKeyboardButton("🔥 Roast Master", callback_data="p_roast_master"),
          types.InlineKeyboardButton("😜 Masti Queen", callback_data="p_masti_queen"))
    m.add(types.InlineKeyboardButton("🏠 ʙᴀᴄᴋ", callback_data="start"))
    bot.send_message(msg.chat.id, "🎭 Choose:", reply_markup=m)

@bot.message_handler(commands=['usage'])
def c_usage(msg):
    try:
        uid = msg.from_user.id; cid = msg.chat.id; s = Session()
        u = s.query(User).filter_by(user_id=uid).first()
        if is_group(msg):
            hc = s.query(GroupHistory).filter_by(chat_id=cid).count(); ht = f"Group: {hc}/20"
        else:
            hc = s.query(PrivateHistory).filter_by(user_id=uid).count(); ht = f"Private: {hc}/50"
        Session.remove()
        bot.send_message(msg.chat.id, f"📊 Msgs:{u.total_messages if u else 0} | {ht} | Mems:{len(get_mems(uid))} | Session:{'✅' if is_active(cid) else '❌'}",
                         reply_markup=kb_back())
    except: Session.remove()

@bot.message_handler(commands=['summary'])
def c_summary(msg):
    h = get_group_hist(msg.chat.id) if is_group(msg) else get_private_hist(msg.from_user.id)
    if h:
        lines = ["╭── 📋 ──⦿"]
        for x in h[-10:]:
            i = "👤" if x["role"] == "user" else "🌹"
            lines.append(f"│ {i} {x['content'][:70]}")
        lines.append("╰──────⦿")
        bot.send_message(msg.chat.id, "\n".join(lines)[:4000])
    else: bot.reply_to(msg, "📋 Empty! 🌸")

@bot.message_handler(commands=['reset'])
def c_reset(msg):
    uid = msg.from_user.id; cid = msg.chat.id
    if is_group(msg): clear_group_hist(cid)
    else: clear_private_hist(uid)
    clear_mems(uid); deactivate(cid)
    try:
        s = Session(); u = s.query(User).filter_by(user_id=uid).first()
        if u: u.language = "hinglish"; u.personality = "savage_girl"; s.commit()
        Session.remove()
    except: Session.remove()
    bot.reply_to(msg, "🔄 Reset! Say 'Ruhi Ji'! 🌸")

# ============================================================================
# ADMIN
# ============================================================================

@bot.message_handler(commands=['admin'])
@admin_only
def c_admin(msg):
    bot.send_message(msg.chat.id, f"""╭──────────⦿
│ 🔐 ᴀᴅᴍɪɴ | 👑 {msg.from_user.first_name}
│ 👥 {total_users()} users | ⚡ {active_count()} active
│ 🔑 GROQ: {'✅' if GROQ_API_KEY else '❌'}
│ 📦 v8.0 — Savage Queen
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
        try: bot.send_message(uid, f"📢\n\n{t}\n\n— Ruhi Ji 🌹"); su += 1
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
    try: clear_group_hist(int(p[1])); clear_private_hist(int(p[1])); bot.reply_to(msg, "🧹")
    except: bot.reply_to(msg, "❌")

@bot.message_handler(commands=['shutdown'])
@admin_only
def c_sd(msg):
    if msg.from_user.id != ADMIN_ID: return
    bot.reply_to(msg, "🔴"); os._exit(0)

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
    if len(p) < 2: bot.reply_to(msg, "/addbadword <w>"); return
    bot.reply_to(msg, "✅" if add_bw(p[1].strip()) else "❌")

@bot.message_handler(commands=['removebadword'])
@admin_only
def c_rbw(msg):
    p = msg.text.split(maxsplit=1)
    if len(p) < 2: bot.reply_to(msg, "/removebadword <w>"); return
    bot.reply_to(msg, "✅" if rem_bw(p[1].strip()) else "❌")

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
        u = call.from_user; d = call.data
        cid = call.message.chat.id; mid = call.message.message_id

        if d == "start":
            bot.edit_message_text(START_MENU, cid, mid, reply_markup=kb_start())
        elif d == "help":
            bot.edit_message_text(HELP_MENU, cid, mid, reply_markup=kb_back())
        elif d == "profile":
            get_user(u.id, u.username, u.first_name, u.last_name)
            s = Session(); du = s.query(User).filter_by(user_id=u.id).first()
            mems = get_mems(u.id)
            mt = "\n".join([f"│ 💭 {k}: {v}" for k, v in mems.items()]) if mems else "│ 💭 None"
            ow = "👑 OWNER" if is_owner(u.id) else "👤"
            bot.edit_message_text(f"""╭──────────⦿
│ {ow} {du.first_name} | 🆔 {du.user_id}
│ 💬 {du.total_messages} | 🌐 {du.language}
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
            s = Session(); du = s.query(User).filter_by(user_id=u.id).first(); Session.remove()
            bot.edit_message_text(f"📊 Msgs:{du.total_messages if du else 0} | Mems:{len(get_mems(u.id))} | Session:{'✅' if is_active(cid) else '❌'}",
                                  cid, mid, reply_markup=kb_back())
        elif d == "reset":
            clear_private_hist(u.id); clear_mems(u.id); deactivate(cid)
            bot.answer_callback_query(call.id, "🔄 Done!")
            bot.edit_message_text(START_MENU, cid, mid, reply_markup=kb_start())

        try: bot.answer_callback_query(call.id)
        except: pass
    except telebot.apihelper.ApiTelegramException as e:
        if "not modified" not in str(e): logger.error(f"cb: {e}")
    except Exception as e: logger.error(f"cb: {e}")

# ============================================================================
# ★★★ MAIN HANDLER ★★★
# ============================================================================

@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle(msg):
    try:
        if msg.text and msg.text.startswith('/'): return

        u = msg.from_user; uid = u.id; cid = msg.chat.id
        text = (msg.text or "").strip(); name = u.first_name or "Dear"
        if not text or is_banned(uid): return

        get_user(uid, u.username, u.first_name, u.last_name)
        lang = get_lang(uid)
        tl = text.lower()
        group = is_group(msg)

        cp = get_cfg("phrase", "") or ACTIVATION_PHRASE
        found = cp.lower() in tl
        active = is_active(cid)

        # === ACTIVATION ===
        if found:
            activate(cid); inc_msg(uid)
            query = text
            for v in [cp, cp.capitalize(), cp.upper(), cp.lower(), cp.title()]:
                query = query.replace(v, "").strip()

            if not query or len(query) < 2:
                if is_owner(uid):
                    r = {"hinglish": f"Ji Sir {name}! 🌹 Bataiye, kya seva karun? Aapke liye hamesha haazir hoon! 😊",
                         "hindi": f"जी Sir {name}! 🌹 बताइये, क्या सेवा करूं? आपके लिए हमेशा हाज़िर हूं! 😊",
                         "english": f"Yes Sir {name}! 🌹 How can I help you? I'm always here for you! 😊"}
                elif group:
                    r = {"hinglish": f"Haan bolo {name}! 😏 Kya chahiye? Jaldi bol, busy hoon 😜",
                         "hindi": f"हाँ बोलो {name}! 😏 क्या चाहिए?",
                         "english": f"Yeah {name}? 😏 What do you want?"}
                else:
                    r = {"hinglish": f"Haan {name}! 😏 Bol kya scene hai? 10 min hai mere paas tere liye 😜",
                         "hindi": f"हाँ {name}! 😏 बोल क्या है? 10 min हैं 😜",
                         "english": f"Yeah {name}? 😏 You've got 10 min, make it count 😜"}

                resp = r.get(lang, r["hinglish"])
                if group:
                    save_group_msg(cid, uid, name, "user", text)
                    save_group_msg(cid, 0, "Ruhi", "assistant", resp)
                else:
                    save_private_msg(uid, "user", text)
                    save_private_msg(uid, "assistant", resp)
                bot.reply_to(msg, resp); return

            if has_bw(query):
                bot.reply_to(msg, "😤 Muh dhoke aa pehle! 🙅‍♀️"); return

            bot.send_chat_action(cid, 'typing')

            if group:
                save_group_msg(cid, uid, name, "user", text)
                response = get_group_response(query, name, uid, cid, lang)
                save_group_msg(cid, 0, "Ruhi", "assistant", response)
            else:
                save_private_msg(uid, "user", text)
                response = get_private_response(query, name, uid, lang)
                save_private_msg(uid, "assistant", response)

            try: bot.reply_to(msg, response)
            except:
                for i in range(0, len(response), 4000):
                    bot.send_message(cid, response[i:i+4000])
            return

        # === ACTIVE SESSION ===
        elif active:
            refresh(cid); inc_msg(uid)
            if has_bw(text): bot.reply_to(msg, "😤 Sharafat se baat kar! 🙅‍♀️"); return
            if len(text) < 1: return

            bot.send_chat_action(cid, 'typing')

            if group:
                save_group_msg(cid, uid, name, "user", text)
                response = get_group_response(text, name, uid, cid, lang)
                save_group_msg(cid, 0, "Ruhi", "assistant", response)
            else:
                save_private_msg(uid, "user", text)
                response = get_private_response(text, name, uid, lang)
                save_private_msg(uid, "assistant", response)

            try: bot.reply_to(msg, response)
            except:
                for i in range(0, len(response), 4000):
                    bot.send_message(cid, response[i:i+4000])
            return

        # === SILENT — observe in group ===
        else:
            if group:
                save_group_msg(cid, uid, name, "user", text)
            return

    except Exception as e:
        logger.error(f"handle: {e}\n{traceback.format_exc()}")
        try: bot.reply_to(msg, "😅 Ek sec! 🌸")
        except: pass

@bot.message_handler(func=lambda m: True, content_types=['photo','video','audio','document','sticker','voice','video_note'])
def media(msg):
    if not is_active(msg.chat.id): return
    refresh(msg.chat.id)
    bot.reply_to(msg, f"😏 {msg.from_user.first_name or 'Sun'}, text bhej na! Photo se baat nahi hoti meri 😜")

# ============================================================================
# START
# ============================================================================

if __name__ == "__main__":
    logger.info("=" * 40)
    logger.info("🌹 RUHI JI v8.0 — Savage Queen 👑")
    logger.info(f"🔑 GROQ: {'✅' if GROQ_API_KEY else '❌'}")
    logger.info(f"👑 Owner: {ADMIN_ID}")
    logger.info(f"💾 DB: {DATABASE_URL[:40]}...")
    logger.info("=" * 40)

    if not GROQ_API_KEY:
        logger.error("❌ GROQ_API_KEY lagao! console.groq.com se free milega!")

    if ADMIN_ID: add_adm(ADMIN_ID, ADMIN_ID)
    sp = get_cfg("phrase", "")
    if sp: ACTIVATION_PHRASE = sp

    threading.Thread(target=run_flask, daemon=True).start()
    logger.info("🌐 Flask ✅")
    logger.info("🤖 Polling...")

    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60, skip_pending=True)
        except Exception as e:
            logger.error(f"Poll: {e}"); time.sleep(5)
            