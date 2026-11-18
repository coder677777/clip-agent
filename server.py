"""Clip Agent local web server. Started by launch.pyw (desktop icon); open http://127.0.0.1:8765"""
from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import clip_agent as ca

HERE = Path(__file__).resolve().parent
PORT = int(os.environ.get("CLIP_AGENT_PORT", "8765"))
UPLOADS = ca.OUT_ROOT / "_uploads"


def app_version() -> str:
    try:
        return json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))["version"]
    except Exception:
        return "dev"


app = FastAPI(title="Clip Agent")
app.mount("/fonts", StaticFiles(directory=str(HERE / "fonts")), name="fonts")
app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

# ---------------------------------------------------------------- jobs
JOBS: dict[str, dict] = {}
JOB_Q: "queue.Queue[tuple[str, callable]]" = queue.Queue()
ANSI = re.compile(r"\x1b\[[0-9;]*m|\[[0-9;]*m(?=\w)")


def _clean(msg) -> str:
    return ANSI.sub("", str(msg)).replace("ERROR: ", "").strip()


def new_job(kind: str, fn, **meta) -> str:
    jid = uuid.uuid4().hex[:10]
    JOBS[jid] = {"id": jid, "kind": kind, "status": "waiting", "logs": [], "stage": "waiting",
                 "progress": None, "result": None, "error": None, "started": time.time(), **meta}
    JOB_Q.put((jid, fn))
    return jid


def _stage_from(job: dict, msg: str):
    m = msg.lower()
    if job["kind"] == "find":
        if "video info" in m:
            job["stage"] = "info"
        elif "caption" in m or "whisper" in m or "transcrib" in m or "audio" in m:
            job["stage"] = "captions"
        elif m.startswith("ai is reading"):
            job["stage"] = "ai"
            g = re.search(r"\((\d+)/(\d+)\)", msg)
            if g:
                job["progress"] = [int(g.group(1)), int(g.group(2))]
        elif m.startswith("found"):
            job["stage"] = "done"
    elif job["kind"] == "render":
        g = re.match(r"\[(\d+)\] (Getting|Rendering|Done|FAILED)", msg)
        if g:
            n, what = int(g.group(1)), g.group(2)
            job["clip_states"][str(n)] = {"Getting": "downloading", "Rendering": "rendering",
                                          "Done": "done", "FAILED": "failed"}[what]


def worker():
    while True:
        jid, fn = JOB_Q.get()
        job = JOBS[jid]
        job["status"] = "running"

        def hook(msg, job=job):
            msg = _clean(msg)
            job["logs"].append(msg)
            job["logs"] = job["logs"][-200:]
            _stage_from(job, msg)

        ca.set_log_hook(hook)
        try:
            job["result"] = fn(job)
            job["status"] = "done"
        except Exception as e:  # surface every error to the UI
            job["status"] = "error"
            job["error"] = _clean(e)
            job["logs"].append("Error: " + job["error"])
        finally:
            ca.set_log_hook(None)


threading.Thread(target=worker, daemon=True).start()

# ---------------------------------------------------------------- helpers


def project_dir(pid: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_.\-]+", pid or ""):
        raise HTTPException(400, "bad project id")
    d = ca.OUT_ROOT / pid
    if not d.is_dir():
        raise HTTPException(404, "project not found")
    return d


def thumb_url(pid: str, video: dict) -> str | None:
    if video.get("is_url") and video.get("id"):
        return f"https://i.ytimg.com/vi/{video['id']}/hqdefault.jpg"
    if (ca.OUT_ROOT / pid / "thumb.jpg").exists():
        return f"/media/{pid}/thumb.jpg"
    return None


def make_local_thumb(workdir: Path, meta: dict):
    try:
        t = max(1.0, (meta.get("duration") or 20) * 0.1)
        ca.run_ffmpeg(["-ss", f"{t:.1f}", "-i", meta["source"], "-frames:v", "1", "-vf", "scale=480:-2",
                       str(workdir / "thumb.jpg")])
    except Exception:
        pass


def rendered_files(workdir: Path) -> dict:
    out = {}
    cdir = workdir / "clips"
    if cdir.is_dir():
        for f in sorted(cdir.glob("*.mp4"), key=lambda p: p.stat().st_mtime):
            g = re.match(r"(\d+)_", f.name)
            if g:
                out[str(int(g.group(1)))] = {"url": f"/media/{workdir.name}/clips/{f.name}",
                                             "name": f.name, "mtime": f.stat().st_mtime}
    return out


