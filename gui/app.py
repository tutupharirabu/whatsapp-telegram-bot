#!/usr/bin/env python3
"""
GCAF 2026 Auto Messenger GUI - FastAPI server
"""
import os
import sys
from pathlib import Path
from fastapi import FastAPI, Request, Form, BackgroundTasks, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

# Fix Python path so bot and cli packages are importable
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from bot import db
from cli.checker import check_all
from bot.whatsapp_bot import send_whatsapp_instant
from bot.telegram_bot import send_telegram_message_sync

load_dotenv()

app = FastAPI(title="GCAF Auto Messenger")

# Paths
BASE_DIR = Path(__file__).parent.parent
GUI_DIR = BASE_DIR / "gui"
app.mount("/static", StaticFiles(directory=GUI_DIR / "static"), name="static")
templates = Jinja2Templates(directory=GUI_DIR / "templates")

@app.on_event("startup")
def startup():
    db.init_db()

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    stats = db.get_dashboard_stats()
    logs = db.get_recent_logs(limit=5)
    return templates.TemplateResponse(request, "dashboard.html", {"stats": stats, "logs": logs})

@app.get("/players", response_class=HTMLResponse)
async def players_list(request: Request, search: str = "", limit: int = 100, offset: int = 0):
    players = db.get_players_summary(search, limit, offset)
    total = db.get_players_total_from_reports()
    
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "_players_table.html", {"players": players, "search": search})
        
    return templates.TemplateResponse(request, "players.html", {"players": players, "total": total, "search": search})

@app.post("/players/toggle-tg/{nomor}", response_class=HTMLResponse)
async def toggle_tg(request: Request, nomor: str):
    new_val = db.toggle_tg_joined(nomor)
    p = db.get_player_summary_by_phone(nomor)
    return templates.TemplateResponse(request, "_player_row.html", {"p": p})

@app.get("/check", response_class=HTMLResponse)
async def check_page(request: Request):
    return templates.TemplateResponse(request, "check.html", {"is_running": False})

@app.post("/check", response_class=HTMLResponse)
async def start_check(request: Request, background_tasks: BackgroundTasks):
    unscanned = db.get_players_unused_numbers()
    if unscanned:
        # We would run this in background
        pass
    
    return templates.TemplateResponse(request, "_check_widget.html", {"is_running": True, "progress": 0, "total": len(unscanned)})

@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request, limit: int = 100, offset: int = 0):
    logs = db.get_send_logs(limit, offset)
    total = db.get_send_logs_count()
    return templates.TemplateResponse(request, "logs.html", {"logs": logs, "total": total})

@app.get("/templates", response_class=HTMLResponse)
async def templates_page(request: Request):
    return templates.TemplateResponse(request, "templates.html", {})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
