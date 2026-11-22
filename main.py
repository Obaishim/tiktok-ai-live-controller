import os
import sys
import json
import asyncio
import logging
import webbrowser
import threading
import time
from typing import Dict, Any, Optional, Set
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn

# TikTokLive imports
try:
    from TikTokLive import TikTokLiveClient
    from TikTokLive.events import (
        ConnectEvent,
        CommentEvent,
        GiftEvent,
        DisconnectEvent,
        LiveEndEvent
    )
    from TikTokLive.client.errors import TikTokLiveError, UserOfflineError
    TIKTOK_AVAILABLE = True
except ImportError:
    TIKTOK_AVAILABLE = False
    print("Warning: TikTokLive library not installed or failed to import.")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("DecartController")

# ==============================================================================
# Helper functions for PyInstaller paths and config loading
# ==============================================================================

def get_base_dir() -> str:
    """
    Get the directory where config.json and user-editable files live.
    When packaged with PyInstaller, this is the directory containing the executable.
    When running as a script, this is the directory containing main.py.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def get_templates_dir() -> str:
    """
    Get the directory containing HTML templates.
    Handles PyInstaller temp extraction directory (_MEIPASS) and source directory.
    """
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
    "DECART_API_KEY": "YOUR_DECART_API_KEY_HERE",
    "default_tiktok_username": "tiktok",
    "default_prompt": "Cinematic lighting, high detail, masterpiece",
    "command_duration_seconds": 15,
    "default_off_mode": "webcam",  # 'webcam' or 'transparent'
    "server_host": "127.0.0.1",
    "server_port": 8000,
    "preset_prompts": [
        {
            "label": "Cyberpunk Room",
            "prompt": "Cyberpunk style room with neon lights, glowing holographic UI, high tech futuristic aesthetic, cinematic lighting"
        },
        {
            "label": "Explosion VFX",
            "prompt": "Action movie explosion VFX, cinematic fireball blast, intense dynamic lighting, smoke, fiery sparks"
        },
        {
            "label": "Anime Style",
            "prompt": "Vibrant Japanese anime style, clean line art, studio Ghibli aesthetic, colorful animation, cel shaded"
        },
        {
            "label": "Retro 80s Synthwave",
            "prompt": "1980s retro synthwave, neon grid horizon, VHS glitch effect, magenta and cyan glow, outrun aesthetic"
        },
        {
            "label": "Zombie Apocalypse",
            "prompt": "Dark apocalyptic horror thriller, gritty ruined wasteland background, dramatic cinematic shadows, eerie atmosphere"
        },
        {
            "label": "Underwater Atlantis",
            "prompt": "Mythical underwater kingdom of Atlantis, swimming bioluminescent marine life, shimmering sunbeams underwater"
        }
    ],
    "gift_actions": {
        "Rose": "Raining neon red roses, magical floral petals swirl, romantic cinematic lighting",
        "Heart": "Floating glowing neon hearts, dreamy pastel aesthetic, sparkling light effects",
        "Fire": "Cinematic raging fire flames vortex, glowing embers around, intense warm lighting",
        "Cap": "Golden crown with sparkling jewels, royal golden aura, dramatic stage lighting",
        "Doughnut": "Floating giant cartoon doughnuts, rainbow sprinkle rain, playful colorful wonderland"
    }
}

def load_config() -> Dict[str, Any]:
    """Load config.json relative to sys.executable (for PyInstaller) or create default."""
    config_file = get_config_path()
    if not os.path.exists(config_file):
        example_path = os.path.join(get_base_dir(), "config.example.json")
        if os.path.exists(example_path):
            try:
                with open(example_path, "r", encoding="utf-8") as f:
                    example_cfg = json.load(f)
                save_config(example_cfg)
                return example_cfg
            except Exception as e:
                logger.warning(f"Failed to copy from config.example.json: {e}")
        logger.info(f"Creating default config file at: {config_file}")
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            # Merge with defaults for missing keys
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg:
                    cfg[k] = v
            return cfg
    except Exception as e:
        logger.error(f"Failed to read {config_file}: {e}. Using defaults.")
        return DEFAULT_CONFIG.copy()

def save_config(cfg: Dict[str, Any]) -> bool:
    """Save configuration to config.json relative to sys.executable."""
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
        config = load_config()
        self.ai_enabled: bool = True
        self.default_prompt: str = config.get("default_prompt", "Cinematic lighting, high detail, masterpiece")
        self.current_prompt: str = self.default_prompt
        self.current_source: str = "default"  # 'default', 'dashboard', 'preset', 'tiktok_comment', 'tiktok_gift'
        self.active_user: Optional[str] = None
        self.active_detail: Optional[str] = None
        
        # Timer management for 15s auto-reset
        self.timer_seconds_left: int = 0
        self.timer_duration: int = 15
        self.reset_task: Optional[asyncio.Task] = None

        # TikTok Live state
        self.tiktok_client: Optional[Any] = None
        self.tiktok_task: Optional[asyncio.Task] = None
        self.tiktok_status: str = "disconnected"  # 'disconnected', 'connecting', 'connected', 'error'
        self.tiktok_username: str = config.get("default_tiktok_username", "tiktok")
        self.tiktok_error: Optional[str] = None
        self.tiktok_room_id: Optional[int] = None

        # WebSocket connections: set of WebSocket objects
        self.clients: Set[WebSocket] = set()
        self.client_roles: Dict[WebSocket, str] = {}  # ws -> 'overlay' | 'dashboard'

    def get_status_payload(self) -> Dict[str, Any]:
        overlay_count = sum(1 for role in self.client_roles.values() if role == "overlay")
        dashboard_count = sum(1 for role in self.client_roles.values() if role == "dashboard")
        return {
            "type": "status_sync",
            "ai_enabled": self.ai_enabled,
            "current_prompt": self.current_prompt,
            "default_prompt": self.default_prompt,
            "source": self.current_source,
            "user": self.active_user,
            "detail": self.active_detail,
            "timer_seconds_left": self.timer_seconds_left,
            "timer_duration": self.timer_duration,
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
        # Send initial status snapshot to the connecting client
        await websocket.send_json(self.get_status_payload())
        # Notify other clients of updated client counts
        await self.broadcast(self.get_status_payload(), target_role="dashboard")

    def _remove_client(self, websocket: WebSocket):
        if websocket in self.clients:
            self.clients.remove(websocket)
        if websocket in self.client_roles:
            del self.client_roles[websocket]
        logger.info(f"WebSocket client disconnected. Total: {len(self.clients)}")

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

    async def set_prompt(
        self,
        prompt: str,
        source: str = "dashboard",
        user: Optional[str] = None,
        detail: Optional[str] = None,
        duration: Optional[int] = None
    ):
        """
        Push new prompt to all clients (especially overlay).
        If duration is provided (e.g. 15s for TikTok commands/gifts),
        starts an auto-reset countdown back to default prompt.
        """
        # Cancel any pending reset countdown
        if self.reset_task and not self.reset_task.done():
            self.reset_task.cancel()
            self.reset_task = None

        # If prompt starts with command prefix '!ai ', strip it
        clean_prompt = prompt.strip()
        if clean_prompt.lower().startswith("!ai "):
            clean_prompt = clean_prompt[4:].strip()

        self.current_prompt = clean_prompt
        self.current_source = source
        self.active_user = user
        self.active_detail = detail

        logger.info(f"Setting AI prompt: '{self.current_prompt}' (source: {source}, user: {user}, duration: {duration})")

        # Broadcast prompt change immediately
        await self.broadcast({
            "type": "set_prompt",
            "prompt": self.current_prompt,
            "source": self.current_source,
            "user": self.active_user,
            "detail": self.active_detail,
            "duration": duration
        })

        if duration and duration > 0:
            self.timer_duration = duration
            self.timer_seconds_left = duration
            self.reset_task = asyncio.create_task(self._run_countdown_and_reset(duration))
        else:
            self.timer_seconds_left = 0
            self.timer_duration = 0
            await self.broadcast({
                "type": "timer_tick",
                "seconds_left": 0,
                "duration": 0,
                "prompt": self.current_prompt
            })

    async def _run_countdown_and_reset(self, duration: int):
        """Asynchronous countdown loop that resets prompt after duration."""
        try:
            for remaining in range(duration, 0, -1):
                self.timer_seconds_left = remaining
                await self.broadcast({
                    "type": "timer_tick",
                    "seconds_left": remaining,
                    "duration": duration,
                    "prompt": self.current_prompt,
                    "source": self.current_source,
                    "user": self.active_user
                })
                await asyncio.sleep(1)

            # Timer expired! Reset back to default prompt
            logger.info("15-second TikTok effect expired. Resetting back to default prompt.")
            self.timer_seconds_left = 0
            self.timer_duration = 0
            self.current_prompt = self.default_prompt
            self.current_source = "default"
            self.active_user = None
            self.active_detail = None

            await self.broadcast({
                "type": "set_prompt",
                "prompt": self.current_prompt,
                "source": "default_reset",
                "user": None,
                "detail": "Reset after timer expired",
                "duration": None
            })
            await self.broadcast({
                "type": "timer_tick",
                "seconds_left": 0,
                "duration": 0,
                "prompt": self.current_prompt
            })
        except asyncio.CancelledError:
            # Overridden by another prompt command
            pass

    async def toggle_ai(self, enabled: bool):
        """Toggle AI WebRTC stream on or off to save API costs."""
        self.ai_enabled = enabled
        logger.info(f"AI Stream toggled to: {'ON' if enabled else 'OFF'}")
        await self.broadcast({
            "type": "toggle_ai",
            "enabled": self.ai_enabled
        })

    # --------------------------------------------------------------------------
    # TikTok Live Connection Manager
    # --------------------------------------------------------------------------
    async def start_tiktok(self, username: str):
        """Connect to TikTok Live stream for the specified username."""
        if not TIKTOK_AVAILABLE:
            self.tiktok_status = "error"
            self.tiktok_error = "TikTokLive library not available."
            await self.broadcast(self.get_status_payload())
            return

        # If already running for this user, return
        if self.tiktok_client and self.tiktok_status == "connected" and self.tiktok_username == username:
            return

        # Disconnect any existing session
        await self.stop_tiktok()

        self.tiktok_username = username.strip().lstrip("@")
        self.tiktok_status = "connecting"
        self.tiktok_error = None
        self.tiktok_room_id = None
        logger.info(f"Initiating TikTok Live connection for @{self.tiktok_username}...")
        await self.broadcast(self.get_status_payload())

        # Create client instance
        client = TikTokLiveClient(unique_id=f"@{self.tiktok_username}")
        self.tiktok_client = client

        # Event Handlers
        @client.on(ConnectEvent)
        async def on_connect(event: ConnectEvent):
            self.tiktok_status = "connected"
            self.tiktok_room_id = getattr(client, "room_id", None)
            logger.info(f"Successfully connected to TikTok Live: @{self.tiktok_username} (Room ID: {self.tiktok_room_id})")
            await self.broadcast({
                "type": "tiktok_status",
                "status": "connected",
                "username": self.tiktok_username,
                "room_id": self.tiktok_room_id
            })

        @client.on(DisconnectEvent)
        async def on_disconnect(event: DisconnectEvent):
            self.tiktok_status = "disconnected"
            logger.info(f"Disconnected from TikTok Live: @{self.tiktok_username}")
            await self.broadcast({
                "type": "tiktok_status",
                "status": "disconnected",
                "username": self.tiktok_username
            })

        @client.on(LiveEndEvent)
        async def on_live_end(event: LiveEndEvent):
            self.tiktok_status = "disconnected"
            self.tiktok_error = "Live stream ended."
            logger.info(f"TikTok Live stream ended for @{self.tiktok_username}")
            await self.broadcast({
                "type": "tiktok_status",
                "status": "disconnected",
                "username": self.tiktok_username,
                "error": "Stream ended"
            })

        @client.on(CommentEvent)
        async def on_comment(event: CommentEvent):
            comment_text = event.comment.strip()
            user_unique_id = getattr(event.user, "unique_id", "Viewer")
            user_nickname = getattr(event.user, "nickname", user_unique_id)

            # Broadcast incoming chat to dashboard live log
            await self.broadcast({
                "type": "tiktok_chat",
                "user": user_unique_id,
                "nickname": user_nickname,
                "comment": comment_text,
                "is_command": comment_text.lower().startswith("!ai ")
            }, target_role="dashboard")

            # Check for AI command trigger: !ai <prompt>
            if comment_text.lower().startswith("!ai "):
                prompt_arg = comment_text[4:].strip()
                if prompt_arg:
                    config = load_config()
                    duration = int(config.get("command_duration_seconds", 15))
                    logger.info(f"TikTok Chat Command '!ai' triggered by @{user_unique_id}: '{prompt_arg}'")
                    await self.set_prompt(
                        prompt=prompt_arg,
                        source="tiktok_comment",
                        user=f"@{user_unique_id}",
                        detail=f"Chat: {comment_text}",
                        duration=duration
                    )

        @client.on(GiftEvent)
        async def on_gift(event: GiftEvent):
            user_unique_id = getattr(event.user, "unique_id", "Viewer")
            user_nickname = getattr(event.user, "nickname", user_unique_id)
            
            # Extract gift name
            gift_name = "Gift"
            if hasattr(event, "gift") and event.gift:
                gift_name = getattr(event.gift, "name", None) or getattr(event.gift, "describe", "Gift")
            repeat_count = getattr(event, "repeat_count", 1) or 1
            diamond_count = getattr(event.gift, "diamond_count", 0) if hasattr(event, "gift") and event.gift else 0

            config = load_config()
            gift_actions = config.get("gift_actions", {})
            mapped_prompt = gift_actions.get(gift_name)

            # Broadcast gift to dashboard live log
            await self.broadcast({
                "type": "tiktok_gift",
                "user": user_unique_id,
                "nickname": user_nickname,
                "gift_name": gift_name,
                "repeat_count": repeat_count,
                "diamond_count": diamond_count,
                "triggered_prompt": mapped_prompt
            }, target_role="dashboard")

            # Trigger AI prompt effect if gift is mapped in config.json
            if mapped_prompt:
                duration = int(config.get("command_duration_seconds", 15))
                logger.info(f"TikTok Gift '{gift_name}' received from @{user_unique_id}! Triggering: '{mapped_prompt}'")
                await self.set_prompt(
                    prompt=mapped_prompt,
                    source="tiktok_gift",
                    user=f"@{user_unique_id}",
                    detail=f"Gift: {repeat_count}x {gift_name}",
                    duration=duration
                )

        # Run client asynchronously in background task
        async def run_client():
            try:
                await client.start()
            except UserOfflineError:
                self.tiktok_status = "error"
                self.tiktok_error = f"User @{self.tiktok_username} is currently offline."
                logger.warning(self.tiktok_error)
            except TikTokLiveError as e:
                self.tiktok_status = "error"
                self.tiktok_error = f"TikTokLive error: {str(e)}"
                logger.error(self.tiktok_error)
            except Exception as e:
                self.tiktok_status = "error"
                self.tiktok_error = f"Connection error: {str(e)}"
                logger.error(self.tiktok_error)
            finally:
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
                logger.warning(f"Error while disconnecting TikTok client: {e}")
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

# Instantiate global stream manager
manager = LiveStreamManager()

# ==============================================================================
# FastAPI Application & Lifecycle
# ==============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure config exists and initialize default prompt
    cfg = load_config()
    manager.default_prompt = cfg.get("default_prompt", "Cinematic lighting, high detail, masterpiece")
    manager.current_prompt = manager.default_prompt
    logger.info("FastAPI Live-Stream Video Effects Controller initialized.")
    yield
    # Shutdown: cleanly close TikTok client and tasks
    logger.info("Shutting down controller...")
    await manager.stop_tiktok()
    if manager.reset_task and not manager.reset_task.done():
        manager.reset_task.cancel()

app = FastAPI(
    title="Decart Live-Stream AI Video Effects Controller",
    description="Realtime AI Video-to-Video controller with WebSockets and TikTok Live integration",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount media_clips directory for viral video clips
app.mount("/media", StaticFiles(directory=get_media_dir()), name="media")

# ==============================================================================
# API Endpoints
# ==============================================================================

@app.get("/")
async def root():
    """Redirect root to dashboard."""
    return Response(status_code=302, headers={"Location": "/dashboard"})

@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)

@app.get("/api/clips")
async def list_media_clips():
    """List all available pre-rendered video clips in media_clips/."""
    media_dir = get_media_dir()
    clips = []
    if os.path.exists(media_dir):
        for f in os.listdir(media_dir):
            if f.lower().endswith((".mp4", ".webm", ".mov")):
                clips.append({
                    "filename": f,
                    "name": os.path.splitext(f)[0].replace("_", " ").title(),
                    "url": f"/media/{f}"
                })
    return {"clips": clips}

@app.post("/api/play_clip")
async def api_play_clip(request: Request):
    """Trigger a pre-rendered video clip to play seamlessly on the overlay."""
    data = await request.json()
    clip_name = data.get("clip")
    if not clip_name:
        return JSONResponse(status_code=400, content={"error": "Clip name required"})
    await manager.broadcast({
        "type": "play_clip",
        "clip": clip_name,
        "url": f"/media/{clip_name}",
        "user": data.get("user")
    })
    return {"success": True, "clip": clip_name}

@app.get("/overlay", response_class=HTMLResponse)
async def serve_overlay():
    """Serve the overlay.html file for OBS browser source or browser window."""
    templates_dir = get_templates_dir()
    overlay_path = os.path.join(templates_dir, "overlay.html")
    if not os.path.exists(overlay_path):
        return HTMLResponse(
            f"<h3>Error: overlay.html not found in {templates_dir}</h3>",
            status_code=404
        )
    with open(overlay_path, "r", encoding="utf-8") as f:
        content = f.read()
    return HTMLResponse(content=content)

@app.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard():
    """Serve the dashboard.html file for stream management console."""
    templates_dir = get_templates_dir()
    dashboard_path = os.path.join(templates_dir, "dashboard.html")
    if not os.path.exists(dashboard_path):
        return HTMLResponse(
            f"<h3>Error: dashboard.html not found in {templates_dir}</h3>",
            status_code=404
        )
    with open(dashboard_path, "r", encoding="utf-8") as f:
        content = f.read()
    return HTMLResponse(content=content)

@app.get("/api/token")
@app.post("/api/token")
async def get_decart_token():
    """
    Securely mints/serves a client token for the Decart Realtime JS SDK
    (@decartai/sdk using models.realtime('lucy-latest')).
    Reads the permanent DECART_API_KEY from config.json so it never leaks to the browser.
    """
    config = load_config()
    api_key = config.get("DECART_API_KEY", "").strip()

    if not api_key or api_key == "YOUR_DECART_API_KEY_HERE":
        return JSONResponse(
            status_code=400,
            content={
                "error": "DECART_API_KEY is not configured in config.json. Please set your Decart API key in the dashboard or config.json.",
                "apiKey": None,
                "configured": False
            }
        )

    # Call Decart Token Minting Endpoint
    url = "https://api.decart.ai/v1/client/tokens"
    headers = {
        "x-api-key": api_key,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "expiresIn": 3600,
        "allowedModels": ["lucy-latest", "lucy-2.6", "lucy-2.1"],
        "constraints": {
            "realtime": {
                "maxSessionDuration": 3600
            }
        }
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as http_client:
            resp = await http_client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                client_token = data.get("apiKey") or data.get("token")
                return {
                    "apiKey": client_token,
                    "expiresAt": data.get("expiresAt"),
                    "configured": True,
                    "model": "lucy-latest"
                }
            else:
                logger.error(f"Decart Token API failed: {resp.status_code} - {resp.text}")
                return JSONResponse(
                    status_code=resp.status_code,
                    content={
                        "error": f"Decart API error ({resp.status_code}): {resp.text}",
                        "apiKey": None,
                        "configured": True
                    }
                )
    except Exception as e:
        logger.error(f"Exception during Decart Token minting: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "error": f"Failed to contact Decart API: {str(e)}",
                "apiKey": None,
                "configured": True
            }
        )

@app.get("/api/config")
async def get_config():
    """Retrieve current configuration (with DECART_API_KEY partially masked for safety)."""
    cfg = load_config()
    safe_cfg = cfg.copy()
    key = safe_cfg.get("DECART_API_KEY", "")
    if key and key != "YOUR_DECART_API_KEY_HERE" and len(key) > 8:
        safe_cfg["DECART_API_KEY_MASKED"] = f"{key[:4]}...{key[-4:]}"
        safe_cfg["is_key_configured"] = True
    else:
        safe_cfg["DECART_API_KEY_MASKED"] = "Not set"
        safe_cfg["is_key_configured"] = False
    return safe_cfg

@app.post("/api/config")
async def update_config(request: Request):
    """Update configuration values and persist to config.json."""
    try:
        body = await request.json()
        cfg = load_config()

        # Update allowed fields
        if "DECART_API_KEY" in body and body["DECART_API_KEY"]:
            cfg["DECART_API_KEY"] = body["DECART_API_KEY"].strip()
        if "default_tiktok_username" in body:
            cfg["default_tiktok_username"] = body["default_tiktok_username"].strip()
            manager.tiktok_username = cfg["default_tiktok_username"]
        if "default_prompt" in body:
            cfg["default_prompt"] = body["default_prompt"].strip()
            manager.default_prompt = cfg["default_prompt"]
        if "command_duration_seconds" in body:
            cfg["command_duration_seconds"] = int(body["command_duration_seconds"])
        if "default_off_mode" in body:
            cfg["default_off_mode"] = body["default_off_mode"]
        if "preset_prompts" in body and isinstance(body["preset_prompts"], list):
            cfg["preset_prompts"] = body["preset_prompts"]
        if "gift_actions" in body and isinstance(body["gift_actions"], dict):
            cfg["gift_actions"] = body["gift_actions"]

        saved = save_config(cfg)
        await manager.broadcast({
            "type": "config_updated",
            "config": cfg
        })
        return {"success": saved, "config": cfg}
    except Exception as e:
        logger.error(f"Error updating config: {e}")
        return JSONResponse(status_code=400, content={"error": str(e)})

@app.get("/api/status")
async def get_status():
    """Get current controller status."""
    return manager.get_status_payload()

@app.post("/api/prompt")
async def api_set_prompt(request: Request):
    """Set AI prompt via REST API."""
    data = await request.json()
    prompt = data.get("prompt", "").strip()
    source = data.get("source", "api")
    user = data.get("user")
    duration = data.get("duration")
    if not prompt:
        return JSONResponse(status_code=400, content={"error": "Prompt cannot be empty"})
    await manager.set_prompt(prompt, source=source, user=user, duration=duration)
    return {"success": True, "prompt": prompt}

@app.post("/api/ai_toggle")
async def api_toggle_ai(request: Request):
    """Toggle AI stream on/off via REST API."""
    data = await request.json()
    enabled = bool(data.get("enabled", True))
    await manager.toggle_ai(enabled)
    return {"success": True, "ai_enabled": enabled}

@app.post("/api/simulate")
async def api_simulate_event(request: Request):
    """
    Simulate a TikTok chat command (!ai <prompt>) or Gift event for testing
    without requiring a live stream.
    """
    data = await request.json()
    sim_type = data.get("type", "comment")  # 'comment' or 'gift'
    user = data.get("user", "Viewer123")
    config = load_config()
    duration = int(config.get("command_duration_seconds", 15))

    if sim_type == "comment":
        prompt = data.get("prompt", "Cyberpunk Neon City").strip()
        raw_comment = f"!ai {prompt}"
        # Broadcast chat event to dashboard feed
        await manager.broadcast({
            "type": "tiktok_chat",
            "user": user,
            "nickname": user,
            "comment": raw_comment,
            "is_command": True
        }, target_role="dashboard")
        # Trigger effect
        await manager.set_prompt(
            prompt=prompt,
            source="tiktok_comment",
            user=f"@{user}",
            detail=f"Simulated Chat: {raw_comment}",
            duration=duration
        )
        return {"success": True, "simulated": "comment", "prompt": prompt}

    elif sim_type == "gift":
        gift_name = data.get("gift_name", "Rose")
        gift_actions = config.get("gift_actions", {})
        mapped_prompt = gift_actions.get(gift_name, "Cinematic flower explosion VFX")
        # Broadcast gift event to dashboard feed
        await manager.broadcast({
            "type": "tiktok_gift",
            "user": user,
            "nickname": user,
            "gift_name": gift_name,
            "repeat_count": 1,
            "diamond_count": 1,
            "triggered_prompt": mapped_prompt
        }, target_role="dashboard")
        # Trigger effect
        await manager.set_prompt(
            prompt=mapped_prompt,
            source="tiktok_gift",
            user=f"@{user}",
            detail=f"Simulated Gift: 1x {gift_name}",
            duration=duration
        )
        return {"success": True, "simulated": "gift", "gift": gift_name, "prompt": mapped_prompt}

    return JSONResponse(status_code=400, content={"error": "Invalid simulation type"})

# ==============================================================================
# WebSocket Endpoint
# ==============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Central real-time WebSocket connection handling prompts, AI toggles,
    TikTok events, and countdown timers.
    Query param ?client=overlay or ?client=dashboard identifies role.
    """
    client_role = websocket.query_params.get("client", "general")
    await manager.connect_client(websocket, role=client_role)
    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("type")

            if action == "set_prompt":
                prompt = data.get("prompt", "").strip()
                source = data.get("source", "dashboard")
                user = data.get("user")
                duration = data.get("duration")
                if prompt:
                    await manager.set_prompt(prompt, source=source, user=user, duration=duration)

            elif action == "toggle_ai":
                enabled = bool(data.get("enabled", True))
                await manager.toggle_ai(enabled)

            elif action == "reset_default":
                await manager.set_prompt(manager.default_prompt, source="default", duration=None)

            elif action == "tiktok_connect":
                username = data.get("username", manager.tiktok_username)
                await manager.start_tiktok(username)

            elif action == "tiktok_disconnect":
                await manager.stop_tiktok()

            elif action == "simulate_event":
                sim_type = data.get("sim_type", "comment")
                sim_user = data.get("user", "Viewer123")
                cfg = load_config()
                duration = int(cfg.get("command_duration_seconds", 15))
                if sim_type == "comment":
                    prompt = data.get("prompt", "Cyberpunk Neon City")
                    await manager.broadcast({
                        "type": "tiktok_chat",
                        "user": sim_user,
                        "nickname": sim_user,
                        "comment": f"!ai {prompt}",
                        "is_command": True
                    }, target_role="dashboard")
                    await manager.set_prompt(
                        prompt=prompt,
                        source="tiktok_comment",
                        user=f"@{sim_user}",
                        detail=f"Chat: !ai {prompt}",
                        duration=duration
                    )
                elif sim_type == "gift":
                    gift_name = data.get("gift_name", "Rose")
                    gift_actions = cfg.get("gift_actions", {})
                    mapped_prompt = gift_actions.get(gift_name, "Cinematic vibrant rose petals")
                    await manager.broadcast({
                        "type": "tiktok_gift",
                        "user": sim_user,
                        "nickname": sim_user,
                        "gift_name": gift_name,
                        "repeat_count": 1,
                        "diamond_count": 1,
                        "triggered_prompt": mapped_prompt
                    }, target_role="dashboard")
                    await manager.set_prompt(
                        prompt=mapped_prompt,
                        source="tiktok_gift",
                        user=f"@{sim_user}",
                        detail=f"Gift: 1x {gift_name}",
                        duration=duration
                    )

            elif action == "play_clip":
                clip_name = data.get("clip")
                if clip_name:
                    await manager.broadcast({
                        "type": "play_clip",
                        "clip": clip_name,
                        "url": f"/media/{clip_name}",
                        "user": data.get("user")
                    })

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

def open_dashboard_in_browser(host: str, port: int, delay: float = 1.2):
    """Open /dashboard in user's default browser after uvicorn initializes."""
    def _run():
        time.sleep(delay)
        url = f"http://{host}:{port}/dashboard"
        logger.info(f"Opening browser at: {url}")
        try:
            webbrowser.open(url)
        except Exception as e:
            logger.warning(f"Could not open browser automatically: {e}")
    threading.Thread(target=_run, daemon=True).start()

if __name__ == "__main__":
    config = load_config()
    server_host = config.get("server_host", "127.0.0.1")
    server_port = int(config.get("server_port", 8000))

    # Auto-open dashboard in browser
    open_dashboard_in_browser(server_host, server_port)

    # Launch uvicorn
    logger.info(f"Starting server on http://{server_host}:{server_port}")
    uvicorn.run(app, host=server_host, port=server_port, log_level="info")
