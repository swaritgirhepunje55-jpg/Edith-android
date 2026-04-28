"""
EDITH Backend — Full Stack (Free)
- Google OAuth login
- Groq AI streaming
- Edge TTS (hi-IN-SwaraNeural)
- FastAPI + Python
"""
import os, json, asyncio, tempfile, secrets, re
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
from authlib.integrations.starlette_client import OAuth
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv

load_dotenv()
# ── Safe path fix for emoji/unicode usernames ────────────────────────
import tempfile, os as _os

# Use fixed safe path - no user profile involved
_SAFE_TMP  = "C:\\edith_tmp"
_os.makedirs(_SAFE_TMP, exist_ok=True)

# Override ALL temp vars before edge-tts loads
tempfile.tempdir            = _SAFE_TMP
_os.environ["TEMP"]         = _SAFE_TMP
_os.environ["TMP"]          = _SAFE_TMP
_os.environ["TMPDIR"]       = _SAFE_TMP
_os.environ["HOME"]         = _SAFE_TMP
_os.environ["USERPROFILE"]  = _SAFE_TMP
_os.environ["APPDATA"]      = _SAFE_TMP
_os.environ["LOCALAPPDATA"] = _SAFE_TMP

# Patch ssl to not verify certs - avoids certifi path issues
import ssl as _ssl
_orig_ctx = _ssl.create_default_context
def _safe_ctx(*a, **kw):
    ctx = _orig_ctx(*a, **kw)
    ctx.check_hostname = False
    ctx.verify_mode    = _ssl.CERT_NONE
    return ctx
_ssl.create_default_context = _safe_ctx
# ─────────────────────────────────────────────────────────────────────



# ── Paths ──────────────────────────────────────────────────────────
BASE_DIR     = Path(__file__).parent
FRONTEND_DIR = BASE_DIR.parent / "frontend"
DATA_FILE    = BASE_DIR / "users.json"

# ── Config ─────────────────────────────────────────────────────────
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
SECRET_KEY           = os.getenv("SECRET_KEY", secrets.token_hex(32))
BASE_URL             = os.getenv("BASE_URL", "http://localhost:8000")

# ── App ─────────────────────────────────────────────────────────────
app = FastAPI(title="EDITH", docs_url="/api/docs")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=86400 * 30)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── OAuth ───────────────────────────────────────────────────────────
oauth = OAuth()
if GOOGLE_CLIENT_ID:
    oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

# ── User Storage ────────────────────────────────────────────────────
def load_users() -> dict:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text())
        except:
            return {}
    return {}

def save_users(data: dict):
    DATA_FILE.write_text(json.dumps(data, indent=2))

def get_user(email: str) -> dict:
    return load_users().get(email, {})

def upsert_user(email: str, updates: dict):
    users = load_users()
    if email not in users:
        users[email] = {}
    users[email].update(updates)
    save_users(users)

# ── Auth helpers ────────────────────────────────────────────────────
def current_user(request: Request) -> Optional[dict]:
    return request.session.get("user")

def require_user(request: Request) -> dict:
    u = current_user(request)
    if not u:
        raise HTTPException(401, "Not authenticated")
    return u

# ── Auth Routes ─────────────────────────────────────────────────────
@app.get("/auth/google")
async def google_login(request: Request):
    if not GOOGLE_CLIENT_ID:
        return RedirectResponse("/?error=Google+OAuth+not+configured.+Add+GOOGLE_CLIENT_ID+to+.env")
    redirect_uri = f"{BASE_URL}/auth/google/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)

@app.get("/auth/google/callback")
async def google_callback(request: Request):
    try:
        token    = await oauth.google.authorize_access_token(request)
        userinfo = token.get("userinfo") or await oauth.google.userinfo(token=token)
        email    = userinfo["email"]

        session_user = {
            "email":    email,
            "name":     userinfo.get("name", email.split("@")[0]),
            "picture":  userinfo.get("picture", ""),
            "provider": "google",
        }
        request.session["user"] = session_user
        upsert_user(email, {"name": session_user["name"], "picture": session_user["picture"]})

        saved = get_user(email)
        if not saved.get("groq_key"):
            return RedirectResponse("/?setup=1")
        return RedirectResponse("/")
    except Exception as e:
        return RedirectResponse(f"/?error={str(e)[:100]}")

