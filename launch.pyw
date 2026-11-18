"""Clip Agent launcher (what the desktop icon runs). No console window:
updates from GitHub, starts the local server in the background if it isn't running, opens the browser."""
import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = int(os.environ.get("CLIP_AGENT_PORT", "8765"))
URL = f"http://127.0.0.1:{PORT}/"
LOG = HERE / "clip-agent.log"


def running() -> bool:
    try:
        with urllib.request.urlopen(URL + "api/state", timeout=1.5) as r:
            return json.load(r).get("app") == "clip-agent"
    except Exception:
        return False


def main():
    args = sys.argv[1:]
    if "--restart" in args:  # wait for the old server to exit
        for _ in range(40):
            if not running():
                break
            time.sleep(0.25)
    if not running():
        if "--no-update" not in args:
            try:
                sys.path.insert(0, str(HERE))
                import updater
                updater.update(log=lambda m: None)
            except Exception:
                pass
        flags = 0
        if sys.platform.startswith("win"):
            flags = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED | NEW_PROCESS_GROUP | NO_WINDOW
        log = open(LOG, "a", encoding="utf-8")
        log.write(f"\n--- start {time.ctime()} ---\n")
        log.flush()
        subprocess.Popen([sys.executable, str(HERE / "server.py")], cwd=str(HERE), stdout=log, stderr=log,
                         stdin=subprocess.DEVNULL, creationflags=flags, close_fds=True)
        for _ in range(240):  # up to 60s for the first start
            if running():
                break
            time.sleep(0.25)
    if "--no-browser" not in args:
        webbrowser.open(URL)


if __name__ == "__main__":
    main()
