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


class CancellableExecutor:
    """Cancellable actuator wrapper"""
    def __init__(self, max_workers):
        self.max_workers = max_workers
        self.executor = None
        self.futures = []
        self.cancelled = False
        self.lock = threading.Lock()
        
    def __enter__(self):
        self.executor = ProcessPoolExecutor(max_workers=self.max_workers)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown(wait=True)

    def shutdown(self, wait=True, cancel_futures=False):
        with self.lock:
            if cancel_futures:
                self.cancelled = True
            if self.executor:
                self.executor.shutdown(wait=wait, cancel_futures=cancel_futures)
    
    def submit(self, fn, *args, **kwargs):
        """Submit task, return None if cancelled"""
        with self.lock:
            if self.cancelled:
                return None
            if self.executor:
                future = self.executor.submit(fn, *args, **kwargs)
                self.futures.append(future)
                return future
        return None
    
    def cancel_all(self):
        """Cancel all unfinished tasks"""
        with self.lock:
            self.cancelled = True
            cancelled_count = 0
            for future in self.futures:
                if not future.done():
                    future.cancel()
                    cancelled_count += 1
            if self.executor:
                self.executor.shutdown(wait=False, cancel_futures=True)
            return cancelled_count


def _run_background_batch(jobs, worker_count, result_queue, cancel_flag):
    """Run ProcessPool work in a background thread and stream updates into a queue."""
    with CancellableExecutor(max_workers=worker_count) as executor:
        future_to_idx = {}
        submitted_count = 0
        
        # Submit the first batch of tasks (up to workr_count)
        for idx, job in enumerate(jobs):
            # Check cancel flag
            if cancel_flag.get("cancel_requested", False):
                executor.shutdown(wait=False, cancel_futures=True)
                # Mark remaining tasks as cancelled
                for j in range(idx, len(jobs)):
                    result_queue.put({
                        "type": "cancel",
                        "index": j,
                        "original_name": jobs[j]["original_name"]
                    })
                break
            
            # Submit task
            future = executor.submit(_process_file_worker, job["payload"])
            if future is None:  
                break
                
            future_to_idx[future] = idx
            result_queue.put({"type": "status", "index": idx, "status": "Processing"})
            submitted_count += 1
            
            # If the maximum number of parallelism has been reached, 
            # wait for some tasks to be completed before continuing to submit
            if len(future_to_idx) >= worker_count:
                # Waiting for at least one task to be completed
                for completed_future in as_completed(future_to_idx.keys()):
                    # Process completed tasks
                    idx = future_to_idx.pop(completed_future)
                    job = jobs[idx]
                    try:
                        processed_content, file_extension, metadata = completed_future.result()
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
                    break  # Continue submitting new tasks after completing one task
        
        # Process the remaining submitted tasks
        for completed_future in as_completed(list(future_to_idx.keys())):
            # Check cancel flag
            if cancel_flag.get("cancel_requested", False):
                pending_futures = [future for future in future_to_idx.keys() if not future.done()]
                executor.shutdown(wait=False, cancel_futures=True)
                cancelled = len(pending_futures)
                if cancelled > 0:
                    # Mark remaining tasks as cancelled
                    for idx in future_to_idx.values():
                        if idx < len(jobs):
                            result_queue.put({
                                "type": "cancel",
                                "index": idx,
                                "original_name": jobs[idx]["original_name"]
                            })
                    result_queue.put({
                        "type": "cancelled", 
                        "submitted": submitted_count, 
                        "total": len(jobs),
                        "cancelled": cancelled
                    })
                break
                
            idx = future_to_idx.pop(completed_future, None)
            if idx is None:
                continue
                
            job = jobs[idx]
            try:
                processed_content, file_extension, metadata = completed_future.result()
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
        
        # If all tasks are completed normally
        if not cancel_flag.get("cancel_requested", False):
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
        "cancel_requested": False,
        "cancel_flag": {"cancel_requested": False},
        "processing_cancelled": False,
        "last_rerun_time": 0,  # Track the time of the last rerun
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
            current_status = st.session_state["status_rows"][idx]["Status"]
            new_status = message.get("status", "Processing")
            
            # Only update if status actually changed
            if current_status != new_status or st.session_state["status_rows"][idx].get("Progress") != 50:
                st.session_state["status_rows"][idx]["Status"] = new_status
                st.session_state["status_rows"][idx]["Progress"] = 50
                updates += 1
        
        elif msg_type == "cancel":
            # Processing cancelled tasks
            if idx is not None and idx < len(st.session_state["status_rows"]):
                current_status = st.session_state["status_rows"][idx]["Status"]
                if current_status in ["Queued", "Processing"]:
                    st.session_state["status_rows"][idx]["Status"] = "Cancelled"
                    st.session_state["status_rows"][idx]["Progress"] = 0
                    updates += 1
        
        elif msg_type == "cancelled":
            # Process batch cancel
            if not st.session_state["processing_cancelled"]:
                st.session_state["processing_cancelled"] = True
                submitted = message.get("submitted", 0)
                total = message.get("total", 0)
                cancelled = message.get("cancelled", 0)
                st.session_state["processing_errors"].append(
                    f"Processing cancelled by user. {submitted - cancelled} files were processed, {cancelled} files were cancelled."
                )
                updates += 1
        
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
                "status": "Done",
            }

            st.session_state["processing_results"].append(result_data)
            
            if idx is not None and idx < len(st.session_state["status_rows"]):
                current_status = st.session_state["status_rows"][idx]["Status"]
                if current_status != "Done" or st.session_state["status_rows"][idx].get("Progress") != 100:
                    st.session_state["status_rows"][idx]["Status"] = "Done"
                    st.session_state["status_rows"][idx]["Progress"] = 100
                    updates += 1
        
        elif msg_type == "error":
            if idx is not None and idx < len(st.session_state["status_rows"]):
                current_status = st.session_state["status_rows"][idx]["Status"]
                if current_status != "Error" or st.session_state["status_rows"][idx].get("Progress") != 0:
                    st.session_state["status_rows"][idx]["Status"] = "Error"
                    st.session_state["status_rows"][idx]["Progress"] = 0
                    updates += 1
            
            error_msg = f"Error processing {message.get('original_name')}: {message.get('error')}"
            if error_msg not in st.session_state["processing_errors"]:
                st.session_state["processing_errors"].append(error_msg)
                updates += 1
        
        elif msg_type == "done" and not st.session_state["processing_done"]:
            st.session_state["processing_done"] = True
            updates += 1
    
    return updates


