from __future__ import annotations

import asyncio
import base64
import io
import json
import os
from pathlib import Path
from typing import Annotated
from urllib import error as urllib_error
from urllib import request as urllib_request

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, UnidentifiedImageError
from dotenv import load_dotenv

try:
    from rembg import remove as remove_background
    REMBG_AVAILABLE = True
except ImportError:
    remove_background = None
    REMBG_AVAILABLE = False


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
load_dotenv(BASE_DIR / ".env")
SITE_URL = os.getenv("SITE_URL", "http://localhost:8000").rstrip("/")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_VISION_MODEL = os.getenv(
    "GROQ_VISION_MODEL",
    "meta-llama/llama-4-scout-17b-16e-instruct",
).strip()

MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_PIXELS = 32_000_000

app = FastAPI(
    title="OneClick Image Editor",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url=None,
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home() -> HTMLResponse:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace("{{SITE_URL}}", SITE_URL))


@app.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
def robots() -> str:
    return f"User-agent: *\nAllow: /\nDisallow: /api/\nSitemap: {SITE_URL}/sitemap.xml\n"


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap() -> Response:
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"  <url><loc>{SITE_URL}/</loc><changefreq>monthly</changefreq><priority>1.0</priority></url>\n"
        "</urlset>"
    )
    return Response(content=xml, media_type="application/xml")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/capabilities")
def capabilities() -> dict:
    return {
        "backgroundRemoval": REMBG_AVAILABLE,
        "superEdit": bool(GROQ_API_KEY),
        "maxUploadMB": MAX_UPLOAD_BYTES // (1024 * 1024),
        "formats": ["PNG", "JPEG", "WEBP"],
    }


def load_image(data: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=400, detail="That file is not a supported image.") from exc

    if image.width * image.height > MAX_PIXELS:
        raise HTTPException(
            status_code=413,
            detail="Image is too large. Please use an image under 32 megapixels.",
        )

    # Respect phone-camera orientation stored in EXIF.
    return ImageOps.exif_transpose(image)


def normalize_for_processing(image: Image.Image) -> Image.Image:
    if image.mode in ("RGB", "RGBA"):
        return image
    if "A" in image.getbands():
        return image.convert("RGBA")
    return image.convert("RGB")


def create_ai_preview(image: Image.Image) -> str:
    preview = image.convert("RGB")
    preview.thumbnail((768, 768), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    preview.save(output, format="JPEG", quality=78, optimize=True)
    return base64.b64encode(output.getvalue()).decode("ascii")


def analyze_with_groq(image: Image.Image) -> dict:
    if not GROQ_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="SUPER EDIT is not configured. Set the GROQ_API_KEY environment variable.",
        )

    prompt = (
        "You are a conservative professional photo editor. Analyze this image and return ONLY a JSON object "
        "with these keys: brightness, contrast, saturation, sharpness (numbers), and autocontrast (boolean). "
        "Use 1.0 for no change. Keep brightness/contrast between 0.85 and 1.20, saturation between 0.80 and "
        "1.20, and sharpness between 0.80 and 1.50. Improve the photo naturally without changing its content."
    )
    payload = {
        "model": GROQ_VISION_MODEL,
        "temperature": 0.1,
        "max_completion_tokens": 180,
        "response_format": {"type": "json_object"},
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{create_ai_preview(image)}"}},
            ],
        }],
    }
    req = urllib_request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=35) as response:
            body = json.loads(response.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"].strip()
        start, end = content.find("{"), content.rfind("}")
        if start < 0 or end < start:
            raise ValueError("Groq did not return an adjustment object.")
        return json.loads(content[start:end + 1])
    except urllib_error.HTTPError as exc:
        detail = "Groq rejected the SUPER EDIT request. Check the API key and vision model."
        raise HTTPException(status_code=502, detail=detail) from exc
    except (urllib_error.URLError, TimeoutError) as exc:
        raise HTTPException(status_code=504, detail="Groq did not respond in time. Please try again.") from exc
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail="Groq returned an invalid edit plan. Please try again.") from exc


def apply_super_edit(image: Image.Image, plan: dict) -> Image.Image:
    def factor(name: str, low: float, high: float) -> float:
        try:
            return max(low, min(float(plan.get(name, 1.0)), high))
        except (TypeError, ValueError):
            return 1.0

    edited = image.convert("RGB")
    if plan.get("autocontrast") is True:
        edited = ImageOps.autocontrast(edited, cutoff=0.5)
    edited = ImageEnhance.Brightness(edited).enhance(factor("brightness", 0.85, 1.20))
    edited = ImageEnhance.Contrast(edited).enhance(factor("contrast", 0.85, 1.20))
    edited = ImageEnhance.Color(edited).enhance(factor("saturation", 0.80, 1.20))
    return ImageEnhance.Sharpness(edited).enhance(factor("sharpness", 0.80, 1.50))


def resize_cover(
    image: Image.Image,
    size: tuple[int, int],
    crop_x: float = 0.5,
    crop_y: float = 0.5,
    crop_zoom: float = 1.0,
) -> Image.Image:
    target_width, target_height = size
    crop_x = max(0.0, min(crop_x, 1.0))
    crop_y = max(0.0, min(crop_y, 1.0))
    crop_zoom = max(1.0, min(crop_zoom, 3.0))

    # Use the same cover + zoom geometry as the browser preview.
    scale = max(target_width / image.width, target_height / image.height) * crop_zoom
    resized_width = max(target_width, round(image.width * scale))
    resized_height = max(target_height, round(image.height * scale))
    resized = image.resize((resized_width, resized_height), Image.Resampling.LANCZOS)
    left = round((resized_width - target_width) * crop_x)
    top = round((resized_height - target_height) * crop_y)
    return resized.crop((left, top, left + target_width, top + target_height))


