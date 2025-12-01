# DocGuard (Streamlit)

A document processing Web app based on Streamlit, providing document anonymization, PII removal, and JSON extraction functions.

### Functional characteristics

- Supports multiple document formats:. txt,. docx,. pdf
- Batch processing multiple documents (up to 10)
- Document anonymization processing
- PII (Personally Identifiable Information) removal
- Extract document content into JSON format
- Package the processing result as a ZIP download
- Parallel per-file processing with live status as files complete
- "Advanced options" expander for throughput mode (skip OCR/tables, regex-only PII) and verbose logging
- "Processing Details" expander surfaces per-stage timing for the first processed file
- Single-pass PyMuPDF PDF extraction (text/tables/images)
- In-session LRU caching skips duplicate re-processing within a worker process

### Installation and operation

Install dependencies:
```
pip install -r requirements.txt
```

### How to run web app
```
streamlit run app.py
```


---
# Docker build
### Make sure docker is installed
Run command following:
```
docker --version
docker ps
```
### OCR & table dependencies
```
# In WSL/Ubuntu
sudo apt update
sudo apt install -y libgl1 libglib2.0-0
```

1. Building Streamlit application images and running containers

In the app directory, execute:
```
# Build an image, name the image with the - t parameter
docker build -t streamlit-app .

# Run the container, with the - p parameter mapping the host port to the container port, 
# and - d indicating background operation
docker run -d -p 8501:8501 --name my-streamlit-app streamlit-app
```

Note: The root-level README.md is the canonical documentation. This file is a brief UI-only reference.

### Access
- Streamlit Web: http://localhost:8501

## Compatibility & Testing (UI)
- Streamlit versions: UI styling tested on 1.50; recommend verifying on 1.48–1.50
- Browsers: Chrome, Firefox, Safari, Edge
- Mobile: Verify layout on iPad/tablets and small screens
- File Upload edge cases:
  - Upload exactly the max count (MAX_FILES)
  - Per-file size near MAX_FILE_SIZE_MB
  - Batch size near MAX_BATCH_SIZE_MB
  - Mixed types: .txt, .docx, .pdf
- OCR toggle: Ensure the toggle state persists between reruns and affects processing output

Notes:
- CSS is scoped to .stApp and stable data-testid selectors to minimize breakage across versions
- Custom fonts are loaded via <link> in app.py for faster performance than CSS @import
- We use unsafe_allow_html=True only for static markup; do not interpolate user input
- Performance tips:
  - Leave OCR disabled (or enable throughput mode) when processing text-only documents.
  - Adjust MAX_WORKERS via .env to bound process-level parallelism.
  - Consult the Processing Details expander for timing when tuning heuristics.
