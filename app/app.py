# app.py

import io
import json
import logging
import zipfile
import queue
import threading
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from config import (
    MAX_BATCH_SIZE_MB,
    MAX_FILES,
    MAX_FILE_SIZE_MB,
    MAX_WORKERS,
    OCR_CONFIG,
    THROUGHPUT_MODE,
    VERBOSE_LOGGING,
)

from worker import _process_file_worker


def _derive_output_name(filename: str, anonymize: bool, remove_pii: bool, extract_json: bool) -> str:
    path = Path(filename)
    stem = path.stem or filename
    if extract_json:
        return f"{stem}.json"
    if anonymize or remove_pii:
        return f"{stem}_processed.pdf"
    return filename


def _parse_anonymize_terms_input(raw_terms: str) -> list:
    """Normalize anonymization terms from the UI input."""
    if not raw_terms:
        return []
    terms = []
    seen = set()
    for line in raw_terms.splitlines():
        parts = [part.strip() for part in line.split(",")]
        for term in parts:
            if not term:
                continue
            key = term.lower()
            if key in seen:
                continue
            seen.add(key)
            terms.append(term)
    return terms


def _run_background_batch(jobs, worker_count, result_queue):
    """Run ProcessPool work in a background thread and stream updates into a queue."""
    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        future_to_idx = {}
        for idx, job in enumerate(jobs):
            future = executor.submit(_process_file_worker, job["payload"])
            future_to_idx[future] = idx
            result_queue.put({"type": "status", "index": idx, "status": "Processing"})

        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            job = jobs[idx]
            try:
                processed_content, file_extension, metadata = future.result()
                result_queue.put(
                    {
                        "type": "result",
                        "index": idx,
                        "original_name": job["original_name"],
                        "order": job["order"],
                        "content": processed_content,
                        "extension": file_extension,
                        "metadata": metadata,
                    }
                )
            except Exception as exc:
                result_queue.put(
                    {
                        "type": "error",
                        "index": idx,
                        "original_name": job["original_name"],
                        "error": str(exc),
                    }
                )
    result_queue.put({"type": "done"})


