# worker.py

def _process_file_worker(payload):
    """Isolated worker entrypoint for ProcessPoolExecutor."""
    from document_processor import DocumentProcessor

    processor = DocumentProcessor()
    return processor.process_document(**payload)
