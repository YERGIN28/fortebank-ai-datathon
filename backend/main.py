import os
import uuid
import shutil
import time
import threading
import queue



from fastapi import FastAPI, UploadFile, File, HTTPException,Header
from backend.media import extract_frame_base64, validate_video
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

def check_api_key(x_api_key: str):
    if x_api_key != API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key"
        )
        
        
@app.get("/", response_class=HTMLResponse)
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
    x_api_key: str = Header(...)
):
    check_api_key(x_api_key)

    if not file.filename.lower().endswith(".mov"):
        raise HTTPException(
            status_code=400,
            detail="Only .mov files are supported"
        )

    job_id = uuid.uuid4().hex[:8]

    file_path = os.path.join(
        UPLOAD_DIR,
        f"{job_id}_{file.filename}"
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

@app.post("/ui/analyze")
async def ui_analyze(file: UploadFile = File(...)):

    if not file.filename.lower().endswith(".mov"):
        raise HTTPException(
            status_code=400,
            detail="Only .mov files are supported"
        )

    job_id = uuid.uuid4().hex[:8]

    file_path = os.path.join(
        UPLOAD_DIR,
        f"{job_id}_{file.filename}"
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
    
@app.get("/ui/jobs/{job_id}")
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
    x_api_key: str = Header(...)
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
        video_info = validate_video(file_path)
        
        time.sleep(20)

        timestamp = 10.0

        evidence_frame = extract_frame_base64(
            file_path,
            timestamp
        )

        jobs[job_id] = {
            "job_id": job_id,
            "status": "done",
            "verdict": "violation",
            "violations": [
                {
                    "type": "Test violation",
                    "timecode_sec": timestamp,
                    "description": "Test violation detected",
                    "evidence_frames": [
                        evidence_frame
                    ]
                }
            ]
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