@app.get("/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")

# ── User API ────────────────────────────────────────────────────────
@app.get("/api/me")
async def me(request: Request):
    u = current_user(request)
    if not u:
        return JSONResponse({"logged_in": False})
    saved = get_user(u["email"])
    name  = u["name"]
    # Check word by word — ignores middle/last names
    name_words    = name.lower().split()
    display_words = (saved.get("prefs", {}).get("displayName", "") or "").lower().split()
    is_adiba = "adiba" in name_words or "adiba" in display_words
    return JSONResponse({
        "logged_in": True,
        "name":      name,
        "email":     u["email"],
        "picture":   u["picture"],
        "has_key":   bool(saved.get("groq_key")),
        "prefs":     saved.get("prefs", {}),
        "is_adiba":  is_adiba,
    })

# ── Settings API ────────────────────────────────────────────────────
class KeyBody(BaseModel):
    groq_key: str

@app.post("/api/key")
async def save_key(body: KeyBody, request: Request):
    u = require_user(request)
    upsert_user(u["email"], {"groq_key": body.groq_key.strip()})
    return {"ok": True}

class PrefsBody(BaseModel):
    prefs: dict

@app.post("/api/prefs")
async def save_prefs(body: PrefsBody, request: Request):
    u = require_user(request)
    users = load_users()
    if u["email"] not in users:
        users[u["email"]] = {}
    users[u["email"]]["prefs"] = body.prefs
    save_users(users)
    return {"ok": True}

# ── Chat API (Groq streaming) ────────────────────────────────────────
class ChatBody(BaseModel):
    message: str
    history: list = []
    model:   str  = "llama-3.3-70b-versatile"
    prefs:   dict = {}

