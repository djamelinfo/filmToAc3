import os
import threading
from pathlib import Path
from typing import Dict, List


from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates


from .converter import plan_jobs, convert, MediaJob


MEDIA_PATH = Path(os.getenv("MEDIA_PATH", "/data")).resolve()
DEFAULT_EXT = os.getenv("FILE_EXT", ".mkv")
AUDIO_BITRATE = os.getenv("AUDIO_BITRATE", "640k")
AUDIO_CHANNELS = int(os.getenv("AUDIO_CHANNELS", "6"))


app = FastAPI(title="AC3Fixer")
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
_templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


STATE: Dict[str, List[MediaJob]] = {"jobs": []}
LOCK = threading.Lock()




@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    with LOCK:
        jobs = STATE["jobs"]
    return _templates.TemplateResponse("index.html", {
        "request": request,
        "media_path": str(MEDIA_PATH),
        "ext": DEFAULT_EXT,
        "bitrate": AUDIO_BITRATE,
        "channels": AUDIO_CHANNELS,
        "jobs": jobs,
    })




@app.post("/scan")
async def scan(ext: str = Form(DEFAULT_EXT)):
    jobs = plan_jobs(MEDIA_PATH, ext=ext, bitrate=AUDIO_BITRATE, channels=AUDIO_CHANNELS)
    with LOCK:
        STATE["jobs"] = jobs
    return RedirectResponse(url="/", status_code=303)




def _run_conversions():
    with LOCK:
        jobs = list(STATE["jobs"]) # snapshot
    for j in jobs:
        if not j.will_convert:
            continue
        try:
            convert(j, bitrate=AUDIO_BITRATE, channels=AUDIO_CHANNELS, move_originals=True)
            j.reason = "converted ✅"
        except Exception as e:
            j.reason = f"error: {e}"
    with LOCK:
        STATE["jobs"] = jobs




@app.post("/convert")
async def do_convert():
    t = threading.Thread(target=_run_conversions, daemon=True)
    t.start()
    return RedirectResponse(url="/", status_code=303)