def _init_processing_state():
    defaults = {
        "processing_thread": None,
        "processing_queue": None,
        "processing_results": [],
        "processing_errors": [],
        "status_rows": [],
        "processing_total": 0,
        "processing_started": False,
        "processing_done": False,
        "processing_batch_options": None,
        "job_operations": [],
        "immediate_download_buttons": {},  
        "download_buttons_rendered": False,  
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _drain_result_queue(anonymize, remove_pii, extract_json):
    """Consume queued messages from the background batch worker."""
    q = st.session_state["processing_queue"]
    if not q:
        return 0

    updates = 0
    while True:
        try:
            message = q.get_nowait()
        except queue.Empty:
            break

        msg_type = message.get("type")
        idx = message.get("index")
        job_ops = st.session_state.get("job_operations") or []
        ops = (
            job_ops[idx]
            if idx is not None and idx < len(job_ops)
            else {"anonymize": anonymize, "remove_pii": remove_pii, "extract_json": extract_json}
        )
        if msg_type == "status" and idx is not None and idx < len(st.session_state["status_rows"]):
            st.session_state["status_rows"][idx]["Status"] = message.get("status", "Processing")
            # Progress update
            if "Progress" in st.session_state["status_rows"][idx]:
                st.session_state["status_rows"][idx]["Progress"] = 50  # Progressing
        elif msg_type == "result":
            output_filename = _derive_output_name(
                message["original_name"], ops["anonymize"], ops["remove_pii"], ops["extract_json"]
            )
            result_data = {
                "name": output_filename,
                "content": message["content"],
                "original_name": message["original_name"],
                "file_extension": message["extension"],
                "metadata": message.get("metadata") or {},
                "order": message.get("order", idx),
                "operations": ops,
                "processed_time": datetime.now(),
            }
            st.session_state["processing_results"].append(result_data)
            
            # Store download button data
            st.session_state["immediate_download_buttons"][idx] = {
                "filename": output_filename,
                "content": message["content"],
                "file_extension": message["extension"],
                "original_name": message["original_name"],
                "operations": ops,
                "processed_time": datetime.now().strftime("%H:%M:%S")
            }
            
            if idx is not None and idx < len(st.session_state["status_rows"]):
                st.session_state["status_rows"][idx]["Status"] = "Done"
                st.session_state["status_rows"][idx]["Progress"] = 100  
                
            updates += 1
        elif msg_type == "error":
            if idx is not None and idx < len(st.session_state["status_rows"]):
                st.session_state["status_rows"][idx]["Status"] = "Error"
                st.session_state["status_rows"][idx]["Progress"] = 0
            st.session_state["processing_errors"].append(
                f"Error processing {message.get('original_name')}: {message.get('error')}"
            )
            updates += 1
        elif msg_type == "done":
            st.session_state["processing_done"] = True
    return updates


# Set page configuration
st.set_page_config(
    page_title="DocGuard by TSA",
    page_icon="🛡️",
    layout="wide"
)

# Inject custom CSS
def inject_custom_css():
    css_path = Path(__file__).with_name("styles.css")
    try:
        css = css_path.read_text()
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        logging.warning("Custom styles.css not found at %s; UI will use default Streamlit styles.", css_path)
    except Exception as e:
        logging.exception("Failed to inject custom CSS: %s", e)

inject_custom_css()
_init_processing_state()

# Hero header
st.markdown(
    """
    <div class="hero">
      <h1>🛡️ DocGuard</h1>
      <div class="subtitle">Fast anonymization, PII removal, and JSON extraction for your documents · <span class=\"badge\">OCR</span> <span class=\"badge\">PDF/DOCX/TXT</span></div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Page intro hint
st.caption(f"Upload up to {MAX_FILES} files (.txt, .docx, .pdf) — we'll handle the rest ✨")

# File upload area
st.header("1. 📤 Upload Files")
uploaded_files = st.file_uploader(
    f"Drag & drop or browse files (max {MAX_FILES})",
    type=['txt', 'docx', 'pdf'],
    accept_multiple_files=True,
    help=f"You can upload up to {MAX_FILES} files of type .txt, .docx, or .pdf"
)

# Validate size limits
size_ok = True
if uploaded_files:
    total_bytes = sum(len(f.getvalue()) for f in uploaded_files)
    oversized = [(f.name, len(f.getvalue())) for f in uploaded_files if len(f.getvalue()) > MAX_FILE_SIZE_MB * 1024 * 1024]
    if oversized:
        size_ok = False
        st.error(
            "The following file(s) exceed the per-file limit of {}MB: {}".format(
                MAX_FILE_SIZE_MB,
                ", ".join([f"{n} ({round(sz/1024/1024,2)}MB)" for n, sz in oversized])
            )
        )
    if total_bytes > MAX_BATCH_SIZE_MB * 1024 * 1024:
        size_ok = False
        st.error(
            "Total upload size exceeds the batch limit of {}MB (current: {:.2f}MB)".format(
                MAX_BATCH_SIZE_MB, total_bytes/1024/1024
            )
        )

# Limit the number of files
if uploaded_files and len(uploaded_files) > MAX_FILES:
    st.error(f"You can only upload up to {MAX_FILES} files. Please remove some files.")
    uploaded_files = uploaded_files[:MAX_FILES]

# Display uploaded file information
if uploaded_files:
    st.subheader("Uploaded Files")
    file_info = []
    for i, file in enumerate(uploaded_files):
        file_info.append({
            "No.": i+1,
            "File Name": file.name,
            "File Type": file.type if hasattr(file, 'type') else "Unknown",
            "Size (KB)": round(len(file.getvalue()) / 1024, 2)
        })
    
    df_files = pd.DataFrame(file_info)
    st.dataframe(df_files, width="stretch", hide_index=True)

# Processing Options
st.header("2. 🛠️ Processing Options")
col1, col2, col3 = st.columns(3)

with col1:
    anonymize = st.checkbox("🛡️ Anonymize", help="Remove personal identifiers from documents")
with col2:
    remove_pii = st.checkbox("🧹 Remove PII", help="Remove Personally Identifiable Information")
with col3:
    extract_json = st.checkbox("🧾 Extract to JSON", help="Extract document content to JSON format")

# OCR toggle (default ON)
ocr_enabled = st.toggle("🖼️ OCR for images (PDF/DOCX)", value=True, help="Extract text from images via PaddleOCR with simple heuristics.")
OCR_CONFIG['enabled'] = bool(ocr_enabled)

# Advanced options expander keeps expert flags tucked away
with st.expander("Advanced options"):
    throughput_mode = st.checkbox(
        "⚡ Max throughput mode (skip OCR/table extraction, regex-only PII)",
        value=THROUGHPUT_MODE,
        help="Disables OCR/table extraction and favors regex-only PII for faster processing.",
    )
    verbose_logging = st.checkbox(
        "🪵 Verbose logging (server console)",
        value=VERBOSE_LOGGING,
        help="Prints additional debug logs from the processing engine.",
    )
    st.caption(f"Parallel workers available: up to {MAX_WORKERS}")

with st.expander("⚙️ Anonymization Settings"):
    anonymize_terms_input = st.text_area(
        "Terms to Anonymize (one per line)",
        value="stc",
        help="One per line or comma-separated; case-insensitive; duplicates removed.",
    )
    anonymize_replace_input = st.text_input(
        "Replacement string",
        value="sss",
        help="Replacement string; leave empty to replace with a single space",
    )

parsed_anonymize_terms = _parse_anonymize_terms_input(anonymize_terms_input)

processing_overrides = {
    "throughput_mode": throughput_mode,
    "verbose_logging": verbose_logging,
    "ocr_enabled": bool(ocr_enabled),
    "anonymize_terms": parsed_anonymize_terms,
    "anonymize_replace": anonymize_replace_input,
}

# Process
st.header('3. Process & Run')
process_btn = st.button(
    '🚀 Process',
    type='primary',
    width="stretch",
    disabled=st.session_state["processing_started"],
)

# Validate processing options
if process_btn and not (anonymize or remove_pii or extract_json):
    st.error("❌ Please select at least one processing option (Anonymize, Remove PII, or Extract to JSON)")

# Create progress display container
progress_placeholder = st.empty()
status_placeholder = st.empty()
immediate_download_container = st.container() 
global_progress_container = st.empty()

if process_btn and uploaded_files and size_ok and (anonymize or remove_pii or extract_json):
    if st.session_state["processing_started"]:
        st.info("Processing is already running. Please wait for it to finish.")
    else:
        st.session_state["processing_results"] = []
        st.session_state["processing_errors"] = []
        st.session_state["processing_done"] = False
        st.session_state["processing_total"] = len(uploaded_files)
        st.session_state["immediate_download_buttons"] = {}  
        st.session_state["download_buttons_rendered"] = False
        
        # Initialization status line, including progress field
        st.session_state["status_rows"] = [
            {
                "File": file.name, 
                "Status": "Queued",
                "Progress": 0
            } for file in uploaded_files
        ]
        
        batch_options_snapshot = {
            "anonymize": anonymize,
            "remove_pii": remove_pii,
            "extract_json": extract_json,
            "throughput_mode": throughput_mode,
            "verbose_logging": verbose_logging,
            "ocr_enabled": bool(ocr_enabled),
            "anonymize_terms": parsed_anonymize_terms,
            "anonymize_replace": anonymize_replace_input,
        }
        st.session_state["processing_batch_options"] = batch_options_snapshot
        st.session_state["job_operations"] = []

        jobs = []
        for order, file in enumerate(uploaded_files):
            file_bytes = file.getvalue()
            payload = {
                "file_content": file_bytes,
                "filename": file.name,
                "anonymize": anonymize,
                "remove_pii": remove_pii,
                "extract_json": extract_json,
                "options": processing_overrides,
            }
            jobs.append({"payload": payload, "original_name": file.name, "order": order})
            st.session_state["job_operations"].append({
                "anonymize": anonymize,
                "remove_pii": remove_pii,
                "extract_json": extract_json,
            })

        worker_count = max(1, min(len(jobs), MAX_WORKERS))
        result_queue = queue.Queue()
        background_thread = threading.Thread(
            target=_run_background_batch,
            args=(jobs, worker_count, result_queue),
            daemon=True,
        )
        background_thread.start()

        st.session_state["processing_thread"] = background_thread
        st.session_state["processing_queue"] = result_queue
        st.session_state["processing_started"] = True

# Render progress/status and consume queue updates
processing_active = bool(st.session_state["processing_thread"] and st.session_state["processing_thread"].is_alive())

if st.session_state["processing_started"] or st.session_state["processing_done"]:
    batch_opts = st.session_state.get("processing_batch_options") or {
        "anonymize": anonymize,
        "remove_pii": remove_pii,
        "extract_json": extract_json,
        "throughput_mode": throughput_mode,
        "verbose_logging": verbose_logging,
        "ocr_enabled": bool(ocr_enabled),
    }
    
    _drain_result_queue(batch_opts["anonymize"], batch_opts["remove_pii"], batch_opts["extract_json"])
    
    total_files = st.session_state["processing_total"]
    completed_count = len(st.session_state["processing_results"]) + len(st.session_state["processing_errors"])
    
    # Display global progress bar
    if total_files > 0:
        progress_ratio = completed_count / total_files
        with global_progress_container.container():
            st.subheader("📊 Global Progress")
            progress_bar = st.progress(progress_ratio, text=f"Processed {completed_count}/{total_files} files")
            
            # Progress statistics
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Queued", total_files - completed_count)
            with col2:
                st.metric("Processing", sum(1 for row in st.session_state["status_rows"] if row["Status"] == "Processing"))
            with col3:
                st.metric("Completed", sum(1 for row in st.session_state["status_rows"] if row["Status"] == "Done"))
            with col4:
                st.metric("Errors", len(st.session_state["processing_errors"]))
    
    # Display detailed progress of each file
    if st.session_state["status_rows"]:
        with status_placeholder.container():
            st.subheader("📋 File Processing Status")
            
            for idx, row in enumerate(st.session_state["status_rows"]):
                col1, col2, col3, col4 = st.columns([3, 2, 3, 2])
                with col1:
                    st.text(f"{row['File'][:30]}..." if len(row['File']) > 30 else row['File'])
                with col2:
                    status_color = {
                        "Queued": "⚪",
                        "Processing": "🟡",
                        "Done": "🟢",
                        "Error": "🔴"
                    }.get(row["Status"], "⚪")
                    st.text(f"{status_color} {row['Status']}")
                with col3:
                    # progress bar
                    progress_val = row.get("Progress", 0)
                    st.progress(progress_val/100, text=f"{progress_val}%")
                with col4:
                    # If the file is completed, display the download button immediately
                    if row["Status"] == "Done" and idx in st.session_state["immediate_download_buttons"]:
                        dl_data = st.session_state["immediate_download_buttons"][idx]
                        mime_type = "application/json" if dl_data["file_extension"] == ".json" else "application/octet-stream"
                        
                        # Get file size
                        content = dl_data["content"]
                        if isinstance(content, bytes):
                            size_kb = len(content) / 1024
                        elif isinstance(content, str):
                            size_kb = len(content.encode('utf-8')) / 1024
                        else:
                            size_kb = 0
                        
                        # Create download button
                        st.download_button(
                            label=f"⬇️ {size_kb:.1f}KB",
                            data=content,
                            file_name=dl_data["filename"],
                            mime=mime_type,
                            key=f"immediate_dl_{idx}",
                            help=f"Download {dl_data['filename']}"
                        )
                    else:
                        # Display file operations
                        if idx < len(st.session_state.get("job_operations", [])):
                            ops = st.session_state["job_operations"][idx]
                            ops_text = ""
                            if ops.get("anonymize"):
                                ops_text += "🛡️"
                            if ops.get("remove_pii"):
                                ops_text += "🧹"
                            if ops.get("extract_json"):
                                ops_text += "🧾"
                            st.text(ops_text if ops_text else "—")
    
    # Display immediate download area
    with immediate_download_container:
        if st.session_state["immediate_download_buttons"]:
            st.subheader("📥 Immediate Download (Available Now)")
            st.caption("Files are available for download as soon as they are processed")
            
            # Sort by completion time
            sorted_downloads = sorted(
                st.session_state["immediate_download_buttons"].items(),
                key=lambda x: x[1].get("processed_time", "")
            )
            
            # Display download buttons by column
            cols_per_row = 3
            for i in range(0, len(sorted_downloads), cols_per_row):
                row_cols = st.columns(cols_per_row)
                for j in range(cols_per_row):
                    idx = i + j
                    if idx < len(sorted_downloads):
                        key, dl_data = sorted_downloads[idx]
                        with row_cols[j]:
                            # Create file card
                            mime_type = "application/json" if dl_data["file_extension"] == ".json" else "application/octet-stream"
                            
                            # Get file size
                            content = dl_data["content"]
                            if isinstance(content, bytes):
                                size_mb = len(content) / 1024 / 1024
                            elif isinstance(content, str):
                                size_mb = len(content.encode('utf-8')) / 1024 / 1024
                            else:
                                size_mb = 0
                            
                            # Create operation label
                            ops_list = []
                            ops = dl_data.get("operations", {})
                            if ops.get("anonymize"):
                                ops_list.append("A")
                            if ops.get("remove_pii"):
                                ops_list.append("P")
                            if ops.get("extract_json"):
                                ops_list.append("J")
                            
                            ops_str = " | ".join(ops_list) if ops_list else "Raw"
                            
                            # Display files
                            with st.container():
                                st.markdown(f"**{dl_data['filename'][:20]}...**" if len(dl_data['filename']) > 20 else f"**{dl_data['filename']}**")
                                st.caption(f"From: {dl_data['original_name'][:15]}..." if len(dl_data['original_name']) > 15 else f"From: {dl_data['original_name']}")
                                st.caption(f"Ops: {ops_str} | {size_mb:.2f}MB | {dl_data.get('processed_time', '')}")
                                
                                # Download button
                                st.download_button(
                                    label="⬇️ Download",
                                    data=content,
                                    file_name=dl_data["filename"],
                                    mime=mime_type,
                                    key=f"card_dl_{key}",
                                    use_container_width=True
                                )
    
    if total_files:
        if completed_count < total_files:
            pass 
        else:
            progress_placeholder.success(f"✅ All {completed_count}/{total_files} files processed successfully!")
    
    if st.session_state["processing_done"] and not processing_active:
        st.session_state["processing_thread"] = None
        st.session_state["processing_queue"] = None
        st.session_state["processing_started"] = False
        
        processed_files = sorted(st.session_state["processing_results"], key=lambda pf: pf["order"])
        
        if processed_files:
            # Final Processing Summary
            with st.expander("📊 Final Processing Summary", expanded=True):
                summary_data = []
                for pf in processed_files:
                    content = pf["content"]
                    if isinstance(content, bytes):
                        content_size = len(content)
                    elif isinstance(content, str):
                        content_size = len(content.encode('utf-8'))
                    else:
                        content_size = 0
                    
                    metadata = pf.get("metadata") or {}
                    ops = pf.get("operations") or batch_opts
                    ops_list = []
                    if ops.get("anonymize"):
                        ops_list.append("Anonymize")
                    if ops.get("remove_pii"):
                        ops_list.append("Remove PII")
                    if ops.get("extract_json"):
                        ops_list.append("Extract JSON")
                    
                    summary_data.append({
                        "Original File": pf["original_name"],
                        "Processed File": pf["name"],
                        "Output Format": pf["file_extension"],
                        "Size (KB)": round(content_size / 1024, 2) if content_size else "N/A",
                        "Cache": "Yes" if metadata.get("cache_hit") else "No",
                        "Operations": ", ".join(ops_list) if ops_list else "None",
                    })
                
                st.dataframe(pd.DataFrame(summary_data), width="stretch", hide_index=True)
                
                # Zip download
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w") as zip_file:
                    for pf in processed_files:
                        content = pf["content"]
                        if isinstance(content, str):
                            content = content.encode('utf-8')
                        zip_file.writestr(pf["name"], content)
                
                zip_buffer.seek(0)
                
                st.subheader("📦 Download All Files")
                download_filename = f"processed_documents_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
                st.download_button(
                    label="📥 Download All as ZIP",
                    data=zip_buffer,
                    file_name=download_filename,
                    mime="application/zip",
                    width="stretch",
                    help="Download all processed files as a ZIP archive"
                )

    if processing_active:
        time.sleep(0.5)
        st.rerun()

elif process_btn and not uploaded_files:
    st.warning("⚠️ Please upload at least one file to process.")

# Sidebar information
with st.sidebar:
    st.header("ℹ️ About")
    st.markdown(f"""
    This Document Processor allows you to:
    - Upload up to {MAX_FILES} files (.txt, .docx, .pdf)
    - Apply various processing options:
      - **Anonymize**: Remove personal identifiers
      - **Remove PII**: Remove Personally Identifiable Information
      - **Extract to JSON**: Convert document content to JSON format
    - Download processed files immediately as they complete
    """)
    
    st.header("📊 Statistics")
    if uploaded_files:
        st.write(f"Files uploaded: {len(uploaded_files)}/{MAX_FILES}")
        total_size_kb = sum(len(file.getvalue()) for file in uploaded_files) / 1024
        c1, c2 = st.columns(2)
        with c1:
            st.metric(label="Files", value=f"{len(uploaded_files)}/{MAX_FILES}")
        with c2:
            st.metric(label="Total size (KB)", value=f"{total_size_kb:.2f}")
    else:
        st.write("No files uploaded")
    
    st.header("⚙️ Processing Status")
    if st.session_state["processing_started"] and not st.session_state["processing_done"]:
        st.info("Processing in progress…")
        
        # Display real-time statistics
        completed = len(st.session_state.get("processing_results", []))
        errors = len(st.session_state.get("processing_errors", []))
        st.metric("Files Completed", f"{completed}/{st.session_state.get('processing_total', 0)}")
        if errors > 0:
            st.metric("Errors", errors, delta=f"-{errors}")
    elif st.session_state["processing_done"]:
        st.success("Processing completed!")
    elif process_btn and not uploaded_files:
        st.error("Processing failed - no files")
    else:
        st.info("Ready to process")
    
    # Display configuration information
    with st.expander("Configuration Info"):
        st.write("**Supported Operations:**")
        st.json({
            "Anonymize Terms": "Configured at runtime in the UI (⚙️ Anonymization Settings)",
            "PII Patterns": "Email, Phone, SSN, Credit Card, IBAN",
            "Output Formats": "PDF (for anonymized/PII removed), JSON (when extracted)"
        })

# Footer
st.markdown("---")
st.markdown(
    "<div style='text-align: center; color: gray;'>DocGuard v1.0 ©TSA 2025</div>", 
    unsafe_allow_html=True
)