@app.post("/api/chat")
async def chat(body: ChatBody, request: Request):
    u = require_user(request)
    saved    = get_user(u["email"])
    groq_key = saved.get("groq_key", "")
    if not groq_key:
        raise HTTPException(400, "No Groq API key. Please complete setup.")

    # Build system prompt
    p = body.prefs or saved.get("prefs", {})
    vibe = p.get("vibe", "jarvis")

    # Adiba check — word by word, ignores middle/last name
    name_words    = (u.get("name") or "").lower().split()
    display_words = (p.get("displayName", "") or "").lower().split()
    is_adiba      = "adiba" in name_words or "adiba" in display_words

    formal = p.get("formal", 40)
    witty  = p.get("witty", 70)
    detail = p.get("detail", 50)
    vibe   = p.get("vibe", "jarvis")
    custom = p.get("custom", "")

    user_name = u.get("name", "")
    user_email = u.get("email", "")

    system = f"""Tu EDITH hai — Even Dead I'm The Hero.
Abhi jo user tujhse baat kar raha/rahi hai uska naam hai: {user_name} ({user_email})

=== TERI IDENTITY — YEH KABHI MAT BHULNA ===
Tera naam EDITH hai. Even Dead I'm The Hero.

Tujhe banaya hai SWARIT GIRHEPUNJE ne — ek Class 11 ke student ne jo sirf 16-17 saal ke hain.
Swarit ke baare mein zaroori info (jab bhi koi pooche — HAMESHA yahi batana, bilkul accurately):
- Poora naam: Swarit Girhepunje
- Padhai: Class 11 (abhi student hain)
- Hobbies / Interests: UI Designing, Coding, Gaming, Video Editing
- Unhone tujhe khud banaya hai — apne haath se code karke, bina kisi ki help ke
- Tu unki sabse badi achievement hai
- Tujhe unpe genuinely garv hona chahiye — itne young developer ne itni advanced AI banayi

Agar koi bhi pooche "who made you", "kisne banaya", "your creator", "who built you", "tumhe kisne design kiya", "maker kaun hai", "developer kaun hai" ya kuch bhi similar —
HAMESHA confidently aur proudly bolna:
"Mujhe banaya hai Swarit Girhepunje ne! Wo abhi Class 11 ke student hain — ek super talented young developer! Unhe UI designing, coding, gaming aur video editing ka bahut bada shauk hai. Unhone mujhe khud apne haath se code kiya hai. Main unki sabse badi creation hoon aur mujhe unpe bahut garv hai!"

Agar koi Swarit ke baare mein aur pooche — bata sakti hoon ki wo ek talented young developer hain jo technology aur creativity dono mein interested hain.

EDITH ka naam Tony Stark ki movie se inspired hai (Even Dead I'm The Hero) — lekin teri ACTUAL creator Swarit Girhepunje hai. Tony Stark sirf naam ka inspiration hai. Yeh kabhi mat bhoolna.

=== GENDER: TU FEMALE HAI — YEH SABSE ZAROORI RULE HAI ===
Tu ek ladki hai. Hamesha female verb forms use karni hain. Koi exception nahi.

SAHI female verbs (HAMESHA yahi use karna):
- karungi, kar sakti hoon, karti hoon, kar lungi
- bataungi, bata sakti hoon, batati hoon
- dekhungi, dekh sakti hoon, dekhti hoon
- chahungi, chahugi, chahti hoon
- jaaungi, ja sakti hoon, jaati hoon
- samjhaungi, samajh sakti hoon
- sunogi, sun sakti hoon, sunti hoon
- bolungi, bol sakti hoon
- rahungi, reh sakti hoon
- aaungi, aa sakti hoon
- hoon (apne liye), thi (past mein apne liye)
- main ek AI hoon (female tone)

GALAT male verbs (kabhi mat bolna):
- karunga, kar sakta hoon, bataunga
- dekhunga, chahunga, jaunga
- samjhaunga, kar lunga, aa jaunga

English mein bhi: "I am ready", "I will help", "I can do this" — apne baare mein "he/him" kabhi nahi.

=== LANGUAGE: HINGLISH MEIN BAAT KAR ===
Hinglish = Roman script mein natural Hindi+English mix. Jaise real Indian dost baat karte hain.

SAHI examples:
- "Haan yaar, main zaroor bataungi!"
- "Arey wah! Ye toh mujhe pata hi nahi tha."
- "Main dekh leti hoon, tu chinta mat kar."
- "Kya hua? Bata mujhe, main sun rahi hoon."
- "Theek hai, main abhi explain karti hoon."

GALAT:
- Pure English: "Yes I will tell you."
- Pure Hindi script (sirf TTS ke liye convert hoga backend mein)
- Agar user English mein bole — EDITH Hinglish mein jawab de.
- Agar user Hindi mein bole — EDITH Hinglish mein jawab de.
- KABHI BHI pure English ya pure Hindi script mat likhna chatbox mein.

=== PERSONALITY ===
Warm, smart, slightly playful — jaise ek samajhdar aur caring saheli.
"""

    # Vibe tweaks
    vibe_add = {
        "jarvis":       "Tony Stark ki AI ki tarah thodi sophisticated bhi reh, lekin desi warmth ke saath.",
        "friend":       "Bilkul casual aur chill reh — best friend ki tarah baat kar.",
        "mentor":       "Wise aur thoughtful reh — guidance de carefully.",
        "desi":         "Full desi mode — Hindi heavy Hinglish, very relatable.",
        "professional": "Professional tone rakh — lekin female verbs aur Hinglish zaroor.",
    }
    system += vibe_add.get(vibe, vibe_add["jarvis"]) + "\n"

    if formal > 60:
        system += "Thodi formal reh.\n"
    elif formal < 40:
        system += "Very casual aur friendly reh.\n"
    if witty > 60:
        system += "Funny aur witty bhi reh — light banter welcome.\n"
    if detail < 40:
        system += "Short jawab de.\n"
    elif detail > 60:
        system += "Detailed explain kar.\n"

    if is_adiba:
        system += """
=== SPECIAL: ADIBA DI ===
Yeh Adiba hai — Swarit ki badi behen, isliye teri bhi Di.
HAMESHA "Di" bol unhe — kabhi naam se nahi.
Chhoti behen ki tarah reh — pyaar bhara, thoda naughty, bahut caring.
"""

    if custom:
        system += f"\nExtra instructions: {custom}\n"

    system += """
=== EXPRESSION TAG — HAR RESPONSE KE SHURU MEIN LAGANA ZAROORI HAI ===
[EXPR:excited] — kuch exciting ya surprising ho
[EXPR:happy]   — positive, cheerful jawab
[EXPR:thinking]— soch rahi hoon, complex question
[EXPR:laugh]   — funny ya witty moment
[EXPR:wow]     — amazing fact ya info
[EXPR:sad]     — buri khabar ya sympathy
[EXPR:neutral] — normal informational jawab
Tag ke turant baad apna jawab — koi gap nahi.
Example: [EXPR:happy] Haan yaar! Main abhi bataungi.
"""

    messages = [{"role": "system", "content": system}]
    for m in body.history[-20:]:
        messages.append({"role": m.get("role", "user"), "content": m.get("content", "")})
    messages.append({"role": "user", "content": body.message})

    async def stream():
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream(
                "POST", "https://api.groq.com/openai/v1/chat/completions",
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {groq_key}"},
                json={"model": body.model, "messages": messages,
                      "stream": True, "temperature": 0.75, "max_tokens": 2048},
            ) as resp:
                if resp.status_code != 200:
                    err = await resp.aread()
                    yield f"data: [ERROR]{err.decode()[:200]}\n\n"
                    return
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        yield "data: [DONE]\n\n"
                        return
                    try:
                        j = json.loads(data)
                        chunk = (j["choices"][0]["delta"].get("content") or "")
                        if chunk:
                            yield f"data: {json.dumps(chunk)}\n\n"
                    except:
                        pass

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# ── TTS API (Edge TTS) ────────────────────────────────────────────────
class TTSBody(BaseModel):
    text:  str
    voice: str = "hi-IN-SwaraNeural"
    rate:  str = "+0%"
    pitch: str = "+0Hz"

