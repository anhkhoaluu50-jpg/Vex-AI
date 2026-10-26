import os, re, json, time, hmac, hashlib, secrets, sqlite3, mimetypes
from pathlib import Path
from typing import Optional
import requests
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Header
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

APP_DIR = Path(__file__).resolve().parent
DB_PATH = os.getenv("DATABASE_PATH", str(APP_DIR / "vex.db"))
BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
API_KEY = os.getenv("LLM_API_KEY", "")
MODEL = os.getenv("LLM_MODEL", "deepseek-flash")
SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", """Bạn là Vex, trợ lý AI chuyên lập trình. Trả lời bằng tiếng Việt tự nhiên, chính xác và thực dụng. Khi viết code, ưu tiên giải pháp chạy được, an toàn, dễ bảo trì và hiệu năng tốt. Dùng markdown và fenced code blocks có nhãn ngôn ngữ. Khi sửa lỗi, giải thích nguyên nhân ngắn gọn rồi đưa code đã sửa. Không bịa kết quả chạy thử.""")
MAX_CHARS = int(os.getenv("MAX_MESSAGE_CHARS", "12000"))
MAX_FILE_BYTES = int(os.getenv("MAX_FILE_BYTES", str(3 * 1024 * 1024)))
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "2500"))
SECRET = os.getenv("APP_SECRET", "")
if not SECRET:
    SECRET = hashlib.sha256((os.getenv("RENDER_EXTERNAL_HOSTNAME", "local-vex") + "-change-this-secret").encode()).hexdigest()

app = FastAPI(title="Vex Code AI")
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL DEFAULT 'Cuộc trò chuyện mới',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            FOREIGN KEY(chat_id) REFERENCES chats(id)
        )""")
        cols = {r[1] for r in con.execute("PRAGMA table_info(users)").fetchall()}
        if "credits_remaining" not in cols:
            con.execute("ALTER TABLE users ADD COLUMN credits_remaining INTEGER NOT NULL DEFAULT 20")
        if "credits_day" not in cols:
            con.execute("ALTER TABLE users ADD COLUMN credits_day TEXT NOT NULL DEFAULT ''")
init_db()

