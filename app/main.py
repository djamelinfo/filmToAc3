import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .converter import AudioTrack, MediaFile, MediaLibrary


class Selection(BaseModel):
    source: str
    track_index: int = Field(ge=0)
    make_default: bool = False


@dataclass
class Job:
    source: str
    output: str
    track_index: int
    status: str = "queued"
    message: str | None = None


class AppState:
    def __init__(self, library: MediaLibrary):
        self.library = library
        self.media: dict[str, MediaFile] = {}
        self.scan_errors: list[str] = []
        self.scanned = False
        self.jobs: list[Job] = []
        self.active_outputs: set[Path] = set()
        self.lock = Lock()
        self.scan_lock = Lock()
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="conversion")

    def enqueue(self, selections: list[Selection]) -> dict[str, int]:
        if not selections:
            raise HTTPException(422, "Select a DTS track for at least one file.")

        queued = 0
        already_active = 0
        with self.lock:
            batch = []
            for selection in selections:
                media = self.media.get(selection.source)
                if not media or media.error:
                    raise HTTPException(422, f"Scan for a readable source file: {selection.source}")
                track = next(
                    (track for track in media.tracks if track.index == selection.track_index and track.is_dts),
                    None,
                )
                if track is None:
                    raise HTTPException(422, f"Select a DTS track for {selection.source}.")
                batch.append((media, track, selection.make_default))

            for media, track, make_default in batch:
                output = Path(media.output)
                if output in self.active_outputs:
                    already_active += 1
                    continue
                job = Job(media.source, media.output, track.index)
                self.active_outputs.add(output)
                self.jobs.append(job)
                self.worker.submit(self._run_job, job, media, track, make_default)
                queued += 1
        return {"queued": queued, "already_active": already_active}

    def _run_job(self, job: Job, media: MediaFile, track: AudioTrack, make_default: bool) -> None:
        with self.lock:
            job.status = "running"
        try:
            published = self.library.convert(media, track, make_default)
            status, message = ("completed", None) if published else ("skipped", "Output already exists.")
        except Exception as exc:
            status, message = "failed", str(exc) or type(exc).__name__
        with self.lock:
            job.status = status
            job.message = message
            self.active_outputs.remove(Path(job.output))


@asynccontextmanager
async def lifespan(app: FastAPI):
    library = MediaLibrary(
        Path(os.getenv("MEDIA_PATH", "/data")),
        Path(os.getenv("OUTPUT_PATH", "/output")),
    )
    state = AppState(library)
    app.state.ac3fixer = state
    try:
        yield
    finally:
        state.worker.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="AC3Fixer", lifespan=lifespan)
app_dir = Path(__file__).parent
app.mount("/static", StaticFiles(directory=app_dir / "static"), name="static")
templates = Jinja2Templates(directory=app_dir / "templates")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    state: AppState = request.app.state.ac3fixer
    with state.lock:
        context = {
            "media_path": state.library.source,
            "output_path": state.library.output,
            "media": list(state.media.values()),
            "scanned": state.scanned,
            "scan_errors": state.scan_errors,
        }
    return templates.TemplateResponse(request=request, name="index.html", context=context)


@app.post("/scan")
def scan(request: Request):
    state: AppState = request.app.state.ac3fixer
    with state.scan_lock:
        media, errors = state.library.scan()
        with state.lock:
            state.media = media
            state.scan_errors = errors
            state.scanned = True
    return RedirectResponse(url="/", status_code=303)


@app.post("/convert", status_code=202)
def enqueue(request: Request, selections: list[Selection]):
    state: AppState = request.app.state.ac3fixer
    return state.enqueue(selections)


@app.get("/jobs")
def jobs(request: Request):
    state: AppState = request.app.state.ac3fixer
    with state.lock:
        return [asdict(job) for job in state.jobs]
