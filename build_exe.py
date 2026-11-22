"""
Build script to package the Decart AI Live-Stream Video Effects Controller
into a standalone executable using PyInstaller.
"""
import os
import sys
import shutil
import subprocess

def build_executable():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    templates_dir = os.path.join(base_dir, "templates")
    config_file = os.path.join(base_dir, "config.json")

    print(f"Building standalone executable in: {base_dir}")
    
    # Separator for PyInstaller --add-data (';' on Windows, ':' on Unix)
    sep = os.pathsep

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--name", "DecartLiveController",
        "--onedir",
        "--add-data", f"templates{sep}templates",
        # Common uvicorn & async hidden imports
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols",
        "--hidden-import", "uvicorn.protocols.http",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "uvicorn.lifespan",
        "--hidden-import", "uvicorn.lifespan.on",
        "--hidden-import", "TikTokLive",
        "--hidden-import", "TikTokLive.events",
        "--hidden-import", "TikTokLive.proto",
        "main.py"
    ]

    print("Executing:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=base_dir)

    if result.returncode == 0:
        dist_dir = os.path.join(base_dir, "dist", "DecartLiveController")
        # Ensure config.json is copied beside the executable
        target_config = os.path.join(dist_dir, "config.json")
        if os.path.exists(config_file):
            shutil.copy2(config_file, target_config)
            print(f"Copied config.json to: {target_config}")

        print("\n" + "=" * 60)
        print("BUILD SUCCESSFUL!")
        print(f"Executable folder: {dist_dir}")
        print("To run, open DecartLiveController.exe inside the dist folder.")
        print("=" * 60)
    else:
        print("\nBUILD FAILED! Return code:", result.returncode)

if __name__ == "__main__":
    build_executable()
