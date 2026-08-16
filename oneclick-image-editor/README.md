# OneClick Image Editor

A small Python image editor with a modern frontend and one-click edits.

## What is included

- One-click Enhance
- Sharpen
- Brighten
- Auto contrast
- Soft touch
- Black & white
- Compress
- Resize presets:
  - Instagram 1:1
  - Instagram Story 9:16
  - LinkedIn 1:1
  - YouTube 16:9
- Convert/download as PNG, JPG or WEBP
- Undo + reset
- Hold-to-compare original
- Optional AI background removal
- No database and no permanent upload storage

## Main libraries

### FastAPI
The small HTTP backend and `/api/edit` endpoint.

### Pillow
The main image-processing engine. It handles resizing, colour/contrast/brightness enhancement, sharpening, filters, compression and format conversion.

### python-multipart
Lets FastAPI receive browser file uploads as multipart form data.

### Uvicorn
Runs the FastAPI application locally and in production-style deployments.

### rembg (optional)
Adds one-click AI background removal. It is intentionally kept separate because it downloads/uses ML model dependencies and makes installation much heavier.

---

## Run the lightweight version

Python 3.11+ recommended.

### Windows PowerShell

```powershell
cd oneclick-image-editor
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

Open:

http://127.0.0.1:8000

## Production SEO configuration

Set `SITE_URL` to the public HTTPS origin before starting the app so canonical,
Open Graph, robots and sitemap URLs use the deployed domain:

```powershell
$env:SITE_URL="https://your-domain.example"
python main.py
```

## Enable AI background removal

The current rembg project supports Python 3.11–3.13.

```powershell
python -m pip install -r requirements-ai.txt
```

Restart the server. The "Remove BG" button will automatically enable.

## Enable AI SUPER EDIT with Groq

SUPER EDIT uses a Groq vision model to analyze a reduced preview and choose safe
photo adjustments. Pillow applies those adjustments locally to the original-resolution
image. Add your Groq API key to the included `.env` file and restart the app:

```dotenv
GROQ_API_KEY=your-groq-api-key
```

The default vision model is `meta-llama/llama-4-scout-17b-16e-instruct`. You can
override it without changing code:

```powershell
$env:GROQ_VISION_MODEL="your-supported-groq-vision-model"
```

The API key is read only by the FastAPI backend and must never be added to
`static/app.js` or committed to source control. Using SUPER EDIT sends a reduced
image preview to Groq for analysis.

## Architecture

Browser
  -> POST /api/edit
  -> FastAPI
  -> Pillow (or rembg for background removal)
  -> processed image returned directly to browser

The app does not need a database. Each edit uploads the current image, processes it, and streams the result back.

## Important note about "Enhance"

The built-in Enhance button is a fast conventional photo enhancement preset using Pillow. It improves contrast, colour and sharpness but it is **not generative AI upscaling**. A real AI super-resolution feature can be added later using a dedicated model such as Real-ESRGAN or an external API.
