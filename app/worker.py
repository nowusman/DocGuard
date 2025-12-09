# worker.py

def _process_file_worker(payload):
    """Isolated worker entrypoint for ProcessPoolExecutor."""
    from document_processor import processor as shared_processor
    return shared_processor.process_document(**payload)