def _get_available_downloads():
    """Retrieve downloadable files from processe_results, sorted by completion time"""
    if not st.session_state.get("processing_results"):
        return []
    
    # Filter completed results and sort them by processing time
    available_results = [
        result for result in st.session_state["processing_results"]
        if result.get("status") == "Done"
    ]
    
    # Sort by processing time (the most recently completed ones come first)
    return sorted(available_results, key=lambda x: x.get("processed_time", datetime.min), reverse=True)


def _cancel_processing():
    """Cancel the current processing batch."""
    if st.session_state.get("processing_started") and not st.session_state.get("processing_done"):
        st.session_state["cancel_requested"] = True
        st.session_state["cancel_flag"]["cancel_requested"] = True
        st.session_state["processing_cancelled"] = True
        
        # Update the status of all pending tasks
        for idx, row in enumerate(st.session_state["status_rows"]):
            if row["Status"] in ["Queued", "Processing"]:
                st.session_state["status_rows"][idx]["Status"] = "Cancelled"
                st.session_state["status_rows"][idx]["Progress"] = 0
        
        st.info("🛑 Processing cancellation requested. Stopping remaining tasks...")


def _safe_rerun():
    """Safely rerun the Streamlit app with WebSocket error handling."""
    current_time = time.time()
    
    # Prevent excessive reruns (with a minimum interval of 0.5 seconds)
    if current_time - st.session_state.get("last_rerun_time", 0) < 0.5:
        return
    
    st.session_state["last_rerun_time"] = current_time
    
    try:
        st.rerun()
    except Exception as e:
        # Ignore WebSocket-related errors
        if "WebSocket" in str(e) or "Stream is closed" in str(e):
            logging.debug(f"WebSocket closed during rerun: {e}")
        else:
            logging.error(f"Error during rerun: {e}")


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

