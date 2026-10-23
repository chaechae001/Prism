"""Server-only configuration. Process > root .env > local chat file."""

import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


def load_environment():
    load_dotenv(ROOT / ".env", interpolate=False, override=False)
    load_dotenv(ROOT / "backend/.env.chat.local", interpolate=False, override=False)


def data_source():
    return os.getenv("PRISM_DATA_SOURCE", "fixture")
