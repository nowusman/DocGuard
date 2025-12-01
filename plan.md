# Phased Implementation Plan: Performance, OCR, Parallelism, and UX Enhancements

This plan converts the current single-threaded, blocking Streamlit app into a robust, parallel, and responsive system while keeping the codebase simple and modular. It consolidates PDF processing, optimizes OCR, adds caching and async execution, improves spaCy usage, and enhances the UI with progress, cancellation, and multi‑session support.

Guiding rules (aligned with org rules):
- Keep it simple; prefer edits to existing code (app.py, streamlit_app/document_processor.py, config.py) over adding new components
- No duplication or wrappers; complete migration when ready (remove legacy paths and dead code)
- Stage complex changes behind simple toggles, then remove legacy paths after validation
- No one-off scripts; use existing Docker and Streamlit flows

Deliverables per phase include development, frontend, testing, deployment, cleanup, documentation, and acceptance criteria.

---

## Current Architecture Pain Points & Baseline

### Pain Points
❌ **Sequential, single-threaded processing**: Files processed one at a time; no parallelism
❌ **Blocking Streamlit UI**: All operations block the main thread; no responsiveness during processing
❌ **No caching or parallel execution**: Duplicate files re-processed; no work reuse
❌ **Excessive temp file I/O**: Images written to disk for OCR, then read back; high I/O overhead
❌ **Multiple PDF parsing passes**: PDFs opened 3-4 times (PyPDF2, pdfplumber, PyMuPDF, Camelot) for text, tables, images
❌ **Inefficient OCR strategy**: All images OCR'd regardless of size, contrast, or text presence; sequential processing
❌ **High render cost for OCR**: Images rendered at 2.0× scale with RGBA (4 channels); memory and CPU intensive
❌ **Inefficient spaCy NER**: Per-paragraph/per-page calls instead of batched nlp.pipe; unused pipeline components loaded
❌ **All files held in memory simultaneously**: Memory scales linearly with batch size
✅ **Simple, predictable behavior**: Current code is easy to understand and debug

### Expected Improvements (Cumulative)
- **Phase 1 (Parallel processing)**: 2–8× throughput for batches (CPU-bound workloads)
- **Phase 2 (OCR optimization)**: 3–10× less OCR time on mixed PDFs (selective + faster engine)
- **Phase 3 (PDF consolidation)**: 2–10× faster PDF text extraction (single-pass with PyMuPDF)
- **Phase 4 (Caching)**: Near-instant re-processing for duplicate files
- **Phase 5 (Async UI)**: Non-blocking UI; responsive during processing
- **Phase 6 (spaCy optimization)**: 2–6× faster NER on document batches
- **Phase 7 (Table extraction)**: Faster, more reliable table detection
- **Phase 8-12 (UX + cleanup)**: Streaming results, progress tracking, cancellation, cleaner codebase

### Baseline Metrics (to be measured in Phase 0)
- Average processing time per file type (PDF/DOCX/TXT)
- Pages per second by document type
- OCR time per page/image
- Memory footprint during batch processing
- Time to first result
- PDF parsing time breakdown (text, tables, images)

---


Phase 0 — Baseline, flags, and instrumentation (1–2 days) — **Status: ✅ Completed (env-backed flags, instrumentation, Advanced options UI)**
- Goals
  - Establish a measurement baseline and minimal feature flags to stage changes safely
  - Add light perf instrumentation to identify hotspots
  - Apply quick micro-optimizations with zero risk
