import logging
import os
from pathlib import Path
import queue
import secrets
import threading
import time
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

from backend.media import extract_frame_base64
from backend.services.analyzer_service import analyze_video

load_dotenv()
log = logging.getLogger(__name__)
API_KEY = os.getenv("API_KEY", "")
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads"))
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
JOB_SECONDS = 300.0
jobs = {}
job_queue = queue.Queue()
worker_ready = threading.Event()
worker_error = None
stop_worker = threading.Event()
engine = None
admission = threading.BoundedSemaphore(1)
job_deadlines = {}


def create_engine():
    from app.inference import InferenceConfig, InferenceEngine
    model_path = os.getenv("MODEL_PATH")
    if not model_path or not Path(model_path).is_dir():
        raise RuntimeError("Set MODEL_PATH to local Qwen3-VL-2B-Instruct weights")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    return InferenceEngine(InferenceConfig(model_path=Path(model_path),
                                          time_budget_seconds=240.0))


def process_video(job_id, file_path, deadline):
    try:
        if deadline - time.perf_counter() < 280:
            raise TimeoutError("Insufficient remaining job budget")
        jobs[job_id] = analyze_video(
            job_id, file_path, engine,
            lambda timestamp: extract_frame_base64(file_path, timestamp, deadline), deadline)
    except Exception as error:
        log.exception("Job %s failed", job_id)
        jobs[job_id] = {"job_id": job_id, "status": "failed", "error": type(error).__name__}
    finally:
        Path(file_path).unlink(missing_ok=True)


def worker():
    global engine, worker_error
    try:
        engine = create_engine()
        engine.load()
        worker_ready.set()
    except Exception as error:
        worker_error = type(error).__name__
        log.exception("Local model worker could not start")
        return
    while not stop_worker.is_set():
        try:
            item = job_queue.get(timeout=0.25)
        except queue.Empty:
            continue
        try:
            process_video(*item)
        finally:
            admission.release()
            job_queue.task_done()
    worker_ready.clear()


@asynccontextmanager
async def lifespan(app):
    global worker_error
    if not API_KEY:
        raise RuntimeError("API_KEY must be configured")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stop_worker.clear()
    worker_ready.clear()
    worker_error = None
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    yield
    stop_worker.set()
    worker_ready.clear()


app = FastAPI(lifespan=lifespan)


def check_api_key(value):
    if not API_KEY or not value or not secrets.compare_digest(value, API_KEY):
        raise HTTPException(401, "Invalid API key")


@app.get("/", response_class=HTMLResponse)
def root():
    return (Path(__file__).parent / "templates" / "index.html").read_text(encoding="utf-8")


@app.get("/health")
def health():
    return {"ready": worker_ready.is_set(), "worker_error": worker_error}


async def submit(file):
    if not worker_ready.is_set():
        raise HTTPException(503, "Local model is not ready")
    if not (file.filename or "").lower().endswith(".mov"):
        raise HTTPException(400, "Only .mov files are supported")
    if not admission.acquire(blocking=False):
        raise HTTPException(503, "Worker is busy; retry later")
    started = time.perf_counter()
    job_id = uuid.uuid4().hex
    file_path = UPLOAD_DIR / (job_id + ".mov")
    size = 0
    try:
        with file_path.open("wb") as target:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "Video exceeds 100 MiB")
                target.write(chunk)
        if size == 0:
            raise HTTPException(400, "Uploaded file is empty")
    except Exception:
        file_path.unlink(missing_ok=True)
        admission.release()
        raise
    finally:
        await file.close()
    jobs[job_id] = {"job_id": job_id, "status": "processing"}
    job_deadlines[job_id] = started + JOB_SECONDS
    job_queue.put((job_id, file_path, started + JOB_SECONDS))
    return {"job_id": job_id}


@app.post("/api/v1/analyze")
async def analyze(file: UploadFile = File(...), x_api_key: str | None = Header(None)):
    check_api_key(x_api_key)
    return await submit(file)


def get_job_result(job_id):
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    if jobs[job_id]["status"] == "processing" and time.perf_counter() >= job_deadlines[job_id]:
        jobs[job_id] = {"job_id": job_id, "status": "failed", "error": "job_timeout"}
    return jobs[job_id]


@app.get("/api/v1/jobs/{job_id}")
def get_job(job_id: str, x_api_key: str | None = Header(None)):
    check_api_key(x_api_key)
    return get_job_result(job_id)


@app.post("/ui/analyze", include_in_schema=False)
async def ui_analyze(file: UploadFile = File(...)):
    return await submit(file)


@app.get("/ui/jobs/{job_id}", include_in_schema=False)
def ui_get_job(job_id: str):
    return get_job_result(job_id)