# Limit the number of files
if uploaded_files and len(uploaded_files) > MAX_FILES:
    st.error(f"You can only upload up to {MAX_FILES} files. Please remove some files.")
    uploaded_files = uploaded_files[:MAX_FILES]

uploaded_file_records = []
if uploaded_files:
    for file in uploaded_files:
        file_bytes = file.getvalue()
        uploaded_file_records.append({
            "file": file,
            "bytes": file_bytes,
            "size": len(file_bytes),
        })

# Validate size limits
size_ok = True
if uploaded_file_records:
    total_bytes = sum(record["size"] for record in uploaded_file_records)
    oversized = [
        (record["file"].name, record["size"])
        for record in uploaded_file_records
        if record["size"] > MAX_FILE_SIZE_MB * 1024 * 1024
    ]
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

# Display uploaded file information
if uploaded_file_records:
    st.subheader("Uploaded Files")
    file_info = []
    for i, record in enumerate(uploaded_file_records):
        file = record["file"]
        file_info.append({
            "No.": i+1,
            "File Name": file.name,
            "File Type": file.type if hasattr(file, 'type') else "Unknown",
            "Size (KB)": round(record["size"] / 1024, 2)
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
col1, col2 = st.columns([3, 1])

with col1:
    process_btn = st.button(
        '🚀 Process',
        type='primary',
        width="stretch",
        disabled=st.session_state["processing_started"] and not st.session_state["processing_done"],
    )

with col2:
    # Display stop button (only displayed when processing is in progress and incomplete)
    if st.session_state["processing_started"] and not st.session_state["processing_done"]:
        stop_btn = st.button(
            '🛑 Stop Processing',
            type='secondary',
            width="stretch",
            on_click=_cancel_processing,
        )

# Validate processing options
if process_btn and not (anonymize or remove_pii or extract_json):
    st.error("❌ Please select at least one processing option (Anonymize, Remove PII, or Extract to JSON)")

# Create progress display container
progress_placeholder = st.empty()
status_placeholder = st.empty()
immediate_download_container = st.container() 
global_progress_container = st.empty()

if process_btn and uploaded_file_records and size_ok and (anonymize or remove_pii or extract_json):
    if st.session_state["processing_started"] and not st.session_state["processing_done"]:
        st.info("Processing is already running. Please wait for it to finish or stop it first.")
    else:
        # Reset state
        st.session_state["processing_results"] = []
        st.session_state["processing_errors"] = []
        st.session_state["processing_done"] = False
        st.session_state["processing_cancelled"] = False
        st.session_state["cancel_requested"] = False
        st.session_state["cancel_flag"] = {"cancel_requested": False}
        st.session_state["processing_total"] = len(uploaded_file_records)
        
        # Initialization status line, including progress field
        st.session_state["status_rows"] = [
            {
                "File": record["file"].name,
                "Status": "Queued",
                "Progress": 0
            } for record in uploaded_file_records
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
        for order, record in enumerate(uploaded_file_records):
            file = record["file"]
            payload = {
                "file_content": record["bytes"],
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
            args=(jobs, worker_count, result_queue, st.session_state["cancel_flag"]),
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
    
    # Drain the queue for updates
    queue_updates = _drain_result_queue(batch_opts["anonymize"], batch_opts["remove_pii"], batch_opts["extract_json"])
    
    total_files = st.session_state["processing_total"]
    completed_count = len(st.session_state["processing_results"])
    error_count = len(st.session_state["processing_errors"])
    cancelled_count = sum(1 for row in st.session_state["status_rows"] if row["Status"] == "Cancelled")
    processing_count = sum(1 for row in st.session_state["status_rows"] if row["Status"] == "Processing")
    queued_count = sum(1 for row in st.session_state["status_rows"] if row["Status"] == "Queued")
    
    # Only update the global progress if there are updates or if it's the first render
    if queue_updates > 0 or not hasattr(st.session_state, "global_progress_rendered"):
        st.session_state["global_progress_rendered"] = True
        
        # If the processing is cancelled, display the cancellation status
        if st.session_state.get("processing_cancelled"):
            with global_progress_container.container():
                st.warning(f"🛑 Processing cancelled by user. {completed_count} files processed, {cancelled_count} files cancelled.")
        
        # Display global progress bar
        elif total_files > 0:
            progress_ratio = (completed_count + error_count + cancelled_count) / total_files
            with global_progress_container.container():
                st.subheader("📊 Global Progress")
                progress_bar = st.progress(min(progress_ratio, 1.0), text=f"Processed {completed_count}/{total_files} files")
                
                # Progress statistics
                col1, col2, col3, col4, col5 = st.columns(5)
                with col1:
                    st.metric("Queued", queued_count)
                with col2:
                    st.metric("Processing", processing_count)
                with col3:
                    st.metric("Completed", completed_count)
                with col4:
                    st.metric("Errors", error_count)
                with col5:
                    st.metric("Cancelled", cancelled_count)
    
    # Display detailed progress of each file
    if st.session_state["status_rows"]:
        with status_placeholder.container():
            st.subheader("📋 File Processing Status")
            
            # Create a dictionary for quick lookup of results by order
            result_by_order = {res.get("order"): res for res in st.session_state["processing_results"]}
            
            for idx, row in enumerate(st.session_state["status_rows"]):
                col1, col2, col3, col4 = st.columns([3, 2, 3, 2])
                with col1:
                    st.text(f"{row['File'][:30]}..." if len(row['File']) > 30 else row['File'])
                with col2:
                    status_color = {
                        "Queued": "⚪",
                        "Processing": "🟡",
                        "Done": "🟢",
                        "Error": "🔴",
                        "Cancelled": "⚫"
                    }.get(row["Status"], "⚪")
                    st.text(f"{status_color} {row['Status']}")
                with col3:
                    # Progress bar
                    progress_val = row.get("Progress", 0)
                    st.progress(progress_val/100, text=f"{progress_val}%")
                with col4:
                    # If the file is completed, display the download button immediately
                    if row["Status"] == "Done":
                        # Get result from the dictionary for O(1) lookup
                        result = result_by_order.get(idx)
                        
                        if result:
                            # Get file size
                            content = result["content"]
                            if isinstance(content, bytes):
                                size_kb = len(content) / 1024
                            elif isinstance(content, str):
                                size_kb = len(content.encode('utf-8')) / 1024
                            else:
                                size_kb = 0
                            
                            mime_type = "application/json" if result["file_extension"] == ".json" else "application/octet-stream"
                            
                            # Create download button
                            st.download_button(
                                label=f"⬇️ {size_kb:.1f}KB",
                                data=content,
                                file_name=result["name"],
                                mime=mime_type,
                                key=f"status_dl_{idx}",
                                help=f"Download {result['name']}"
                            )
                    else:
                        # Display file operations or cancelled status
                        if row["Status"] == "Cancelled":
                            st.text("🚫")
                        elif idx < len(st.session_state.get("job_operations", [])):
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
        available_downloads = _get_available_downloads()
        
        if available_downloads:
            st.subheader("📥 Immediate Download (Available Now)")
            st.caption("Files are available for download as soon as they are processed")
            
            # Display download button
            cols_per_row = 3
            for i in range(0, len(available_downloads), cols_per_row):
                row_cols = st.columns(cols_per_row)
                for j in range(cols_per_row):
                    idx = i + j
                    if idx < len(available_downloads):
                        result = available_downloads[idx]
                        with row_cols[j]:
                            # Create file card
                            mime_type = "application/json" if result["file_extension"] == ".json" else "application/octet-stream"
                            
                            # Get file size
                            content = result["content"]
                            if isinstance(content, bytes):
                                size_mb = len(content) / 1024 / 1024
                            elif isinstance(content, str):
                                size_mb = len(content.encode('utf-8')) / 1024 / 1024
                            else:
                                size_mb = 0
                            
                            # Create operation label
                            ops_list = []
                            ops = result.get("operations", {})
                            if ops.get("anonymize"):
                                ops_list.append("A")
                            if ops.get("remove_pii"):
                                ops_list.append("P")
                            if ops.get("extract_json"):
                                ops_list.append("J")
                            
                            ops_str = " | ".join(ops_list) if ops_list else "Raw"
                            processed_time = result.get("processed_time", datetime.now())
                            time_str = processed_time.strftime("%H:%M:%S") if isinstance(processed_time, datetime) else str(processed_time)
                            
                            # Display files
                            with st.container():
                                st.markdown(f"**{result['name'][:20]}...**" if len(result['name']) > 20 else f"**{result['name']}**")
                                st.caption(f"From: {result['original_name'][:15]}..." if len(result['original_name']) > 15 else f"From: {result['original_name']}")
                                st.caption(f"Ops: {ops_str} | {size_mb:.2f}MB | {time_str}")
                                
                                # Download button
                                st.download_button(
                                    label="⬇️ Download",
                                    data=content,
                                    file_name=result["name"],
                                    mime=mime_type,
                                    key=f"card_dl_{result['order']}_{i}_{j}",
                                    width="stretch"
                                )
    
    if total_files:
        if completed_count < total_files and not st.session_state["processing_cancelled"]:
            pass 
        elif st.session_state["processing_cancelled"]:
            progress_placeholder.warning(f"🛑 Processing cancelled. {completed_count} of {total_files} files were processed.")
        else:
            progress_placeholder.success(f"✅ All {completed_count}/{total_files} files processed successfully!")
    
    if st.session_state["processing_done"] and not processing_active:
        st.session_state["processing_thread"] = None
        st.session_state["processing_queue"] = None
        st.session_state["processing_started"] = False
        
        processed_files = sorted(st.session_state["processing_results"], key=lambda pf: pf["order"])
        
        if processed_files:
            # Final Processing Summary
            if not st.session_state.get("processing_cancelled"):
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
                    effective_terms = batch_opts.get("anonymize_terms", parsed_anonymize_terms)
                    _replace_raw = batch_opts.get("anonymize_replace", anonymize_replace_input)
                    effective_replace = _replace_raw if _replace_raw != "" else " "
                    
                    with st.expander("Processing Details"):
                        st.write("**Applied Processing Options:**")
                        st.json({
                            "Anonymize": batch_opts.get("anonymize", False),
                            "Remove PII": batch_opts.get("remove_pii", False),
                            "Extract to JSON": batch_opts.get("extract_json", False),
                            "Throughput mode": batch_opts.get("throughput_mode", False),
                            "Verbose logging": batch_opts.get("verbose_logging", False),
                            "OCR enabled": batch_opts.get("ocr_enabled", False),
                            "Anonymize terms (effective)": effective_terms,
                            "Anonymize replace (effective)": effective_replace,
                        })

                        if processed_files and processed_files[0].get("metadata"):
                            first_meta = processed_files[0]["metadata"]
                            timing = first_meta.get("timing", {})
                            st.write(f"**Timing (first file: {processed_files[0]['original_name']})**")
                            if timing:
                                timing_rows = [
                                    {"Step": key.replace("_", " ").title(), "Seconds": round(value, 3)}
                                    for key, value in timing.items()
                                ]
                                st.dataframe(pd.DataFrame(timing_rows), width="stretch", hide_index=True)
                            else:
                                st.info("Timing data not available for this file.")
                            st.caption(f"Throughput mode applied: {'Yes' if first_meta.get('throughput_mode') else 'No'}")
                            st.write("**Engine & Cache**")
                            st.write(f"Cache hit: {'Yes' if first_meta.get('cache_hit') else 'No'}")
                            pdf_engine = first_meta.get('pdf_engine')
                            if pdf_engine:
                                st.write(f"PDF engine: {pdf_engine}")
                            ocr_meta = first_meta.get("ocr") or {}
                            if ocr_meta:
                                st.write("**OCR details**")
                                st.write(
                                    f"Engine: {ocr_meta.get('engine', 'unknown')} · "
                                    f"Images processed: {ocr_meta.get('images_processed', 0)} · "
                                    f"Skipped: {ocr_meta.get('images_skipped', 0)} "
                                    f"(max per doc: {ocr_meta.get('max_images_per_doc', 'N/A')})"
                                )
                            ner_mode = first_meta.get("ner_mode")
                            if ner_mode:
                                st.write(f"NER mode: {ner_mode}")

                        if batch_opts.get("extract_json") and processed_files and isinstance(processed_files[0]["content"], str):
                            st.write("**JSON Output Preview (first file):**")
                            try:
                                json_preview = json.loads(processed_files[0]["content"])
                                st.json(json_preview)
                            except:
                                st.text_area("JSON Content", processed_files[0]["content"][:1000] + "...", height=200)

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
            else:
                # If the processing is cancelled, display partial result download options
                with st.expander("📊 Partial Results", expanded=True):
                    st.warning("Processing was cancelled. Here are the files that were completed before cancellation.")
                    
                    if processed_files:
                        summary_data = []
                        for pf in processed_files:
                            content = pf["content"]
                            if isinstance(content, bytes):
                                content_size = len(content)
                            elif isinstance(content, str):
                                content_size = len(content.encode('utf-8'))
                            else:
                                content_size = 0
                            
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
                                "Operations": ", ".join(ops_list) if ops_list else "None",
                            })
                        
                        st.dataframe(pd.DataFrame(summary_data), width="stretch", hide_index=True)
                        
                        # Partial Results ZIP Download
                        zip_buffer = io.BytesIO()
                        with zipfile.ZipFile(zip_buffer, "w") as zip_file:
                            for pf in processed_files:
                                content = pf["content"]
                                if isinstance(content, str):
                                    content = content.encode('utf-8')
                                zip_file.writestr(pf["name"], content)
                        
                        zip_buffer.seek(0)
                        
                        st.download_button(
                            label="📥 Download Completed Files as ZIP",
                            data=zip_buffer,
                            file_name=f"partial_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                            mime="application/zip",
                            width="stretch",
                            help="Download only the files that were completed before cancellation"
                        )

    if processing_active:
        time.sleep(1.5)  
        _safe_rerun()  

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
    - Stop long-running batch processing at any time
    - Download processed files immediately as they complete
    """)
    
    st.header("📊 Statistics")
    if uploaded_files:
        st.write(f"Files uploaded: {len(uploaded_files)}/{MAX_FILES}")
        total_size_kb = sum(record["size"] for record in uploaded_file_records) / 1024
        c1, c2 = st.columns(2)
        with c1:
            st.metric(label="Files", value=f"{len(uploaded_files)}/{MAX_FILES}")
        with c2:
            st.metric(label="Total size (KB)", value=f"{total_size_kb:.2f}")
    else:
        st.write("No files uploaded")
    
    st.header("⚙️ Processing Status")
    if st.session_state["processing_started"] and not st.session_state["processing_done"]:
        if st.session_state.get("processing_cancelled"):
            st.warning("Processing cancelled")
        else:
            st.info("Processing in progress…")
            
            # Display real-time statistics
            completed = len(st.session_state.get("processing_results", []))
            errors = len(st.session_state.get("processing_errors", []))
            cancelled = sum(1 for row in st.session_state.get("status_rows", []) if row.get("Status") == "Cancelled")
            
            st.metric("Files Completed", f"{completed}/{st.session_state.get('processing_total', 0)}")
            if errors > 0:
                st.metric("Errors", errors, delta=f"-{errors}")
            if cancelled > 0:
                st.metric("Cancelled", cancelled)
                
            # Display a stop button in the sidebar
            if st.button("🛑 Stop Processing", type="secondary", use_container_width=True):
                _cancel_processing()
                _safe_rerun()
                
    elif st.session_state["processing_done"]:
        if st.session_state.get("processing_cancelled"):
            st.warning("Processing was cancelled")
        else:
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
