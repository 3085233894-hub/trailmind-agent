from pathlib import Path
import os
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"

load_dotenv(dotenv_path=ENV_PATH, override=True)

API_KEY = os.getenv("API_KEY", "").strip()
BASE_URL = os.getenv("BASE_URL", "").strip()
MODEL = os.getenv("MODEL", "").strip()
ORS_API_KEY = os.getenv("ORS_API_KEY", "").strip()


def get_anthropic_api_url() -> str:
    if not BASE_URL:
        raise RuntimeError(f"BASE_URL 未配置，请检查 {ENV_PATH}")
    return BASE_URL.rstrip("/")


if not API_KEY:
    raise RuntimeError(f"API_KEY 未配置，请检查 {ENV_PATH}")

if not BASE_URL:
    raise RuntimeError(f"BASE_URL 未配置，请检查 {ENV_PATH}")

if not MODEL:
    raise RuntimeError(f"MODEL 未配置，请检查 {ENV_PATH}")