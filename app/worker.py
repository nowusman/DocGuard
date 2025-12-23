# worker.py

def _process_file_worker(payload):
    """Isolated worker entrypoint for ProcessPoolExecutor."""
    from document_processor import DocumentProcessor

    if not hasattr(_process_file_worker, "_processor"):
        _process_file_worker._processor = DocumentProcessor()
    return _process_file_worker._processor.process_document(**payload)
