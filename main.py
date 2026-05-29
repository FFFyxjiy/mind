import io
import base64
import uuid
import os
import sqlite3
from fastapi import FastAPI, Request, Form, UploadFile, File, Depends
from fastapi.responses import HTMLResponse, Response, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, Column, String, Integer, Text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from itsdangerous import URLSafeSerializer
import segno

# --- НАСТРОЙКИ ЭКОСИСТЕМЫ LABID ---
SECRET_KEY = os.getenv("SECRET_KEY", "labretto_super_secret_change_later")
DOMAIN = os.getenv("DOMAIN", "labretto.ru")

# Путь до базы данных твоего LabID (labretto-register)
LABID_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "labretto-register", "users.db"))

serializer = URLSafeSerializer(SECRET_KEY, salt="labid-session")


def get_labid_user(request: Request):
    """Читает куку LabID и достает данные пользователя из соседней базы"""
    session_cookie = request.cookies.get("labid_session")
    if not session_cookie:
        return None
    try:
        data = serializer.loads(session_cookie)
        user_id = data.get("user_id")
    except Exception:
        return None

    try:
        conn = sqlite3.connect(LABID_DB_PATH)
        conn.row_factory = sqlite3.Row
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        conn.close()

        if user:
            user_dict = dict(user)
            # Формируем имя: Никнейм -> Имя Фамилия -> Логин
            full_name = user_dict.get('nickname') or f"{user_dict.get('first_name', '')} {user_dict.get('last_name', '')}".strip() or user_dict.get('username')
            user_dict['display_name'] = full_name
            # Формируем ссылку на аватарку
            avatar_path = user_dict.get('avatar')
            user_dict['avatar_url'] = f"https://id.{DOMAIN}{avatar_path}" if avatar_path else ""
            return user_dict
    except Exception as e:
        print(f"Ошибка подключения к БД LabID: {e}")
    return None


# --- БАЗА ДАННЫХ ВИЗИТОК ---
DATABASE_URL = "sqlite:///./labretto_cards.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class DBProfile(Base):
    __tablename__ = "profiles"
    short_id = Column(String, primary_key=True, index=True)
    owner_id = Column(String, index=True)  # ID пользователя из LabID
    name = Column(String, default="")
    role = Column(String, default="")
    bio = Column(Text, default="")
    photo = Column(Text, default="")
    image_size = Column(Integer, default=140)
    image_radius = Column(Integer, default=50)
    font_size = Column(Integer, default=18)
    accent_color = Column(String, default="#2563eb")


class DBImage(Base):
    __tablename__ = "images"
    img_id = Column(String, primary_key=True, index=True)
    bytes_data = Column(Text)
    content_type = Column(String)


Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- ИНИЦИАЛИЗАЦИЯ ПРИЛОЖЕНИЯ ---
app = FastAPI(title="Card Labretto")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# --- ОСНОВНЫЕ РОУТЫ ---
@app.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request, db: Session = Depends(get_db)):
    user = get_labid_user(request)
    if not user:
        # Если не вошел — отправляем на авторизацию
        return RedirectResponse(url="/login")

    # Ищем визитки, принадлежащие этому пользователю
    profiles = db.query(DBProfile).filter(DBProfile.owner_id == str(user["id"])).all()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"request": request, "user": user, "profiles": profiles}
    )


@app.get("/login")
async def login_redirect(request: Request):
    # Перекидываем на LabID с возвратом обратно
    return RedirectResponse(url=f"https://id.{DOMAIN}/login?next=https://card.{DOMAIN}/")


@app.get("/editor", response_class=HTMLResponse)
async def editor_page(request: Request):
    user = get_labid_user(request)
    if not user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(request=request, name="editor.html", context={"request": request, "qr_code": None})


@app.post("/upload_image")
async def upload_image(image: UploadFile = File(...), db: Session = Depends(get_db)):
    img_id = str(uuid.uuid4())[:8]
    image_bytes = await image.read()
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    db_img = DBImage(img_id=img_id, bytes_data=image_b64, content_type=image.content_type)
    db.add(db_img)
    db.commit()
    return {"url": f"/image/{img_id}"}


@app.get("/image/{img_id}")
async def get_image(img_id: str, db: Session = Depends(get_db)):
    db_img = db.query(DBImage).filter(DBImage.img_id == img_id).first()
    if not db_img:
        return Response(status_code=404)
    raw_bytes = base64.b64decode(db_img.bytes_data)
    return Response(content=raw_bytes, media_type=db_img.content_type)


@app.post("/editor", response_class=HTMLResponse)
async def generate_profile(
        request: Request,
        name: str = Form(""),
        role: str = Form(""),
        bio_html: str = Form(""),
        image_size: int = Form(140),
        image_radius: int = Form(50),
        font_size: int = Form(18),
        accent_color: str = Form("#2563eb"),
        photo: UploadFile = File(None),
        db: Session = Depends(get_db)
):
    user = get_labid_user(request)
    if not user:
        return RedirectResponse(url="/login")

    photo_b64 = ""
    if photo and photo.filename:
        photo_bytes = await photo.read()
        if photo_bytes:
            photo_b64 = base64.b64encode(photo_bytes).decode("utf-8")

    short_id = str(uuid.uuid4())[:8]

    new_profile = DBProfile(
        short_id=short_id,
        owner_id=str(user["id"]),
        name=name,
        role=role,
        bio=bio_html,
        photo=photo_b64,
        image_size=image_size,
        image_radius=image_radius,
        font_size=font_size,
        accent_color=accent_color
    )
    db.add(new_profile)
    db.commit()

    target_url = f"{str(request.base_url).rstrip('/')}/view/{short_id}"
    qr = segno.make(target_url)
    buffer = io.BytesIO()
    qr.save(buffer, kind="png", scale=6)
    buffer.seek(0)
    qr_data_url = f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode('utf-8')}"

    return templates.TemplateResponse(
        request=request,
        name="editor.html",
        context={"request": request, "qr_code": qr_data_url, "target_url": target_url}
    )


@app.get("/view/{short_id}", response_class=HTMLResponse)
async def view_profile(request: Request, short_id: str, db: Session = Depends(get_db)):
    profile = db.query(DBProfile).filter(DBProfile.short_id == short_id).first()
    if not profile:
        return HTMLResponse(
            "<h1 style='text-align:center; margin-top:50px; font-family:sans-serif;'>Профиль не найден</h1>",
            status_code=404)
    return templates.TemplateResponse(request=request, name="card.html", context={"request": request, "profile": profile})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8020, reload=True)