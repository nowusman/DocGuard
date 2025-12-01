# app.py

import io
import json
import logging
import zipfile
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


def _process_file_worker(payload):
    """Isolated worker entrypoint for ProcessPoolExecutor."""
    from document_processor import processor as shared_processor

    return shared_processor.process_document(**payload)


def _derive_output_name(filename: str, anonymize: bool, remove_pii: bool, extract_json: bool) -> str:
    path = Path(filename)
    stem = path.stem or filename
    if extract_json:
        return f"{stem}.json"
    if anonymize or remove_pii:
        return f"{stem}_processed.pdf"
    return filename

# Set page configuration
st.set_page_config(
    page_title="DocGuard",
    page_icon="🛡️",
    layout="wide"
)

# Inject custom CSS
def inject_custom_css():
    css_path = Path(__file__).with_name("styles.css")
    # Preconnect + load Inter via <link> for better performance than @import
    st.markdown(
        """

        <link rel=\"preconnect\" href=\"https://fonts.googleapis.com\">
        <link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>
        <link href=\"https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap\" rel=\"stylesheet\">
        """,
        unsafe_allow_html=True,
    )
    try:
        css = css_path.read_text()
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        logging.warning("Custom styles.css not found at %s; UI will use default Streamlit styles.", css_path)
    except Exception as e:
        logging.exception("Failed to inject custom CSS: %s", e)

inject_custom_css()

# Hero header
# Security: The following HTML is static only; avoid interpolating any user input
# when using unsafe_allow_html=True to prevent XSS.

st.markdown(
    """
    <div class="hero">
      <h1>🛡️ DocGuard</h1>
      <div class="subtitle">Fast anonymization, PII removal, and JSON extraction for your documents · <span class=\"badge\">OCR</span> <span class=\"badge\">PDF/DOCX/TXT</span></div>
    </div>
    """,
    unsafe_allow_html=True,
)


# Size limits are configured in config.py
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
    st.dataframe(df_files, use_container_width=True, hide_index=True)

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
# Apply OCR setting for local processor contexts (workers get the override via options)
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

processing_overrides = {
    "throughput_mode": throughput_mode,
    "verbose_logging": verbose_logging,
    "ocr_enabled": bool(ocr_enabled),
}

# Process
st.header('3. Process & Run')
process_btn = st.button('🚀 Process', type='primary', use_container_width=True)

# Validate processing options
if process_btn:
    if not (anonymize or remove_pii or extract_json):
        st.error("❌ Please select at least one processing option (Anonymize, Remove PII, or Extract to JSON)")