- Development
  - config.py
    - Load variables from .env with these defaults:
      - THROUGHPUT_MODE = False (If True: disables OCR/Tables, uses PyMuPDF, uses Regex-only PII)
      - OCR_MAX_IMAGES_PER_DOC = 10
      - OCR_RENDER_SCALE = 1.25
      - VERBOSE_LOGGING = False
    - Hardcoded/Internal defaults (Keep it simple):
      - PDF_ENGINE = "pymupdf" (Superior performance and rendering)
      - OCR_ENGINE = "paddle" (Faster, better accuracy for text)
      - MAX_WORKERS = os.cpu_count() or 4
    - **Micro-optimizations** (immediate gains):
    - **Micro-optimizations** (immediate gains):
      - Precompile all PII_PATTERNS regexes once at module import (use re.compile)
      - Replace string concatenation (text += page) with list.append + "".join() pattern throughout
  - document_processor.py
    - Add optional simple timing with perf_counter to: _read_* functions, OCR, spaCy/PII removal, table extraction, PDF generation
    - Return timings in metadata["timing"]
    - **Apply text-building optimization**: Replace all `text += page_text` patterns with:
      ```python
      text_chunks = []
      for page in pages:
          text_chunks.append(page_text)
      text = "\n".join(text_chunks)
      ```
    - **Reduce log noise**: Guard verbose prints (e.g., "Clear temp file...") with VERBOSE_LOGGING flag
  - No other functional changes yet
- Frontend (streamlit_app/app.py)
  - Add an “Advanced options” expander with:
    - Simple toggles for "Verbose Logging" or similar if needed (keep technical toggles hidden)
  - Add a “Processing Details” expander to show timing summary for first processed file
- Testing
  - Create a small local corpus of 5–10 mixed PDFs/DOCX/TXT and log durations
- Deployment
  - No build changes. Ensure compose up works as baseline
- Cleanup
  - Identify dead code/log noise hotspots (e.g., verbose prints, commented blocks) for removal in later phases
- Documentation
  - Update README.md with new toggles; add “Performance Tips” section
- Acceptance criteria
  - App still behaves exactly the same by default
  - Timing data visible when expanding Processing Details


Phase 1 — Parallel per‑file processing (TIER 1) (0.5–1 day) — **Status: ✅ Completed (ProcessPool executor + live status UI)**
- Goals
  - 2–8× throughput for batches by processing files in parallel processes
  - Keep UI responsive; avoid blocking Streamlit thread
- Development (app.py)
  - Replace sequential loop with concurrent.futures.ProcessPoolExecutor
  - Implement a small worker to avoid pickling issues and ensure per‑process spaCy/Tesseract state
    - def _worker(args): from document_processor import DocumentProcessor; return DocumentProcessor().process_document(**args)
  - Use max_workers = min(len(uploaded_files), MAX_WORKERS_DEFAULT)
  - Collect results via as_completed for incremental UI updates
  - Ensure bytes payloads are small enough; Streamlit uploaded files are already in memory; pass file.getvalue(), file.name, flags
- Frontend
  - Show per‑file progress (simple counter + status list)
  - Keep spinner but add “n/N processed” in real time
- Testing
  - Measure with 4–10 files; confirm speedup vs baseline
- Deployment
  - Ensure container has multiple CPUs available; document recommendation in README
- Cleanup
  - None yet; minimal change to existing structure
- Documentation
  - Update README “Parallel processing” section and environment guidance (CPU availability)
- Acceptance criteria
  - Batch run uses multiple CPU cores; UI remains responsive with incremental updates


Phase 2 — OCR strategy optimization and faster engine option (TIER 1) (1–2 days) — **Status: ✅ Completed (Selective PaddleOCR + bounded parallel OCR)**
- Goals
  - Reduce unnecessary OCR work; switch from Tesseract to PaddleOCR for speed and accuracy
  - Add parallel OCR processing for multiple images within a document
  - Reduce OCR render overhead (scale and color mode)
