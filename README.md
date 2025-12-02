<p align="center">
  <h1 align="center">🛡️ DocGuard</h1>
  <p align="center">
    <strong>Enterprise Document Processing & Privacy Protection Platform</strong>
  </p>
</p>

<p align="center">
  <a href="#"><img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="Python Version" /></a>
  <a href="#"><img src="https://img.shields.io/badge/streamlit-1.50.0-FF4B4B.svg" alt="Streamlit" /></a>
  <a href="#"><img src="https://img.shields.io/badge/docker-ready-2496ED.svg" alt="Docker" /></a>
  <a href="#"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License" /></a>
</p>

<p align="center">
  <em>Production-grade document processing with anonymization, PII removal, JSON extraction, and OCR capabilities</em>
</p>

---

## 📋 Table of Contents

- [Overview](#-overview)
- [Key Features](#-key-features)
- [Quick Start](#-quick-start)
- [Architecture](#-architecture)
- [Installation](#-installation)
  - [Docker Deployment (Recommended)](#docker-deployment-recommended)
  - [Local Development](#local-development)
- [Configuration](#-configuration)
- [Usage Guide](#-usage-guide)
- [API & Integration](#-api--integration)
- [Performance & Optimization](#-performance--optimization)
- [Security & Compliance](#-security--compliance)
- [Compatibility & Testing](#-compatibility--testing)
- [Monitoring & Observability](#-monitoring--observability)
- [Troubleshooting](#-troubleshooting)
- [Development](#-development)
- [Deployment](#-deployment)
- [Contributing](#-contributing)
- [Roadmap](#-roadmap)
- [Support](#-support)
- [License](#-license)

---

## 🎯 Overview

**DocGuard** is a production-ready, enterprise-grade document processing platform built with Streamlit that enables secure batch processing of sensitive documents. Designed for organizations requiring robust privacy controls, it provides automated anonymization, PII (Personally Identifiable Information) detection and removal, structured data extraction, and OCR capabilities across multiple document formats.

### Problem Statement

Organizations across healthcare, finance, legal, and government sectors face critical challenges:
- **Privacy Compliance**: GDPR, HIPAA, SOC 2 requirements for handling sensitive documents
- **Data Extraction**: Need for structured data from unstructured document sources
- **Scale**: Processing large document batches efficiently
- **Security**: Ensuring sensitive information doesn't leak through document sharing

### Solution

DocGuard provides a self-contained, containerized solution that:
- Processes documents locally without external API calls
- Applies configurable anonymization and PII removal
- Extracts structured JSON representations for downstream processing
- Supports batch operations with parallel processing
- Offers optional OCR for scanned documents and images
- Maintains audit trails and processing metadata

### Design Philosophy

- **Simplicity**: Single service architecture with minimal moving parts
- **Robustness**: Predictable behavior, clear error handling, explicit resource limits
- **Adaptability**: Environment-driven configuration, UI toggles, containerized dependencies
- **Privacy-First**: No external API calls, in-memory processing, no server-side persistence
- **Zero Code Duplication**: Reusable components, consistent patterns throughout

---

## ✨ Key Features

### Core Capabilities

| Feature | Description |
|---------|-------------|
| **Multi-Format Support** | Process `.txt`, `.docx`, and `.pdf` files seamlessly |
| **Batch Processing** | Handle up to 10 files per batch with configurable limits (20MB/file, 100MB/batch) |
| **Parallel Execution** | Leverage `ProcessPoolExecutor` for concurrent document processing |
| **Anonymization** | Replace configured sensitive terms (case-insensitive) across document content |
| **PII Removal** | Regex + spaCy NER detection for emails, phones, SSN, credit cards, IBAN, PERSON/ORG/GPE entities |
| **JSON Extraction** | Structured output with metadata, text content, tables, and image information |
| **OCR Support** | PaddleOCR-based text recognition with intelligent heuristics and per-document limits |
| **Table Detection** | PyMuPDF-powered table extraction with header/footer clipping |
| **In-Session Caching** | LRU cache prevents re-processing of duplicate documents |
| **PDF Generation** | Output processed documents as PDFs with layout preservation |
| **Live Progress Tracking** | Per-file status updates during batch processing |

### Advanced Features

- **Throughput Mode**: Skip OCR/table extraction, use regex-only PII for maximum speed
- **Verbose Logging**: Detailed console output for debugging and troubleshooting
- **Processing Metrics**: Timing details and performance breakdown per file
- **Selective OCR**: Heuristics-based image filtering to skip low-value content
- **Header/Footer Clipping**: Configurable PDF extraction regions to exclude boilerplate
- **Base64 Thumbnails**: Optional image previews in JSON output
- **Single-Pass PDF Extraction**: Efficient PyMuPDF text/table/image extraction
- **Environment Configuration**: `.env` file support for deployment-specific settings

---

## 🚀 Quick Start

Get up and running in under 5 minutes with Docker:

```bash
# Clone the repository
git clone https://github.com/nowusman/DocGuard.git
cd DocGuard

# Start the application
docker-compose up -d

# Access the web interface
open http://localhost:8501
```

### Basic Workflow

1. **Upload Documents**: Select up to 10 files (`.txt`, `.docx`, `.pdf`)
2. **Choose Operations**: 
   - ✅ Anonymize sensitive terms
   - ✅ Remove PII
   - ✅ Extract to JSON
3. **Configure OCR**: Toggle OCR on/off (enabled by default)
4. **Process**: Click "Process Documents" and monitor progress
5. **Review**: Examine summary and JSON preview
6. **Download**: Get results as ZIP or individual files

---

## 🏗️ Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      Streamlit UI (Port 8501)               │
│                         (app/app.py)                        │
└───────────────┬─────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────┐
│              DocumentProcessor (In-Process)                 │
│               (app/document_processor.py)                   │
│                                                             │
│  ┌──────────────┐  ┌───────────────┐  ┌─────────────────┐   │
│  │   Parsing    │  │  PII Removal  │  │   PDF Output    │   │
│  │ python-docx  │  │ Regex + spaCy │  │   ReportLab     │   │
│  │   PyMuPDF    │  │               │  │                 │   │
│  └──────────────┘  └───────────────┘  └─────────────────┘   │
│                                                             │
│  ┌──────────────┐  ┌────────────────┐ ┌─────────────────┐   │
│  │   OCR (Opt)  │  │Table Extraction│ │    Caching      │   │
│  │  PaddleOCR   │  │   PyMuPDF      │ │  LRU (in-mem)   │   │
│  └──────────────┘  └────────────────┘ └─────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────┐
│                    Configuration Layer                      │
│                      (app/config.py)                        │
│                                                             │
│  • Runtime UI options  • PII_PATTERNS    • OCR_CONFIG       │
│  • PDF_HEADER_RATIO    • JSON_SCHEMA     • Feature Flags    │
└─────────────────────────────────────────────────────────────┘
```

### Component Details

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Frontend** | Streamlit 1.50.0 | Web UI, file upload, progress tracking, results display |
| **Processing Core** | Python 3.12 | Document parsing, transformation, output generation |
| **PDF Engine** | PyMuPDF (fitz) | Text/table/image extraction, single-pass processing |
| **Word Processing** | python-docx | DOCX parsing and content extraction |
| **OCR Engine** | PaddleOCR + PaddlePaddle | Optical character recognition for images |
| **NER/PII** | spaCy (en_core_web_sm) | Named entity recognition for advanced PII detection |
| **PDF Generation** | ReportLab | PDF creation and layout rendering |
| **Parallelization** | ProcessPoolExecutor | Multi-core batch processing |
| **Caching** | OrderedDict (LRU) | In-memory duplicate detection |

### Data Flow

```
Document Upload → Validation → Parallel Processing → Aggregation → Download
                      │              │
                      │              ├─> Parse (format-specific)
                      │              ├─> Anonymize (optional)
                      │              ├─> PII Removal (optional)
                      │              ├─> OCR (optional)
                      │              ├─> Table Extraction
                      │              ├─> JSON Generation (optional)
                      │              └─> PDF Output
                      │
                      └─> Size Limits (20MB/file, 100MB/batch, 10 files)
```

### No External Dependencies

- **No Database**: All processing in-memory
- **No External APIs**: Self-contained processing
- **No Backend Services**: Single Streamlit application
- **No Data Persistence**: Files processed and delivered per session

---

## 📦 Installation

### Prerequisites

- **Docker** (recommended) and Docker Compose 3.9+
- **OR** Python 3.12+ for local development
- **System Libraries** (for local installs): `libgl1`, `libglib2.0-0`

### Docker Deployment (Recommended)

#### Option 1: Docker Compose (Easiest)

```bash
# Clone repository
git clone https://github.com/nowusman/DocGuard.git
cd DocGuard

# Start services
docker-compose up -d

# View logs
docker-compose logs -f frontend

# Access application
# http://localhost:8501
```

#### Option 2: Docker Build & Run

```bash
cd app

# Build image
docker build -t docguard:latest /app

# Run container
docker run -d \
  -p 8501:8501 \
  --name docguard \
  --restart unless-stopped \
  docguard:latest

# View logs
docker logs -f docguard
```

#### Docker Configuration

The `docker-compose.yml` configuration:

```yaml
version: "3.9"

services:
  frontend:
    build:
      context: ./app
    container_name: docguard-frontend
    ports:
      - "8501:8501"
    restart: unless-stopped
    # Optional: Mount .env for configuration
    # volumes:
    #   - ./.env:/app/.env:ro
    # Optional: Resource limits
    # deploy:
    #   resources:
    #     limits:
    #       cpus: '4.0'
    #       memory: 8G

networks:
  default:
    name: docguard-net
```

### Local Development

#### System Dependencies (Ubuntu/Debian)

```bash
sudo apt update
sudo apt install -y libgl1 libglib2.0-0
```

#### Python Setup

```bash
# Clone repository
git clone https://github.com/nowusman/DocGuard.git
cd DocGuard/app

# Create virtual environment
python3.12 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Download spaCy model
python -m spacy download en_core_web_sm

# Run application
streamlit run app.py
```

#### Environment Configuration

Create a `.env` file in the project root:

```bash
# Performance Tuning
THROUGHPUT_MODE=false          # Skip OCR/tables for maximum speed
OCR_MAX_IMAGES_PER_DOC=10     # Max images to OCR per document
OCR_RENDER_SCALE=1.25          # PDF render scale for OCR (lower = faster)
MAX_WORKERS=4                   # Parallel processing workers
MAX_CACHE_ITEMS=64              # LRU cache size (0 to disable)

# Debugging
VERBOSE_LOGGING=false           # Enable detailed console output
```

---

## ⚙️ Configuration

### Configuration Files

| File | Purpose |
|------|---------|
| `app/config.py` | Core configuration: PII patterns, OCR settings, limits, feature flags |
| `.env` | Runtime overrides for feature flags and performance tuning |
| `app/.streamlit/config.toml` | Streamlit-specific UI configuration |

### Key Configuration Options

#### PII Patterns (`config.py`)

```python
PII_PATTERNS = {
    'email': re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
    'phone': re.compile(r'\b(\+\d{1,2}\s?)?1?\-?\.?\s?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b'),
    'ssn': re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),
    'credit_card': re.compile(r'\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b'),
    'iban': re.compile(r'\b[A-Z]{2}\d{2}[\s\-]?[A-Z\d]{4}[\s\-]?[A-Z\d]{4}[\s\-]?[A-Z\d]{4}[\s\-]?[A-Z\d]{1,4}\b')
}
```

#### OCR Configuration (`config.py`)

```python
OCR_CONFIG = {
    'enabled': True,              # Default OCR state (UI toggle overrides)
    'languages': ['eng'],         # OCR languages
    'timeout': 30                  # Seconds per image
}

# Runtime overrides (.env)
OCR_MAX_IMAGES_PER_DOC = 10      # Cap OCR work per document
OCR_RENDER_SCALE = 1.25           # Balance quality vs performance
```

#### File Limits (`config.py`)

```python
MAX_FILE_SIZE_MB = 20            # Per-file upload limit
MAX_BATCH_SIZE_MB = 100          # Total batch size limit
MAX_FILES = 10                    # Maximum files per batch
PDF_HEADER_RATIO = 0.08          # Skip top/bottom 8% of PDF pages
```

### Runtime Feature Flags (`.env`)

| Flag | Default | Description |
|------|---------|-------------|
| `THROUGHPUT_MODE` | `false` | Skip OCR/tables, regex-only PII for max speed |
| `OCR_MAX_IMAGES_PER_DOC` | `10` | Limit OCR images per document |
| `OCR_RENDER_SCALE` | `1.25` | PDF render scale (lower = faster, less accurate) |
| `VERBOSE_LOGGING` | `false` | Enable detailed debug logging |
| `MAX_WORKERS` | `os.cpu_count()` | Parallel processing worker count |
| `MAX_CACHE_ITEMS` | `64` | LRU cache size (0 = disabled) |

---

## 📖 Usage Guide

### Processing Operations

#### 1. Anonymization

Configured at runtime in the UI under **⚙️ Anonymization Settings**. Terms are case-insensitive; duplicates are removed; empty replacement turns into a single space.

**Example:**
- Input: `"CompanyName released ProjectCode in 2024"`
- Output: `"  released   in 2024"` (with blank replacement) or custom replacement text

#### 2. PII Removal

Two-stage approach:
1. **Regex-based**: Detects emails, phones, SSNs, credit cards, IBANs
2. **spaCy NER** (when not in throughput mode): Identifies PERSON, ORG, GPE entities

**Example:**
- Input: `"Contact john.doe@example.com or call 555-123-4567"`
- Output: `"Contact [REDACTED] or call [REDACTED]"`

#### 3. JSON Extraction

Outputs structured JSON with:

```json
{
  "document_metadata": {
    "filename": "document.pdf",
    "file_type": "pdf",
    "processing_date": "2024-12-01T10:30:00",
    "file_size": 1048576
  },
  "content": {
    "text": "Extracted text content...",
    "tables": [
      {
        "page": 1,
        "bbox": [x0, y0, x1, y1],
        "data": [[...]]
      }
    ],
    "images": [
      {
        "page": 1,
        "bbox": [x0, y0, x1, y1],
        "width": 800,
        "height": 600,
        "ocr_text": "Text from OCR...",
        "thumbnail": "data:image/png;base64,..." 
      }
    ]
  },
  "processing_info": {
    "anonymized": true,
    "pii_removed": true,
    "extracted_to_json": true,
    "timing": {
      "parse": 0.5,
      "anonymize": 0.1,
      "pii_removal": 0.3,
      "ocr": 2.5,
      "total": 3.4
    }
  }
}
```

### Advanced Options

#### Throughput Mode

Enable for maximum processing speed:

- **Skips**: OCR, table extraction
- **Uses**: Regex-only PII (no spaCy NER)
- **Best for**: Text-heavy batches, bulk backlogs
- **Speed gain**: 5-10x on mixed document sets

```bash
# In .env
THROUGHPUT_MODE=true
```

Or toggle via UI "Advanced options" expander.

#### Processing Details

View timing breakdown for the first processed file:

- Parse time
- Anonymization time
- PII removal time
- OCR time (if enabled)
- Table extraction time
- Total processing time

Access via "Processing Details" expander in UI after batch completion.

### PDF Output Behavior

| Input Format | Output PDF |
|--------------|-----------|
| **TXT** | Re-rendered as PDF via ReportLab |
| **DOCX** | Converted to PDF with layout preservation attempt |
| **PDF** | Modified PDF with anonymization/PII applied |

---

## 🔌 API & Integration

### Programmatic Usage

While DocGuard is primarily a Streamlit UI application, the processing core can be imported for programmatic use:

```python
from document_processor import DocumentProcessor

processor = DocumentProcessor()

# Process a single file
result = processor.process_document(
    file_bytes=open('document.pdf', 'rb').read(),
    filename='document.pdf',
    operations={
        'anonymize': True,
        'remove_pii': True,
        'extract_json': True
    },
    enable_ocr=True
)

# Access results
pdf_output = result['pdf_bytes']
json_output = result['json_data']
metadata = result['metadata']
```

### Batch Processing

```python
from concurrent.futures import ProcessPoolExecutor

files = [
    ('doc1.pdf', open('doc1.pdf', 'rb').read()),
    ('doc2.docx', open('doc2.docx', 'rb').read()),
]

with ProcessPoolExecutor(max_workers=4) as executor:
    futures = [
        executor.submit(processor.process_document, content, name, {...})
        for name, content in files
    ]
    results = [f.result() for f in futures]
```

### REST API (Future Roadmap)

A FastAPI gateway is planned for programmatic access:

```bash
# Planned endpoints
POST /api/v1/process     # Process documents
GET  /api/v1/health      # Health check
GET  /api/v1/config      # Configuration info
```

---

## ⚡ Performance & Optimization

### Performance Characteristics

| Metric | Value | Notes |
|--------|-------|-------|
| **Throughput** | 2-8x with parallelism | CPU-bound, scales with cores |
| **File Size Limits** | 20MB/file, 100MB/batch | Configurable in `config.py` |
| **Batch Size** | 10 files maximum | UI-enforced constraint |
| **OCR Performance** | 3-10x faster with selective OCR | Heuristics skip low-value images |
| **PDF Extraction** | 2-10x faster (single-pass) | PyMuPDF consolidation |
| **Cache Hit Rate** | Near-instant for duplicates | LRU cache per worker |
| **Memory Usage** | ~500MB-2GB | Depends on batch size and OCR |

### Optimization Strategies

#### 1. Disable OCR When Not Needed

```bash
# In UI: Uncheck "Enable OCR" checkbox
# Or via .env:
THROUGHPUT_MODE=true  # Disables OCR entirely
```

**Impact**: 5-10x speed improvement on text-rich documents

#### 2. Tune Worker Count

```bash
# .env
MAX_WORKERS=8  # Match available CPU cores
```

**Guideline**: Set to `os.cpu_count()` for CPU-bound workloads

#### 3. Adjust OCR Settings

```bash
# .env
OCR_MAX_IMAGES_PER_DOC=5     # Reduce for faster processing
OCR_RENDER_SCALE=1.0          # Lower resolution = faster
```

**Trade-off**: Speed vs. OCR accuracy

#### 4. Enable Throughput Mode

```bash
# .env
THROUGHPUT_MODE=true
```

**Disables**:
- OCR processing
- Table extraction
- spaCy NER (uses regex-only PII)

**Best for**: Bulk text processing where accuracy is validated

#### 5. Leverage Caching

```bash
# .env
MAX_CACHE_ITEMS=128  # Increase for more duplicate detection
```

**Impact**: Near-instant processing for duplicate uploads

### Resource Recommendations

| Deployment | CPUs | RAM | Use Case |
|------------|------|-----|----------|
| **Development** | 2 cores | 4GB | Testing, light workloads |
| **Small Team** | 4 cores | 8GB | 10-50 docs/day |
| **Production** | 8+ cores | 16GB+ | 100+ docs/day, OCR-heavy |
| **High-Volume** | 16+ cores | 32GB+ | 1000+ docs/day, real-time |

### Bottleneck Identification

Use "Processing Details" expander to identify bottlenecks:

```
Processing Details (doc1.pdf):
- Parse: 0.2s
- Anonymize: 0.1s
- PII Removal: 0.3s
- OCR: 5.2s ← BOTTLENECK
- Tables: 0.4s
- Total: 6.2s
```

**Action**: Reduce `OCR_MAX_IMAGES_PER_DOC` or enable `THROUGHPUT_MODE`

---

## 🔒 Security & Compliance

### Security Features

#### Data Privacy

- ✅ **No External API Calls**: All processing happens locally
- ✅ **No Server Persistence**: Files processed in-memory only
- ✅ **Session Isolation**: No cross-session data leakage
- ✅ **Temporary File Cleanup**: Automatic cleanup of intermediate artifacts
- ✅ **In-Memory Processing**: Minimal disk I/O

#### PII Protection

- ✅ **Multi-Layer Detection**: Regex + spaCy NER
- ✅ **Configurable Patterns**: Extend PII detection per domain
- ✅ **Audit Trail**: Processing metadata tracks operations applied
- ⚠️ **Accuracy Disclaimer**: Not 100% guaranteed - validate outputs

#### Container Security

```dockerfile
# Minimal attack surface
FROM python:3.12-slim

# Non-root execution (recommended)
RUN useradd -m -u 1000 appuser
USER appuser

# Read-only filesystem (recommended)
# Add to docker-compose.yml:
# read_only: true
# tmpfs:
#   - /tmp
```

### Compliance Considerations

#### GDPR Compliance

| Requirement | Status | Implementation |
|-------------|--------|----------------|
| **Data Minimization** | ✅ | No persistent storage |
| **Right to Erasure** | ✅ | Session-only processing |
| **Data Portability** | ✅ | JSON/PDF export |
| **Transparency** | ✅ | Processing metadata |
| **Security** | ⚠️ | TLS recommended for public deployment |

#### HIPAA Considerations

| Requirement | Status | Notes |
|-------------|--------|-------|
| **Access Controls** | ⚠️ | Add authentication layer for production |
| **Audit Logs** | ⚠️ | Implement application logging |
| **Encryption at Rest** | ✅ | No data persisted |
| **Encryption in Transit** | ⚠️ | Add TLS/HTTPS reverse proxy |
| **PHI Redaction** | ✅ | PII removal capabilities |

**Recommendation**: For HIPAA compliance, add:
1. Authentication (OAuth2, SAML)
2. HTTPS/TLS termination
3. Audit logging to immutable storage
4. Network isolation

### Security Best Practices

#### Production Deployment

```yaml
# docker-compose.yml
services:
  frontend:
    build: ./app
    read_only: true              # Read-only root filesystem
    security_opt:
      - no-new-privileges:true    # Prevent privilege escalation
    cap_drop:
      - ALL                       # Drop all capabilities
    tmpfs:
      - /tmp:noexec,nosuid        # Temp storage for processing
    networks:
      - internal                  # Isolated network
```

#### Reverse Proxy (HTTPS)

```nginx
# nginx.conf
server {
    listen 443 ssl http2;
    server_name docguard.example.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://localhost:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```

#### Authentication Integration

```python
# Add to app.py for production
import streamlit_authenticator as stauth

authenticator = stauth.Authenticate(
    credentials,
    'cookie_name',
    'signature_key',
    cookie_expiry_days=30
)

name, authentication_status, username = authenticator.login('Login', 'main')

if not authentication_status:
    st.stop()
```

### Known Limitations

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| **PII Detection Not Perfect** | May miss edge cases | Manual review of critical documents |
| **No Authentication Built-in** | Open access in default setup | Add auth layer for production |
| **Single Node Only** | No horizontal scaling | Deploy multiple instances behind load balancer |
| **No Persistent Audit Trail** | Cannot track historical processing | Add external logging/SIEM |
| **OCR Language Support** | English-only by default | Add additional PaddleOCR language packs |

---

## ✅ Compatibility & Testing

### Browser Compatibility

| Browser | Version | Status | Notes |
|---------|---------|--------|-------|
| **Chrome** | 90+ | ✅ Fully Supported | Recommended |
| **Firefox** | 88+ | ✅ Fully Supported | |
| **Safari** | 14+ | ✅ Supported | Some CSS variations |
| **Edge** | 90+ | ✅ Fully Supported | Chromium-based |
| **Mobile Safari** | iOS 14+ | ⚠️ Limited | File upload constraints |
| **Chrome Mobile** | Android 10+ | ⚠️ Limited | Touch optimization needed |

### Streamlit Compatibility

- **Tested Versions**: 1.48.0 - 1.50.0
- **Recommended**: 1.50.0
- **CSS Scoping**: Uses stable `.stApp` and `data-testid` selectors
- **Custom Fonts**: Loaded via `<link>` for optimal performance
- **HTML Rendering**: `unsafe_allow_html=True` used only for static markup

**Note**: CSS styling is scoped to minimize breakage across Streamlit versions. However, major Streamlit updates may require CSS adjustments.

### Testing Checklist

#### Functional Testing

- [ ] Upload exactly `MAX_FILES` (10) documents
- [ ] Upload single file at `MAX_FILE_SIZE_MB` limit (20MB)
- [ ] Upload batch at `MAX_BATCH_SIZE_MB` limit (100MB)
- [ ] Test mixed formats: `.txt`, `.docx`, `.pdf` in single batch
- [ ] Verify anonymization with configured terms
- [ ] Verify PII removal (emails, phones, SSNs, credit cards, IBANs)
- [ ] Verify JSON extraction output structure
- [ ] Verify OCR toggle persists across UI interactions
- [ ] Test throughput mode via Advanced options
- [ ] Verify processing details timing display
- [ ] Test ZIP download with all processed files
- [ ] Test individual file downloads

#### Edge Cases

- [ ] Empty files (0 bytes)
- [ ] Corrupted PDF/DOCX files
- [ ] Password-protected PDFs
- [ ] PDFs with no extractable text (scanned images)
- [ ] DOCX with complex tables and images
- [ ] Unicode/non-ASCII characters
- [ ] Very long filenames (>255 chars)
- [ ] Duplicate file uploads in same batch

#### Performance Testing

- [ ] 10-file batch with OCR enabled
- [ ] 10-file batch with OCR disabled
- [ ] Throughput mode vs standard mode comparison
- [ ] Cache hit detection for duplicate uploads
- [ ] Memory usage under max load
- [ ] Concurrent user sessions (Streamlit multi-user)

#### Security Testing

- [ ] HTML injection attempts in filenames
- [ ] Script injection in document content
- [ ] Path traversal attempts
- [ ] Oversized file upload attempts
- [ ] Rapid request flooding

### Platform Support

| Platform | Status | Notes |
|----------|--------|-------|
| **Linux (Ubuntu 20.04+)** | ✅ Fully Supported | Primary development platform |
| **Linux (Debian 11+)** | ✅ Fully Supported | Docker base image |
| **macOS** | ✅ Supported | System libs may vary |
| **Windows** | ⚠️ Limited | WSL2 recommended for development |
| **Docker** | ✅ Fully Supported | Recommended deployment |

---

## 📊 Monitoring & Observability

### Logging

#### Log Levels

```bash
# Enable verbose logging
VERBOSE_LOGGING=true
```

**Default Logging**:
- ℹ️ INFO: Processing start/completion, file counts
- ⚠️ WARNING: File size warnings, OCR timeouts
- ❌ ERROR: Processing failures, invalid formats

**Verbose Logging** (adds):
- 🔍 DEBUG: Per-stage timing, cache hits, intermediate results

#### Log Format

```
[2024-12-01 10:30:45] INFO: Processing batch of 5 files
[2024-12-01 10:30:45] DEBUG: Worker pool initialized with 4 workers
[2024-12-01 10:30:46] INFO: document.pdf - Completed (3.2s)
[2024-12-01 10:30:47] WARNING: large_file.pdf - Size 18MB near limit
[2024-12-01 10:30:50] INFO: Batch processing completed (5.1s total)
```

### Metrics

#### Built-in Metrics (UI)

- **Processing Summary**: File count, success/failure rates
- **Processing Details**: Per-stage timing for first file
- **Worker Info**: Available parallelism (`MAX_WORKERS`)
- **Configuration**: Active feature flags, limits

#### External Monitoring (Recommended)

```python
# Add to document_processor.py for production
import prometheus_client as prom

processing_duration = prom.Histogram(
    'docguard_processing_duration_seconds',
    'Document processing duration'
)

processing_total = prom.Counter(
    'docguard_processing_total',
    'Total documents processed',
    ['status', 'file_type']
)

@processing_duration.time()
def process_document(...):
    # Existing logic
    processing_total.labels(status='success', file_type=ext).inc()
```

### Health Checks

#### Docker Health Check

```yaml
# docker-compose.yml
services:
  frontend:
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8501/_stcore/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

#### Application Monitoring

```bash
# Check if Streamlit is responsive
curl -f http://localhost:8501/_stcore/health

# Check container health
docker inspect --format='{{.State.Health.Status}}' docguard-frontend
```

### Troubleshooting Tools

```bash
# View real-time logs
docker-compose logs -f frontend

# Check resource usage
docker stats docguard-frontend

# Inspect running processes
docker exec docguard-frontend ps aux

# Check Python packages
docker exec docguard-frontend pip list
```

---

## 🔧 Troubleshooting

### Common Issues

#### 1. PaddleOCR Import Errors

**Symptoms**:
```
ImportError: libGL.so.1: cannot open shared object file
```

**Solution**:
```bash
# Ubuntu/Debian
sudo apt update
sudo apt install -y libgl1 libglib2.0-0

# Docker: Ensure Dockerfile includes
RUN apt-get update && apt-get install -y libgl1 libglib2.0-0
```

#### 2. Slow OCR Processing

**Symptoms**: Long processing times on PDF-heavy batches

**Solutions**:
```bash
# Option 1: Disable OCR via UI checkbox
# Option 2: Enable throughput mode
THROUGHPUT_MODE=true

# Option 3: Reduce OCR workload
OCR_MAX_IMAGES_PER_DOC=5
OCR_RENDER_SCALE=1.0
```

#### 3. PDF Extraction Issues

**Symptoms**: Missing text, incorrect table extraction

**Solutions**:
```python
# Adjust header/footer ratio in config.py
PDF_HEADER_RATIO = 0.10  # Skip more of page top/bottom

# Try different render scale
OCR_RENDER_SCALE = 1.5  # Higher quality for OCR
```

#### 4. Memory Issues

**Symptoms**: Container OOM kills, slow performance

**Solutions**:
```yaml
# docker-compose.yml - Add resource limits
deploy:
  resources:
    limits:
      memory: 8G
    reservations:
      memory: 4G

# Or reduce batch processing
MAX_WORKERS=2  # Fewer parallel workers
MAX_CACHE_ITEMS=32  # Smaller cache
```

#### 5. spaCy Model Not Found

**Symptoms**:
```
OSError: [E050] Can't find model 'en_core_web_sm'
```

**Solution**:
```bash
# Install spaCy model
python -m spacy download en_core_web_sm

# Docker: Ensure Dockerfile includes
RUN python -m spacy download en_core_web_sm
```

#### 6. File Upload Limits

**Symptoms**: "File too large" errors

**Solutions**:
```python
# Adjust in config.py
MAX_FILE_SIZE_MB = 50      # Increase per-file limit
MAX_BATCH_SIZE_MB = 200    # Increase batch limit
MAX_FILES = 20             # Allow more files
```

**Note**: Larger limits require more memory and processing time.

#### 7. Streamlit Connection Errors

**Symptoms**: "Connection lost" or websocket errors

**Solutions**:
```toml
# app/.streamlit/config.toml
[server]
enableCORS = false
enableXsrfProtection = true
maxUploadSize = 200

[browser]
gatherUsageStats = false
```

### Debug Mode

Enable comprehensive debugging:

```bash
# .env
VERBOSE_LOGGING=true

# Run with full output
docker-compose up  # Without -d flag
```

### Getting Help

1. **Check Logs**: `docker-compose logs -f frontend`
2. **Review Configuration**: Verify `.env` and `config.py` settings
3. **Test Isolation**: Try single file processing to isolate issues
4. **Resource Check**: Ensure adequate CPU/RAM allocation
5. **Version Check**: Confirm compatible dependency versions

---

## 👨‍💻 Development

### Project Structure

```
DocGuard/
├── README.md                    # This file (primary documentation)
├── docker-compose.yml          # Container orchestration
├── .env.example                # Environment variable template
├── .gitignore                  # Git exclusions
└── app/
    ├── app.py                  # Streamlit UI application
    ├── document_processor.py   # Core processing logic
    ├── config.py               # Configuration management
    ├── requirements.txt        # Python dependencies
    ├── app/Dockerfile              # Container build instructions
    ├── app/.dockerignore           # Docker build exclusions
    ├── styles.css              # Custom UI styling
    └── .streamlit/
        └── config.toml         # Streamlit configuration
```

### Development Setup

```bash
# Clone repository
git clone https://github.com/nowusman/DocGuard.git
cd DocGuard

# Create virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install dependencies
cd app
pip install -r requirements.txt
python -m spacy download en_core_web_sm

# Run development server
streamlit run app.py --server.runOnSave=true
```

### Code Style

```bash
# Install development dependencies
pip install black isort flake8 mypy

# Format code
black app/*.py
isort app/*.py

# Lint
flake8 app/ --max-line-length=120
mypy app/ --ignore-missing-imports
```

### Testing

```bash
# Install test dependencies
pip install pytest pytest-cov

# Run tests
pytest tests/ -v --cov=app

# Test coverage report
pytest --cov=app --cov-report=html
```

### Adding New Features

1. **PII Patterns**: Add to `PII_PATTERNS` in `config.py`
2. **Anonymization Terms**: Configure via the Streamlit UI (⚙️ Anonymization Settings)
3. **OCR Languages**: Add to `OCR_CONFIG['languages']` and install language packs
4. **File Formats**: Extend `supported_formats` in `document_processor.py`
5. **Output Formats**: Modify JSON schema in `JSON_SCHEMA` in `config.py`

### Environment Variables

```bash
# Copy example environment file
cp .env.example .env

# Edit configuration
vim .env
```

---

## 🚢 Deployment

### Production Deployment Checklist

- [ ] Enable HTTPS/TLS via reverse proxy
- [ ] Add authentication layer
- [ ] Configure resource limits in docker-compose.yml
- [ ] Set up monitoring and logging
- [ ] Enable read-only filesystem
- [ ] Configure network isolation
- [ ] Set up automated backups (if storing configs)
- [ ] Document incident response procedures
- [ ] Perform security audit
- [ ] Load testing for expected throughput

### Cloud Deployment

#### AWS ECS

```json
{
  "family": "docguard",
  "containerDefinitions": [{
    "name": "frontend",
    "image": "your-registry/docguard:latest",
    "memory": 8192,
    "cpu": 4096,
    "portMappings": [{
      "containerPort": 8501,
      "protocol": "tcp"
    }],
    "environment": [
      {"name": "MAX_WORKERS", "value": "8"},
      {"name": "THROUGHPUT_MODE", "value": "false"}
    ]
  }]
}
```

#### Kubernetes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: docguard
spec:
  replicas: 3
  selector:
    matchLabels:
      app: docguard
  template:
    metadata:
      labels:
        app: docguard
    spec:
      containers:
      - name: frontend
        image: your-registry/docguard:latest
        ports:
        - containerPort: 8501
        resources:
          requests:
            memory: "4Gi"
            cpu: "2000m"
          limits:
            memory: "8Gi"
            cpu: "4000m"
        env:
        - name: MAX_WORKERS
          value: "8"
        - name: VERBOSE_LOGGING
          value: "false"
---
apiVersion: v1
kind: Service
metadata:
  name: docguard
spec:
  selector:
    app: docguard
  ports:
  - protocol: TCP
    port: 80
    targetPort: 8501
  type: LoadBalancer
```

#### Azure Container Instances

```bash
az container create \
  --resource-group docguard-rg \
  --name docguard \
  --image your-registry/docguard:latest \
  --cpu 4 \
  --memory 8 \
  --ports 8501 \
  --environment-variables \
    MAX_WORKERS=8 \
    THROUGHPUT_MODE=false
```

### On-Premise Deployment

```yaml
# docker-compose.prod.yml
version: "3.9"

services:
  frontend:
    build: ./app
    container_name: docguard-frontend
    ports:
      - "8501:8501"
    restart: always
    read_only: true
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    tmpfs:
      - /tmp:noexec,nosuid,size=2G
    deploy:
      resources:
        limits:
          cpus: '8.0'
          memory: 16G
        reservations:
          cpus: '4.0'
          memory: 8G
    env_file:
      - .env.production
    networks:
      - internal

  nginx:
    image: nginx:alpine
    container_name: docguard-proxy
    ports:
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./ssl:/etc/nginx/ssl:ro
    depends_on:
      - frontend
    networks:
      - internal

networks:
  internal:
    driver: bridge
```

---

## 🤝 Contributing

We welcome contributions! Please follow these guidelines:

### Getting Started

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests and linting
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

### Code Standards

- Follow PEP 8 style guidelines
- Add docstrings to all functions and classes
- Include unit tests for new features
- Update README.md for user-facing changes
- Keep changes focused and atomic

### Pull Request Process

1. Ensure all tests pass
2. Update documentation
3. Add entry to CHANGELOG.md (if exists)
4. Get review from maintainers
5. Address review feedback
6. Merge after approval

---

## 🗺️ Roadmap

### Planned Features

#### Short-Term (Q1 2025)

- [ ] **REST API**: FastAPI gateway for programmatic access
- [ ] **Multi-language OCR**: Support for additional languages (Spanish, French, German)
- [ ] **Advanced PII**: Medical/healthcare-specific PII patterns
- [ ] **Batch API**: Process multiple batches via API
- [ ] **Export Formats**: CSV, HTML, Markdown output options

#### Mid-Term (Q2-Q3 2025)

- [ ] **Authentication**: OAuth2, SAML integration
- [ ] **Audit Logging**: Comprehensive processing trail to external storage
- [ ] **Custom Models**: Bring-your-own spaCy/OCR models
- [ ] **Webhooks**: Notification on batch completion
- [ ] **S3/Blob Storage**: Input/output to cloud storage
- [ ] **GPU Support**: CUDA acceleration for OCR
- [ ] **Multi-tenant**: Organization isolation and user management

#### Long-Term (2025+)

- [ ] **ML-Based PII**: Custom entity recognition models
- [ ] **Document Classification**: Auto-categorization
- [ ] **Redaction Preview**: Visual PDF redaction preview
- [ ] **Workflow Engine**: Multi-stage processing pipelines
- [ ] **Kubernetes Operator**: Native k8s deployment
- [ ] **Horizontal Scaling**: Distributed processing architecture

### Experimental Features

- Real-time document streaming
- Video/audio file support
- Collaborative review workflows
- API rate limiting and quotas
- Plugin architecture for custom processors

---

## 💬 Support

### Community Support

- **GitHub Issues**: [Report bugs or request features](https://github.com/nowusman/DocGuard/issues)
- **GitHub Discussions**: [Ask questions and share ideas](https://github.com/nowusman/DocGuard/discussions)
- **Documentation**: This README and inline code comments

### Commercial Support

For enterprise support, consulting, or custom development:
- Contact: [Open an issue](https://github.com/nowusman/DocGuard/issues) for inquiries
- Response Time: Best effort (community project)

### Security Issues

**Do not** report security vulnerabilities via public GitHub issues.

Please report security issues privately to repository maintainers via GitHub Security Advisories.

---

## 📄 License

This project is licensed under the **MIT License** - see below for details:

```
MIT License

Copyright (c) 2024 DocGuard Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## 🙏 Acknowledgments

### Technologies

- **[Streamlit](https://streamlit.io/)**: Web application framework
- **[PyMuPDF](https://pymupdf.readthedocs.io/)**: PDF processing
- **[PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)**: OCR engine
- **[spaCy](https://spacy.io/)**: NLP and NER
- **[ReportLab](https://www.reportlab.com/)**: PDF generation
- **[python-docx](https://python-docx.readthedocs.io/)**: Word document processing

### Contributors

Thank you to all contributors who have helped improve DocGuard!

---

<p align="center">
  <strong>Built with ❤️ for secure document processing</strong>
</p>

<p align="center">
  <sub>⭐ Star us on GitHub if you find DocGuard useful!</sub>
</p>