DAILY_CREDITS = int(os.getenv("DAILY_CREDITS", "20"))
def credit_status(user_id: int):
    today = time.strftime("%Y-%m-%d", time.gmtime())
    with db() as con:
        row = con.execute("SELECT credits_remaining,credits_day FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(401, "Tài khoản không tồn tại.")
        if row["credits_day"] != today:
            con.execute("UPDATE users SET credits_remaining=?,credits_day=? WHERE id=?", (DAILY_CREDITS, today, user_id))
            return {"credits": DAILY_CREDITS, "daily_credits": DAILY_CREDITS, "credits_reset": "00:00 UTC"}
        return {"credits": row["credits_remaining"], "daily_credits": DAILY_CREDITS, "credits_reset": "00:00 UTC"}

def password_hash(password: str, salt: Optional[bytes] = None) -> str:
    salt = salt or secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return salt.hex() + "$" + key.hex()

def password_verify(password: str, saved: str) -> bool:
    try:
        salt_hex, key_hex = saved.split("$", 1)
        test = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
        return hmac.compare_digest(test.hex(), key_hex)
    except Exception:
        return False

def make_token(user_id: int) -> str:
    expires = int(time.time()) + 60 * 60 * 24 * 14
    body = f"{user_id}.{expires}.{secrets.token_hex(8)}"
    sig = hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
    return body + "." + sig

def get_user(authorization: Optional[str] = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Vui lòng đăng nhập.")
    token = authorization[7:].strip()
    try:
        uid_s, exp_s, nonce, sig = token.split(".", 3)
        body = ".".join([uid_s, exp_s, nonce])
        expected = hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected) or int(exp_s) < int(time.time()):
            raise ValueError()
        uid = int(uid_s)
    except Exception:
        raise HTTPException(401, "Phiên đăng nhập hết hạn. Hãy đăng nhập lại.")
    with db() as con:
        user = con.execute("SELECT id, username FROM users WHERE id=?", (uid,)).fetchone()
    if not user:
        raise HTTPException(401, "Tài khoản không tồn tại.")
    return dict(user)

class AuthBody(BaseModel):
    username: str = Field(min_length=3, max_length=24)
    password: str = Field(min_length=8, max_length=128)

class ChatCreate(BaseModel):
    title: str = Field(default="Cuộc trò chuyện mới", max_length=100)

class ChatBody(BaseModel):
    chat_id: Optional[int] = None
    message: str = Field(min_length=1, max_length=MAX_CHARS)
    history: list[dict] = Field(default_factory=list, max_length=30)
    file_text: Optional[str] = Field(default=None, max_length=MAX_CHARS)
    mode: str = Field(default="code", pattern="^(code|security)$")

@app.get("/")
def home():
    return FileResponse(APP_DIR / "static" / "index.html")

@app.get("/health")
def health():
    return {"ok": True, "model_configured": bool(API_KEY and MODEL)}

@app.post("/api/register")
def register(body: AuthBody):
    username = body.username.strip().lower()
    if not re.fullmatch(r"[a-z0-9_.-]{3,24}", username):
        raise HTTPException(400, "Tên tài khoản chỉ dùng chữ thường, số, dấu chấm, gạch ngang hoặc gạch dưới.")
    if len(body.password) < 8:
        raise HTTPException(400, "Mật khẩu cần ít nhất 8 ký tự.")
    with db() as con:
        try:
            today = time.strftime("%Y-%m-%d", time.gmtime())
            cur = con.execute("INSERT INTO users(username,password_hash,created_at,credits_remaining,credits_day) VALUES(?,?,?,?,?)",
                              (username, password_hash(body.password), int(time.time()), DAILY_CREDITS, today))
            uid = cur.lastrowid
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Tên tài khoản đã được sử dụng.")
    return {"token": make_token(uid), "username": username}

@app.post("/api/login")
def login(body: AuthBody):
    username = body.username.strip().lower()
    with db() as con:
        user = con.execute("SELECT id,username,password_hash FROM users WHERE username=?", (username,)).fetchone()
    if not user or not password_verify(body.password, user["password_hash"]):
        raise HTTPException(401, "Tên tài khoản hoặc mật khẩu không đúng.")
    return {"token": make_token(user["id"]), "username": user["username"]}

@app.get("/api/me")
def me(user=Depends(get_user)):
    return {**user, **credit_status(user["id"])}

@app.get("/api/chats")
def list_chats(user=Depends(get_user)):
    with db() as con:
        rows = con.execute("SELECT id,title,created_at,updated_at FROM chats WHERE user_id=? ORDER BY updated_at DESC LIMIT 100",
                           (user["id"],)).fetchall()
    return [dict(r) for r in rows]

@app.post("/api/chats")
def create_chat(body: ChatCreate, user=Depends(get_user)):
    now = int(time.time())
    with db() as con:
        cur = con.execute("INSERT INTO chats(user_id,title,created_at,updated_at) VALUES(?,?,?,?)",
                          (user["id"], body.title.strip() or "Cuộc trò chuyện mới", now, now))
        return {"id": cur.lastrowid, "title": body.title.strip() or "Cuộc trò chuyện mới"}

@app.get("/api/chats/{chat_id}")
def get_chat(chat_id: int, user=Depends(get_user)):
    with db() as con:
        chat = con.execute("SELECT id,title FROM chats WHERE id=? AND user_id=?", (chat_id, user["id"])).fetchone()
        if not chat:
            raise HTTPException(404, "Không tìm thấy cuộc trò chuyện.")
        messages = con.execute("SELECT role,content,created_at FROM messages WHERE chat_id=? ORDER BY id", (chat_id,)).fetchall()
    return {"chat": dict(chat), "messages": [dict(m) for m in messages]}

@app.delete("/api/chats/{chat_id}")
def delete_chat(chat_id: int, user=Depends(get_user)):
    with db() as con:
        cur = con.execute("DELETE FROM chats WHERE id=? AND user_id=?", (chat_id, user["id"]))
        if cur.rowcount == 0:
            raise HTTPException(404, "Không tìm thấy cuộc trò chuyện.")
    return {"ok": True}

@app.post("/api/upload")
async def upload(file: UploadFile = File(...), user=Depends(get_user)):
    name = Path(file.filename or "file.txt").name
    ext = Path(name).suffix.lower()
    allowed = {".txt", ".md", ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".json", ".yaml", ".yml", ".toml", ".xml", ".sql", ".java", ".kt", ".c", ".h", ".cpp", ".cs", ".go", ".rs", ".php", ".rb", ".sh", ".log", ".csv"}
    if ext not in allowed:
        raise HTTPException(415, "Phiên bản này nhận file văn bản/code phổ biến; file PDF/DOCX/ZIP chưa được bật.")
    data = await file.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(413, "File quá lớn. Giới hạn hiện tại là 3 MB.")
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "Không đọc được file UTF-8.")
    return {"filename": name, "content": content[:MAX_CHARS], "truncated": len(content) > MAX_CHARS}