- Development (document_processor.py)
  - **Smart OCR logic** - Add _should_apply_ocr(image_bytes):
    - Skip OCR if there is no suitable image (e.g., image size is not small, image is low contrast/poor quality)
    - Use fast heuristic: check for text-like patterns (simple edge detection)
    - Dynamically check image and use appropriate mode (L/RGB)
  - **Per-document OCR cap**: Process up to OCR_MAX_IMAGES_PER_DOC images per document
  - **Parallel OCR processing**: 
    - Use ThreadPoolExecutor or ProcessPoolExecutor to OCR multiple images concurrently within a document
    - Bounded concurrency: OCR_MAX_WORKERS = min(2, cpu_count) to avoid memory spikes
    - Preserve reading order: collect results in order (future.result() or as_completed with ordering)
  - **Reduce render overhead**:
    - Lower OCR_RENDER_SCALE from 2.0 to 1.0–1.25 in _extract_image_with_pymupdf
    - Use grayscale mode ("L") instead of RGB/RGBA for OCR preprocessing (faster, less memory)
  - **OCR_ENGINE switch**:
    - Replace Tesseract with PaddleOCR (CPU)
    - Integrate PaddleOCR with minimal deps (faster, especially for Asian languages)
- Completed items: PaddleOCR default engine, heuristic gating (size/contrast and tiny images), per-document OCR cap, thread-pooled OCR (max 2), grayscale rendering at OCR_RENDER_SCALE defaults, OCR metadata surfaced (processed/skipped counts).
- Frontend
  - Show OCR image count and skip count in Processing Details
- Testing
  - PDFs with few images and image‑heavy PDFs; validate quality and measure 3–10× less OCR time in mixed docs
  - Test parallel OCR with bounded workers; verify no memory issues
  - Compare Tesseract vs PaddleOCR quality and speed
- Deployment
  - requirements.txt: add paddleocr; Dockerfile: install paddle dependencies (opencv is already present)
  - Add ENV OMP_NUM_THREADS=1 in Dockerfile to reduce thread oversubscription with spaCy/OCR
- Cleanup
  - Guard noisy prints with VERBOSE_LOGGING; ensure temporary files are always cleaned (finally blocks)
- Documentation
  - README: OCR heuristics explained; parallel OCR behavior
- Acceptance criteria
  - OCR is skipped for tiny/low‑value images; Paddle engine works when selected
  - Multiple images OCR'd in parallel within document; bounded memory usage


Phase 3 — Single-pass PDF consolidation with PyMuPDF (TIER 1) (1–2 days) — **Status: ✅ Completed (PyMuPDF single-pass + metadata surfaced)**
- Goals
  - Open each PDF once; extract text, tables, images in one pass using fitz; reduce I/O and memory churn
  - Eliminate redundant PDF parsing (Standardize on PyMuPDF)
  - 2–10× faster PDF text extraction vs pdfminer/pdfplumber path
- Development (document_processor.py)
  - **Implement _read_pdf_optimized(file_content)** using fitz (PyMuPDF):
    ```python
    def _read_pdf_optimized(self, file_content):
        """Single pass through PDF using PyMuPDF only"""
        import fitz
        text_chunks, images_data, tables_data = [], [], []
        
        with fitz.open(stream=file_content, filetype="pdf") as pdf_doc:
            for page_num, page in enumerate(pdf_doc):
                # Clip header/footer using PDF_HEADER_RATIO
                rect = page.rect
                header_ratio = PDF_HEADER_RATIO
                clip = fitz.Rect(0, rect.height * header_ratio, 
                                rect.width, rect.height * (1 - header_ratio))
                
                # Extract text in one pass
                page_text = page.get_text(clip=clip) or ""
                if page_text:
                    text_chunks.append(page_text)
                
                # Extract tables (PyMuPDF >= 1.23)
                page_tables = page.find_tables()
                tables_data.extend(page_tables)
                
                # Extract images
                page_images = page.get_images()
                for img_idx, img in enumerate(page_images):
                    # Combine with existing _extract_image_with_pymupdf logic
                    # Apply smart OCR gating from Phase 2
                    pass
        
        text = "\n".join(text_chunks)  # Use list join pattern
        return text, {"text_content": text, "tables": tables_data, "images": images_data}
    ```
  - **Wire selection logic**: 
    - Always use _read_pdf_optimized (PyMuPDF)
  - **Fallback handling**: Remove pdfplumber fallback unless strictly necessary for edge cases