def project_summary(d: Path) -> dict | None:
    pp, tp = d / "clip_plan.json", d / "transcript.json"
    if pp.exists():
        plan = json.loads(pp.read_text(encoding="utf-8"))
        video, n = plan["video"], len(plan["clips"])
    elif tp.exists():
        video, n = json.loads(tp.read_text(encoding="utf-8"))["meta"], 0
    else:
        return None
    return {"id": d.name, "title": video.get("title"), "duration": video.get("duration"),
            "clips": n, "made": len(rendered_files(d)), "thumb": thumb_url(d.name, video),
            "updated": max(p.stat().st_mtime for p in d.iterdir()) if any(d.iterdir()) else 0}


# ---------------------------------------------------------------- pages & api


@app.get("/", response_class=HTMLResponse)
def index():
    return (HERE / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/api/state")
def state():
    cfg = ca.load_config()
    upd = {}
    try:
        upd = json.loads((HERE / ".update_status.json").read_text())
    except Exception:
        pass
    return {"app": "clip-agent", "version": app_version(), "has_key": bool(cfg.get("gemini_api_key")),
            "provider": cfg.get("provider", "gemini"), "update": upd,
            "has_cookies_file": ca.COOKIES_FILE.exists(),
            "settings": {k: v for k, v in cfg.items() if k != "gemini_api_key"},
            "key_hint": ("…" + cfg["gemini_api_key"][-4:]) if cfg.get("gemini_api_key") else ""}


@app.post("/api/settings")
async def save_settings(req: Request):
    body = await req.json()
    cfg = ca.load_config()
    for k in ("provider", "gemini_model", "ollama_model", "ollama_host", "cookies_browser", "whisper_fallback"):
        if k in body:
            cfg[k] = body[k]
    if body.get("gemini_api_key"):
        cfg["gemini_api_key"] = body["gemini_api_key"].strip()
    ca.save_config(cfg)
    ca._COOKIES_BROKEN = False  # give the (possibly new) login setting a fresh try
    return {"ok": True}


@app.post("/api/cookies")
async def save_cookies(req: Request):
    text = (await req.body()).decode("utf-8", errors="ignore")
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    yt = [ln for ln in lines if "youtube.com" in ln and len(ln.split("\t")) >= 7]
    if not yt:
        raise HTTPException(400, "That file doesn't have YouTube cookies in it. Export it while you're on youtube.com "
                                 "and signed in, and choose the Netscape / cookies.txt format.")
    if not text.startswith("# Netscape"):
        text = "# Netscape HTTP Cookie File\n" + text
    ca.COOKIES_FILE.write_text(text, encoding="utf-8")
    ca._COOKIES_BROKEN = False
    return {"ok": True, "cookies": len(yt)}


@app.delete("/api/cookies")
def delete_cookies():
    ca.COOKIES_FILE.unlink(missing_ok=True)
    return {"ok": True}


@app.get("/api/projects")
def projects():
    if not ca.OUT_ROOT.exists():
        return []
    items = [s for d in ca.OUT_ROOT.iterdir() if d.is_dir() and not d.name.startswith("_")
             for s in [project_summary(d)] if s]
    return sorted(items, key=lambda s: -s["updated"])


@app.get("/api/projects/{pid}")
def project(pid: str):
    d = project_dir(pid)
    pp = d / "clip_plan.json"
    if not pp.exists():
        raise HTTPException(404, "This project has no clip plan yet.")
    plan = json.loads(pp.read_text(encoding="utf-8"))
    plan["id"] = pid
    plan["thumb"] = thumb_url(pid, plan["video"])
    plan["rendered"] = rendered_files(d)
    return plan


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    import shutil
    shutil.rmtree(project_dir(pid), ignore_errors=True)
    return {"ok": True}


@app.post("/api/upload")
async def upload(req: Request):
    name = re.sub(r"[^A-Za-z0-9 _.\-]", "", req.query_params.get("name", "video.mp4")).strip() or "video.mp4"
    UPLOADS.mkdir(parents=True, exist_ok=True)
    dest = UPLOADS / name
    with open(dest, "wb") as f:
        async for chunk in req.stream():
            f.write(chunk)
    return {"path": str(dest)}


@app.post("/api/find")
async def find(req: Request):
    b = await req.json()
    source = (b.get("source") or "").strip()
    if not source:
        raise HTTPException(400, "Paste a YouTube link or add a video file.")
    n, length, notes = int(b.get("clips", 10)), int(b.get("length", 40)), b.get("notes", "")

    def run(job):
        cfg = ca.load_config()
        meta, words, workdir = ca.get_transcript(source)
        job["project"] = workdir.name
        if not meta.get("is_url"):
            make_local_thumb(workdir, meta)
        ca.find_clips(meta, words, workdir, n, length, cfg.get("provider", "gemini"), cfg, notes)
        return {"project": workdir.name}

    return {"job": new_job("find", run)}


@app.post("/api/paste")
async def paste(req: Request):
    b = await req.json()
    url = (b.get("url") or "").strip()
    try:
        data = json.loads(b.get("plan") or "")
        clips = data["clips"] if isinstance(data, dict) else data
        assert isinstance(clips, list) and clips
    except Exception:
        raise HTTPException(400, "That isn't a clip plan. It should be JSON with a \"clips\" list.")

    def run(job):
        try:
            meta, words, workdir = ca.get_transcript(url, allow_whisper=False)
        except Exception as e:
            ca.log(f"Couldn't get captions ({str(e)[:90]}). Using the plan's timestamps as they are.")
            meta = ca._meta_from_info(ca.youtube_info(url), url)
            workdir = ca.OUT_ROOT / f"{ca.slugify(meta['title'])}_{meta['id']}"
            workdir.mkdir(parents=True, exist_ok=True)
            words = []
        ca.build_plan(meta, words, workdir, clips, n_clips=len(clips), target_len=40)
        return {"project": workdir.name}

    return {"job": new_job("find", run)}


@app.post("/api/render")
async def render(req: Request):
    b = await req.json()
    pid = b.get("project")
    d = project_dir(pid)
    only = [int(x) for x in b.get("clips", [])]
    if not only:
        raise HTTPException(400, "Pick at least one clip.")
    opts = dict(layout=b.get("layout", "blur") if b.get("layout") in ca.LAYOUTS else "blur",
                highlight=b.get("color", "#FFE500"), use_whisper=bool(b.get("whisper", True)),
                tighten=bool(b.get("tighten", True)))

    def run(job):
        plan, workdir = ca.load_plan(d / "clip_plan.json")
        tp = workdir / "transcript.json"
        words_all = json.loads(tp.read_text(encoding="utf-8"))["words"] if tp.exists() else []
        made = []
        for c in plan["clips"]:
            if c["n"] not in only:
                continue
            # replace an older render of the same clip
            for old in (workdir / "clips").glob(f"{c['n']:02d}_*.mp4") if (workdir / "clips").exists() else []:
                old.unlink(missing_ok=True)
            try:
                made.append(ca.render_clip(c, plan, workdir, words_all, **opts).name)
            except Exception as e:
                ca.log(f"[{c['n']}] FAILED: {_clean(e)[:300]}")
        if not made:
            raise RuntimeError("None of the clips could be made. See the details above.")
        return {"project": pid, "made": made}

    jid = new_job("render", run, project=pid)
    JOBS[jid]["clip_states"] = {str(n): "queued" for n in only}
    return {"job": jid}


@app.get("/api/jobs/{jid}")
def job(jid: str):
    j = JOBS.get(jid)
    if not j:
        raise HTTPException(404, "unknown job")
    out = {k: v for k, v in j.items() if k != "logs"}
    out["logs"] = j["logs"][-30:]
    out["elapsed"] = round(time.time() - j["started"])
    return out


@app.get("/api/jobs")
def jobs():
    return [{"id": j["id"], "kind": j["kind"], "status": j["status"], "project": j.get("project")}
            for j in JOBS.values() if j["status"] in ("waiting", "running")]


@app.get("/media/{pid}/{path:path}")
def media(pid: str, path: str):
    d = project_dir(pid)
    f = (d / path).resolve()
    if d.resolve() not in f.parents or not f.is_file():
        raise HTTPException(404)
    return FileResponse(f)


@app.post("/api/open-folder")
async def open_folder(req: Request):
    b = await req.json()
    d = project_dir(b.get("project", ""))
    target = d / "clips" if (d / "clips").exists() else d
    if sys.platform.startswith("win"):
        os.startfile(str(target))  # noqa
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target)])
    return {"ok": True}


@app.post("/api/update")
def update_now():
    import updater
    res = updater.update(log=lambda m: None)
    if res.get("updated"):
        threading.Thread(target=_restart, daemon=True).start()
    return res


def _restart():
    time.sleep(0.8)
    flags = 0
    if sys.platform.startswith("win"):
        flags = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED | NEW_GROUP | NO_WINDOW
    subprocess.Popen([sys.executable, str(HERE / "launch.pyw"), "--restart", "--no-browser"], cwd=str(HERE),
                     creationflags=flags, close_fds=True)
    os._exit(0)


@app.post("/api/quit")
def quit_app():
    threading.Thread(target=lambda: (time.sleep(0.5), os._exit(0)), daemon=True).start()
    return {"ok": True}


@app.exception_handler(HTTPException)
async def http_err(_, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


if __name__ == "__main__":
    import uvicorn
    ca.OUT_ROOT.mkdir(exist_ok=True)
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
