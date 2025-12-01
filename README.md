# DocGuard

A production-ready, Streamlit-based document processing application that:
- Processes TXT, DOCX, and PDF files (up to 10 files per batch)
- Anonymizes sensitive terms and removes PII (regex + spaCy NER)
- Extracts a structured JSON representation (text, tables, images/ocr info)
- Outputs processed PDFs (for anonymize/PII remove) or JSON (for extraction)
- Offers optional OCR for images in PDFs/DOCX (PaddleOCR with heuristics), enabled by default via UI toggle

This repository is intentionally simple and robust: a single Streamlit app with a self-contained processing pipeline and Dockerized runtime. It avoids code duplication and unnecessary moving parts.

---

## Table of Contents
- Overview
- Key Features
- Architecture & Components
- Installation (Docker recommended)
- Quick Start
- Configuration & Tunables
- Usage Guide
- Performance & Sizing
- Security & Privacy
- Troubleshooting
- Development
- Directory Structure
- Roadmap & Extensibility
- License

---

## Overview
This app enables batch document processing with minimal setup. It is suitable for local/desktop use, internal teams, and containerized deployments. The UI guides users through uploading files, selecting processing options, viewing summaries, previewing JSON (for the first file), and downloading results as a ZIP or individually.

The design goals are:
- Keep it simple: single service, single code path
- Be robust: predictable behavior, clear errors, explicit limits
- Be adaptable: configuration in code, toggles in the UI, Dockerized dependencies

---

## Key Features
- Supported formats: .txt, .docx, .pdf
- Batch processing: up to 10 files per run
- Operations:
  - Anonymize: replace configured terms (case-insensitive)
  - Remove PII: redact emails, phones, SSN, credit cards, IBAN; enhance with spaCy NER for PERSON/ORG/GPE
  - Extract to JSON: structured output with document metadata, text, tables, and image metadata (with optional thumbnails)
- PDF output:
  - For TXT: re-renders as PDF via ReportLab
  - For DOCX/PDF: generates PDF while attempting to preserve layout
- OCR (default ON):
  - PaddleOCR-based OCR with per-document caps and heuristics to skip low-value images
  - Configurable via UI checkbox at runtime
- Table extraction:
  - PyMuPDF `find_tables()` path with header/footer clipping
- PDF text extraction:
  - Single-pass PyMuPDF path (header/footer clipping + tables/images)
- In-session caching skips re-processing duplicate inputs (LRU per worker)
- Built-in constraints:
  - 20MB per file max, 100MB total batch max (configurable in code)
- Parallel processing with live per-file status (ProcessPoolExecutor)
- Advanced options expander exposes throughput mode, verbose logging, and timing details for the first processed file

---

## Architecture & Components
- Streamlit UI: app/app.py
  - Handles uploads, option selection, progress, results, and downloads
- Processing Core: app/document_processor.py
  - Parsing & extraction: python-docx and PyMuPDF (single-pass text/table/image extraction)
  - PII/NER: regex + spaCy (en_core_web_sm)
  - OCR: PaddleOCR (CPU) with selective heuristics and per-document caps
  - PDF generation: ReportLab
- Config: app/config.py
  - ANONYMIZE_TERMS, PII_PATTERNS, JSON_SCHEMA, OCR_CONFIG, PDF_HEADER_RATIO
- Containerization:
  - app/Dockerfile installs system deps and Python packages
  - docker-compose.yml runs the single Streamlit service on :8501

Notes
- No separate backend: The UI calls the processing core in-process.
- No data persistence: Files are processed in-memory for a single session. You download the results.

---

## Installation (Docker recommended)
Prerequisites
- Docker (and optionally Docker Compose)

Build the image
```
cd app
docker build -t docprocessor-streamlit .
```

Run with Docker Compose (root of repo)
```
docker-compose up -d
# App: http://localhost:8501
```

Or run the container directly
```
docker run -d -p 8501:8501 --name docprocessor docprocessor-streamlit
```

Local (without Docker)
- Python 3.12 recommended
- System dependencies (Ubuntu/Debian):
  - libgl1 and libglib2.0-0 (for PaddleOCR/OpenCV)
```
sudo apt update
sudo apt install -y libgl1 libglib2.0-0
```
- Install Python deps and run Streamlit
```
cd app
pip install -r requirements.txt
streamlit run app.py
```

---

## Quick Start
1) Open the app at http://localhost:8501
2) Upload up to 10 documents (.txt, .docx, .pdf)
3) Choose operations: Anonymize, Remove PII, Extract to JSON
4) Toggle OCR (enabled by default)
5) Click Process
6) Review the summary and preview JSON (if selected)
7) Download all results as a ZIP or individual files

---

## Configuration & Tunables
Most options live in app/config.py:
- ANONYMIZE_TERMS: list of terms to replace with ANONYMIZE_REPLACE
- ANONYMIZE_REPLACE: replacement string (default: [REDACTED])
- PII_PATTERNS: regexes for email/phone/SSN/credit_card/IBAN
- JSON_SCHEMA: shape of the JSON output (metadata + content)
- OCR_CONFIG:
  - enabled: runtime toggle via UI overrides this
  - languages: default ["eng"]
  - timeout: OCR timeout per image (seconds)