- Frontend
  - Show selected engine in Processing Details
- Testing
  - Compare text accuracy and timing vs pdfplumber on mixed PDFs (text-heavy, scanned, complex layouts)
  - Validate header/footer clipping accuracy
  - Measure single-pass vs multi-pass time savings
- Deployment
  - None (PyMuPDF/fitz already present in requirements.txt)
- Cleanup (staged)
  - Keep pdfplumber fallback until Phase 11 after validation period
  - Tag TODOs where duplicate PDF parsing logic exists (_read_pdf vs _read_pdf_optimized)
- Documentation
  - README: state recommended default is PyMuPDF after validation; explain single-pass benefits
  - Document fallback behavior for edge cases
- Acceptance criteria
  - End‑to‑end PDF processing runs 2–10× faster with comparable text quality
  - Single pass per PDF (no redundant opens)
  - Fallback works for complex PDFs


Phase 4 — Caching layer (TIER 2) (0.5 day) — **Status: ✅ Completed (per-worker LRU cache + UI surfacing)**
- Goals
  - Instant re‑processing for duplicate inputs and unchanged options within a session
- Development
  - DocumentProcessor: add simple in‑memory LRU cache keyed by sha256(file_bytes + options)
  - Provide MAX_CACHE_ITEMS in config (e.g., 64)
- Frontend
  - Optional: show “(from cache)” label in Processing Details
- Testing
  - Re‑upload identical files; verify cache hits and time near‑zero
- Deployment
  - None
- Cleanup
  - N/A
- Documentation
  - README: caching behavior and limits
- Acceptance criteria
  - Duplicate work within a session is skipped; memory bounded by max cache items


Phase 5 — Async UI with background worker (TIER 2) (1 day)
- Goals
  - Decouple UI from processing to avoid blocking Streamlit interactions
- Development (app.py)
  - Introduce a lightweight background thread with Queue collecting per‑file results while ProcessPool handles CPU work
  - Stream updates: as_completed loop puts results into Queue; UI consumes and updates progress table
- Frontend
  - Live progress list with statuses: queued, running, done, error
- Testing
  - Start/stop, navigate UI while processing; ensure no freezes
- Deployment
  - None
- Cleanup
  - N/A
- Documentation
  - README: “How progress works”
- Acceptance criteria
  - UI remains interactive during processing; partial results appear as they finish


Phase 6 — spaCy and PII pipeline optimization (TIER 2) (1 day)
- Goals
  - 2–6× faster NER on many small chunks via batching; regex‑only fast mode
  - Reduce spaCy overhead by disabling unused pipeline components
- Development (document_processor.py)
  - **Load spaCy model**:
    ```python
    # Keep parser and lemmatizer enabled (standard pipeline)
    self.nlp = spacy.load("en_core_web_sm")
    ```
  - **Batch processing for DOCX/XML text**:
    - Instead of calling nlp(text) per paragraph/run, collect all text chunks first:
    ```python
    # Collect all paragraphs/text nodes
    text_chunks = [para.text for para in document.paragraphs if para.text]
    
    # Batch process with nlp.pipe for 2-6× speedup
    docs = list(self.nlp.pipe(text_chunks, batch_size=50, n_process=1))
    
    # Apply redactions to original structures
    for idx, doc in enumerate(docs):
        for ent in doc.ents:
            if ent.label_ in ["PERSON", "ORG", "GPE"]:
                # Replace in original paragraph structure
                paragraphs[idx].text = paragraphs[idx].text.replace(ent.text, "[REDACTED]")
    ```
  - **Regex-only fast mode**:
    - When THROUGHPUT_MODE = True, skip spaCy entirely and use precompiled regex patterns only
    - Add _remove_pii_fast(text) method that uses only PII_PATTERNS regexes
    - Trade-off: faster but may miss context-dependent entities (e.g., names without obvious patterns)
  - **Precompile all regex patterns** in config.py (already in Phase 0, ensure reuse here)
