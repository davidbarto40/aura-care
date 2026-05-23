"""
Aura-Care · web.py
───────────────────
Servidor web FastAPI.
  GET  /           → dashboard HTML
  GET  /api/state  → snapshot JSON del sistema
  GET  /api/stream → Server-Sent Events (push en tiempo real al navegador)
  POST /api/resolve/{idx} → marcar alerta como resuelta
"""

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import state as st

# Rutas absolutas relativas a este fichero → funciona desde cualquier directorio
BASE_DIR     = Path(__file__).parent           # .../aura-care/server/
TEMPLATE_DIR = BASE_DIR.parent / "templates"  # .../aura-care/templates/
STATIC_DIR   = BASE_DIR.parent / "static"     # .../aura-care/static/

# Crear static/ si no existe (Git no sube carpetas vacías)
STATIC_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Aura-Care Dashboard")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/api/state")
async def api_state():
    return JSONResponse(st.system_snapshot())


@app.post("/api/resolve/{idx}")
async def api_resolve(idx: int):
    if 0 <= idx < len(st.alert_history):
        st.alert_history[idx].resolved = True
        return {"ok": True}
    return JSONResponse({"ok": False, "error": "index out of range"}, status_code=404)


@app.get("/api/stream")
async def api_stream():
    """Server-Sent Events: envía un snapshot cada segundo."""
    async def generator():
        while True:
            data = json.dumps(st.system_snapshot())
            yield f"data: {data}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    html_path = TEMPLATE_DIR / "dashboard.html"
    return html_path.read_text(encoding="utf-8")