- PDF_HEADER_RATIO: fraction of page height to skip at top/bottom when extracting text
- MAX_CACHE_ITEMS: per-worker in-memory cache size (set to 0 to disable duplicate detection)
- Environment/feature flags (configurable via `.env` and surfaced in the Advanced options expander):
  - THROUGHPUT_MODE: skips OCR/table extraction and uses regex-only PII for maximum speed
  - OCR_MAX_IMAGES_PER_DOC: caps OCR work per document (default 10 images)
  - OCR_RENDER_SCALE: PyMuPDF render scale for OCR crops (default 1.25)
  - VERBOSE_LOGGING: enables additional console logs for debugging
  - MAX_WORKERS: upper bound for the ProcessPool worker count (defaults to `os.cpu_count()` or 4)

Streamlit UI defaults (app.py)
- OCR default: ON (checkbox)
- Size limits: MAX_FILE_SIZE_MB=20, MAX_BATCH_SIZE_MB=100

To change defaults, edit config.py or app.py and rebuild/redeploy.

---

## Usage Guide
- Anonymize
  - Replaces configured terms (case-insensitive) across document content
- Remove PII
  - Applies regex removal plus spaCy NER for PERSON/ORG/GPE entities
  - spaCy model: en_core_web_sm (installed at Docker build)
- Extract to JSON
  - Outputs a structured JSON containing text, tables, and image metadata
  - Small images may include base64 thumbnails
- PDF Outputs
  - TXT becomes a PDF (content rendered via ReportLab)
  - DOCX/PDF produces a processed PDF attempting to preserve layout
- OCR
  - When ON, OCR is applied to images extracted from DOCX/PDF (subject to timeout)
  - Use only when needed to save CPU cycles
- Advanced options
  - Enable throughput mode to skip OCR/tables and favor regex-only PII
  - Toggle verbose logging for debugging
  - Inspect the new Processing Details expander to see timing metrics for the first processed file

---

## Performance & Sizing
- Batch size: 10 files (UI-enforced)
- File size limits: 20MB per file, 100MB per batch (UI-enforced)
- OCR is CPU-intensive: disable via checkbox if not needed
- PyMuPDF single-pass extraction clips headers/footers via PDF_HEADER_RATIO
- Per-worker LRU caching (MAX_CACHE_ITEMS) skips duplicate documents within a session
- Container resources: Ensure adequate CPU/RAM for large batches or OCR-heavy workloads
- The ProcessPool worker count defaults to `min(uploaded_files, MAX_WORKERS)` so that batches saturate available CPU

---

## Performance Tips
- Disable OCR (or enable throughput mode) for text-heavy batches to skip expensive image work and Camelot table extraction.
- Keep MAX_WORKERS in sync with available CPU cores; the UI shows how many workers are available for the current deployment.
- Use the Processing Details expander to inspect timing per stage and identify bottlenecks on representative files.
- Verbose logging is helpful during debugging sessions but should stay off during regular runs to limit console noise.
- Throughput mode also switches PII removal to regex-only; rely on it for bulk backlogs once accuracy has been validated.

---

## Security & Privacy
- No server-side persistence: files are processed in memory for the session and then offered for download
- PII handling:
  - Regex-based and NER-based redaction may not catch 100% of edge cases
  - Validate outputs for your domain and compliance needs (e.g., HIPAA, GDPR)
- Dependencies include PaddleOCR, Ghostscript (for Camelot), and Python libraries; keep them updated via image rebuilds
- If exposing publicly, consider reverse proxy (TLS), auth, network policies, and resource limits

---

## Troubleshooting
- Camelot errors
  - Ensure Ghostscript and python3-tk are installed in the container/host
- PaddleOCR import errors
  - Confirm paddlepaddle and paddleocr are installed; in containers rebuild the image to pull the deps
- Mixed results on PDFs
  - Tweak PDF_HEADER_RATIO in config.py
  - Try disabling OCR to isolate issues
- Large/complex documents are slow
  - Reduce batch size; disable OCR; allocate more CPU/RAM

---

## Development
- Run locally with a venv (optional)
```
python -m venv .venv
source .venv/bin/activate
pip install -r app/requirements.txt
streamlit run app/app.py
```
- Code layout:
  - app/app.py: UI & workflow
  - app/document_processor.py: processing core
  - app/config.py: configuration
- Style/testing: Add your preferred linters/tests; a small test suite around anonymize/PII/JSON output is recommended for CI

---

## Directory Structure
```
.
├── docker-compose.yml
├── README.md (this file)
└── app/
    ├── app.py
    ├── config.py
    ├── document_processor.py
    ├── Dockerfile
    ├── README.md (legacy UI README; root README is canonical)
    └── requirements.txt
```

---

## Roadmap & Extensibility
- Optional FastAPI gateway (if a programmatic API is needed) importing the same processor
- Multi-language OCR/NER (add models and languages)
- Pluggable PII detectors (domain-specific)
- Additional output formats (CSV, HTML summaries)

---

## License
Specify your license terms here (e.g., MIT, Apache 2.0), if applicable.

---

For questions or requests, please open an issue or PR.