- Frontend
  - "Max throughput mode" checkbox already maps to THROUGHPUT_MODE → fast mode
  - Show "NER mode: spaCy batch" or "NER mode: regex-only" in Processing Details
- Testing
  - DOCX with many paragraphs (50+); verify 2–6× speedup vs per-paragraph processing
  - Compare accuracy: spaCy batch vs regex-only vs current sequential spaCy
  - Measure memory usage during batch processing
- Deployment
  - None (spaCy already present)
- Cleanup
  - Remove redundant spaCy calls in loops (e.g., per-paragraph or per-page calls)
  - Centralize all PII redaction logic into _remove_pii_batch and _remove_pii_fast methods
  - Remove duplicate entity detection logic
- Documentation
  - README: explain accuracy vs speed tradeoff; when to use fast mode
  - Document spaCy batch processing benefits and limitations
  - Note: fast mode may miss context-dependent entities
- Acceptance criteria
  - Batch processing delivers 2–6× speedup on multi-paragraph documents
  - Fast mode (regex-only) works correctly with acceptable accuracy for high-throughput scenarios
  - Memory usage remains bounded during batching


Phase 7 — Table extraction modernization (TIER 3) (1–2 days)
- Goals
  - Faster, simpler table extraction with fewer dependencies
- Development
  - Prefer PyMuPDF page.find_tables() when PDF_ENGINE==pymupdf
  - Only run Camelot when extract_json is selected and feature flag explicitly enables “legacy tables”
  - Add quick text-heuristic precheck to skip expensive table extraction if no table hints
- Frontend
  - Advanced: “Try legacy Camelot tables” toggle (default OFF)
- Testing
  - PDFs with and without tables; compare outputs
- Deployment
  - None
- Cleanup
  - After validation, remove Camelot dependency and code paths entirely (requirements.txt, _extract_tables_from_pdf, _process_camelot_table, related helpers)
- Documentation
  - README: updated table extraction behavior, removed Camelot
- Acceptance criteria
  - Similar or better table recall with faster runtime; Camelot removed post‑validation


Phase 8 — Streaming results, progress bar, and per‑file availability (TIER 3) (1 day)
- Goals
  - Incremental availability of outputs and visible progress
- Development (app.py)
  - Implement generator pattern or loop over as_completed futures to update:
    - results_container.write(f"Processed i/N")
    - Make download buttons for completed files immediately available
- Frontend
  - Global progress bar + per‑file progress list
- Testing
  - Large batches; confirm early files are downloadable without waiting for all
- Deployment
  - None
- Cleanup
  - N/A
- Documentation
  - README: Streaming and partial downloads
- Acceptance criteria
  - Users see progress and can download files as they complete


Phase 9 — Cancel/kill processing from UI (TIER 3) (0.5–1 day)
- Goals
  - Users can stop long batch processing
- Development (app.py)
  - Add “Stop processing” button that sets st.session_state["cancel_requested"] = True and triggers executor.shutdown(cancel_futures=True)
  - Skip scheduling remaining files if cancel requested; mark pending as canceled
- Frontend
  - Show canceled status for pending items
- Testing
  - Cancel mid‑run; ensure executor tears down cleanly and UI remains usable
- Deployment
  - None
- Cleanup
  - N/A
- Documentation
  - README: cancellation behavior and limitations (running tasks may finish)
- Acceptance criteria
  - Pending tasks are canceled and no new work is scheduled; UI updates correctly


Phase 10 — Multi‑session support hardening (0.5 day)
- Goals
  - Ensure multiple users do not contend on shared globals
- Development
  - Avoid sharing global mutable state across sessions
    - Keep global lightweight: processor construction moves inside worker processes
    - Keep caches scoped to per‑process DocumentProcessor
  - Use st.session_state to store UI state and cancellation flags
