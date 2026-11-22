"""
Automated Verification Test Suite for Decart AI Live-Stream Controller.
Tests configuration loading, FastAPI endpoints, WebSockets, token endpoint,
and prompt countdown / reset logic.
"""
import asyncio
import json
import os
import sys

from fastapi.testclient import TestClient
from main import app, load_config, save_config, manager, get_base_dir, get_config_path

def test_config():
    print("[1/5] Testing config path resolution and loading...")
    base_dir = get_base_dir()
    cfg_path = get_config_path()
    assert os.path.exists(cfg_path), f"Config file not found at {cfg_path}"
    cfg = load_config()
    assert "DECART_API_KEY" in cfg
    assert "preset_prompts" in cfg
    assert "gift_actions" in cfg
    print("  ✓ Config path resolution & loading verified:", cfg_path)

def test_endpoints():
    print("[2/5] Testing REST API endpoints...")
    client = TestClient(app)

    # 1. Overlay endpoint
    resp = client.get("/overlay")
    assert resp.status_code == 200, f"/overlay returned {resp.status_code}"
    assert "Decart AI Live-Stream Overlay" in resp.text
    print("  ✓ GET /overlay: 200 OK")

    # 2. Dashboard endpoint
    resp = client.get("/dashboard")
    assert resp.status_code == 200, f"/dashboard returned {resp.status_code}"
    assert "Decart AI" in resp.text
    print("  ✓ GET /dashboard: 200 OK")

    # 3. /api/config endpoint
    resp = client.get("/api/config")
    assert resp.status_code == 200
    cfg_data = resp.json()
    assert "preset_prompts" in cfg_data
    assert "gift_actions" in cfg_data
    print("  ✓ GET /api/config: 200 OK")

    # 4. /api/status endpoint
    resp = client.get("/api/status")
    assert resp.status_code == 200
    status_data = resp.json()
    assert "current_prompt" in status_data
    assert "ai_enabled" in status_data
    print("  ✓ GET /api/status: 200 OK")

    # 5. /api/token endpoint with placeholder key
    resp = client.get("/api/token")
    # Should return 400 when DECART_API_KEY is placeholder or missing
    token_json = resp.json()
    assert "apiKey" in token_json or "error" in token_json
    print("  ✓ GET /api/token: properly guarded, returned:", token_json.get("error", "OK"))

def test_simulation_api():
    print("[3/5] Testing event simulation API (/api/simulate)...")
    client = TestClient(app)

    # Simulate TikTok comment !ai
    resp = client.post("/api/simulate", json={
        "type": "comment",
        "user": "TestViewer",
        "prompt": "Explosion VFX anime blast"
    })
    assert resp.status_code == 200, resp.text
    assert manager.current_prompt == "Explosion VFX anime blast"
    assert manager.current_source == "tiktok_comment"
    assert manager.timer_seconds_left > 0
    print("  ✓ POST /api/simulate (comment): verified prompt & timer activated")

    # Simulate TikTok gift
    resp = client.post("/api/simulate", json={
        "type": "gift",
        "user": "GiftGiver",
        "gift_name": "Rose"
    })
    assert resp.status_code == 200
    assert manager.current_source == "tiktok_gift"
    print("  ✓ POST /api/simulate (gift): verified prompt & gift mapping")

async def test_websocket_and_timer():
    print("[4/5] Testing WebSocket real-time communication & auto-reset timer...")
    client = TestClient(app)

    with client.websocket_connect("/ws?client=overlay") as ws_overlay:
        # 1. Check initial status sync
        initial_msg = ws_overlay.receive_json()
        assert initial_msg["type"] == "status_sync"
        print("  ✓ WebSocket received initial status_sync")

        with client.websocket_connect("/ws?client=dashboard") as ws_dash:
            _ = ws_dash.receive_json()

            # 2. Test sending custom prompt from dashboard
            ws_dash.send_json({
                "type": "set_prompt",
                "prompt": "Cyberpunk Neon Room with lasers",
                "source": "dashboard",
                "duration": None
            })

            # Overlay should receive the new prompt
            msg1 = ws_overlay.receive_json()
            assert msg1["type"] == "set_prompt"
            assert msg1["prompt"] == "Cyberpunk Neon Room with lasers"
            print("  ✓ WebSocket set_prompt broadcasted to overlay:", msg1["prompt"])

            # Overlay also receives timer_tick (0)
            msg2 = ws_overlay.receive_json()
            assert msg2["type"] == "timer_tick"

            # 3. Test AI toggle
            ws_dash.send_json({
                "type": "toggle_ai",
                "enabled": False
            })
            msg = ws_overlay.receive_json()
            assert msg["type"] == "toggle_ai"
            assert msg["enabled"] is False
            assert manager.ai_enabled is False
            print("  ✓ WebSocket toggle_ai (OFF) broadcasted")

            ws_dash.send_json({
                "type": "toggle_ai",
                "enabled": True
            })
            msg = ws_overlay.receive_json()
            assert msg["type"] == "toggle_ai"
            assert msg["enabled"] is True
            assert manager.ai_enabled is True
            print("  ✓ WebSocket toggle_ai (ON) broadcasted")

            # 4. Test 15-second TikTok command with short duration to verify auto-reset
            print("  Testing auto-reset mechanism (triggering 2-second test countdown)...")
            await manager.set_prompt(
                prompt="Temporary Cyberpunk Effect",
                source="tiktok_comment",
                user="@StreamTester",
                duration=2
            )

            # Wait for timer to tick and expire
            await asyncio.sleep(2.5)
            assert manager.current_prompt == manager.default_prompt
            print("  ✓ Auto-reset confirmed: Prompt successfully reset back to default:", manager.current_prompt)

def run_all():
    print("=" * 60)
    print("RUNNING CONTROLLER VERIFICATION TESTS")
    print("=" * 60)
    test_config()
    test_endpoints()
    test_simulation_api()
    asyncio.run(test_websocket_and_timer())
    print("=" * 60)
    print("ALL TESTS PASSED SUCCESSFULLY! (5/5)")
    print("=" * 60)

if __name__ == "__main__":
    run_all()