# Processing logic
if process_btn and uploaded_files and size_ok and (anonymize or remove_pii or extract_json):
    with st.spinner("Processing your documents..."):
        processed_files = []
        processing_errors = []
        total_files = len(uploaded_files)
        worker_count = max(1, min(total_files, MAX_WORKERS))
        progress_placeholder = st.empty()
        status_placeholder = st.empty()
        status_rows = []
        future_to_job = {}

        def render_status():
            if status_rows:
                status_placeholder.dataframe(
                    pd.DataFrame(status_rows),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                status_placeholder.empty()

        with ProcessPoolExecutor(max_workers=worker_count) as executor:
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
                future = executor.submit(_process_file_worker, payload)
                status_index = len(status_rows)
                status_rows.append({"File": file.name, "Status": "Processing"})
                future_to_job[future] = {
                    "order": order,
                    "original_name": file.name,
                    "status_index": status_index,
                }

            render_status()
            completed = 0

            for future in as_completed(future_to_job):
                job_info = future_to_job[future]
                completed += 1
                try:
                    processed_content, file_extension, metadata = future.result()
                    output_filename = _derive_output_name(
                        job_info["original_name"],
                        anonymize,
                        remove_pii,
                        extract_json,
                    )
                    processed_files.append({
                        "name": output_filename,
                        "content": processed_content,
                        "original_name": job_info["original_name"],
                        "file_extension": file_extension,
                        "metadata": metadata,
                        "order": job_info["order"],
                    })
                    status_rows[job_info["status_index"]]["Status"] = "Done"
                except Exception as exc:
                    status_rows[job_info["status_index"]]["Status"] = "Error"
                    processing_errors.append(f"Error processing {job_info['original_name']}: {exc}")

                render_status()
                progress_placeholder.info(f"Processed {completed}/{total_files} files…")

        processed_files.sort(key=lambda pf: pf["order"])
        progress_placeholder.success(f"Processed {len(processed_files)}/{total_files} files.")

        if processed_files:
            st.success(f"✅ Successfully processed {len(processed_files)} files!")

            st.subheader("Processing Summary")
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
                summary_data.append({
                    "Original File": pf["original_name"],
                    "Processed File": pf["name"],
                    "Output Format": pf["file_extension"],
                    "Size (KB)": round(content_size / 1024, 2) if content_size else "N/A",
                    "Cache": "Yes" if metadata.get("cache_hit") else "No",
                })
            st.dataframe(pd.DataFrame(summary_data), use_container_width=True, hide_index=True)

            with st.expander("Processing Details"):
                st.write("**Applied Processing Options:**")
                st.json({
                    "Anonymize": anonymize,
                    "Remove PII": remove_pii,
                    "Extract to JSON": extract_json,
                    "Throughput mode": throughput_mode,
                    "Verbose logging": verbose_logging,
                    "OCR enabled": bool(ocr_enabled),
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
                        st.dataframe(pd.DataFrame(timing_rows), use_container_width=True, hide_index=True)
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

                if extract_json and processed_files and isinstance(processed_files[0]["content"], str):
                    st.write("**JSON Output Preview (first file):**")
                    try:
                        json_preview = json.loads(processed_files[0]["content"])
                        st.json(json_preview)
                    except:
                        st.text_area("JSON Content", processed_files[0]["content"][:1000] + "...", height=200)

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w") as zip_file:
                for pf in processed_files:
                    content = pf["content"]
                    if isinstance(content, str):
                        content = content.encode('utf-8')
                    zip_file.writestr(pf["name"], content)

            zip_buffer.seek(0)

            st.header("4. Download Processed Files")
            download_filename = f"processed_documents_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
            st.download_button(
                label="📥 Download All Processed Files",
                data=zip_buffer,
                file_name=download_filename,
                mime="application/zip",
                use_container_width=True,
                help="Download all processed files as a ZIP archive"
            )

            st.subheader("Download Individual Files")
            cols = st.columns(3)
            for idx, pf in enumerate(processed_files):
                with cols[idx % 3]:
                    mime_type = "application/json" if pf["file_extension"] == ".json" else "application/octet-stream"
                    st.download_button(
                        label=f"📄 {pf['name']}",
                        data=pf["content"],
                        file_name=pf["name"],
                        mime=mime_type,
                        key=f"single_{idx}"
                    )

        if processing_errors:
            st.error("Processing Errors:")
            for error in processing_errors:
                st.write(f"• {error}")

elif process_btn and not uploaded_files:
    st.warning("⚠️ Please upload at least one file to process.")

# Sidebar infomation
with st.sidebar:
    st.header("ℹ️ About")
    st.markdown(f"""
    This Document Processor allows you to:
    - Upload up to {MAX_FILES} files (.txt, .docx, .pdf)
    - Apply various processing options:
      - **Anonymize**: Remove personal identifiers
      - **Remove PII**: Remove Personally Identifiable Information
      - **Extract to JSON**: Convert document content to JSON format
    - Download processed files individually or as a ZIP archive
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
    if process_btn and uploaded_files and size_ok and (anonymize or remove_pii or extract_json):
        st.success("Processing completed!")
    elif process_btn and not uploaded_files:
        st.error("Processing failed - no files")
    else:
        st.info("Ready to process")
    
    # Display configuration information
    with st.expander("Configuration Info"):
        st.write("**Supported Operations:**")
        st.json({
            "Anonymize Terms": "Configurable terms from config.py",
            "PII Patterns": "Email, Phone, SSN, Credit Card, IBAN",
            "Output Formats": "PDF (for anonymized/PII removed), JSON (when extracted)"
        })

# Footer
st.markdown("---")
st.markdown(
    "<div style='text-align: center; color: gray;'>DocGuard v1.0 © STC 2025</div>", 
    unsafe_allow_html=True
)
