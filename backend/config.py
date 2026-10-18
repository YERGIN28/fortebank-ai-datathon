import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(os.getenv("FORTEBANK_ENV_FILE", str(BASE_DIR / ".env")))

API_KEY = os.getenv("API_KEY")
ANALYSIS_MODE = os.getenv("ANALYSIS_MODE", "real").strip().lower()
ASSESSMENT_MODE = os.getenv('ASSESSMENT_MODE', 'possible_signs').strip().lower()
if ASSESSMENT_MODE not in ('possible_signs', 'strict'):
    raise ValueError('ASSESSMENT_MODE must be possible_signs or strict')
MODEL_PATH = os.getenv("MODEL_PATH")
MODEL_QUANTIZATION = os.getenv('MODEL_QUANTIZATION', 'none')
_verify_positive = os.getenv('VERIFY_POSITIVE_CONDITIONS', 'false').strip().lower()
if _verify_positive not in ('true', 'false'):
    raise ValueError('VERIFY_POSITIVE_CONDITIONS must be true or false')
VERIFY_POSITIVE_CONDITIONS = _verify_positive == 'true'
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "uploads")))
WORKER_LOCK_PATH = Path(os.getenv("WORKER_LOCK_PATH", str(UPLOAD_DIR / ".worker.lock")))
_audit_dir = os.getenv("INFERENCE_AUDIT_DIR")
INFERENCE_AUDIT_DIR = Path(_audit_dir) if _audit_dir else None
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(64 * 1024 * 1024)))
MAX_PENDING_JOBS = int(os.getenv('MAX_PENDING_JOBS', '4'))
if MAX_PENDING_JOBS < 1:
    raise ValueError('MAX_PENDING_JOBS must be positive')
if MAX_UPLOAD_BYTES <= 0:
    raise ValueError("MAX_UPLOAD_BYTES must be positive")