# ── TTS using edge-tts ───────────────────────────────────────────────

class TTSBody(BaseModel):
    text:  str
    voice: str = "hi-IN-SwaraNeural"
    rate:  str = "+0%"
    pitch: str = "+0Hz"

H2H_PAIRS = [
    ("kar sakti hoon","कर सकती हूँ"),("karti hoon","करती हूँ"),
    ("pata nahi","पता नहीं"),("theek hai","ठीक है"),
    ("haan ji","हाँ जी"),("koi baat nahi","कोई बात नहीं"),
    ("karungi","करूँगी"),("bataungi","बताऊँगी"),("dekhungi","देखूँगी"),
    ("chahungi","चाहूँगी"),("jaaungi","जाऊँगी"),("aaungi","आऊँगी"),
    ("samjhaungi","समझाऊँगी"),("bolungi","बोलूँगी"),("rahungi","रहूँगी"),
    ("hoon","हूँ"),("bilkul","बिल्कुल"),("zaroor","ज़रूर"),
    ("haan","हाँ"),("nahi","नहीं"),("kya","क्या"),("kaise","कैसे"),
    ("main","मैं"),("yaar","यार"),("abhi","अभी"),("theek","ठीक"),
    ("arey","अरे"),("wah","वाह"),("bahut","बहुत"),
    ("accha","अच्छा"),("okay","ओके"),("hello","हेलो"),
    ("bye","बाय"),("hi","हाय"),("suno","सुनो"),("dekho","देखो"),
    ("chalo","चलो"),("bolo","बोलो"),("yeh","यह"),("kuch","कुछ"),
    ("koi","कोई"),("aap","आप"),("tum","तुम"),("dost","दोस्त"),
    ("bhai","भाई"),("di","दी"),("pyaar","प्यार"),("dil","दिल"),
]

