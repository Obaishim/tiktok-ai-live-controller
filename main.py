"""
TikTok Live Viral AI Stream Controller - SSwurve Edition
==========================================================
Streamline viral clip playback, TikTok Live gift/chat triggers,
and camera overlays for TikTok LIVE Studio and OBS Studio.
"""

import asyncio
import json
import logging
import os
import shutil
import sys
import threading
import time
import webbrowser
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Set

import uvicorn
from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# TikTokLive import
try:
    from TikTokLive import TikTokLiveClient
    from TikTokLive.events import ConnectEvent, DisconnectEvent, CommentEvent, GiftEvent
    TIKTOK_AVAILABLE = True
except ImportError:
    TIKTOK_AVAILABLE = False

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("LiveController")

# ==============================================================================
# Path & Configuration Management
# ==============================================================================

def get_base_dir() -> str:
    """Get the base execution directory (supports PyInstaller frozen binary)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def get_templates_dir() -> str:
    """Find templates directory in PyInstaller _MEIPASS or local directory."""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass and os.path.exists(os.path.join(meipass, "templates")):
            return os.path.join(meipass, "templates")
        exe_templates = os.path.join(os.path.dirname(sys.executable), "templates")
        if os.path.exists(exe_templates):
            return exe_templates
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

def get_config_path() -> str:
    return os.path.join(get_base_dir(), "config.json")

def get_media_dir() -> str:
    media_dir = os.path.join(get_base_dir(), "media_clips")
    os.makedirs(media_dir, exist_ok=True)
    return media_dir

DEFAULT_CONFIG: Dict[str, Any] = {
    "default_tiktok_username": "his_lordshipp",
    "active_theme": "obsidian_neon",
    "overlay_audio": True,
    "overlay_volume": 1.0,
    "show_hud_on_clip": True,
    "server_host": "127.0.0.1",
    "server_port": 8000,
    "gift_mappings": {}
}

def load_config() -> Dict[str, Any]:
    """Load config.json or initialize from config.example.json / default."""
    config_file = get_config_path()
    if not os.path.exists(config_file):
        example_path = os.path.join(get_base_dir(), "config.example.json")
        if os.path.exists(example_path):
            try:
                with open(example_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                save_config(cfg)
                return cfg
            except Exception as e:
                logger.warning(f"Failed to copy from config.example.json: {e}")
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg:
                    cfg[k] = v
            return cfg
    except Exception as e:
        logger.error(f"Failed to read {config_file}: {e}. Using defaults.")
        return DEFAULT_CONFIG.copy()

def save_config(cfg: Dict[str, Any]) -> bool:
    """Save configuration to config.json."""
    config_file = get_config_path()
    try:
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Failed to save {config_file}: {e}")
        return False

# ==============================================================================
# Live Stream State & WebSocket Manager
# ==============================================================================

class LiveStreamManager:
    def __init__(self):
        cfg = load_config()
        self.active_clip: Optional[Dict[str, Any]] = None
        self.gift_mappings: Dict[str, str] = cfg.get("gift_mappings", {})
        self.active_theme: str = cfg.get("active_theme", "obsidian_neon")
        self.feed_enabled: bool = True

        # TikTok Live state
        self.tiktok_client: Optional[Any] = None
        self.tiktok_task: Optional[asyncio.Task] = None
        self.tiktok_status: str = "disconnected"
        self.tiktok_username: str = cfg.get("default_tiktok_username", "his_lordshipp")
        self.tiktok_error: Optional[str] = None
        self.tiktok_room_id: Optional[int] = None

        # WebSocket connections
        self.clients: Set[WebSocket] = set()
        self.client_roles: Dict[WebSocket, str] = {}

    def get_status_payload(self) -> Dict[str, Any]:
        overlay_count = sum(1 for role in self.client_roles.values() if role == "overlay")
        dashboard_count = sum(1 for role in self.client_roles.values() if role == "dashboard")
        return {
            "type": "status_sync",
            "feed_enabled": self.feed_enabled,
            "active_clip": self.active_clip,
            "active_theme": self.active_theme,
            "gift_mappings": self.gift_mappings,
            "tiktok": {
                "status": self.tiktok_status,
                "username": self.tiktok_username,
                "error": self.tiktok_error,
                "room_id": self.tiktok_room_id
            },
            "connected_clients": {
                "total": len(self.clients),
                "overlay": overlay_count,
                "dashboard": dashboard_count
            }
        }

    async def connect_client(self, websocket: WebSocket, role: str = "general"):
        await websocket.accept()
        self.clients.add(websocket)
        self.client_roles[websocket] = role
        logger.info(f"WebSocket client connected ({role}). Total: {len(self.clients)}")
        await websocket.send_json(self.get_status_payload())
        await self.broadcast(self.get_status_payload(), target_role="dashboard")

    def _remove_client(self, websocket: WebSocket):
        if websocket in self.clients:
            self.clients.remove(websocket)
        if websocket in self.client_roles:
            del self.client_roles[websocket]

    async def disconnect_client(self, websocket: WebSocket):
        self._remove_client(websocket)
        await self.broadcast(self.get_status_payload(), target_role="dashboard")

    async def broadcast(self, message: Dict[str, Any], target_role: Optional[str] = None):
        """Broadcast message to connected clients, optionally filtered by role."""
        if not self.clients:
            return
        dead_clients = set()
        for client in self.clients:
            if target_role and self.client_roles.get(client) != target_role:
                continue
            try:
                await client.send_json(message)
            except Exception as e:
                logger.warning(f"Error sending message to client: {e}")
                dead_clients.add(client)
        for dead in dead_clients:
            self._remove_client(dead)

    async def trigger_clip(self, clip_name: str, user: str = "Streamer", source: str = "dashboard", detail: str = ""):
        """Trigger a viral video clip across all overlays and dashboard monitors."""
        media_dir = get_media_dir()
        clip_path = os.path.join(media_dir, clip_name)
        if not os.path.exists(clip_path):
            logger.warning(f"Clip not found: {clip_path}")
            return False

        name_display = os.path.splitext(clip_name)[0].replace("_", " ").title()
        self.active_clip = {
            "clip": clip_name,
            "name": name_display,
            "url": f"/media/{clip_name}",
            "user": user,
            "source": source,
            "detail": detail,
            "timestamp": time.time()
        }

        payload = {
            "type": "play_clip",
            "clip": clip_name,
            "name": name_display,
            "url": f"/media/{clip_name}",
            "user": user,
            "source": source,
            "detail": detail
        }
        logger.info(f"Triggering clip: {clip_name} (by {user} via {source})")
        await self.broadcast(payload)
        return True

    async def stop_clip(self):
        """Stop active clip and seamlessly return overlay to raw webcam."""
        self.active_clip = None
        await self.broadcast({"type": "stop_clip"})
        logger.info("Stopped active clip - return to webcam.")

    async def set_feed_enabled(self, enabled: bool):
        """Enable or disable the video feed / live review."""
        self.feed_enabled = enabled
        logger.info(f"Video feed state changed: {'ENABLED' if enabled else 'DISABLED'}")
        await self.broadcast({"type": "feed_status", "enabled": enabled})

    # --------------------------------------------------------------------------
    # TikTok Live Client
    # --------------------------------------------------------------------------
    async def start_tiktok(self, username: str):
        """Connect to TikTok Live room."""
        if not TIKTOK_AVAILABLE:
            self.tiktok_status = "error"
            self.tiktok_error = "TikTokLive package not installed"
            await self.broadcast(self.get_status_payload())
            return

        username = username.strip().replace("@", "")
        if not username:
            return

        await self.stop_tiktok()
        self.tiktok_username = username
        self.tiktok_status = "connecting"
        self.tiktok_error = None
        await self.broadcast({
            "type": "tiktok_status",
            "status": "connecting",
            "username": username
        })

        async def run_client():
            loop = asyncio.get_running_loop()
            try:
                self.tiktok_client = TikTokLiveClient(unique_id=username)

                @self.tiktok_client.on(ConnectEvent)
                async def on_connect(event: ConnectEvent):
                    self.tiktok_status = "connected"
                    self.tiktok_room_id = getattr(event, "room_id", None)
                    logger.info(f"Connected to TikTok Live: @{username} (Room ID: {self.tiktok_room_id})")
                    await self.broadcast({
                        "type": "tiktok_status",
                        "status": "connected",
                        "username": username,
                        "room_id": self.tiktok_room_id
                    })

                @self.tiktok_client.on(DisconnectEvent)
                async def on_disconnect(event: DisconnectEvent):
                    self.tiktok_status = "disconnected"
                    logger.info(f"Disconnected from TikTok Live: @{username}")
                    await self.broadcast({
                        "type": "tiktok_status",
                        "status": "disconnected",
                        "username": username
                    })

                @self.tiktok_client.on(CommentEvent)
                async def on_comment(event: CommentEvent):
                    comment_text = event.comment.strip()
                    user_nick = getattr(event.user, "nickname", event.user.unique_id)
                    user_handle = event.user.unique_id

                    # Check for clip command: !clip <name> or !<name>
                    matched_clip = None
                    if comment_text.lower().startswith("!clip "):
                        query = comment_text[6:].strip().lower()
                        # Search in media clips
                        for f in os.listdir(get_media_dir()):
                            if query in f.lower():
                                matched_clip = f
                                break
                    elif comment_text.startswith("!"):
                        query = comment_text[1:].strip().lower()
                        for f in os.listdir(get_media_dir()):
                            if query in os.path.splitext(f)[0].lower():
                                matched_clip = f
                                break

                    is_command = matched_clip is not None
                    await self.broadcast({
                        "type": "tiktok_chat",
                        "user": user_handle,
                        "nickname": user_nick,
                        "comment": comment_text,
                        "is_command": is_command,
                        "triggered_clip": matched_clip
                    }, target_role="dashboard")

                    if matched_clip:
                        await self.trigger_clip(
                            clip_name=matched_clip,
                            user=f"@{user_handle}",
                            source="tiktok_comment",
                            detail=f"Chat: {comment_text}"
                        )

                @self.tiktok_client.on(GiftEvent)
                async def on_gift(event: GiftEvent):
                    gift_name = event.gift.name
                    user_nick = getattr(event.user, "nickname", event.user.unique_id)
                    user_handle = event.user.unique_id
                    repeat_count = getattr(event, "repeat_count", 1)
                    diamond_count = getattr(event.gift, "diamond_count", 0)

                    # Look up gift mapping
                    cfg = load_config()
                    mappings = cfg.get("gift_mappings", {})
                    matched_clip = mappings.get(gift_name)

                    await self.broadcast({
                        "type": "tiktok_gift",
                        "user": user_handle,
                        "nickname": user_nick,
                        "gift_name": gift_name,
                        "repeat_count": repeat_count,
                        "diamond_count": diamond_count,
                        "triggered_clip": matched_clip
                    }, target_role="dashboard")

                    if matched_clip:
                        await self.trigger_clip(
                            clip_name=matched_clip,
                            user=f"@{user_handle}",
                            source="tiktok_gift",
                            detail=f"Gift: {repeat_count}x {gift_name}"
                        )

                await self.tiktok_client.start()
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"TikTok Live connection error: {e}")
                self.tiktok_error = str(e)
                if self.tiktok_status == "connecting":
                    self.tiktok_status = "error"
                await self.broadcast(self.get_status_payload())

        self.tiktok_task = asyncio.create_task(run_client())

    async def stop_tiktok(self):
        """Disconnect active TikTok Live client."""
        if self.tiktok_client:
            try:
                await self.tiktok_client.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting TikTok client: {e}")
            self.tiktok_client = None

        if self.tiktok_task and not self.tiktok_task.done():
            self.tiktok_task.cancel()
            self.tiktok_task = None

        self.tiktok_status = "disconnected"
        self.tiktok_error = None
        self.tiktok_room_id = None
        await self.broadcast({
            "type": "tiktok_status",
            "status": "disconnected",
            "username": self.tiktok_username
        })

# Global manager instance
manager = LiveStreamManager()

# ==============================================================================
# FastAPI Application & Lifecycle
# ==============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load_config()
    manager.gift_mappings = cfg.get("gift_mappings", {})
    manager.active_theme = cfg.get("active_theme", "obsidian_neon")
    logger.info("SSwurve TikTok Live Viral Stream Controller initialized.")
    yield
    logger.info("Shutting down controller...")
    await manager.stop_tiktok()

app = FastAPI(
    title="SSwurve Viral AI Live-Stream Controller",
    description="Photoreal viral video-clip soundboard, camera overlay, and TikTok Live integration",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount media directory for video playback
app.mount("/media", StaticFiles(directory=get_media_dir()), name="media")

# ==============================================================================
# HTTP Routes
# ==============================================================================

@app.get("/")
async def root():
    return Response(status_code=302, headers={"Location": "/dashboard"})

@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)

@app.get("/overlay", response_class=HTMLResponse)
async def serve_overlay():
    """OBS Browser Source or Fullscreen Overlay."""
    templates_dir = get_templates_dir()
    path = os.path.join(templates_dir, "overlay.html")
    if not os.path.exists(path):
        return HTMLResponse("<h3>overlay.html not found</h3>", status_code=404)
    with open(path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard():
    """Streamer Control Deck."""
    templates_dir = get_templates_dir()
    path = os.path.join(templates_dir, "dashboard.html")
    if not os.path.exists(path):
        return HTMLResponse("<h3>dashboard.html not found</h3>", status_code=404)
    with open(path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/api/clips")
async def list_media_clips():
    """List all available viral video clips in media_clips/."""
    media_dir = get_media_dir()
    clips = []
    if os.path.exists(media_dir):
        files = sorted(os.listdir(media_dir))
        for f in files:
            if f.lower().endswith((".mp4", ".webm", ".mov")):
                full_path = os.path.join(media_dir, f)
                stat = os.stat(full_path)
                clips.append({
                    "filename": f,
                    "name": os.path.splitext(f)[0].replace("_", " ").title(),
                    "url": f"/media/{f}",
                    "size_mb": round(stat.st_size / (1024 * 1024), 2),
                    "modified": stat.st_mtime
                })
    return {"clips": clips}

@app.post("/api/play_clip")
async def api_play_clip(request: Request):
    """Trigger a viral video clip to play on the overlay."""
    data = await request.json()
    clip_name = data.get("clip")
    user = data.get("user", "Streamer")
    source = data.get("source", "dashboard")
    detail = data.get("detail", "")
    if not clip_name:
        return JSONResponse(status_code=400, content={"error": "Clip name required"})
    
    success = await manager.trigger_clip(clip_name, user=user, source=source, detail=detail)
    if not success:
        return JSONResponse(status_code=404, content={"error": f"Clip '{clip_name}' not found"})
    return {"success": True, "clip": clip_name}

@app.post("/api/stop_clip")
async def api_stop_clip():
    """Stop active clip and return to webcam."""
    await manager.stop_clip()
    return {"success": True}

@app.post("/api/feed_toggle")
async def api_feed_toggle(request: Request):
    """Enable or disable the video feed / live review."""
    data = await request.json()
    enabled = bool(data.get("enabled", True))
    await manager.set_feed_enabled(enabled)
    return {"success": True, "feed_enabled": enabled}

@app.post("/api/upload_clip")
async def api_upload_clip(file: UploadFile = File(...)):
    """Upload a new .mp4/.webm clip directly into media_clips/."""
    filename = os.path.basename(file.filename or "video.mp4")
    if not filename.lower().endswith((".mp4", ".webm", ".mov")):
        raise HTTPException(status_code=400, detail="Only .mp4, .webm, or .mov files allowed")
    
    save_path = os.path.join(get_media_dir(), filename)
    with open(save_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    logger.info(f"Uploaded new clip: {filename}")
    await manager.broadcast({"type": "clips_updated"})
    return {"success": True, "filename": filename, "url": f"/media/{filename}"}

@app.delete("/api/clips/{filename}")
async def api_delete_clip(filename: str):
    """Delete a clip from media_clips/."""
    clean_name = os.path.basename(filename)
    path = os.path.join(get_media_dir(), clean_name)
    if os.path.exists(path):
        os.remove(path)
        await manager.broadcast({"type": "clips_updated"})
        return {"success": True}
    return JSONResponse(status_code=404, content={"error": "File not found"})

@app.get("/api/config")
async def get_config():
    return load_config()

@app.post("/api/config")
async def update_config(request: Request):
    """Update and persist configuration."""
    data = await request.json()
    cfg = load_config()
    for key in ["default_tiktok_username", "active_theme", "overlay_audio", "overlay_volume", "show_hud_on_clip", "gift_mappings"]:
        if key in data:
            cfg[key] = data[key]
    saved = save_config(cfg)
    manager.gift_mappings = cfg.get("gift_mappings", {})
    manager.active_theme = cfg.get("active_theme", "obsidian_neon")
    await manager.broadcast({"type": "config_updated", "config": cfg})
    return {"success": saved, "config": cfg}

@app.get("/api/status")
async def get_status():
    return manager.get_status_payload()

@app.post("/api/simulate")
async def api_simulate_event(request: Request):
    """Simulate a TikTok chat comment or Gift event for testing without a live stream."""
    data = await request.json()
    sim_type = data.get("type", "comment")
    user = data.get("user", "TikTokViewer")
    cfg = load_config()
    mappings = cfg.get("gift_mappings", {})

    if sim_type == "comment":
        comment = data.get("comment", "!clip dragon")
        matched_clip = None
        query = comment.lower().replace("!clip", "").replace("!", "").strip()
        for f in os.listdir(get_media_dir()):
            if query and query in f.lower():
                matched_clip = f
                break
        if not matched_clip and os.listdir(get_media_dir()):
            matched_clip = os.listdir(get_media_dir())[0]

        await manager.broadcast({
            "type": "tiktok_chat",
            "user": user,
            "nickname": user,
            "comment": comment,
            "is_command": True,
            "triggered_clip": matched_clip
        }, target_role="dashboard")

        if matched_clip:
            await manager.trigger_clip(
                clip_name=matched_clip,
                user=f"@{user}",
                source="tiktok_comment",
                detail=f"Simulated: {comment}"
            )
        return {"success": True, "simulated": "comment", "clip": matched_clip}

    elif sim_type == "gift":
        gift_name = data.get("gift_name", "Rose")
        matched_clip = mappings.get(gift_name)
        if not matched_clip and os.listdir(get_media_dir()):
            matched_clip = os.listdir(get_media_dir())[0]

        await manager.broadcast({
            "type": "tiktok_gift",
            "user": user,
            "nickname": user,
            "gift_name": gift_name,
            "repeat_count": 1,
            "diamond_count": 1,
            "triggered_clip": matched_clip
        }, target_role="dashboard")

        if matched_clip:
            await manager.trigger_clip(
                clip_name=matched_clip,
                user=f"@{user}",
                source="tiktok_gift",
                detail=f"Simulated Gift: 1x {gift_name}"
            )
        return {"success": True, "simulated": "gift", "gift": gift_name, "clip": matched_clip}

    return JSONResponse(status_code=400, content={"error": "Invalid simulation type"})

# ==============================================================================
# WebSocket Endpoint
# ==============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    client_role = websocket.query_params.get("client", "general")
    await manager.connect_client(websocket, role=client_role)
    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("type")

            if action == "play_clip":
                clip_name = data.get("clip")
                user = data.get("user", "Streamer")
                source = data.get("source", "dashboard")
                detail = data.get("detail", "")
                if clip_name:
                    await manager.trigger_clip(clip_name, user=user, source=source, detail=detail)

            elif action == "stop_clip":
                await manager.stop_clip()

            elif action == "feed_toggle":
                enabled = bool(data.get("enabled", True))
                await manager.set_feed_enabled(enabled)

            elif action == "tiktok_connect":
                username = data.get("username", manager.tiktok_username)
                await manager.start_tiktok(username)

            elif action == "tiktok_disconnect":
                await manager.stop_tiktok()

            elif action == "simulate_event":
                sim_type = data.get("sim_type", "comment")
                sim_user = data.get("user", "Viewer123")
                cfg = load_config()
                mappings = cfg.get("gift_mappings", {})
                if sim_type == "comment":
                    raw_comment = data.get("comment", "!clip dragon")
                    matched = None
                    query = raw_comment.lower().replace("!clip", "").replace("!", "").strip()
                    for f in os.listdir(get_media_dir()):
                        if query and query in f.lower():
                            matched = f
                            break
                    if not matched and os.listdir(get_media_dir()):
                        matched = os.listdir(get_media_dir())[0]

                    await manager.broadcast({
                        "type": "tiktok_chat",
                        "user": sim_user,
                        "nickname": sim_user,
                        "comment": raw_comment,
                        "is_command": True,
                        "triggered_clip": matched
                    }, target_role="dashboard")
                    if matched:
                        await manager.trigger_clip(matched, user=f"@{sim_user}", source="tiktok_comment", detail=f"Simulated: {raw_comment}")

                elif sim_type == "gift":
                    gift_name = data.get("gift_name", "Rose")
                    matched = mappings.get(gift_name)
                    if not matched and os.listdir(get_media_dir()):
                        matched = os.listdir(get_media_dir())[0]

                    await manager.broadcast({
                        "type": "tiktok_gift",
                        "user": sim_user,
                        "nickname": sim_user,
                        "gift_name": gift_name,
                        "repeat_count": 1,
                        "diamond_count": 1,
                        "triggered_clip": matched
                    }, target_role="dashboard")
                    if matched:
                        await manager.trigger_clip(matched, user=f"@{sim_user}", source="tiktok_gift", detail=f"Simulated Gift: 1x {gift_name}")

            elif action == "set_theme":
                theme = data.get("theme", "obsidian_neon")
                manager.active_theme = theme
                cfg = load_config()
                cfg["active_theme"] = theme
                save_config(cfg)
                await manager.broadcast({"type": "theme_changed", "theme": theme})

            elif action == "request_status":
                await websocket.send_json(manager.get_status_payload())

    except WebSocketDisconnect:
        await manager.disconnect_client(websocket)
    except Exception as e:
        logger.warning(f"WebSocket error: {e}")
        await manager.disconnect_client(websocket)

# ==============================================================================
# Browser Launcher & Entrypoint
# ==============================================================================

def open_dashboard_in_browser(host: str, port: int, delay_seconds: float = 1.2):
    """Automatically open dashboard URL in default browser after server boots."""
    def _open():
        time.sleep(delay_seconds)
        url = f"http://{host}:{port}/dashboard"
        logger.info(f"Opening browser at: {url}")
        try:
            webbrowser.open(url)
        except Exception as e:
            logger.warning(f"Could not open browser automatically: {e}")
    threading.Thread(target=_open, daemon=True).start()

def run_server():
    cfg = load_config()
    host = cfg.get("server_host", "127.0.0.1")
    port = int(cfg.get("server_port", 8000))

    open_dashboard_in_browser(host, port)

    logger.info(f"Starting SSwurve Viral Stream Controller on http://{host}:{port}")
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=False
    )

if __name__ == "__main__":
    run_server()
