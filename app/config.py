import os
import re
from pathlib import Path

from dotenv import load_dotenv

# Load .env once so flags can be tuned without code changes
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _get_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# Anonymous configuration
ANONYMIZE_TERMS = ["STC"]
ANONYMIZE_REPLACE = "[REDACTED]"

# Runtime flags (tweak via .env or Streamlit toggles)
THROUGHPUT_MODE = _get_bool("THROUGHPUT_MODE", False)
OCR_MAX_IMAGES_PER_DOC = _get_int("OCR_MAX_IMAGES_PER_DOC", 10)
OCR_RENDER_SCALE = _get_float("OCR_RENDER_SCALE", 1.25)
VERBOSE_LOGGING = _get_bool("VERBOSE_LOGGING", False)

# Hardcoded/internal defaults
PDF_ENGINE = "pymupdf"
OCR_ENGINE = "paddle"
MAX_WORKERS = os.cpu_count() or 4
MAX_CACHE_ITEMS = _get_int("MAX_CACHE_ITEMS", 64)

# PII Detection Mode (precompile for speed)
PII_PATTERNS = {
    'email': re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
    'phone': re.compile(r'\b(\+\d{1,2}\s?)?1?\-?\.?\s?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b'),
    'ssn': re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),
    'credit_card': re.compile(r'\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b'),
    'iban': re.compile(r'\b[A-Z]{2}\d{2}[\s\-]?[A-Z\d]{4}[\s\-]?[A-Z\d]{4}[\s\-]?[A-Z\d]{4}[\s\-]?[A-Z\d]{1,4}\b')
}

# JSON Output configuration
JSON_SCHEMA = {
    "document_metadata": {
        "filename": "",
        "file_type": "",
        "processing_date": "",
        "file_size": 0
    },
    "content": {
        "text": "",
        "tables": [],
        "images": []
    },
    "processing_info": {
        "anonymized": False,
        "pii_removed": False,
        "extracted_to_json": False
    }
}

# OCR setting
OCR_CONFIG = {
    'enabled': True,
    'languages': ['eng'],
    'timeout': 30
}

# UI and Upload limits
MAX_FILE_SIZE_MB = 20
MAX_BATCH_SIZE_MB = 100
MAX_FILES = 10

PDF_HEADER_RATIO = 0.08
