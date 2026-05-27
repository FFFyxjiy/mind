import io
import base64
import uuid
from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import segno

app = FastAPI(title="Mind Profiles")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

fake_db = {}
image_store = {}

@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={"request": request})

@app.get("/editor", response_class=HTMLResponse)
async def editor_page(request: Request):
    return templates.TemplateResponse(request=request, name="editor.html", context={"request": request, "qr_code": None})

@app.post("/upload_image")
async def upload_image(image: UploadFile = File(...)):
    img_id = str(uuid.uuid4())[:8]
    image_bytes = await image.read()
    image_store[img_id] = {
        "bytes": image_bytes,
        "content_type": image.content_type
    }
    return {"url": f"/image/{img_id}"}

@app.get("/image/{img_id}")
async def get_image(img_id: str):
    img_data = image_store.get(img_id)
    if not img_data:
        return Response(status_code=404)
    return Response(content=img_data["bytes"], media_type=img_data["content_type"])

@app.post("/editor", response_class=HTMLResponse)
async def generate_profile(
    request: Request,
    name: str = Form(""),
    role: str = Form(""),
    bio_html: str = Form(""),
    image_size: int = Form(140),         # Размер в пикселях
    image_radius: int = Form(50),        # Скругление в %
    font_size: int = Form(18),           # Размер шрифта в px
    accent_color: str = Form("#2563eb"), # Цвет акцента HEX
    photo: UploadFile = File(None)
):
    photo_b64 = ""
    if photo and photo.filename:
        photo_bytes = await photo.read()
        if photo_bytes:
            photo_b64 = base64.b64encode(photo_bytes).decode("utf-8")

    short_id = str(uuid.uuid4())[:8]
    fake_db[short_id] = {
        "name": name,
        "role": role,
        "bio": bio_html,
        "photo": photo_b64,
        "image_size": image_size,
        "image_radius": image_radius,
        "font_size": font_size,
        "accent_color": accent_color
    }

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
async def view_profile(request: Request, short_id: str):
    profile = fake_db.get(short_id)
    if not profile:
        return HTMLResponse(
            "<h1 style='text-align:center; margin-top:50px; font-family:sans-serif;'>Профиль не найден</h1>",
            status_code=404
        )
    return templates.TemplateResponse(request=request, name="card.html", context={"request": request, "profile": profile})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)