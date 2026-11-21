import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock
from time import monotonic

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .converter import DEFAULT_SCAN_WORKERS, AudioTrack, MediaFile, MediaLibrary


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
    progress: int | None = None


class AppState:
    def __init__(self, library: MediaLibrary):
        self.library = library
        self.media: dict[str, MediaFile] = {}
        self.scan_errors: list[str] = []
        self.scanned = False
        self.jobs: list[Job] = []
        self.active_outputs: set[Path] = set()
        self.recent_outputs: dict[str, float] = {}
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
        def report_progress(percent: int) -> None:
            with self.lock:
                job.progress = percent

        with self.lock:
            job.status = "running"
        try:
            published = self.library.convert(media, track, make_default, report_progress=report_progress)
            status, message = ("completed", None) if published else ("skipped", "Output already exists.")
        except Exception as exc:
            status, message = "failed", str(exc) or type(exc).__name__
        with self.lock:
            job.status = status
            job.message = message
            if status == "completed":
                job.progress = 100
            if status in ("completed", "skipped"):
                self.recent_outputs[job.source] = monotonic()
            self.active_outputs.remove(Path(job.output))

    def library_view(self) -> tuple[dict[str, int], list[MediaFile], list[str]]:
        """Collect dashboard counts and conversion rows with the state lock held."""
        statuses = {job.source: job.status for job in self.jobs}
        active = {source for source, status in statuses.items() if status in ("queued", "running")}
        stats = {
            "found": len(self.media),
            "needs_attention": 0,
            "completed": 0,
            "in_progress": len(active),
        }
        conversion_files = []
        pending_sources = []
        for source, file in self.media.items():
            has_output = file.output_exists or source in self.recent_outputs
            can_convert = not file.error and not has_output and any(track.is_dts for track in file.tracks)
            if can_convert:
                # Keep active rows available to show again if their job fails.
                conversion_files.append(file)
            if source in active:
                continue
            if can_convert:
                pending_sources.append(source)
            if file.error or statuses.get(source) == "failed" or can_convert:
                stats["needs_attention"] += 1
            elif has_output:
                stats["completed"] += 1
        return stats, conversion_files, pending_sources


@asynccontextmanager
async def lifespan(app: FastAPI):
    library = MediaLibrary(
        Path(os.getenv("MEDIA_PATH", "/data")),
        Path(os.getenv("OUTPUT_PATH", "/output")),
        scan_workers=int(os.getenv("SCAN_WORKERS", str(DEFAULT_SCAN_WORKERS))),
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
        stats, conversion_files, pending_sources = state.library_view()
        context = {
            "media_path": state.library.source,
            "output_path": state.library.output,
            "media": conversion_files,
            "pending_sources": set(pending_sources),
            "scanned": state.scanned,
            "scan_errors": state.scan_errors,
            "file_errors": [file for file in state.media.values() if file.error],
            "stats": stats,
        }
    return templates.TemplateResponse(request=request, name="index.html", context=context)


@app.post("/scan")
def scan(request: Request):
    state: AppState = request.app.state.ac3fixer
    with state.scan_lock:
        started_at = monotonic()
        media, errors = state.library.scan()
        with state.lock:
            state.media = media
            state.scan_errors = errors
            state.scanned = True
            # The scan replaces older output state. Keep jobs that finished while it ran.
            state.recent_outputs = {
                source: finished_at for source, finished_at in state.recent_outputs.items()
                if finished_at >= started_at
            }
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


@app.get("/dashboard")
def dashboard(request: Request):
    state: AppState = request.app.state.ac3fixer
    with state.lock:
        stats, _, pending_sources = state.library_view()
        return {
            "stats": stats,
            "jobs": [asdict(job) for job in state.jobs],
            "pending_sources": pending_sources,
        }
