import os
import uuid
import shutil
import time
import threading
import queue



from fastapi import FastAPI, UploadFile, File, HTTPException,Header
from backend.media import extract_frame_base64, validate_video
from backend.services.analyzer_service import run_analysis
from fastapi.responses import HTMLResponse
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("API_KEY")

app = FastAPI()

jobs = {}
job_queue = queue.Queue()

UPLOAD_DIR = "uploads"

os.makedirs(UPLOAD_DIR, exist_ok=True)

def check_api_key(x_api_key: str | None):
    if not API_KEY or not x_api_key or x_api_key != API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key"
        )
        
        
def safe_upload_name(filename: str | None) -> str:
    # Normalize both Windows and POSIX paths before taking the basename.
    safe_name = Path((filename or "").replace("\\", "/")).name
    if not safe_name.lower().endswith(".mov"):
        raise HTTPException(status_code=400, detail="Only .mov files are supported")
    if any(ord(char) < 32 or char in '<>:"|?*' for char in safe_name):
        raise HTTPException(status_code=400, detail="Invalid filename")
    return safe_name


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def root():

    html_path = Path(
        "backend/templates/index.html"
    )

    return html_path.read_text(
        encoding="utf-8"
    )


@app.post("/api/v1/analyze")
async def analyze(
    file: UploadFile = File(...),
    x_api_key: str | None = Header(default=None)
):
    check_api_key(x_api_key)

    safe_name = safe_upload_name(file.filename)

    job_id = uuid.uuid4().hex[:8]

    file_path = os.path.join(
        UPLOAD_DIR,
        f"{job_id}_{safe_name}"
    )

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    if os.path.getsize(file_path) == 0:
        os.remove(file_path)

        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty"
        )

    jobs[job_id] = {
        "job_id": job_id,
        "status": "processing"
    }

    job_queue.put((job_id, file_path))

    return {
        "job_id": job_id
    }

@app.post("/ui/analyze", include_in_schema=False)
async def ui_analyze(file: UploadFile = File(...)):

    safe_name = safe_upload_name(file.filename)

    job_id = uuid.uuid4().hex[:8]

    file_path = os.path.join(
        UPLOAD_DIR,
        f"{job_id}_{safe_name}"
    )

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    if os.path.getsize(file_path) == 0:
        os.remove(file_path)

        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty"
        )

    jobs[job_id] = {
        "job_id": job_id,
        "status": "processing"
    }

    job_queue.put((job_id, file_path))

    return {
        "job_id": job_id
    }
    
@app.get("/ui/jobs/{job_id}", include_in_schema=False)
def ui_get_job(job_id: str):

    if job_id not in jobs:
        raise HTTPException(
            status_code=404,
            detail="Job not found"
        )

    return jobs[job_id]    

@app.get("/api/v1/jobs/{job_id}")
def get_job(
    job_id: str,
    x_api_key: str | None = Header(default=None)
):
    check_api_key(x_api_key)

    if job_id not in jobs:
        raise HTTPException(
            status_code=404,
            detail="Job not found"
        )

    return jobs[job_id]

def process_video(job_id: str, file_path: str):
    try:
        result = run_analysis(file_path)
        jobs[job_id] = {
            "job_id": job_id,
            "status": "done",
            **result,
        }

    except Exception as e:
        jobs[job_id] = {
            "job_id": job_id,
            "status": "failed",
            "error": str(e)
        }

    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

def worker():
    while True:
        job_id, file_path = job_queue.get()

        try:
            process_video(job_id, file_path)
        finally:
            job_queue.task_done()

worker_thread = threading.Thread(
    target=worker,
    daemon=True
)

worker_thread.start()
