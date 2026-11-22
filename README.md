# SSwurve Viral AI Stream Controller

A standalone Python + HTML/JS livestream soundboard and camera controller for TikTok LIVE Studio and OBS Studio, modeled after creator **@sswurve**'s viral stream format.

Streamers drag and drop their own AI video clips (`.mp4`, `.webm`) into the dashboard and put them on screen live on cue (via hotkeys, dashboard triggers, or TikTok chat comments and gifts).

---

## 🌟 Key Features

1. **Custom Video Soundboard (Zero Hardcoded/Mock Effects)**:
   - Full drag-and-drop upload zone directly inside the dashboard.
   - Drop your custom AI video clips (.mp4) and they instantly appear on your soundboard with video hover previews and file size indicators.
   - Delete unwanted videos with 1-click (`🗑️`).
2. **Instant On-Screen Triggers**:
   - One-click **▶ Put on Screen** button for every video.
   - Keyboard hotkeys **`[1]` through `[9]`** trigger videos instantly without needing mouse clicks.
   - **`[ESC]`** hotkey immediately cuts back to clean webcam.
3. **Live Stream Review & Monitor (Connect / Disconnect Controls)**:
   - Built-in real-time video monitor inside the dashboard.
   - **Connect Live Review** button activates the stream preview.
   - **Disconnect / Disable Feed** button immediately disables the live feed and blanks the broadcast.
4. **4 Modern Themes**:
   - 🟣 **Obsidian Neon** (Default)
   - 🩵 **Cyberpunk Cyan**
   - 💚 **Matrix Emerald**
   - 🖤 **Stealth Carbon**
5. **TikTok Live Integration**:
   - Connects to any TikTok streamer's live room without requiring login credentials.
   - Dedicated **Connect** and **Disconnect** buttons with live status badges.
   - Viewers can trigger uploaded videos via chat commands (e.g. `!clip <video_name>` or `!<video_name>`) or gifts.
6. **OBS & TikTok LIVE Studio Ready**:
   - Browser source overlay at `http://localhost:8000/overlay` (1280x720).
   - High-resolution webcam feed with seamless cross-fade video transitions and audio playback.

---

## 🚀 Quick Start

### 1. Installation
```bash
pip install -r requirements.txt
```

### 2. Launch Controller
```bash
python main.py
```
This automatically boots the server and opens the dashboard at `http://127.0.0.1:8000/dashboard`.

### 3. Add Your Videos
- Drag and drop your `.mp4` video clips into the **Drag & Drop** area at the top of the dashboard.
- Press **`[1]`–`[9]`** or click **Put on Screen** to trigger them live!

---

## 🎥 OBS Studio Setup

1. In OBS Studio or TikTok LIVE Studio, add a new **Browser Source**.
2. Set URL to:
   ```
   http://localhost:8000/overlay
   ```
3. Set **Width**: `1280`, **Height**: `720`.
4. (Optional) URL parameters:
   - `?hud=0`: Completely hides on-screen notifications for a 100% clean video feed.
   - `?mirror=0`: Disables camera horizontal flip.

---

## 📁 Project Structure

```
tiktok-ai-live-controller/
├── main.py                  # FastAPI + WebSocket + TikTokLive server
├── config.json              # Local configuration (created automatically)
├── config.example.json      # Starter configuration template
├── requirements.txt         # Dependencies
├── build_exe.py             # PyInstaller standalone build script
├── media_clips/             # Folder holding your uploaded video files
├── templates/
│   ├── dashboard.html       # Streamer Control Deck & soundboard
│   └── overlay.html         # OBS camera capture & video player
├── test_app.py              # Automated verification test suite
└── README.md                # Documentation
```
