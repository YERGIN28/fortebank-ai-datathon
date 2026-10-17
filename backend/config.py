import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

API_KEY = os.getenv("API_KEY")
ANALYSIS_MODE = os.getenv("ANALYSIS_MODE", "fake").strip().lower()
MODEL_PATH = os.getenv("MODEL_PATH")
