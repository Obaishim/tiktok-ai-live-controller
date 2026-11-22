"""
Automated Verification Test Suite for SSwurve Viral Stream Controller.
Tests configuration loading, clip listing, feed connect/disconnect, and WebSockets.
"""
import asyncio
import os
import sys

from fastapi.testclient import TestClient
from main import app, load_config, save_config, manager, get_base_dir, get_config_path, get_media_dir

def test_config():
    print("[1/4] Testing config path resolution and loading...")
    base_dir = get_base_dir()
    cfg_path = get_config_path()
    assert os.path.exists(cfg_path), f"Config file not found at {cfg_path}"
    cfg = load_config()
    assert "default_tiktok_username" in cfg
    assert "gift_mappings" in cfg
    print("  ✓ Config verified at:", cfg_path)

def test_endpoints():
    print("[2/4] Testing REST API endpoints...")
    client = TestClient(app)

    # 1. Overlay endpoint
    resp = client.get("/overlay")
    assert resp.status_code == 200, f"/overlay returned {resp.status_code}"
    assert "SSwurve Viral Stream Overlay" in resp.text
    print("  ✓ GET /overlay: 200 OK")

    # 2. Dashboard endpoint
    resp = client.get("/dashboard")
    assert resp.status_code == 200, f"/dashboard returned {resp.status_code}"
    assert "SSwurve Viral AI Stream Controller" in resp.text
    print("  ✓ GET /dashboard: 200 OK")

    # 3. /api/clips endpoint
    resp = client.get("/api/clips")
    assert resp.status_code == 200
    clips_data = resp.json().get("clips", [])
    print(f"  ✓ GET /api/clips: 200 OK (Clean list: {len(clips_data)} custom videos)")

    # 4. /api/status endpoint
    resp = client.get("/api/status")
    assert resp.status_code == 200
    status_data = resp.json()
    assert "feed_enabled" in status_data
    assert "active_clip" in status_data
    assert "tiktok" in status_data
    print("  ✓ GET /api/status: 200 OK")

def test_feed_toggle():
    print("[3/4] Testing Connect / Disconnect live feed...")
    client = TestClient(app)

    # Disconnect feed
    resp = client.post("/api/feed_toggle", json={"enabled": False})
    assert resp.status_code == 200
    assert manager.feed_enabled is False
    print("  ✓ POST /api/feed_toggle (Disconnect / Disable): feed disabled")

    # Connect feed
    resp = client.post("/api/feed_toggle", json={"enabled": True})
    assert resp.status_code == 200
    assert manager.feed_enabled is True
    print("  ✓ POST /api/feed_toggle (Connect / Enable): feed enabled")

async def test_websocket():
    print("[4/4] Testing WebSocket communication...")
    client = TestClient(app)

    with client.websocket_connect("/ws?client=overlay") as ws_overlay:
        initial_msg = ws_overlay.receive_json()
        assert initial_msg["type"] == "status_sync"
        print("  ✓ WebSocket received initial status_sync")

        with client.websocket_connect("/ws?client=dashboard") as ws_dash:
            _ = ws_dash.receive_json()

            # Disconnect feed via WebSocket
            ws_dash.send_json({"type": "feed_toggle", "enabled": False})
            msg_feed = ws_overlay.receive_json()
            assert msg_feed["type"] == "feed_status"
            assert msg_feed["enabled"] is False
            print("  ✓ WebSocket feed_status (disable) broadcasted to overlay")

            # Connect feed via WebSocket
            ws_dash.send_json({"type": "feed_toggle", "enabled": True})
            msg_feed_on = ws_overlay.receive_json()
            assert msg_feed_on["type"] == "feed_status"
            assert msg_feed_on["enabled"] is True
            print("  ✓ WebSocket feed_status (enable) broadcasted to overlay")

def run_all():
    print("=" * 60)
    print("RUNNING SSWURVE CONTROLLER VERIFICATION TESTS")
    print("=" * 60)
    test_config()
    test_endpoints()
    test_feed_toggle()
    asyncio.run(test_websocket())
    print("=" * 60)
    print("ALL TESTS PASSED SUCCESSFULLY! (4/4)")
    print("=" * 60)

if __name__ == "__main__":
    run_all()