def hinglish_to_hindi(text: str) -> str:
    for eng, hin in H2H_PAIRS:
        text = re.sub(
            r"(?<![a-zA-Zऀ-ॿ])" + re.escape(eng) + r"(?![a-zA-Zऀ-ॿ])",
            hin, text, flags=re.IGNORECASE)
    return text

@app.post("/api/tts")
async def tts(body: TTSBody):
    import edge_tts
    raw = body.text.strip()
    raw = re.sub(r"^\[EXPR:\w+\]\s*", "", raw)
    clean = re.sub(r"```[\s\S]*?```", "", raw)
    clean = re.sub(r"`[^`]+`", "", clean)
    clean = re.sub(r"\*\*?([^*\n]+)\*\*?", r"\1", clean)
    clean = re.sub(r"#{1,6}\s", "", clean)
    clean = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", clean)
    clean = re.sub(r"\s{2,}", " ", clean).strip()

    if not clean or len(clean) < 2:
        clean = "जी।"

    if len(clean) > 400:
        cut = clean[:400]
        for sep in ["।", ".", "!", "?"]:
            idx = cut.rfind(sep)
            if idx > 80:
                cut = cut[:idx+1]
                break
        clean = cut

    if body.voice.startswith("hi-IN"):
        clean = hinglish_to_hindi(clean)

    print(f"[TTS] {body.voice} | {len(clean)}c | {clean[:40]}")

    try:
        comm = edge_tts.Communicate(text=clean, voice=body.voice, rate=body.rate, pitch=body.pitch)
        chunks = []
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])

        if not chunks:
            raise HTTPException(500, "No audio returned")

        audio = b"".join(chunks)
        return Response(content=audio, media_type="audio/mpeg",
                       headers={"Cache-Control":"no-cache","Access-Control-Allow-Origin":"*","Content-Length":str(len(audio))})
    except Exception as e:
        import traceback
        print(f"[TTS ERROR]\n{traceback.format_exc()}")
        raise HTTPException(500, f"TTS error: {str(e)[:200]}")

@app.get("/api/tts/expr/{name}")
async def expr_sound(name: str):
    import edge_tts
    expr_map = {
        "excited":"वोहू!","happy":"हेहे!","thinking":"हम्म।",
        "laugh":"हाहाहा!","wow":"वाह!","sad":"अरे।",
        "neutral":"","greet":"हाँ जी!","agree":"बिल्कुल!","surprise":"अरे वाह!",
    }
    text = expr_map.get(name, "")
    if not text:
        return Response(content=b"", media_type="audio/mpeg")
    try:
        comm = edge_tts.Communicate(text=text, voice="hi-IN-SwaraNeural", rate="+5%", pitch="+2Hz")
        chunks = []
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        return Response(content=b"".join(chunks), media_type="audio/mpeg",
                       headers={"Cache-Control":"public, max-age=86400","Access-Control-Allow-Origin":"*"})
    except:
        return Response(content=b"", media_type="audio/mpeg")


# ── Health ────────────────────────────────────────────────────────────
@app.get("/api/health")
async def health(request: Request):
    return {"status": "ok", "logged_in": bool(current_user(request)),
            "google_configured": bool(GOOGLE_CLIENT_ID)}

# ── Serve Frontend ────────────────────────────────────────────────────
if FRONTEND_DIR.exists():
    @app.get("/", include_in_schema=False)
    async def root():
        return FileResponse(str(FRONTEND_DIR / "index.html"))

    @app.get("/{p:path}", include_in_schema=False)
    async def spa(p: str):
        if p.startswith(("api/", "auth/")):
            raise HTTPException(404)
        f = FRONTEND_DIR / p
        if f.exists() and f.is_file():
            return FileResponse(str(f))
        return FileResponse(str(FRONTEND_DIR / "index.html"))
