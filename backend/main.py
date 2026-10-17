import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
from pathlib import Path
import queue
import shutil
import threading
import time
import uuid

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

from backend.config import API_KEY, BASE_DIR
from backend import config
from backend.contracts import JobDoneResponse
from backend.services.analyzer_service import VideoAnalyzer
from backend.worker_lock import WorkerLock

logger = logging.getLogger(__name__)
jobs = {}
# Separate metadata keeps internal timestamps out of the public JSON contract.
job_lifecycle = {}
job_queue = queue.Queue()
UPLOAD_DIR = BASE_DIR / "uploads"
WORKER_LOCK_PATH = UPLOAD_DIR / ".worker.lock"
worker_thread = None
accepting_jobs = False
state_lock = threading.Lock()
_stop = object()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def remove_upload(file_path):
    try:
        Path(file_path).unlink(missing_ok=True)
        return None
    except OSError as exc:
        logger.exception("Could not remove uploaded video")
        return str(exc)


def process_video(job_id: str, file_path: str, analyzer):
    metadata = job_lifecycle[job_id]
    metadata["started_at"] = utc_now()
    started = time.perf_counter()
    try:
        result = analyzer.run_analysis(file_path)
        response = JobDoneResponse(
            job_id=job_id, status="done",
            verdict=result["verdict"], violations=result["violations"],
        )
        if (response.verdict == "violation") != bool(response.violations):
            raise ValueError("Analysis returned an inconsistent verdict")
        if any(not 1 <= len(item.evidence_frames) <= 3 for item in response.violations):
            raise ValueError("Each violation requires 1 to 3 evidence frames")
        final = response.model_dump()
    except Exception as exc:
        logger.exception("Analysis failed for job %s", job_id)
        final = {"job_id": job_id, "status": "failed", "error": str(exc) or type(exc).__name__}
    finally:
        cleanup_error = remove_upload(file_path)
        if cleanup_error:
            metadata["cleanup_error"] = cleanup_error
        metadata["finished_at"] = utc_now()
        metadata["processing_time_sec"] = round(time.perf_counter() - started, 6)
    jobs[job_id] = final


def worker(ready, startup):
    try:
        analyzer = VideoAnalyzer()
        analyzer.load()  # Once in this thread, before requests are accepted.
    except Exception as exc:
        startup["error"] = exc
        ready.set()
        return
    ready.set()
    while True:
        item = job_queue.get()
        try:
            if item is _stop:
                return
            job_id, file_path = item
            process_video(job_id, file_path, analyzer)
        finally:
            job_queue.task_done()


@asynccontextmanager
async def lifespan(app):
    global worker_thread, accepting_jobs
    if not API_KEY:
        raise RuntimeError("API_KEY must be set in .env or the environment")
    guard = WorkerLock(Path(WORKER_LOCK_PATH))
    guard.acquire()
    ready = threading.Event()
    startup = {}
    thread = threading.Thread(target=worker, args=(ready, startup), name="video-worker", daemon=True)
    worker_thread = thread
    try:
        Path(UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
        thread.start()
        await asyncio.to_thread(ready.wait)
        if "error" in startup:
            raise RuntimeError(f"Analysis worker startup failed: {startup['error']}") from startup["error"]
        with state_lock:
            accepting_jobs = True
        yield
    finally:
        with state_lock:
            accepting_jobs = False
            if thread.is_alive():
                job_queue.put(_stop)  # Drain accepted jobs before stopping.
        if thread.ident is not None:
            await asyncio.to_thread(thread.join)
        worker_thread = None
        guard.release()


app = FastAPI(lifespan=lifespan)


def check_api_key(x_api_key: str | None):
    if not API_KEY or not x_api_key or x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


def safe_upload_name(filename: str | None) -> str:
    safe_name = Path((filename or "").replace("\\", "/")).name
    if not safe_name.lower().endswith(".mov"):
        raise HTTPException(status_code=400, detail="Only .mov files are supported")
    if any(ord(char) < 32 or char in '<>:"|?*' for char in safe_name):
        raise HTTPException(status_code=400, detail="Invalid filename")
    return safe_name


def enqueue_video(file: UploadFile):
    safe_name = safe_upload_name(file.filename)
    with state_lock:
        if not accepting_jobs:
            raise HTTPException(status_code=503, detail="Analysis worker is not ready")
    job_id = uuid.uuid4().hex
    file_path = Path(UPLOAD_DIR) / f"{job_id}_{safe_name}"
    try:
        with file_path.open("xb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        if file_path.stat().st_size == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
        with state_lock:
            if not accepting_jobs:
                raise HTTPException(status_code=503, detail="Analysis worker is not ready")
            job_lifecycle[job_id] = {
                "created_at": utc_now(), "started_at": None,
                "finished_at": None, "processing_time_sec": None,
            }
            jobs[job_id] = {"job_id": job_id, "status": "processing"}
            job_queue.put((job_id, str(file_path)))
    except Exception:
        remove_upload(file_path)
        raise
    finally:
        file.file.close()
    return {"job_id": job_id}


def job_response(job_id):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def root():
    html = (BASE_DIR / "backend/templates/index.html").read_text(encoding="utf-8")
    notice = (
        "Demo mode: results are simulated and do not confirm violations."
        if config.ANALYSIS_MODE == "fake" else
        "AI mode: final decisions are unavailable until the Rule Engine is completed."
    )
    return html.replace("__ANALYSIS_NOTICE__", notice)


@app.post("/api/v1/analyze")
def analyze(file: UploadFile = File(...), x_api_key: str | None = Header(default=None)):
    check_api_key(x_api_key)
    return enqueue_video(file)


@app.get("/api/v1/jobs/{job_id}")
def get_job(job_id: str, x_api_key: str | None = Header(default=None)):
    check_api_key(x_api_key)
    return job_response(job_id)


@app.post("/ui/analyze", include_in_schema=False)
def ui_analyze(file: UploadFile = File(...)):
    return enqueue_video(file)


@app.get("/ui/jobs/{job_id}", include_in_schema=False)
def ui_get_job(job_id: str):
    return job_response(job_id)
