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
- [Configuration](#-configuration)
- [Usage Guide](#-usage-guide)
- [API Reference](#-api-reference)
- [Security & Compliance](#-security--compliance)
- [Performance Optimization](#-performance-optimization)
- [Troubleshooting](#-troubleshooting)
- [Development](#-development)
- [Contributing](#-contributing)
- [License](#-license)

---

## 🎯 Overview

**DocGuard** is an enterprise-grade document processing platform designed for organizations that require robust privacy controls and efficient document handling. Built with Streamlit and powered by advanced NLP and OCR technologies, DocGuard provides automated anonymization, PII detection and removal, structured data extraction, and OCR capabilities across multiple document formats.

### Problem Statement

Organizations across healthcare, finance, legal, and government sectors face critical challenges:

- **Privacy Compliance**: GDPR, HIPAA, SOC 2 requirements for handling sensitive documents
- **Data Extraction**: Need for structured data from unstructured document sources
- **Scale**: Processing large document batches efficiently
- **Security**: Ensuring sensitive information doesn't leak through document sharing

### Solution

DocGuard provides a self-contained, containerized solution that:

- ✅ Processes documents locally without external API calls
- ✅ Applies configurable anonymization and PII removal
- ✅ Extracts structured JSON representations for downstream processing
- ✅ Supports batch operations with parallel processing
- ✅ Offers optional OCR for scanned documents and images
- ✅ Maintains audit trails and processing metadata

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
- **Configurable OCR**: Control image limits, resolution scaling, and language models
- **Resource Management**: CPU thread limits, memory bounds, worker pool configuration
- **Custom Anonymization**: Define domain-specific terms via UI or environment variables

---

## 🚀 Quick Start

### Prerequisites

- Docker & Docker Compose (recommended)
- OR Python 3.12+ with pip

### Docker Deployment (Recommended)

```bash
# Clone the repository
git clone https://github.com/nowusman/DocGuard.git
cd DocGuard

# Start the application
docker-compose up -d

# Access the application
open http://localhost:8501
```

### Local Development

```bash
# Create virtual environment
python3.12 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r app/requirements.txt

# Download spaCy language model
python -m spacy download en_core_web_sm

# Install system dependencies (Linux/macOS)
# Ubuntu/Debian: sudo apt-get install libgl1 libglib2.0-0 ghostscript
# macOS: brew install ghostscript

# Run the application
cd app
streamlit run app.py
```

---

## 🏗️ Architecture

### System Components

```
DocGuard/
├── app/
│   ├── app.py                    # Main Streamlit UI and orchestration
│   ├── document_processor.py    # Core document processing logic
│   ├── worker.py                 # Worker process for parallel execution
│   ├── config.py                 # Configuration and environment variables
│   ├── styles.css                # Custom UI styling
│   ├── requirements.txt          # Python dependencies
│   ├── Dockerfile                # Container image definition
│   └── .streamlit/
│       └── config.toml           # Streamlit configuration
├── docker-compose.yml            # Service orchestration
└── README.md                     # This file
```

### Technology Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| **Frontend** | Streamlit 1.50.0 | Web UI and user interaction |
| **Document Parsing** | PyMuPDF 1.26.4, python-docx 1.2.0 | PDF/DOCX extraction |
| **NLP** | spaCy 3.8.7 (en_core_web_sm) | Named Entity Recognition for PII |
| **OCR** | PaddleOCR 2.9.1, PaddlePaddle 2.6.2 | Optical Character Recognition |
| **Image Processing** | OpenCV 4.9.0, Pillow 11.3.0 | Image manipulation and rendering |
| **PDF Generation** | ReportLab 4.4.4 | PDF output creation |
| **Concurrency** | ProcessPoolExecutor | Parallel document processing |
| **Containerization** | Docker, Docker Compose | Deployment and isolation |

### Processing Flow

```
Upload → Validation → Batch Queue → Parallel Workers → Processing → Output Generation
                                          ↓
                              [Anonymization, PII Removal,
                               Table Extraction, OCR, JSON Export]
```

---

## 📦 Installation

### System Requirements

- **CPU**: 4+ cores recommended (supports multi-core parallelism)
- **RAM**: 8GB minimum, 16GB recommended for large batches
- **Storage**: 1GB for application, additional space for temporary processing
- **OS**: Linux (Ubuntu 20.04+), macOS (11+), Windows 10/11 with WSL2

### Docker Installation

1. **Install Docker**: [Get Docker](https://docs.docker.com/get-docker/)
2. **Install Docker Compose**: [Get Docker Compose](https://docs.docker.com/compose/install/)
3. **Clone and Run**:
   ```bash
   git clone https://github.com/nowusman/DocGuard.git
   cd DocGuard
   docker-compose up -d
   ```

### Manual Installation

1. **Python 3.12+**:
   ```bash
   python --version  # Verify Python 3.12+
   ```

2. **Install Dependencies**:
   ```bash
   cd app
   pip install -r requirements.txt
   python -m spacy download en_core_web_sm
   ```

3. **System Libraries** (Linux):
   ```bash
   sudo apt-get update
   sudo apt-get install -y libgl1 libglib2.0-0 ghostscript
   ```

4. **System Libraries** (macOS):
   ```bash
   brew install ghostscript
   ```

---

## ⚙️ Configuration

### Environment Variables

Create a `.env` file in the project root:

```env
# Performance & Throughput
THROUGHPUT_MODE=false           # Skip OCR/tables for speed
MAX_WORKERS=4                   # Parallel worker processes
VERBOSE_LOGGING=false           # Detailed console output

# OCR Configuration
OCR_MAX_IMAGES_PER_DOC=10       # Max images to OCR per document
OCR_RENDER_SCALE=1.25           # PDF rendering resolution multiplier

# Resource Limits
MAX_CACHE_ITEMS=64              # In-memory document cache size
```

### Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `THROUGHPUT_MODE` | `false` | Disable OCR/table extraction for faster processing |
| `MAX_WORKERS` | CPU count | Number of parallel worker processes |
| `OCR_MAX_IMAGES_PER_DOC` | `10` | Maximum images to process per document |
| `OCR_RENDER_SCALE` | `1.25` | PDF page rendering scale (higher = better quality, slower) |
| `VERBOSE_LOGGING` | `false` | Enable detailed logging output |
| `MAX_CACHE_ITEMS` | `64` | LRU cache size for processed documents |

### Runtime Configuration

The UI provides toggles for:
- **Anonymization**: Enable/disable and configure custom terms
- **PII Removal**: Toggle PII detection and removal
- **JSON Extraction**: Export structured JSON instead of PDF
- **Throughput Mode**: Skip heavy processing for speed
- **Verbose Logging**: Enable detailed logs in real-time

---

## 📖 Usage Guide

### Basic Workflow

1. **Access the Application**: Navigate to `http://localhost:8501`
2. **Upload Documents**: Drag and drop files or click to browse
3. **Configure Processing**:
   - Toggle anonymization, PII removal, JSON extraction
   - Add custom anonymization terms (optional)
   - Enable throughput mode for speed (optional)
4. **Process**: Click "Process Documents"
5. **Download Results**: Download individual files or batch ZIP

### Supported File Formats

- **Text Files**: `.txt` (UTF-8, Latin-1 encoding)
- **Word Documents**: `.docx` (Microsoft Word 2007+)
- **PDF Documents**: `.pdf` (native text, scanned, or hybrid)

### File Size Limits

- **Per File**: 20MB maximum
- **Per Batch**: 100MB total
- **File Count**: 10 files per batch

### Anonymization

Define custom terms to be replaced (case-insensitive):

```
John Doe
Acme Corporation
john.doe@example.com
```

Each term is replaced with `[REDACTED]` in the output.

### PII Detection

Automatically detects and removes:
- **Emails**: `user@domain.com`
- **Phone Numbers**: US/International formats
- **SSN**: `123-45-6789`
- **Credit Cards**: `1234-5678-9012-3456`
- **IBAN**: European bank accounts
- **Named Entities**: PERSON, ORG, GPE (via spaCy NER)

### JSON Output Format

```json
{
  "document_metadata": {
    "filename": "example.pdf",
    "file_type": "pdf",
    "processing_date": "2024-01-15T10:30:00",
    "file_size": 524288
  },
  "content": {
    "text": "Processed document text...",
    "tables": [
      {"page": 1, "data": [...]}
    ],
    "images": [
      {"page": 1, "index": 0, "ocr_text": "..."}
    ]
  },
  "processing_info": {
    "anonymized": true,
    "pii_removed": true,
    "extracted_to_json": true
  }
}
```

---

## 🔌 API Reference

### Core Modules

#### `document_processor.py`

**`process_document(file_bytes, filename, options)`**
- Processes a single document with specified options
- Returns: `(success: bool, result: dict, error_msg: str)`

**`extract_text_from_pdf(pdf_bytes)`**
- Extracts text from PDF using PyMuPDF
- Returns: `str` (extracted text)

**`extract_text_from_docx(docx_bytes)`**
- Extracts text from DOCX using python-docx
- Returns: `str` (extracted text)

**`detect_and_remove_pii(text, use_ner=True)`**
- Detects and removes PII using regex and spaCy
- Returns: `str` (sanitized text)

#### `config.py`

Configuration constants and environment variable loaders:
- `MAX_WORKERS`: Parallel worker count
- `PII_PATTERNS`: Regex patterns for PII detection
- `JSON_SCHEMA`: Output JSON structure
- `OCR_CONFIG`: OCR engine settings

#### `worker.py`

**`_process_file_worker(args)`**
- Worker function for parallel processing
- Designed for use with `ProcessPoolExecutor`

---

## 🔒 Security & Compliance

### Privacy Guarantees

- **No External Calls**: All processing happens locally
- **No Server-Side Storage**: Documents processed in-memory only
- **Session Isolation**: Each user session is independent
- **Secure Defaults**: PII patterns cover common identifiers

### Compliance Features

- **GDPR**: Right to erasure (no persistent storage), data minimization
- **HIPAA**: PHI detection and removal (names, identifiers)
- **SOC 2**: Audit trail via processing metadata, access controls via deployment
- **ISO 27001**: Data classification support, encryption at rest (deployment-dependent)

### Deployment Security

Refer to [deployment.md](deployment.md) for:
- TLS/SSL configuration
- Network isolation
- Access control
- Secrets management
- Monitoring and alerting

---

## ⚡ Performance Optimization

### Throughput Mode

Enable for maximum speed when OCR and table extraction are not required:

```bash
THROUGHPUT_MODE=true
```

**Benefits**:
- 3-5x faster processing
- Lower CPU utilization
- Reduced memory footprint

**Trade-offs**:
- No OCR for scanned documents
- No table extraction
- Regex-only PII detection (no NER)

### Worker Tuning

Adjust `MAX_WORKERS` based on CPU cores and workload:

```bash
# Conservative (memory-constrained)
MAX_WORKERS=2

# Balanced (default)
MAX_WORKERS=4

# Aggressive (high-CPU systems)
MAX_WORKERS=8
```

### OCR Optimization

Control OCR performance vs. quality:

```bash
# Fewer images, faster processing
OCR_MAX_IMAGES_PER_DOC=5

# Higher resolution, better accuracy
OCR_RENDER_SCALE=1.5
```

### Caching

The application uses LRU caching to avoid re-processing identical documents within a session. Adjust cache size:

```bash
MAX_CACHE_ITEMS=128  # Larger cache for repeated documents
```

---

## 🛠️ Troubleshooting

### Common Issues

**Issue**: Application won't start
```bash
# Check Docker status
docker ps

# View logs
docker-compose logs -f

# Rebuild if needed
docker-compose down && docker-compose up --build
```

**Issue**: Out of memory errors
```bash
# Reduce workers
MAX_WORKERS=2

# Reduce OCR images
OCR_MAX_IMAGES_PER_DOC=5

# Enable throughput mode
THROUGHPUT_MODE=true
```

**Issue**: Slow processing
```bash
# Enable throughput mode
THROUGHPUT_MODE=true

# Increase workers (if CPU available)
MAX_WORKERS=8

# Reduce OCR quality
OCR_RENDER_SCALE=1.0
```

**Issue**: PII not detected
```bash
# Enable verbose logging
VERBOSE_LOGGING=true

# Check spaCy model installation
python -m spacy download en_core_web_sm
```

### Debug Mode

Enable verbose logging for troubleshooting:

```bash
VERBOSE_LOGGING=true
docker-compose up
```

---

## 👨‍💻 Development

### Local Development Setup

```bash
# Clone repository
git clone https://github.com/nowusman/DocGuard.git
cd DocGuard

# Create virtual environment
python3.12 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r app/requirements.txt
python -m spacy download en_core_web_sm

# Run in development mode
cd app
streamlit run app.py
```

### Project Structure

```
DocGuard/
├── app/
│   ├── app.py                 # Main application and UI
│   ├── document_processor.py # Document processing logic
│   ├── worker.py              # Worker process wrapper
│   ├── config.py              # Configuration management
│   ├── styles.css             # Custom UI styling
│   ├── requirements.txt       # Python dependencies
│   ├── Dockerfile             # Container definition
│   └── .streamlit/
│       └── config.toml        # Streamlit settings
├── docker-compose.yml         # Docker orchestration
├── .env.example               # Environment variables template
└── README.md                  # This file
```

### Code Style

- Follow PEP 8 for Python code
- Use type hints where applicable
- Document functions with docstrings
- Keep functions small and focused (single responsibility)
- Avoid code duplication

### Testing

```bash
# Run application with test documents
cd app
streamlit run app.py

# Manual testing checklist:
# - Upload single file (txt, docx, pdf)
# - Upload batch files
# - Test anonymization
# - Test PII removal
# - Test JSON extraction
# - Test error handling (large files, invalid formats)
```

---

## 🤝 Contributing

We welcome contributions! Please follow these guidelines:

1. **Fork the repository**
2. **Create a feature branch**: `git checkout -b feature/your-feature`
3. **Make your changes**: Follow code style guidelines
4. **Test thoroughly**: Ensure no regressions
5. **Commit**: Use clear, descriptive commit messages
6. **Push**: `git push origin feature/your-feature`
7. **Submit a Pull Request**: Describe your changes

### Contribution Areas

- 🐛 Bug fixes
- ✨ New features (OCR improvements, additional file formats)
- 📖 Documentation improvements
- 🧪 Test coverage
- ⚡ Performance optimizations
- 🌍 Internationalization (additional language models)

---

## 📄 License

This project is licensed under the MIT License. See [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

Built with:
- [Streamlit](https://streamlit.io/) - Web application framework
- [spaCy](https://spacy.io/) - NLP and named entity recognition
- [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) - OCR engine
- [PyMuPDF](https://pymupdf.readthedocs.io/) - PDF processing
- [python-docx](https://python-docx.readthedocs.io/) - DOCX processing

---

<p align="center">
  Made with ❤️ by the DocGuard team
</p>

<p align="center">
  <a href="https://github.com/nowusman/DocGuard/issues">Report Bug</a> •
  <a href="https://github.com/nowusman/DocGuard/issues">Request Feature</a>
</p>