- Frontend
  - None beyond existing changes
- Testing
  - Two browsers / users running different batches concurrently; validate isolation
- Deployment
  - None
- Cleanup
  - Remove unused global variables; ensure document_processor.processor global is not used by workers
- Documentation
  - README: note on multi‑session behavior
- Acceptance criteria
  - Independent sessions without cross‑talk or shared cache surprises


Phase 11 — Cleanup, dead‑code removal, and migration completion (0.5–1 day)
- Goals
  - Zero legacy/dead code, consistent patterns, and no duplicate flows
  - Eliminate temp file I/O overhead for images
- Development
  - **Remove legacy PDF/OCR paths**:
    - Remove pdfplumber and Tesseract dependencies completely
    - Remove Camelot code if Phase 7 succeeds; drop dependency from requirements.txt
  - **In-memory image handling** (high-impact cleanup):
    - Replace all temp image file writes/reads with in-memory buffers
    - Current pattern (slow, I/O heavy):
      ```python
      # Write to temp file
      temp_img_path = "/tmp/img.png"
      img.save(temp_img_path)
      # Read back for OCR or PDF
      with open(temp_img_path, 'rb') as f:
          img_data = f.read()
      os.remove(temp_img_path)
      ```
    - New pattern (fast, in-memory):
      ```python
      # Keep in memory
      img_buffer = io.BytesIO()
      img.save(img_buffer, format='PNG')
      img_data = img_buffer.getvalue()
      # Use directly for OCR or PDF generation
      ```
    - For PDF generation in _create_pdf_with_layout:
      ```python
      from reportlab.lib.utils import ImageReader
      # No temp file needed
      img_reader = ImageReader(io.BytesIO(img_data['image_data']))
      img = Image(img_reader, width=400, height=300)
      story.append(img)
      ```
  - **Consolidate duplicate code**:
    - Remove duplicate loops for header/footer processing
    - Centralize text extraction patterns (list + join)
  - **Reduce logging noise**:
    - Guard all verbose prints (e.g., "Clear temp file...", "Processing page X") under VERBOSE_LOGGING flag
  - **Apply bytes→str optimization**:
    - Avoid repeated bytes→str→bytes conversions in file handling
    - Use consistent encoding throughout (UTF-8)
- Frontend
  - Remove legacy toggles that are no longer relevant (e.g., "legacy tables", old PDF engine selector if pymupdf is default)
- Testing
  - Regression pass over sample corpus (text, tables, images, JSON)
  - Verify no temp files created during processing (check /tmp)
  - Measure I/O reduction and speed improvement from in-memory handling
- Deployment
  - requirements.txt and Dockerfile pruning:
    - Remove unused dependencies (Camelot, pdfplumber if not needed)
    - Smaller Docker image; faster builds
- Documentation
  - Update README and strip references to removed engines/paths
  - Document in-memory processing benefits
- Acceptance criteria
  - No dead code paths; no temp file I/O for images
  - Smaller, cleaner image and codebase
  - Measurable I/O and performance improvements


Phase 12 — Deployment, runtime tuning, and docs (0.5 day)
- Goals
  - Make performance predictable in containers and document best practices
- Development / Deployment
  - Dockerfile:
    - Set ENV OMP_NUM_THREADS=1 for spaCy/Numpy and OCR libs
    - Install PaddleOCR if chosen; ensure wheel use where possible
    - Expose a WORKERS env to bound ProcessPoolExecutor when needed
  - docker-compose.yml:
    - Optionally document CPU resources, e.g., deploy.resources or guidance in README
- Documentation
  - Detailed “Performance & Scaling” section:
    - Choosing worker count
    - OCR heuristics and engines
    - Throughput mode
    - Multi‑session usage
- Acceptance criteria
  - Clear runtime guidance; stable performance under typical loads


