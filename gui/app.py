#!/usr/bin/env python3
"""
GCAF 2026 Auto Messenger GUI - FastAPI server
"""
import asyncio
import html
import os
import secrets
import shutil
import sys
import threading
import time
import urllib.parse
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from dotenv import load_dotenv
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Fix Python path so bot and cli packages are importable
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from bot import db
from bot.whatsapp_bot import send_whatsapp_instant
from gui.checker_async import get_check_status, start_check_background, stop_check_background

load_dotenv()

# ── Auth config ──
DASHBOARD_TOKEN = os.getenv("DASHBOARD_TOKEN", "")
if not DASHBOARD_TOKEN:
    print("⚠ DASHBOARD_TOKEN belum di-set; hanya bind 127.0.0.1")

_AUTH_EXEMPT_PATHS = {"/login", "/healthz"}

# Rate limiter in-memory sederhana: {client_ip: [timestamps]}
_RATE_LIMIT: dict = {}
_RATE_LOCK = threading.Lock()
_RATE_LIMIT_MAX = 10
_RATE_LIMIT_WINDOW = 60.0

# Cache TTL kecil untuk cek "sudah ada peserta?" (hindari query COUNT tiap request)
_PLAYERS_CACHE = {"has_players": None, "ts": 0.0}
_PLAYERS_CACHE_TTL = 3.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    db.init_db()
    yield
    # Shutdown: tutup resource jangka panjang (Selenium driver, Telethon client)
    try:
        from bot.whatsapp_bot import close_wa_driver
        close_wa_driver()
    except (OSError, RuntimeError) as e:
        print(f"[GUI] close_wa_driver error: {e}")
    try:
        from bot import telegram_bot as _tg_module
        _closer = getattr(_tg_module, "close_telegram_client", None)
        if callable(_closer):
            res = _closer()
            if asyncio.iscoroutine(res):
                await res
    except (OSError, RuntimeError, ValueError) as e:
        print(f"[GUI] close_telegram_client error: {e}")


app = FastAPI(title="GCAF Auto Messenger", lifespan=lifespan)


# Paths
BASE_DIR = Path(__file__).parent.parent
GUI_DIR = BASE_DIR / "gui"
app.mount("/static", StaticFiles(directory=GUI_DIR / "static"), name="static")
templates = Jinja2Templates(directory=GUI_DIR / "templates")

# Rute yang tetap boleh diakses walau belum ada peserta sama sekali
_ONBOARDING_ALLOWED_PATHS = {"/", "/upload", "/api/dashboard-upload", "/templates", "/login", "/healthz"}


def _has_players_cached() -> bool:
    """Cek keberadaan peserta dengan cache TTL pendek (hindari COUNT per request)."""
    global _PLAYERS_CACHE
    now = time.time()
    with _RATE_LOCK:
        cached = _PLAYERS_CACHE
        if cached["has_players"] is not None and now - cached["ts"] < _PLAYERS_CACHE_TTL:
            return cached["has_players"]
        has = db.get_players_total_from_reports() > 0
        _PLAYERS_CACHE = {"has_players": has, "ts": now}
        return has


def _is_rate_limited(client_ip: str) -> bool:
    """True jika client melebihi batas request dalam window 1 menit."""
    now = time.time()
    with _RATE_LOCK:
        # Bersihkan key yang sudah tidak aktif (cegah pertumbuhan tak terbatas)
        if len(_RATE_LIMIT) > 500:
            for ip in [ip for ip, ts_list in _RATE_LIMIT.items() if not any(now - t < _RATE_LIMIT_WINDOW for t in ts_list)]:
                del _RATE_LIMIT[ip]
        hits = [t for t in _RATE_LIMIT.get(client_ip, []) if now - t < _RATE_LIMIT_WINDOW]
        if len(hits) >= _RATE_LIMIT_MAX:
            _RATE_LIMIT[client_ip] = hits
            return True
        hits.append(now)
        _RATE_LIMIT[client_ip] = hits
        return False


def _token_valid(request: Request) -> bool:
    """Cek token dari Authorization header, cookie gcaf_token, atau ?token= (GET saja)."""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer ") and secrets.compare_digest(auth[7:].strip(), DASHBOARD_TOKEN):
        return True
    cookie = request.cookies.get("gcaf_token", "")
    if cookie and secrets.compare_digest(cookie, DASHBOARD_TOKEN):
        return True
    if request.method == "GET":
        q = request.query_params.get("token")
        if q and secrets.compare_digest(q, DASHBOARD_TOKEN):
            return True
    return False


