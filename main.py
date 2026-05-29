import io
import base64
import uuid
from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, Column, String, Integer, Text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
import segno

# --- НАСТРОЙКА НАДЁЖНОЙ БАЗЫ ДАННЫХ (SQLite) ---
DATABASE_URL = "sqlite:///./labretto_cards.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# Таблица для хранения профилей
class DBProfile(Base):
    __tablename__ = "profiles"
    short_id = Column(String, primary_key=True, index=True)
    name = Column(String, default="")
    role = Column(String, default="")
    bio = Column(Text, default="")
    photo = Column(Text, default="")  # Главное фото в Base64
    image_size = Column(Integer, default=140)
    image_radius = Column(Integer, default=50)
    font_size = Column(Integer, default=18)
    accent_color = Column(String, default="#2563eb")


# Таблица для хранения картинок из текста статьи
class DBImage(Base):
    __tablename__ = "images"
    img_id = Column(String, primary_key=True, index=True)
    bytes_data = Column(Text)  # Сами байты картинки в Base64 для простоты хранения в SQLite
    content_type = Column(String)


# Создаем таблицы в файле базы данных, если их ещё нет
Base.metadata.create_all(bind=engine)

# --- ИНИЦИАЛИЗАЦИЯ FASTAPI ---
app = FastAPI(title="Mind Profiles")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# Зависимость для удобного подключения к БД
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={"request": request})


@app.get("/editor", response_class=HTMLResponse)
async def editor_page(request: Request):
    return templates.TemplateResponse(request=request, name="editor.html",
                                      context={"request": request, "qr_code": None})


# --- ЗАГРУЗКА КАРТИНОК ИЗ ТЕКСТА В БД ---
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


# --- СОХРАНЕНИЕ ПРОФИЛЯ В БД ---
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
    photo_b64 = ""
    if photo and photo.filename:
        photo_bytes = await photo.read()
        if photo_bytes:
            photo_b64 = base64.b64encode(photo_bytes).decode("utf-8")

    short_id = str(uuid.uuid4())[:8]

    # Записываем всё в базу данных SQLite
    new_profile = DBProfile(
        short_id=short_id,
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

    # Формируем железную ссылку через домен из Caddy
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
    # Ищем профиль в базе данных файле
    profile = db.query(DBProfile).filter(DBProfile.short_id == short_id).first()
    if not profile:
        return HTMLResponse(
            "<h1 style='text-align:center; margin-top:50px; font-family:sans-serif;'>Профиль не найден</h1>",
            status_code=404
        )
    return templates.TemplateResponse(request=request, name="card.html",
                                      context={"request": request, "profile": profile})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8020, reload=True)