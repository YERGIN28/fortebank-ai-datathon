import os
import uuid
import shutil
import time
import threading



from fastapi import FastAPI, UploadFile, File, HTTPException,Header

API_KEY = "forte-datathon-secret"

app = FastAPI()

jobs = {}

UPLOAD_DIR = "uploads"

os.makedirs(UPLOAD_DIR, exist_ok=True)

def check_api_key(x_api_key: str):
    if x_api_key != API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key"
        )
        
        
@app.get("/")
def root():
    return {"status": "ok"}


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

    jobs[job_id] = {
        "job_id": job_id,
        "status": "processing"
    }

    thread = threading.Thread(
        target=process_video,
        args=(job_id, file_path)
    )

    thread.start()

    return {
        "job_id": job_id
    }


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
        time.sleep(15)

        jobs[job_id] = {
            "job_id": job_id,
            "status": "done",
            "verdict": "violation",
            "violations": [
                {
                    "type": "Test violation",
                    "timecode_sec": 10.0,
                    "description": "Test violation detected",
                    "evidence_frames": []
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