# Decart AI Live-Stream Video Effects Controller

A standalone Python + HTML/JS live-stream controller for real-time video-to-video AI transformation during live streams (OBS Studio, TikTok Live, etc.).

Powered by **FastAPI**, **Uvicorn**, **WebSockets**, **TikTokLive**, and the **Decart Realtime SDK** (`@decartai/sdk` running `models.realtime('lucy-latest')`).

---

## 🌟 Key Features

1. **Secure Decart Realtime Token Minting (`/api/token`)**:
   - Master `DECART_API_KEY` stays safely on the backend in `config.json` (relative to `sys.executable`).
   - Securely generates short-lived client tokens for `@decartai/sdk` in the browser over WebRTC.
2. **OBS-Ready Stream Overlay (`/overlay`)**:
   - Fullscreen camera capture via `getUserMedia` matched to the Decart realtime model parameters (720p @ 30fps).
   - Instant WebRTC connection to Decart when AI is enabled.
   - Listens to local WebSocket for immediate prompt switching (`realtimeClient.setPrompt(newPrompt)`).
   - **AI Cost-Saving Switch**: When toggled OFF, WebRTC disconnects immediately and switches to clean transparent mode (OBS background camera pass-through) or raw webcam view.
   - Built-in broadcast HUD with 15-second countdown timer bar and trigger source badges (press `H` to hide/show).
3. **Streamer Control Dashboard (`/dashboard`)**:
   - Master AI Stream ON/OFF toggle with prominent visual glow and cost-saving indicators.
   - Instant Prompt Pusher with `Ctrl+Enter` shortcut.
   - One-click effect presets ('Cyberpunk Room', 'Explosion VFX', 'Anime Style', 'Retro 80s Synthwave', 'Zombie Apocalypse', 'Underwater Atlantis').
   - Live 15s Countdown progress bar showing remaining effect duration before resetting to default prompt.
4. **TikTok Live Stream Integration**:
   - Connects to any TikTok streamer's live room without requiring login credentials.
   - Listens to chat comments starting with `!ai <prompt>` and triggers the effect for 15 seconds before resetting.
   - Listens to gifts (e.g. 🌹 Rose, ❤️ Heart, 🔥 Fire, 🧢 Cap, 🍩 Doughnut) mapped in `config.json` and triggers visual effects for 15 seconds.
   - **Interactive Test Simulator**: Test simulated `!ai` comments and gifts with a single click without needing to go live on TikTok!
   - Real-time chat & gift activity log.
5. **Standalone PyInstaller Ready**:
   - Loads `config.json` relative to `sys.executable`.
   - Auto-opens `/dashboard` in your default browser on launch.

---

## 🚀 Quick Start

### 1. Installation
Install the dependencies:
```bash
pip install -r requirements.txt
```

### 2. Configure Decart API Key
Copy `config.example.json` to `config.json` (the app will also auto-generate it from `config.example.json` on first run):
```bash
cp config.example.json config.json
```
Open `config.json` (or configure via the Settings modal in `/dashboard`) and add your Decart API key:
```json
{
  "DECART_API_KEY": "YOUR_ACTUAL_DECART_API_KEY",
  "default_tiktok_username": "your_tiktok_handle",
  "default_prompt": "Cinematic lighting, high detail, masterpiece",
  "command_duration_seconds": 15,
  "default_off_mode": "webcam"
}
```

### 3. Launch the Controller
```bash
python main.py
```
This automatically starts Uvicorn at `http://127.0.0.1:8000` and opens `/dashboard` in your default web browser.

---

## 🎥 OBS Studio Setup

To add the AI video effects overlay into OBS Studio:

1. In OBS, click **+** under **Sources** and select **Browser**.
2. Name it `Decart AI Overlay`.
3. Set the **URL** to:
   ```
   http://localhost:8000/overlay
   ```
4. Set **Width** to `1280` and **Height** to `720` (or `1920` x `1080`).
5. (Optional) URL parameters:
   - `?mode=transparent`: Transparent background when AI is OFF (lets your OBS camera source underneath show through).
   - `?mode=webcam`: Displays raw webcam directly in the browser source when AI is OFF.
   - `?hud=0`: Hides the on-screen prompt badge and timer for a clean video-only feed.
   - `?mirror=0`: Disables camera horizontal mirroring.

---

## 🕹️ Streamer Dashboard (`/dashboard`)

The dashboard gives you full live control:
- **Master AI Stream Switch**: Toggle between AI WebRTC and Standby. Turn it OFF between stream segments to save Decart API credits.
- **Push AI Prompt**: Type any custom visual style and click **Push to Stream** or press `Ctrl+Enter`.
- **One-Click Presets**: Immediately switch between configured styles like Cyberpunk, Anime, Explosion VFX, and Synthwave.
- **TikTok Live Connect**: Enter your TikTok handle and click **Connect**. All incoming `!ai` commands and gifts will automatically transform your stream.
- **Test Event Simulator**: Use the buttons to simulate viewer commands and gifts during rehearsals.

---

## 📦 Packaging with PyInstaller

To build a standalone executable:

```bash
python build_exe.py
```

The resulting folder will be located in `dist/DecartLiveController/`:
- `DecartLiveController.exe`: Run this to start the server and open the dashboard.
- `config.json`: Kept beside the `.exe` so you can easily update API keys, default username, and presets without rebuilding!

---

## 📁 Project Structure

```
globa/
├── config.json              # Config loaded relative to sys.executable
├── main.py                  # FastAPI + Uvicorn + WebSockets + TikTokLive
├── requirements.txt         # Dependencies including pyinstaller
├── build_exe.py             # One-click PyInstaller build script
├── templates/
│   ├── overlay.html         # WebRTC video capture & Decart remote player
│   └── dashboard.html       # Streamer live control deck & TikTok manager
└── README.md                # Documentation
```