@app.post("/api/chat")
def chat(body: ChatBody, user=Depends(get_user)):
    if not API_KEY or not MODEL:
        raise HTTPException(503, "Chưa cấu hình LLM_API_KEY và LLM_MODEL trong Environment của Render.")
    message = body.message.strip()
    if not message:
        raise HTTPException(400, "Tin nhắn đang trống.")
    status = credit_status(user["id"])
    if status["credits"] < 1:
        raise HTTPException(429, "Bạn đã dùng hết credit hôm nay. Credit miễn phí sẽ làm mới lúc 00:00 UTC.")
    now = int(time.time())
    chat_id = body.chat_id
    with db() as con:
        if chat_id:
            chat_row = con.execute("SELECT id,title FROM chats WHERE id=? AND user_id=?", (chat_id, user["id"])).fetchone()
            if not chat_row:
                raise HTTPException(404, "Cuộc trò chuyện không tồn tại.")
        else:
            title = message[:48] + ("…" if len(message) > 48 else "")
            cur = con.execute("INSERT INTO chats(user_id,title,created_at,updated_at) VALUES(?,?,?,?)",
                              (user["id"], title or "Cuộc trò chuyện mới", now, now))
            chat_id = cur.lastrowid
        con.execute("INSERT INTO messages(chat_id,role,content,created_at) VALUES(?,?,?,?)",
                    (chat_id, "user", message, now))
        history = con.execute("SELECT role,content FROM messages WHERE chat_id=? ORDER BY id DESC LIMIT 20", (chat_id,)).fetchall()
        history = list(reversed(history))
        con.execute("UPDATE chats SET updated_at=? WHERE id=?", (now, chat_id))
    mode_prompt = (
        "\nChế độ hiện tại: VEX CODE. Ưu tiên viết, sửa, review, giải thích code; đưa giải pháp thực tế và kiểm tra giả định."
        if body.mode == "code" else
        "\nChế độ hiện tại: VEX SECURITY. Hỗ trợ CTF/lab, phân tích mã độc phòng thủ, threat modeling, rà soát lỗ hổng và kiểm thử hệ thống có quyền. Trình bày cách tái hiện trong môi trường được phép, tác động và biện pháp khắc phục. Không hướng dẫn đánh cắp thông tin đăng nhập, triển khai mã độc để gây hại, né tránh phát hiện nhằm xâm nhập trái phép hoặc tấn công mục tiêu không được phép; khi yêu cầu vượt giới hạn, chuyển sang cách kiểm thử/phòng thủ an toàn cụ thể."
    )
    msgs = [{"role": "system", "content": SYSTEM_PROMPT + mode_prompt}]
    for item in history:
        content = item["content"]
        if item["role"] == "user" and body.file_text and content == message:
            content += "\n\nNội dung file đính kèm:\n" + body.file_text[:MAX_CHARS]
        msgs.append({"role": item["role"], "content": content})
    try:
        response = requests.post(
            BASE_URL + "/chat/completions",
            headers={"Authorization": "Bearer " + API_KEY, "Content-Type": "application/json",
                     "HTTP-Referer": os.getenv("APP_PUBLIC_URL", "https://localhost"),
                     "X-Title": "Vex Code AI"},
            json={"model": MODEL, "messages": msgs, "temperature": 0.25, "max_tokens": MAX_OUTPUT_TOKENS},
            timeout=(10, 120)
        )
        if response.status_code >= 400:
            try:
                detail = response.json().get("error", {}).get("message", response.text[:400])
            except Exception:
                detail = response.text[:400]
            raise HTTPException(502, "Nhà cung cấp AI: " + str(detail))
        result = response.json()["choices"][0]["message"]["content"]
        if not isinstance(result, str):
            result = json.dumps(result, ensure_ascii=False)
    except HTTPException:
        raise
    except requests.Timeout:
        raise HTTPException(504, "AI phản hồi quá lâu. Hãy thử lại.")
    except Exception:
        raise HTTPException(502, "Không kết nối được nhà cung cấp AI. Kiểm tra model, API key và hạn mức.")
    with db() as con:
        con.execute("INSERT INTO messages(chat_id,role,content,created_at) VALUES(?,?,?,?)",
                    (chat_id, "assistant", result, int(time.time())))
        con.execute("UPDATE chats SET updated_at=? WHERE id=?", (int(time.time()), chat_id))
        today = time.strftime("%Y-%m-%d", time.gmtime())
        row = con.execute("SELECT credits_remaining,credits_day FROM users WHERE id=?", (user["id"],)).fetchone()
        remaining = DAILY_CREDITS if row["credits_day"] != today else row["credits_remaining"]
        remaining = max(0, remaining - 1)
        con.execute("UPDATE users SET credits_remaining=?,credits_day=? WHERE id=?", (remaining, today, user["id"]))
    return {"chat_id": chat_id, "reply": result, "credits": remaining, "daily_credits": DAILY_CREDITS}