@app.middleware("http")
async def require_players_middleware(request: Request, call_next):
    """Blokir semua fitur selain dashboard/upload jika belum ada peserta yang diimport."""
    path = request.url.path
    if path.startswith("/static") or path in _ONBOARDING_ALLOWED_PATHS:
        return await call_next(request)

    if not _has_players_cached():
        if request.headers.get("HX-Request"):
            from starlette.responses import Response
            return Response(status_code=200, headers={"HX-Redirect": "/"})
        return RedirectResponse(url="/", status_code=303)

    return await call_next(request)


@app.middleware("http")
async def csrf_origin_middleware(request: Request, call_next):
    """Tolak state-changing request (POST/PUT/DELETE) dari origin/referer beda host."""
    if request.method in ("POST", "PUT", "DELETE"):
        origin = request.headers.get("origin")
        referer = request.headers.get("referer")
        source = None
        if origin:
            source = urllib.parse.urlparse(origin).netloc
        elif referer:
            source = urllib.parse.urlparse(referer).netloc
        if source and source != request.url.netloc:
            return JSONResponse(status_code=403, content={"detail": "Forbidden: asal permintaan tidak dikenali"})
    return await call_next(request)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Token auth: Bearer header / cookie gcaf_token / ?token= (GET)."""
    path = request.url.path
    if not DASHBOARD_TOKEN:
        return await call_next(request)  # mode terbuka — warning sudah dicetak saat startup
    if path.startswith("/static") or path in _AUTH_EXEMPT_PATHS:
        return await call_next(request)
    if _token_valid(request):
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    response = RedirectResponse(url="/login", status_code=303)
    if request.headers.get("HX-Request"):
        response.headers["HX-Redirect"] = "/login"
    return response


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if not DASHBOARD_TOKEN:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "_login.html", {"error": ""})


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request):
    if not DASHBOARD_TOKEN:
        return RedirectResponse(url="/", status_code=303)
    form = await request.form()
    token = form.get("token", "")
    if isinstance(token, str) and token and secrets.compare_digest(token, DASHBOARD_TOKEN):
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(
            "gcaf_token", DASHBOARD_TOKEN, httponly=True, samesite="lax",
            secure=request.url.scheme == "https", max_age=7 * 24 * 3600,
        )
        return response
    return templates.TemplateResponse(request, "_login.html", {"error": "Token akses salah."})


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    stats = db.get_dashboard_stats()
    logs = db.get_recent_logs(limit=5)
    
    # If no reports, show onboarding instead of dashboard
    if stats.get("total_reports", 0) == 0:
        return templates.TemplateResponse(request, "_onboarding.html", {})

    s = get_check_status()
    return templates.TemplateResponse(request, "dashboard.html", {
        "stats": stats, "logs": logs,
        "is_running": s.get("status") == "running",
        "status": s.get("status", "idle"),
        "progress": s.get("progress", 0),
        "total": s.get("total", 1),
        "phase": s.get("phase", ""),
        "error": s.get("error", ""),
        "all_checked": stats.get("unscanned_count", 0) == 0,
    })

@app.get("/api/dashboard-upload", response_class=HTMLResponse)
async def dashboard_upload_form(request: Request):
    return templates.TemplateResponse(request, "_dashboard_upload.html", {})

def _persist_upload(tmp_path: str, src) -> None:
    """Tulis file upload ke disk (blocking; dipanggil via asyncio.to_thread)."""
    with open(tmp_path, "wb") as dst:
        shutil.copyfileobj(src, dst)


@app.post("/upload", response_class=HTMLResponse)
async def upload_csv(request: Request, file: Annotated[UploadFile, File()]):
    import os
    import tempfile
    from pathlib import Path

    tmpdir = tempfile.mkdtemp(prefix="gcaf_upload_")
    safe_name = Path(file.filename or "upload.csv").name
    tmp_path = os.path.join(tmpdir, safe_name)
    await asyncio.to_thread(_persist_upload, tmp_path, file.file)

    is_dashboard = request.headers.get("HX-Target") == "dashboard-upload"
    template_name = "_dashboard_upload_result.html" if is_dashboard else "_upload_result.html"
    try:
        imported, skipped = db.import_daily_report(tmp_path)
        if imported > 0:
            # Import sukses — invalidasi cache "sudah ada peserta?" agar dashboard langsung beralih
            global _PLAYERS_CACHE
            _PLAYERS_CACHE = {"has_players": True, "ts": 0.0}
            return templates.TemplateResponse(request, template_name, {
                "state": "success", "imported": imported, "skipped": skipped,
            })
        return templates.TemplateResponse(request, template_name, {"state": "empty"})
    except (ValueError, OSError):
        return templates.TemplateResponse(request, template_name, {"state": "error"})
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

@app.get("/players", response_class=HTMLResponse)
async def players_list(request: Request, search: str = "", limit: int = 100, offset: int = 0):
    limit = max(1, limit)
    offset = max(0, offset)
    players = db.get_players_summary(search, limit, offset)
    total = db.get_players_total_from_reports()
    has_prev = offset > 0
    has_next = offset + limit < total
    ctx = {
        "players": players, "total": total, "search": search,
        "limit": limit, "offset": offset,
        "has_prev": has_prev, "has_next": has_next,
    }

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "_players_table.html", ctx)

    return templates.TemplateResponse(request, "players.html", ctx)

@app.post("/players/toggle-tg/{nomor}", response_class=HTMLResponse)
async def toggle_tg(request: Request, nomor: str):
    db.toggle_tg_joined(nomor)
    p = db.get_player_summary_by_phone(nomor)
    if not p:
        return HTMLResponse(content="""<span class="text-xs" style="color: var(--danger);">Peserta tidak ditemukan</span>""")
    return templates.TemplateResponse(request, "_player_row.html", {"p": p})


@app.post("/check", response_class=HTMLResponse)
async def start_check(request: Request):
    s = get_check_status()
    if s.get("status") == "running":
        # Sudah ada check berjalan — jangan start proses kedua
        return templates.TemplateResponse(request, "_check_widget.html", {
            "is_running": True, "status": "running",
            "progress": s.get("progress", 0),
            "total": max(s.get("total", 1), 1),
            "phase": s.get("phase", ""),
            "error": s.get("error", ""),
        })

    unscanned = db.get_players_unused_numbers()
    if unscanned:
        start_check_background()
        return templates.TemplateResponse(request, "_check_widget.html", {
            "is_running": True, "status": "running",
            "progress": 0, "total": len(unscanned),
            "phase": "", "error": "",
        })

    # Tidak ada nomor baru untuk dicek — jangan pura-pura "memeriksa".
    return templates.TemplateResponse(request, "_check_widget.html", {
        "is_running": False,
        "status": "done" if s.get("status") == "done" else "idle",
        "progress": s.get("progress", 0),
        "total": max(s.get("total", 1), 1),
        "phase": s.get("phase", ""),
        "error": s.get("error", ""),
        "all_checked": True,
        "notice": "Tidak ada nomor baru untuk dicek.",
    })

@app.get("/check", response_class=HTMLResponse)
async def check_page(request: Request):
    # Fitur cek nomor difokuskan di dashboard utama; halaman standalone dihapus.
    return RedirectResponse(url="/", status_code=303)

@app.post("/check/stop", response_class=HTMLResponse)
async def stop_check(request: Request):
    """Hentikan check yang sedang berjalan tanpa menunggu batas waktu stale."""
    s = stop_check_background()
    return templates.TemplateResponse(request, "_check_widget.html", {
        "is_running": False,
        "status": s.get("status", "idle"),
        "progress": s.get("progress", 0),
        "total": max(s.get("total", 1), 1),
        "phase": s.get("phase", ""),
        "error": s.get("error", ""),
    })


@app.get("/check/status", response_class=HTMLResponse)
async def check_status(request: Request):
    s = get_check_status()
    status = s.get("status", "idle")

    if status in ("idle", "done"):
        unscanned = db.get_players_unused_numbers()
        all_checked = not unscanned
        # Kalau semua sudah dicek, tampilkan hasil nyata dari status file (progress=total),
        # bukan "0 dari 1" yang menyesatkan. Jangan mengarang angka bila belum ada riwayat check.
        if all_checked:
            done_total = max(s.get("total", 1), 1)
            done_progress = s.get("progress", 0)
        else:
            done_total = len(unscanned) or 1
            done_progress = 0
        response = templates.TemplateResponse(request, "_check_widget.html", {
            "is_running": False,
            "progress": done_progress,
            "total": done_total,
            "status": None if unscanned else "done",
            "all_checked": all_checked,
        })
        if status == "done":
            response.headers["HX-Trigger"] = "update-dashboard"
        return response

    response = templates.TemplateResponse(request, "_check_widget.html", {
        "is_running": status == "running",
        "status": status,
        "progress": s.get("progress", 0),
        "total": max(s.get("total", 1), 1),
        "phase": s.get("phase", ""),
        "error": s.get("error", ""),
    })
    return response

@app.get("/api/dashboard-stats", response_class=HTMLResponse)
async def api_dashboard_stats(request: Request):
    stats = db.get_dashboard_stats()
    return templates.TemplateResponse(request, "_dashboard_stats.html", {"stats": stats})

@app.get("/api/dashboard-logs", response_class=HTMLResponse)
async def api_dashboard_logs(request: Request):
    logs = db.get_recent_logs(limit=5)
    return templates.TemplateResponse(request, "_dashboard_logs.html", {"logs": logs})

@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request, limit: int = 100, offset: int = 0):
    limit = max(1, limit)
    offset = max(0, offset)
    logs = db.get_send_logs(limit, offset)
    total = db.get_send_logs_count()
    has_prev = offset > 0
    has_next = offset + limit < total
    return templates.TemplateResponse(request, "logs.html", {
        "logs": logs, "total": total,
        "limit": limit, "offset": offset,
        "has_prev": has_prev, "has_next": has_next,
    })

@app.get("/api/message-preview/{nomor_normalized}", response_class=HTMLResponse)
async def message_preview(request: Request, nomor_normalized: str, type: str = "kasual"):
    from bot.utils import TEMPLATES, personalize_message
    
    player = db.get_player_summary_by_phone(nomor_normalized)
    if not player:
        return """<span class="text-xs" style="color: var(--danger);">Peserta tidak ditemukan</span>"""
    
    fasil_name = os.getenv("FASIL_NAME", "Irfan Zharauri")
    fasil_kode = os.getenv("FASIL_CODE", "GCAF26-ID-9MJ-EP6")
    
    if type == "remind-both":
        # Preview menunjukkan PESAN GABUNGAN yang benar-benar akan dikirim
        tpl = TEMPLATES.get("remind-both")
        if not tpl:
            return """<span class="text-xs" style="color: var(--danger);">Template tak dikenal</span>"""
        msg = personalize_message(tpl, player, fasil_name, fasil_kode)
        return templates.TemplateResponse(request, "_msg_preview.html", {
            "player": player, "type": type, "msg_wa": msg, "msg_tg": msg,
        })
    
    tpl = TEMPLATES.get(type)
    if not tpl:
        return """<span class="text-xs" style="color: var(--danger);">Template tak dikenal</span>"""
    
    msg = personalize_message(tpl, player, fasil_name, fasil_kode)
    return templates.TemplateResponse(request, "_msg_preview.html", {
        "player": player, "type": type, "msg_wa": msg
    })

@app.post("/api/send-wa/{nomor_normalized}", response_class=HTMLResponse)
async def send_wa(request: Request, nomor_normalized: str, type: str = "kasual"):
    from bot.utils import TEMPLATES, personalize_message

    client_ip = request.client.host if request.client else "unknown"
    if _is_rate_limited(client_ip):
        return HTMLResponse(
            content="""<span style="color: var(--danger);">Terlalu banyak permintaan — coba lagi sebentar lagi</span>""",
            status_code=429,
        )

    player = db.get_player_summary_by_phone(nomor_normalized)
    if not player:
        return HTMLResponse(content="""<span style="color: var(--danger);">Error</span>""")
    fasil_name = os.getenv("FASIL_NAME", "Irfan Zharauri")
    fasil_kode = os.getenv("FASIL_CODE", "GCAF26-ID-9MJ-EP6")
    tpl = TEMPLATES.get(type)
    if not tpl:
        return HTMLResponse(content="""<span style="color: var(--danger);">Template tak dikenal</span>""")
    msg = personalize_message(tpl, player, fasil_name, fasil_kode)
    try:
        # Selenium blocking → jalankan di thread terpisah agar event loop tidak macet
        result = await asyncio.to_thread(send_whatsapp_instant, nomor_normalized, msg)
        if result.get("status") == "success":
            db.insert_send_log({
                "nomor_hp": player["nomor_hp"],
                "nama": player["nama"],
                "wa_available": True,
                "wa_sent": True,
                "mode": type,
            })
            return HTMLResponse(
                content="""<span style="color: var(--wa-green);">✓ Terkirim via WA</span>""",
                headers={"HX-Trigger": "update-dashboard"}
            )
        return HTMLResponse(content=f"""<span style="color: var(--danger);">Gagal: {html.escape(str(result.get("error", "unknown")))}</span>""")
    except (ValueError, OSError, RuntimeError) as e:
        return HTMLResponse(content=f"""<span style="color: var(--danger);">Gagal: {html.escape(str(e))}</span>""")

@app.post("/api/send-tg/{nomor_normalized}", response_class=HTMLResponse)
async def send_tg(request: Request, nomor_normalized: str, type: str = "kasual"):
    from bot.telegram_bot import send_telegram_user
    from bot.utils import TEMPLATES, personalize_message

    client_ip = request.client.host if request.client else "unknown"
    if _is_rate_limited(client_ip):
        return HTMLResponse(
            content="""<span style="color: var(--danger);">Terlalu banyak permintaan — coba lagi sebentar lagi</span>""",
            status_code=429,
        )

    player = db.get_player_summary_by_phone(nomor_normalized)
    if not player:
        return HTMLResponse(content="""<span style="color: var(--danger);">Error</span>""")
    if not player.get("tg_user_id"):
        return HTMLResponse(content="""<span style="color: var(--danger);">Gagal: TG User ID tidak ditemukan</span>""")
    fasil_name = os.getenv("FASIL_NAME", "Irfan Zharauri")
    fasil_kode = os.getenv("FASIL_CODE", "GCAF26-ID-9MJ-EP6")
    tpl = TEMPLATES.get(type)
    if not tpl:
        return HTMLResponse(content="""<span style="color: var(--danger);">Template tak dikenal</span>""")
    msg = personalize_message(tpl, player, fasil_name, fasil_kode)
    try:
        result = await send_telegram_user(int(player["tg_user_id"]), msg)
        if result.get("message_id"):
            db.insert_send_log({
                "nomor_hp": player["nomor_hp"],
                "nama": player["nama"],
                "tg_available": True,
                "tg_sent": True,
                "mode": type,
            })
            return HTMLResponse(
                content="""<span style="color: var(--tg-blue);">✓ Terkirim via TG</span>""",
                headers={"HX-Trigger": "update-dashboard"}
            )
        return HTMLResponse(content="""<span style="color: var(--danger);">Gagal</span>""")
    except (ValueError, OSError, RuntimeError) as e:
        return HTMLResponse(content=f"""<span style="color: var(--danger);">Gagal: {html.escape(str(e))}</span>""")

@app.get("/templates", response_class=HTMLResponse)
async def templates_page(request: Request):
    from bot.utils import TEMPLATES
    return templates.TemplateResponse(request, "templates.html", {"templates": TEMPLATES})

@app.post("/templates/save/{key}", response_class=HTMLResponse)
async def save_template(request: Request, key: str):
    import json

    from bot.utils import _DEFAULT_TEMPLATES, _TEMPLATES_JSON, _load_templates
    
    form = await request.form()
    new_content = form.get("content", "")
    if not isinstance(new_content, str):
        new_content = ""
    
    current = _load_templates() or dict(_DEFAULT_TEMPLATES)
    current[key] = new_content
    
    # Persist
    _TEMPLATES_JSON.parent.mkdir(parents=True, exist_ok=True)
    _TEMPLATES_JSON.write_text(json.dumps(current, indent=2, ensure_ascii=False))
    
    # Hot-reload in-process
    from bot import utils as utils_mod
    utils_mod.TEMPLATES.clear()
    utils_mod.TEMPLATES.update(current)
    
    return templates.TemplateResponse(request, "_template_card.html", {"key": key, "tpl": new_content})

if __name__ == "__main__":
    import uvicorn
    default_host = "127.0.0.1" if not DASHBOARD_TOKEN else "0.0.0.0"
    # reload=True tidak aman dipakai bersama multiprocessing.Process (worker pengecekan):
    # reloader men-spawn server, lalu spawn worker di dalamnya → pada macOS/Linux
    # child worker ikut mengeksekusi ulang uvicorn.run. Default OFF; aktifkan hanya
    # saat pengembangan via env GUI_RELOAD=1.
    reload = os.getenv("GUI_RELOAD", "").lower() in ("1", "true", "yes")
    uvicorn.run("gui.app:app", host=os.getenv("HOST", default_host), port=8000, reload=reload)