Timeline and sequencing
- Week 1: Phases 0–3 (baseline, parallelism, OCR heuristics, PyMuPDF consolidation)
- Week 2: Phases 4–8 (caching, async UI, spaCy optimizations, streaming/progress)
- Week 3: Phases 9–12 (cancel, multi‑session hardening, cleanup, deployment/docs)


Testing plan (applies to all phases)
- Unit‑like checks where practical inside document_processor methods
- Golden files for small sample corpus (text extract, table presence counts, JSON keys)
- Side‑by‑side timing logs per file and per step
- Manual exploratory tests for UI: progress, cancellation, and partial downloads


Risk/mitigation and rollback
- PyMuPDF accuracy vs pdfplumber: Validate on baseline corpus; fallback only if critical issues found
- PaddleOCR: Validate installation size and CPU usage
- ProcessPool memory: Use bounded max_workers; avoid holding giant intermediate buffers in UI; stream results incrementally
- Cancellation granularity: cancel_futures=True cancels queued work only; document this limitation


Acceptance summary (overall)
- End‑to‑end batch throughput improved by 3–8× in typical mixed workloads
- UI remains responsive with progress, streaming results, and cancellation
- Codebase consolidated (single‑pass PDF path, fewer deps), no dead code
- Clear configuration, deployment guidance, and documentation


Open questions (to finalize defaults)
- Typical workload: PDF vs DOCX vs TXT; average pages; % image‑only PDFs?
- OCR accuracy needs: Is aggressive OCR skipping acceptable by default?
- Expected concurrency: single user large batches vs multiple users? Affects sensible default for max_workers
- Target environment: local laptop vs server vs container platform (CPUs/Memory)?

---

## Implementation Notes & Best Practices

### Cross-Cutting Patterns
1. **Text Building**: Always use `list.append() + "".join()` instead of `text += page` for string concatenation
2. **Regex Patterns**: Precompile all regexes once at module import with `re.compile()` and reuse
3. **Temp Files**: Replace all temp file I/O with in-memory `io.BytesIO()` buffers where possible
4. **Logging**: Guard verbose prints with `VERBOSE_LOGGING` flag to reduce I/O overhead
5. **Error Handling**: Always use `try/finally` blocks to ensure temp file cleanup
6. **Bytes/Str**: Avoid repeated conversions; use consistent UTF-8 encoding

### Performance Priorities (Sorted by Impact)
1. **Parallel file processing** (Phase 1): 2–8× gain, low complexity
2. **PyMuPDF single-pass** (Phase 3): 2–10× gain on PDF-heavy workloads
3. **Selective OCR** (Phase 2): 3–10× gain on mixed scanned/text PDFs
4. **Parallel OCR** (Phase 2): 2–4× gain on image-heavy pages
5. **spaCy batching** (Phase 6): 2–6× gain on DOCX with many paragraphs
6. **In-memory images** (Phase 11): Eliminates I/O bottleneck, faster on image-heavy docs

### Risk Mitigation
- **PyMuPDF accuracy**: Validate on baseline corpus
- **OCR engine switch**: Validate PaddleOCR quality
- **ProcessPool memory**: Bound max_workers; monitor memory usage; stream results incrementally
- **Cancellation**: cancel_futures=True only cancels queued work; running tasks may complete
- **Multi-session**: Avoid global state; use per-process DocumentProcessor instances

### Configuration Strategy
- **Feature flags**: Use config.py toggles only for critical staging
- **Progressive rollout**: Start with safe defaults
- **Validation period**: Keep legacy paths available for 1-2 weeks after new implementation; measure differences
- **Final cleanup**: Remove legacy code only after comprehensive validation (Phase 11)

### Testing Strategy
- **Baseline corpus**: 5-10 representative files (PDF text, PDF scanned, DOCX, TXT, mixed)
- **Golden files**: Track text extraction accuracy, table counts, JSON structure
- **Performance tracking**: Log per-phase timing improvements vs baseline
- **Memory monitoring**: Track peak memory usage during batch processing
- **Multi-user**: Test concurrent sessions with isolated state