def apply_action(
    image: Image.Image,
    action: str,
    preset: str | None = None,
    crop_x: float = 0.5,
    crop_y: float = 0.5,
    crop_zoom: float = 1.0,
) -> Image.Image:
    image = normalize_for_processing(image)

    if action == "enhance":
        # Deliberately subtle: avoid the over-processed "HDR" look.
        image = ImageOps.autocontrast(image.convert("RGB"), cutoff=0.4)
        image = ImageEnhance.Contrast(image).enhance(1.10)
        image = ImageEnhance.Color(image).enhance(1.08)
        image = ImageEnhance.Sharpness(image).enhance(1.22)
        return image

    if action == "sharpen":
        return image.filter(ImageFilter.UnsharpMask(radius=1.4, percent=135, threshold=3))

    if action == "brighten":
        return ImageEnhance.Brightness(image).enhance(1.14)

    if action == "autocontrast":
        if image.mode == "RGBA":
            alpha = image.getchannel("A")
            rgb = ImageOps.autocontrast(image.convert("RGB"), cutoff=0.5)
            rgb.putalpha(alpha)
            return rgb
        return ImageOps.autocontrast(image.convert("RGB"), cutoff=0.5)

    if action == "grayscale":
        return ImageOps.grayscale(image).convert("RGB")

    if action == "soft":
        softened = image.filter(ImageFilter.GaussianBlur(radius=0.45))
        return Image.blend(image.convert("RGB"), softened.convert("RGB"), 0.24)

    if action == "resize":
        presets = {
            "instagram": (1080, 1080),
            "story": (1080, 1920),
            "linkedin": (800, 800),
            "whatsapp": (800, 800),
            "youtube": (1280, 720),
        }
        if preset not in presets:
            raise HTTPException(status_code=400, detail="Unknown resize preset.")
        return resize_cover(image, presets[preset], crop_x, crop_y, crop_zoom)

    if action == "remove_bg":
        if not REMBG_AVAILABLE or remove_background is None:
            raise HTTPException(
                status_code=503,
                detail='Background removal is optional. Install: pip install "rembg[cpu]"',
            )
        source = io.BytesIO()
        image.convert("RGBA").save(source, format="PNG")
        output = remove_background(source.getvalue())
        result = Image.open(io.BytesIO(output))
        result.load()
        return result.convert("RGBA")

    if action in {"compress", "convert"}:
        # Encoding happens later; pixels do not need changing.
        return image

    raise HTTPException(status_code=400, detail="Unknown edit action.")


def prepare_for_format(image: Image.Image, output_format: str) -> Image.Image:
    if output_format == "JPEG":
        if image.mode == "RGBA":
            background = Image.new("RGB", image.size, "white")
            background.paste(image, mask=image.getchannel("A"))
            return background
        return image.convert("RGB")

    if output_format in {"PNG", "WEBP"}:
        if image.mode not in ("RGB", "RGBA"):
            return image.convert("RGBA" if "A" in image.getbands() else "RGB")
        return image

    raise HTTPException(status_code=400, detail="Unsupported output format.")


def encode_image(
    image: Image.Image,
    output_format: str,
    quality: int,
    action: str,
) -> io.BytesIO:
    image = prepare_for_format(image, output_format)
    output = io.BytesIO()

    save_kwargs: dict = {}
    if output_format == "JPEG":
        save_kwargs = {
            "quality": quality,
            "optimize": True,
            "progressive": True,
        }
    elif output_format == "WEBP":
        save_kwargs = {
            "quality": quality,
            "method": 6,
        }
    elif output_format == "PNG":
        save_kwargs = {
            "optimize": True,
            "compress_level": 9 if action == "compress" else 6,
        }

    image.save(output, format=output_format, **save_kwargs)
    output.seek(0)
    return output


@app.post("/api/edit")
async def edit_image(
    file: Annotated[UploadFile, File(description="Image to edit")],
    action: Annotated[str, Form()],
    preset: Annotated[str | None, Form()] = None,
    crop_x: Annotated[float, Form()] = 0.5,
    crop_y: Annotated[float, Form()] = 0.5,
    crop_zoom: Annotated[float, Form()] = 1.0,
    output_format: Annotated[str, Form()] = "WEBP",
    quality: Annotated[int, Form()] = 82,
):
    content_type = (file.content_type or "").lower()
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Please upload an image file.")

    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Maximum upload size is 12 MB.")

    output_format = output_format.upper()
    if output_format == "JPG":
        output_format = "JPEG"
    if output_format not in {"PNG", "JPEG", "WEBP"}:
        raise HTTPException(status_code=400, detail="Choose PNG, JPEG or WEBP.")

    quality = max(35, min(int(quality), 95))

    image = load_image(raw)
    if action == "super_edit":
        plan = await asyncio.to_thread(analyze_with_groq, image)
        edited = apply_super_edit(image, plan)
    else:
        edited = apply_action(image, action, preset, crop_x, crop_y, crop_zoom)

    # Transparent background requires a format that supports transparency.
    if action == "remove_bg" and output_format == "JPEG":
        output_format = "PNG"

    output = encode_image(edited, output_format, quality, action)

    media_types = {
        "PNG": "image/png",
        "JPEG": "image/jpeg",
        "WEBP": "image/webp",
    }
    extensions = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}

    headers = {
        "Content-Disposition": f'inline; filename="edited.{extensions[output_format]}"',
        "X-Image-Width": str(edited.width),
        "X-Image-Height": str(edited.height),
        "X-Output-Format": output_format,
    }

    return StreamingResponse(
        output,
        media_type=media_types[output_format],
        headers=headers,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
