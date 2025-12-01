# document_processor.py

import base64
import hashlib
import io
import json
import os
import re
import tempfile
import html
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime

import PyPDF2
import fitz  # PyMuPDF
import numpy as np
import pandas as pd
import pdfplumber
import spacy
import zipfile
import xml.etree.ElementTree as ET
from PIL import Image as PILImage, ImageStat
from docx import Document
from docx.shared import Inches
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from time import perf_counter

from config import (
    ANONYMIZE_TERMS,
    ANONYMIZE_REPLACE,
    PII_PATTERNS,
    JSON_SCHEMA,
    OCR_CONFIG,
    PDF_HEADER_RATIO,
    THROUGHPUT_MODE,
    OCR_MAX_IMAGES_PER_DOC,
    OCR_RENDER_SCALE,
    VERBOSE_LOGGING,
    PDF_ENGINE,
    OCR_ENGINE,
    MAX_CACHE_ITEMS,
)

class DocumentProcessor:
    def __init__(self):
        self.supported_formats = ['.txt', '.docx', '.pdf']
        self.verbose_logging = VERBOSE_LOGGING
        self.throughput_mode = THROUGHPUT_MODE
        self._timing = {}
        self._ocr_images_processed = 0
        self._ocr_images_skipped = 0
        self.max_cache_items = MAX_CACHE_ITEMS
        self._cache = OrderedDict()
        self._paddle_ocr = None
        self.ocr_engine = OCR_ENGINE
        # Load spaCy model
        try:
            self.nlp = spacy.load("en_core_web_sm")
        except OSError:
            print("Warning: spaCy model 'en_core_web_sm' not found. Please install it.")
            self.nlp = None
        
        # Check OCR availability
        self.ocr_available = self._check_ocr_availability()
        
        # Check the availability of the table extraction library
        self.table_extraction_available = self._check_table_extraction_availability()

        self.pdfplumber_available = self._check_pdfplumber()
        self.pymupdf_available = self._check_pymupdf()

    def _log(self, message: str):
        if self.verbose_logging:
            print(message)

    def _reset_timing(self):
        self._timing = {}
        self._ocr_images_processed = 0
        self._ocr_images_skipped = 0

    def _record_timing(self, key: str, duration: float):
        if duration is None:
            return
        self._timing[key] = self._timing.get(key, 0.0) + float(duration)

    def _build_cache_key(self, file_content, anonymize, remove_pii, extract_json, options):
        if not self.max_cache_items:
            return None
        hasher = hashlib.sha256()
        if isinstance(file_content, (bytes, bytearray)):
            file_bytes = bytes(file_content)
        else:
            file_bytes = str(file_content).encode('utf-8', errors='ignore')
        hasher.update(file_bytes)
        normalized = {
            'anonymize': bool(anonymize),
            'remove_pii': bool(remove_pii),
            'extract_json': bool(extract_json),
            'throughput_mode': bool(self.throughput_mode),
            'ocr_enabled': bool(OCR_CONFIG.get('enabled', True)),
            'options': options or {}
        }
        hasher.update(json.dumps(normalized, sort_keys=True, default=str).encode('utf-8'))
        return hasher.hexdigest()

    def _get_cached_result(self, cache_key):
        if not cache_key or not self._cache:
            return None
        cached = self._cache.get(cache_key)
        if cached:
            self._cache.move_to_end(cache_key)
        return cached

    def _store_cache_result(self, cache_key, result):
        if not cache_key or not self.max_cache_items:
            return
        content, extension, metadata = result
        self._cache[cache_key] = (content, extension, deepcopy(metadata))
        self._cache.move_to_end(cache_key)
        if len(self._cache) > self.max_cache_items:
            self._cache.popitem(last=False)

    def _finalize_metadata(self, metadata):
        metadata = metadata or {}
        metadata['timing'] = dict(self._timing)
        metadata['throughput_mode'] = self.throughput_mode
        metadata['cache_hit'] = metadata.get('cache_hit', False)
        metadata['ocr'] = {
            'engine': self.ocr_engine if self.ocr_available else 'unavailable',
            'images_processed': self._ocr_images_processed,
            'images_skipped': self._ocr_images_skipped,
            'max_images_per_doc': OCR_MAX_IMAGES_PER_DOC,
            'enabled': bool(OCR_CONFIG.get('enabled', True)) and not self.throughput_mode,
        }
        return metadata

    def _finalize_result(self, content, extension, metadata):
        return content, extension, self._finalize_metadata(metadata)

    def _finalize_with_cache(self, content, extension, metadata, cache_key):
        result = self._finalize_result(content, extension, metadata)
        if cache_key:
            self._store_cache_result(cache_key, result)
        return result
    
    def _check_ocr_availability(self):
        """
        Check OCR availability
        """
        try:
            from paddleocr import PaddleOCR

            self._paddle_ocr = PaddleOCR(
                lang="en",
                use_angle_cls=False,
                show_log=False,
                use_gpu=False,
            )
            self.ocr_engine = "paddle"
            return True
        except ImportError:
            print("Warning: PaddleOCR not available. Install paddleocr for OCR support.")
            self._paddle_ocr = None
            return False
        except Exception as exc:
            print(f"Warning: PaddleOCR initialization failed: {exc}")
            self._paddle_ocr = None
            return False
    
    def _check_table_extraction_availability(self):
        """
        Check the availability of the table extraction library
        """
        try:
            import camelot
            return True
        except ImportError:
            print("Warning: Camelot not available. PDF table extraction will be limited.")
            return False
        except Exception as e:
            print(f"Warning: Camelot initialization failed: {e}")
            return False
    
    def process_document(self, file_content, filename, anonymize=False, remove_pii=False, extract_json=False, options=None):
        """
        The main functions for processing documents
        """
        options = options or {}
        self.verbose_logging = options.get('verbose_logging', VERBOSE_LOGGING)
        self.throughput_mode = options.get('throughput_mode', THROUGHPUT_MODE)
        if 'ocr_enabled' in options:
            OCR_CONFIG['enabled'] = bool(options['ocr_enabled'])
        self._reset_timing()
        cache_key = None
        cached_result = None
        if self.max_cache_items:
            cache_key = self._build_cache_key(
                file_content,
                anonymize,
                remove_pii,
                extract_json,
                options,
            )
            cached_result = self._get_cached_result(cache_key)
            if cached_result:
                cached_content, cached_extension, cached_metadata = cached_result
                metadata_copy = deepcopy(cached_metadata)
                metadata_copy['cache_hit'] = True
                return cached_content, cached_extension, metadata_copy

        file_extension = f".{filename.split('.')[-1].lower()}"
        
        # Read document content
        if file_extension == '.txt':
            content, metadata = self._read_txt(file_content)
        elif file_extension == '.docx':
            content, metadata = self._read_docx(file_content)
        elif file_extension == '.pdf':
            content, metadata = self._read_pdf(file_content)
        else:
            raise ValueError(f"Unsupported file format: {file_extension}")
        
        # Processing Options
        processing_info = {
            'anonymized': anonymize,
            'pii_removed': remove_pii,
            'extracted_to_json': extract_json
        }
        
        original_content = content
        
        # DOCX files, handle byte data when applying processing options
        if file_extension == '.docx':
            if anonymize or remove_pii:
                
                processed_bytes = file_content  
                
                if anonymize:
                    processed_bytes = self._process_docx_xml(processed_bytes, 'anonymize')
                
                if remove_pii:
                    processed_bytes = self._process_docx_xml(processed_bytes, 'remove_pii')
                
                if anonymize or remove_pii:
                    doc = Document(io.BytesIO(processed_bytes))
                    full_text = []
                    for paragraph in doc.paragraphs:
                        full_text.append(paragraph.text)
                    for table in doc.tables:
                        for row in table.rows:
                            for cell in row.cells:
                                full_text.append(cell.text)
                    content = '\n'.join(full_text)
                    
                    if extract_json:
                        result = self._extract_to_json(content, filename, file_extension, processing_info, metadata)
                        return self._finalize_with_cache(result, '.json', metadata, cache_key)
                    else:
                        pdf_content = self._create_pdf_with_layout(content, filename, file_content, metadata)
                        return self._finalize_with_cache(pdf_content, '.pdf', metadata, cache_key)
            
            if extract_json:
                result = self._extract_to_json(content, filename, file_extension, processing_info, metadata)
                return self._finalize_with_cache(result, '.json', metadata, cache_key)
            else:
                pdf_content = self._create_pdf_with_layout(content, filename, file_content, metadata)
                return self._finalize_with_cache(pdf_content, '.pdf', metadata, cache_key)
        
        else:
            # TXT and PDF files, use the existing string processing logic
            if anonymize:
                content = self._apply_anonymization(content, file_extension, file_content)
            
            if remove_pii:
                content = self._remove_pii(content, file_extension, file_content)
            
            if extract_json:
                result = self._extract_to_json(content, filename, file_extension, processing_info, metadata)
                return self._finalize_with_cache(result, '.json', metadata, cache_key)
            else:
                if anonymize or remove_pii:
                    if file_extension == '.txt':
                        pdf_content = self._create_pdf(content, filename)
                        return self._finalize_with_cache(pdf_content, '.pdf', metadata, cache_key)
                    else:
                        pdf_content = self._create_pdf_with_layout(content, filename, file_content, metadata)
                        return self._finalize_with_cache(pdf_content, '.pdf', metadata, cache_key)
                else:
                    return self._finalize_with_cache(file_content, file_extension, metadata, cache_key)
    
    def _read_txt(self, file_content):
        """Read TXT file"""
        start_time = perf_counter()
        if isinstance(file_content, bytes):
            content = file_content.decode('utf-8')
        else:
            content = file_content
            
        metadata = {
            'text_content': content,
            'tables': [],
            'images': []
        }
        self._record_timing('read_txt', perf_counter() - start_time)
        return content, metadata
    
    def _read_docx(self, file_content):
        """Read DOCX file"""
        start_time = perf_counter()
        doc = Document(io.BytesIO(file_content))
        full_text = []
        tables_data = []
        images_data = []
        
        # Read paragraph
        for paragraph in doc.paragraphs:
            full_text.append(paragraph.text)
        
        # Read talbe
        for table_idx, table in enumerate(doc.tables):
            table_data = []
            for row in table.rows:
                row_data = []
                for cell in row.cells:
                    row_data.append(cell.text)
                table_data.append(row_data)
            tables_data.append({
                'table_index': table_idx,
                'data': table_data,
                'rows': len(table.rows),
                'cols': len(table.columns) if hasattr(table, 'columns') else len(table.rows[0].cells) if table.rows else 0
            })
            
            for row in table_data:
                full_text.append(' | '.join(row))
        
        # Extract images
        images_data = self._extract_images_from_docx(doc, file_content)
        
        content = '\n'.join(full_text)
        metadata = {
            'text_content': content,
            'tables': tables_data,
            'images': images_data,
            'paragraphs': [p.text for p in doc.paragraphs if p.text.strip()]
        }
        
        self._record_timing('read_docx', perf_counter() - start_time)
        return content, metadata
    
    def _read_pdf_fallback(self, file_content):
        """Read PDF file"""
        start_time = perf_counter()
        pdf_file = io.BytesIO(file_content)
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        text_chunks = []
        tables_data = []
        images_data = []
        
        # Save PDF to temporary file for table extraction
        temp_pdf_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_pdf:
                temp_pdf.write(file_content)
                temp_pdf_path = temp_pdf.name
            
            for page_num, page in enumerate(pdf_reader.pages):
                page_text = page.extract_text()
                if page_text:
                    text_chunks.append(page_text)
            
            if not self.throughput_mode:
                tables_start = perf_counter()
                tables_data = self._extract_tables_from_pdf(temp_pdf_path)
                self._record_timing('table_extraction', perf_counter() - tables_start)
            
            # Extract images
            try:
                # images_data = self._extract_images_from_pdf(pdf_reader)
                images_data = self.extract_images_with_pdfplumber_locations(temp_pdf_path)
            except Exception as e:
                print(f"Warning: Could not extract images from PDF: {e}")
        
        except Exception as e:
            print(f"Error processing PDF: {e}")
            # If the table extraction fails, go back to extracting only text
            for page_num, page in enumerate(pdf_reader.pages):
                page_text = page.extract_text()
                if page_text:
                    text_chunks.append(page_text)
        
        finally:
            self._log(f"Clear temp file:{temp_pdf_path}")
            # Clear temp files
            if temp_pdf_path and os.path.exists(temp_pdf_path):
                try:
                    os.unlink(temp_pdf_path)
                except:
                    pass
        
        text = "\n".join(text_chunks)
        metadata = {
            'text_content': text,
            'tables': tables_data,
            'images': images_data,
            'pdf_engine': 'pypdf2_fallback'
        }
        
        self._record_timing('read_pdf', perf_counter() - start_time)
        return text, metadata


    #############################3
    def _read_pdf(self, file_content):
        """Entry point for PDF reads with PyMuPDF single-pass when available."""
        if self.pymupdf_available:
            try:
                return self._read_pdf_optimized(file_content)
            except Exception as exc:
                self._log(f"PyMuPDF single-pass failed, falling back: {exc}")
        return self._read_pdf_pdfplumber(file_content)

    def _read_pdf_optimized(self, file_content):
        """Single-pass PDF extraction using PyMuPDF only."""
        read_start = perf_counter()
        text_chunks = []
        tables_data = []
        images_data = []
        table_index = 0
        header_ratio = PDF_HEADER_RATIO or 0
        file_bytes = bytes(file_content) if isinstance(file_content, (bytes, bytearray)) else str(file_content).encode('utf-8', errors='ignore')

        with fitz.open(stream=file_bytes, filetype="pdf") as pdf_doc:
            for page_num, page in enumerate(pdf_doc):
                rect = page.rect
                clip = rect
                if rect is not None and rect.height > 0:
                    top_offset = rect.height * header_ratio
                    bottom_offset = rect.height * (1 - header_ratio)
                    if bottom_offset > top_offset:
                        clip = fitz.Rect(rect.x0, rect.y0 + top_offset, rect.x1, rect.y0 + bottom_offset)
                try:
                    page_text = page.get_text("text", clip=clip)
                except TypeError:
                    page_text = page.get_text(clip=clip)
                if page_text:
                    text_chunks.append(page_text)

                if not self.throughput_mode:
                    tables_start = perf_counter()
                    new_tables, table_index = self._extract_tables_with_pymupdf(page, page_num, table_index)
                    if new_tables:
                        tables_data.extend(new_tables)
                    self._record_timing('table_extraction', perf_counter() - tables_start)

                page_images = self._extract_images_with_pymupdf(pdf_doc, page, page_num)
                if page_images:
                    images_data.extend(page_images)

        text = "\n".join(text_chunks)
        images_data = self._process_images_with_ocr(images_data)
        metadata = {
            'text_content': text,
            'tables': tables_data,
            'images': images_data,
            'pdf_engine': 'pymupdf_single_pass'
        }
        self._record_timing('read_pdf', perf_counter() - read_start)
        return text, metadata


    def _read_pdf_pdfplumber(self, file_content):
        """Read PDF files and use pdfplumber to accurately filter headers and footers"""
        read_start = perf_counter()
        try:
            import pdfplumber
        except ImportError:
            print("pdfplumber not available, falling back to PyPDF2")
            return self._read_pdf_fallback(file_content)
        
        text_chunks = []
        tables_data = []
        images_data = []
        
        # Save PDF to temporary file
        temp_pdf_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_pdf:
                temp_pdf.write(file_content)
                temp_pdf_path = temp_pdf.name
            
            # Extracting Text with pdfplumber
            with pdfplumber.open(temp_pdf_path) as pdf:
                for page in pdf.pages:
                    # 
                    page_height = page.height
                    # header_region = (0, 0, page.width, page_height * 0.1)  # 顶部10%
                    # footer_region = (0, page_height * 0.9, page.width, page_height)  # 底部10%
                    
                    # Extract text from non header and footer areas
                    # main_region = page.within_bbox((0, page_height * 0.1, page.width, page_height * 0.9))
                    header_ratio = PDF_HEADER_RATIO
                    main_region = page.within_bbox((0, page_height * header_ratio, page.width, page_height * (1 - header_ratio)))
                    page_text = main_region.extract_text()
                    
                    if page_text:
                        text_chunks.append(page_text)
            
            # Proportion extraction table (still using the original method)
            if not self.throughput_mode:
                tables_start = perf_counter()
                tables_data = self._extract_tables_from_pdf(temp_pdf_path)
                self._record_timing('table_extraction', perf_counter() - tables_start)
            
            # Extract images
            # pdf_file = io.BytesIO(file_content)
            # pdf_reader = PyPDF2.PdfReader(pdf_file)
            try:
                # images_data = self._extract_images_from_pdf(pdf_reader)
                images_data = self.extract_images_with_pdfplumber_locations(temp_pdf_path)
            except Exception as e:
                print(f"Warning: Could not extract images from PDF: {e}")
        
        except Exception as e:
            print(f"Error processing PDF with pdfplumber: {e}")
            # back to old read_pdf
            return self._read_pdf_fallback(file_content)
        
        finally:
            self._log(f"Clear temp file:{temp_pdf_path}")
            if temp_pdf_path and os.path.exists(temp_pdf_path):
                try:
                    os.unlink(temp_pdf_path)
                except:
                    pass
        
        text = "\n".join(text_chunks)
        metadata = {
            'text_content': text,
            'tables': tables_data,
            'images': images_data
        }
        
        metadata['pdf_engine'] = 'pdfplumber'
        self._record_timing('read_pdf', perf_counter() - read_start)
        return text, metadata

    #############################3

    def _extract_tables_with_pymupdf(self, page, page_num, start_index):
        tables = []
        table_offset = 0
        try:
            finder = page.find_tables()
            if finder is None:
                return tables, start_index
            if hasattr(finder, 'tables'):
                table_list = finder.tables or []
            elif isinstance(finder, (list, tuple)):
                table_list = list(finder)
            else:
                table_list = [finder]
            for table in table_list:
                try:
                    data = table.extract()
                except Exception:
                    data = table.to_list() if hasattr(table, 'to_list') else None
                if not data:
                    continue
                rows = len(data)
                cols = len(data[0]) if rows else 0
                tables.append({
                    'table_index': start_index + table_offset,
                    'data': data,
                    'rows': rows,
                    'cols': cols,
                    'page': page_num + 1
                })
                table_offset += 1
        except Exception as exc:
            self._log(f"PyMuPDF table extraction failed on page {page_num + 1}: {exc}")
        return tables, start_index + table_offset

    def _extract_images_with_pymupdf(self, doc, page, page_num):
        images = []
        seen_xrefs = set()
        try:
            image_list = page.get_images(full=True) or []
        except Exception as exc:
            self._log(f"PyMuPDF image listing failed on page {page_num + 1}: {exc}")
            return images
        for img_idx, img in enumerate(image_list):
            xref = img[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)
            pix = self._extract_image_with_pymupdf(doc, page_num, img_idx, bbox=None, xref=xref)
            if not pix:
                continue
            try:
                image_bytes = pix.tobytes("png")
            except Exception:
                continue
            finally:
                pix = None
            image_info = {
                "page": page_num + 1,
                "type": "pdf_embedded_image",
                "description": f"Image on page {page_num + 1}",
                "image_data": image_bytes,
                "image_format": self._get_image_format(image_bytes),
                "extracted_text": "",
                "ocr_applied": False,
            }
            images.append(image_info)
        return images

    def _extract_tables_from_pdf(self, pdf_path):
        """
        Extract Tables from PDF - Using Camelot
        """
        if self.throughput_mode:
            return []

        tables_data = []
        
        if not self.table_extraction_available:
            print("Table extraction not available. Install camelot-py for PDF table extraction.")
            return tables_data
        
        try:
            import camelot
            
            # # 尝试使用stream模式（基于文本的表格）
            # try:
            #     tables_stream = camelot.read_pdf(pdf_path, flavor='stream', pages='all')
            #     print(f"Found {len(tables_stream)} tables using stream method")
                
            #     for i, table in enumerate(tables_stream):
            #         table_data = self._process_camelot_table(table, i, 'stream')
            #         if table_data:
            #             tables_data.append(table_data)
            # except Exception as e:
            #     print(f"Stream table extraction failed: {e}")
            
            # 尝试使用lattice模式（基于线的表格）
            try:
                tables_lattice = camelot.read_pdf(pdf_path, flavor='lattice', pages='all')
                self._log(f"Found {len(tables_lattice)} tables using lattice method")
                
                for i, table in enumerate(tables_lattice):
                    # Check if this table has already been extracted (to avoid duplication)
                    if not self._is_table_duplicate(table, tables_data):
                        table_data = self._process_camelot_table(table, i + len(tables_data), 'lattice')
                        if table_data:
                            tables_data.append(table_data)
            except Exception as e:
                print(f"Lattice table extraction failed: {e}")
            
            # If neither way finds the table, try using simple text analysis
            if not tables_data:
                tables_data = self._extract_tables_from_text(pdf_path)
            
        except Exception as e:
            print(f"Error extracting tables from PDF: {e}")
            # Going back to simple text analysis
            tables_data = self._extract_tables_from_text(pdf_path)
        
        return tables_data
    
    def _process_camelot_table(self, table, table_index, method):
        """
        Processing Camelot extracted tables
        """
        try:
            df = table.df
            
            table_data = []
            for _, row in df.iterrows():
                table_data.append(row.tolist())
            
            accuracy = table.accuracy
            whitespace = table.whitespace
            order = table.order
            page = table.page
            
            table_info = {
                'table_index': table_index,
                'data': table_data,
                # 'method': method,
                # 'accuracy': accuracy,
                # 'whitespace': whitespace,
                'order': order,
                'page': page,
                'shape': df.shape
                # ,
                # 'extraction_method': 'camelot'
            }
            
            return table_info
            
        except Exception as e:
            print(f"Error processing Camelot table {table_index}: {e}")
            return None
    
    def _is_table_duplicate(self, new_table, existing_tables):
        """
        Check if the table is duplicated
        """
        if not existing_tables:
            return False
        
        new_data = new_table.df.values.tolist()
        
        for existing_table in existing_tables:
            existing_data = existing_table.get('data', [])
            
            if len(new_data) == len(existing_data) and len(new_data) > 0:
                if len(new_data[0]) == len(existing_data[0]):
                    match_count = 0
                    for i in range(min(3, len(new_data))):
                        if new_data[i] == existing_data[i]:
                            match_count += 1
                    
                    if match_count >= 2:  
                        return True
        
        return False
    
    def _extract_tables_from_text(self, pdf_path):
        """
        Extracting Tables from PDF Text
        """
        tables_data = []
        
        try:
            # Extracting Text with PyPDF2
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                text_chunks = []
                
                for page_num, page in enumerate(pdf_reader.pages):
                    page_text = page.extract_text()
                    if page_text:
                        text_chunks.append(page_text)
                
                lines = "\n".join(text_chunks).split('\n')
                current_table = []
                in_table = False
                
                for i, line in enumerate(lines):
                    line_stripped = line.strip()
                    
                    # Heuristic rules for table detection:
                    # 1. Contains multiple consecutive spaces or tabs
                    # 2. Contains multiple vertical characters
                    # 3. Similar line length
                    
                    if re.search(r'(\s{2,}.*){3,}', line) or '|' in line:
                        if not in_table:
                            in_table = True
                            current_table = []
                        
                        if '|' in line:
                            row_data = [cell.strip() for cell in line.split('|')]
                        else:
                            row_data = [cell.strip() for cell in re.split(r'\s{2,}', line) if cell.strip()]
                        
                        current_table.append(row_data)
                    else:
                        if in_table and len(current_table) >= 2:  
                            table_info = {
                                'table_index': len(tables_data),
                                'data': current_table,
                                'method': 'text_analysis',
                                'extraction_method': 'text_heuristic'
                            }
                            tables_data.append(table_info)
                        
                        in_table = False
                        current_table = []
                
                # Last table
                if in_table and len(current_table) >= 2:
                    table_info = {
                        'table_index': len(tables_data),
                        'data': current_table,
                        'method': 'text_analysis',
                        'extraction_method': 'text_heuristic'
                    }
                    tables_data.append(table_info)
            
        except Exception as e:
            print(f"Error extracting tables from text: {e}")
        
        return tables_data
    
    def _apply_anonymization(self, content, file_extension, original_content):
        """Application anonymization processing - only for TXT and PDF"""
        
        if isinstance(content, bytes):
            content = content.decode('utf-8')
            
        anonymized_content = content
        for term in ANONYMIZE_TERMS:
            anonymized_content = re.sub(
                re.escape(term), 
                ANONYMIZE_REPLACE, 
                anonymized_content, 
                flags=re.IGNORECASE
            )
        
        return anonymized_content
    
    def _remove_pii(self, content, file_extension, original_content):
        """Remove PII information - for TXT and PDF only"""
        start_time = perf_counter()
        
        if isinstance(content, bytes):
            content = content.decode('utf-8')
            
        pii_removed_content = content
        
        # Remove various PII using regular expressions
        for pattern in PII_PATTERNS.values():
            pii_removed_content = pattern.sub('[PII_REMOVED]', pii_removed_content)
        
        if not self.throughput_mode:
            pii_removed_content = self._detect_pii_with_spacy(pii_removed_content)
        
        self._record_timing('pii_removal', perf_counter() - start_time)
        return pii_removed_content
    
    def _detect_pii_with_spacy(self, content):
        """
        Use spaCy to detect PII
        """
        if self.nlp is None:
            name_pattern = r'\b[A-Z][a-z]+ [A-Z][a-z]+\b'
            content = re.sub(name_pattern, '[NAME_REDACTED]', content)
            return content
        
        doc = self.nlp(content)
        pii_entities = []
        
        for ent in doc.ents:
            if ent.label_ in ['PERSON', 'ORG', 'GPE']:  
                pii_entities.append(ent.text)
        
        for entity in pii_entities:
            content = content.replace(entity, '[PII_REMOVED]')
        
        return content
    
    def _process_docx_xml(self, file_content, operation):
        """
        Processing XML Content of DOCX Files
        """
        try:
            return self._process_docx_direct(file_content, operation)
        except Exception as e:
            print(f"Error in direct DOCX processing: {e}, falling back to python-docx")
            return self._process_docx_with_python_docx(file_content, operation)
    
    def _process_docx_direct(self, file_content, operation):
        """
        Process DOCX
        """
        try:
            input_zip = io.BytesIO(file_content)
            output_zip = io.BytesIO()
            
            with zipfile.ZipFile(input_zip, 'r') as zin:
                with zipfile.ZipFile(output_zip, 'w') as zout:
                    for item in zin.infolist():
                        content = zin.read(item.filename)
                        
                        if item.filename == 'word/document.xml':
                            content = self._process_docx_xml_content(content, operation)
                        elif item.filename.startswith('word/header') and item.filename.endswith('.xml'):
                            content = self._process_docx_xml_content(content, operation)
                        elif item.filename.startswith('word/footer') and item.filename.endswith('.xml'):
                            content = self._process_docx_xml_content(content, operation)
                        
                        zout.writestr(item, content)
            
            return output_zip.getvalue()
        
        except Exception as e:
            print(f"Error in direct DOCX processing: {e}")
            raise
    
    def _process_docx_xml_content(self, xml_content, operation):
        """
        Process DOCX XML
        """
        try:
            root = ET.fromstring(xml_content)
            
            namespaces = {
                'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
            }
            
            text_elements = root.findall('.//w:t', namespaces)
            
            for elem in text_elements:
                if elem.text:
                    original_text = elem.text
                    processed_text = original_text
                    
                    if operation == 'anonymize':
                        # Anonymization
                        for term in ANONYMIZE_TERMS:
                            if term.lower() in original_text.lower():
                                # Using regular expressions for case insensitive substitution
                                processed_text = re.sub(
                                    re.escape(term), 
                                    ANONYMIZE_REPLACE, 
                                    processed_text, 
                                    flags=re.IGNORECASE
                                )
                    
                    elif operation == 'remove_pii':
                        # PII remove
                        for pattern in PII_PATTERNS.values():
                            processed_text = pattern.sub('[PII_REMOVED]', processed_text)
                        
                        # PII check
                        if not self.throughput_mode and self.nlp:
                            doc = self.nlp(processed_text)
                            for ent in doc.ents:
                                if ent.label_ in ['PERSON', 'ORG', 'GPE']:
                                    processed_text = processed_text.replace(ent.text, '[PII_REMOVED]')
                    
                    if processed_text != original_text:
                        elem.text = processed_text
            
            # Return the processed XML content
            return ET.tostring(root, encoding='utf-8', method='xml')
        
        except Exception as e:
            print(f"Error processing DOCX XML content: {e}")
            return xml_content
    
    def _process_docx_with_python_docx(self, file_content, operation):
        """
        Using Python docx to process DOCX files
        """
        try:
            doc = Document(io.BytesIO(file_content))
            
            for paragraph in doc.paragraphs:
                self._process_paragraph_comprehensive(paragraph, operation)
            
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        for paragraph in cell.paragraphs:
                            self._process_paragraph_comprehensive(paragraph, operation)
            
            for section in doc.sections:
                for paragraph in section.header.paragraphs:
                    self._process_paragraph_comprehensive(paragraph, operation)
                for table in section.header.tables:
                    for row in table.rows:
                        for cell in row.cells:
                            for paragraph in cell.paragraphs:
                                self._process_paragraph_comprehensive(paragraph, operation)
            
            for section in doc.sections:
                for paragraph in section.footer.paragraphs:
                    self._process_paragraph_comprehensive(paragraph, operation)
                for table in section.footer.tables:
                    for row in table.rows:
                        for cell in row.cells:
                            for paragraph in cell.paragraphs:
                                self._process_paragraph_comprehensive(paragraph, operation)
            
            output = io.BytesIO()
            doc.save(output)
            return output.getvalue()
            
        except Exception as e:
            print(f"Error processing DOCX with python-docx: {e}")
            return file_content
    
    def _process_paragraph_comprehensive(self, paragraph, operation):
        """
        Process paragraphs
        """
        if not paragraph.text:
            return
        
        original_text = paragraph.text
        processed_text = original_text
        
        if operation == 'anonymize':
            for term in ANONYMIZE_TERMS:
                if term.lower() in original_text.lower():
                    processed_text = re.sub(
                        re.escape(term), 
                        ANONYMIZE_REPLACE, 
                        processed_text, 
                        flags=re.IGNORECASE
                    )
        
        elif operation == 'remove_pii':
            for pattern in PII_PATTERNS.values():
                processed_text = pattern.sub('[PII_REMOVED]', processed_text)
            
            if not self.throughput_mode and self.nlp:
                doc = self.nlp(processed_text)
                for ent in doc.ents:
                    if ent.label_ in ['PERSON', 'ORG', 'GPE']:
                        processed_text = processed_text.replace(ent.text, '[PII_REMOVED]')
        
        if processed_text != original_text:
            for run in paragraph.runs:
                run.text = ""
            
            if paragraph.runs:
                paragraph.runs[0].text = processed_text
            else:
                paragraph.add_run(processed_text)
    
    def _create_pdf_with_layout(self, content, filename, original_file_content, metadata):
        """
        Create a PDF with preserved layout
        """
        start_time = perf_counter()
        try:
            temp_img_path_arr = []
            pdf_buffer = io.BytesIO()
            
            doc = SimpleDocTemplate(
                pdf_buffer,
                pagesize=letter,
                rightMargin=72,
                leftMargin=72,
                topMargin=72,
                bottomMargin=18
            )
            
            styles = getSampleStyleSheet()
            title_style = styles['Heading1']
            normal_style = styles['Normal']
            
            story = []
            
            title = Paragraph(f"Processed Document: {filename}", title_style)
            story.append(title)
            story.append(Spacer(1, 12))
            
            time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            time_para = Paragraph(f"Processed on: {time_str}", normal_style)
            story.append(time_para)
            story.append(Spacer(1, 12))
            
            story.append(Spacer(1, 6))
            
            paragraphs = content.split('\n')
            for para_text in paragraphs:
                if para_text.strip():  
                    safe_text = html.escape(para_text)
                    safe_text = safe_text.replace('\n', '<br/>')
                    
                    try:
                        para = Paragraph(safe_text, normal_style)
                        story.append(para)
                        story.append(Spacer(1, 6))
                    except Exception as para_error:
                        print(f"Error creating paragraph: {para_error}")
                        safe_text = "【The content contains characters that cannot be processed, skipped】"
                        para = Paragraph(safe_text, normal_style)
                        story.append(para)
                        story.append(Spacer(1, 6))
            
            tables = metadata.get('tables', [])
            if tables:
                story.append(Spacer(1, 12))
                story.append(Paragraph("Extracted Tables:", styles['Heading2']))
                story.append(Spacer(1, 6))
                
                for i, table_data in enumerate(tables):
                    # if i > 2:  # 只显示前3个表格，避免PDF过大
                    #     story.append(Paragraph(f"... and {len(tables) - 3} more tables", normal_style))
                    #     break
                    
                    story.append(Paragraph(f"Table {i+1}:", styles['Heading3']))
                    
                    table_content = table_data.get('data', [])
                    if table_content:
                        max_rows = min(10, len(table_content))
                        max_cols = min(6, len(table_content[0]) if table_content else 0)
                        
                        display_data = []
                        for row_idx in range(max_rows):
                            if row_idx < len(table_content):
                                row = table_content[row_idx]
                                display_row = []
                                for col_idx in range(max_cols):
                                    if col_idx < len(row):
                                        cell_text = str(row[col_idx])[:50]  
                                        display_row.append(cell_text)
                                    else:
                                        display_row.append("")
                                display_data.append(display_row)
                        
                        if display_data:
                            table = Table(display_data)
                            table.setStyle(TableStyle([
                                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                                ('FONTSIZE', (0, 0), (-1, 0), 10),
                                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                                ('FONTSIZE', (0, 1), (-1, -1), 8),
                                ('GRID', (0, 0), (-1, -1), 1, colors.black)
                            ]))
                            story.append(table)
                            story.append(Spacer(1, 12))
            
            images = metadata.get('images', [])
            # print(images)
            if images:
                story.append(Spacer(1, 12))
                story.append(Paragraph("Extracted Images:", styles['Heading2']))
                story.append(Spacer(1, 6))
                
                image_count = 0
                for img_data in images:
                    # if image_count >= 3:  # 只显示前3张图片，避免PDF过大
                    #     story.append(Paragraph(f"... and {len(images) - 3} more images", normal_style))
                    #     break
                    
                    if 'image_data' in img_data:
                        try:
                            # remove stc logo
                            extracted_text = img_data.get('extracted_text', '')
                            self._log(extracted_text)
                            if extracted_text and extracted_text.lower() in ["stc","sic"]:
                                continue

                            # Create temporary image file
                            # print(img_data['image_data'])
                            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_img:
                                temp_img.write(img_data['image_data'])
                                temp_img_path = temp_img.name
                                temp_img_path_arr.append(temp_img_path)
                            
                            # Verify if the image file is valid
                            if not os.path.exists(temp_img_path) or os.path.getsize(temp_img_path) == 0:
                                self._log(f"Invalid temporary image file: {temp_img_path}")
                                continue

                            # Use secure image loading methods
                            img = self._safe_load_image(temp_img_path, width=400, height=300)
                            if img:
                                story.append(img)
                                story.append(Spacer(1, 6))
                                story.append(Spacer(1, 12))
                                image_count += 1
                            else:
                                self._log(f"Failed to load image: {temp_img_path}")
                            
                            # # 添加图片到PDF
                            # img = Image(temp_img_path, width=400, height=300)
                            # story.append(img)
                            # story.append(Spacer(1, 6))
                            
                            # # # 添加图片描述
                            # # description = img_data.get('description', f'Image {image_count + 1}')
                            # # extracted_text = img_data.get('extracted_text', '')
                            # # if extracted_text and len(extracted_text) > 200:
                            # #     extracted_text = extracted_text[:200] + "..."
                            
                            # # story.append(Paragraph(f"Description: {description}", normal_style))
                            # # if extracted_text:
                            # #     story.append(Paragraph(f"OCR Text: {extracted_text}", normal_style))
                            # story.append(Spacer(1, 12))
                            
                            # image_count += 1
                            
                            # 清理临时文件
                            # os.unlink(temp_img_path)
                            
                        except Exception as img_error:
                            print(f"Error adding image to PDF: {img_error}")
                            continue
            
            # Build PDF
            doc.build(story)
            
            pdf_content = pdf_buffer.getvalue()
            pdf_buffer.close()
            
            return pdf_content
            
        except Exception as e:
            print(f"Error creating PDF with layout: {e}")
            # If the creation fails, go back to simple PDF creation
            return self._create_pdf(content, filename)
        finally:
            for path in temp_img_path_arr:
                os.unlink(path)
                # print(f"Clear temp image:{path}")
            self._record_timing('pdf_generation_layout', perf_counter() - start_time)
    
    def _safe_load_image(self, image_path, width=400, height=300):
        """
        Use secure image loading methods
        """
        try:
            if not os.path.exists(image_path):
                self._log(f"Image file not found: {image_path}")
                return None
            
            file_size = os.path.getsize(image_path)
            if file_size == 0:
                self._log(f"Image file is empty: {image_path}")
                return None
            
            # Verify images using PIL
            try:
                from PIL import Image as PILImage
                with PILImage.open(image_path) as img:
                    img.verify()  # 验证图片完整性
            except ImportError:
                self._log("PIL not available, skipping image verification")
            except Exception as pil_error:
                self._log(f"Image verification failed: {pil_error}")
                return None
            
            img = Image(image_path, width=width, height=height)
            return img
            
        except Exception as e:
            print(f"Error in _safe_load_image for {image_path}: {e}")
            return None
        
    def _create_pdf(self, content, filename):
        """
        Create simple PDF file
        """
        start_time = perf_counter()
        try:
            if isinstance(content, bytes):
                content = content.decode('utf-8', errors='ignore')
                
            pdf_buffer = io.BytesIO()
            
            doc = SimpleDocTemplate(
                pdf_buffer,
                pagesize=letter,
                rightMargin=72,
                leftMargin=72,
                topMargin=72,
                bottomMargin=18
            )
            
            styles = getSampleStyleSheet()
            title_style = styles['Heading1']
            normal_style = styles['Normal']
            
            story = []
            
            title = Paragraph(f"Processed Document: {filename}", title_style)
            story.append(title)
            story.append(Spacer(1, 12))
            
            time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            time_para = Paragraph(f"Processed on: {time_str}", normal_style)
            story.append(time_para)
            story.append(Spacer(1, 12))
            
            story.append(Spacer(1, 6))
            
            paragraphs = content.split('\n')
            for para_text in paragraphs:
                if para_text.strip():  
                    safe_text = html.escape(para_text)
                    safe_text = safe_text.replace('\n', '<br/>')
                    
                    try:
                        para = Paragraph(safe_text, normal_style)
                        story.append(para)
                        story.append(Spacer(1, 6))
                    except Exception as para_error:
                        print(f"Error creating paragraph: {para_error}")
                        safe_text = "【The content contains characters that cannot be processed, skipped】"
                        para = Paragraph(safe_text, normal_style)
                        story.append(para)
                        story.append(Spacer(1, 6))
            
            # Build PDF
            doc.build(story)
            
            pdf_content = pdf_buffer.getvalue()
            pdf_buffer.close()
            
            return pdf_content
            
        except Exception as e:
            print(f"Error creating PDF: {e}")
            return self._create_error_pdf(f"Error creating PDF: {str(e)}")
        finally:
            self._record_timing('pdf_generation', perf_counter() - start_time)
    
    def _create_error_pdf(self, error_message):
        """
        Create a PDF containing error information
        """
        try:
            pdf_buffer = io.BytesIO()
            doc = SimpleDocTemplate(pdf_buffer, pagesize=letter)
            styles = getSampleStyleSheet()
            
            story = []
            title = Paragraph("PDF Generation Error", styles['Heading1'])
            story.append(title)
            story.append(Spacer(1, 12))
            
            error_para = Paragraph(f"Error: {error_message}", styles['Normal'])
            story.append(error_para)
            
            doc.build(story)
            pdf_content = pdf_buffer.getvalue()
            pdf_buffer.close()
            
            return pdf_content
        except:
            return f"PDF generation failed: {error_message}".encode('utf-8')
    
    def _extract_images_from_docx(self, doc, file_content):
        """
        Extract image information and data from DOCX
        """
        images_data = []
        
        try:
            for rel_id, rel in doc.part.rels.items():
                if "image" in rel.target_ref:
                    try:
                        image_part = rel.target_part
                        image_bytes = image_part.blob
                        image_info = {
                            "type": "docx_embedded_image",
                            "description": f"Embedded image {rel_id}",
                            "image_data": image_bytes,
                            "image_format": self._get_image_format(image_bytes),
                            "extracted_text": "",
                            "ocr_applied": False,
                        }

                        images_data.append(image_info)
                    except Exception as e:
                        print(f"Error extracting image {rel_id}: {e}")
                        images_data.append({
                            "type": "docx_embedded_image",
                            "description": f"Embedded image {rel_id} (extraction failed)",
                            "extracted_text": f"[Image extraction failed: {str(e)}]",
                            "ocr_applied": False,
                            "image_data": b"",
                        })
        except Exception as e:
            print(f"Error processing DOCX images: {e}")
        
        return self._process_images_with_ocr(images_data)
    
    def _extract_images_from_pdf(self, pdf_reader):
        """
        Extract image information from PDF
        """
        images_data = []
        
        try:
            for page_num in range(len(pdf_reader.pages)):
                page = pdf_reader.pages[page_num]
                
                if not hasattr(page, 'get'):
                    continue
                    
                resources = page.get('/Resources')
                if not resources:
                    continue
                
                if not hasattr(resources, 'get'):
                    continue    
                xObject = resources.get('/XObject')
                if not xObject:
                    continue
                
                try:
                    xObject_dict = xObject.get_object() if hasattr(xObject, 'get_object') else xObject
                except:
                    continue
                
                for obj_name, obj in xObject_dict.items():
                    try:
                        if hasattr(obj, 'get_object'):
                            obj = obj.get_object()
                        
                        if not hasattr(obj, 'get'):
                            continue
                            
                        subtype = obj.get('/Subtype')
                        if subtype != '/Image':
                            continue
                            
                        # 获取图像数据
                        # obj._data
                        # print("obj._data ok")
                        # with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as temp_img:
                        #     temp_img.write(obj._data)
                        # obj.get_data()
                        # print("obj.get_data() ok")
                        # with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as temp_img:
                        #     temp_img.write(obj.get_data())
                        
                        if hasattr(obj, '_data'):
                            image_data = obj._data
                        elif hasattr(obj, 'get_data'):
                            image_data = obj.get_data()
                        else:
                            try:
                                import struct
                                if hasattr(obj, 'stream'):
                                    image_data = obj.stream.get_data()
                                else:
                                    continue
                            except:
                                continue
                        
                        image_info = {
                            "page": page_num + 1,
                            "type": "pdf_embedded_image",
                            "description": f"Image on page {page_num + 1}",
                            "image_data": image_data,
                            "image_format": self._get_image_format(image_data),
                            "extracted_text": "",
                            "ocr_applied": False,
                        }
                        images_data.append(image_info)
                        
                    except Exception as e:
                        print(f"Error extracting PDF image {obj_name}: {e}")
                        images_data.append({
                            "page": page_num + 1,
                            "type": "pdf_embedded_image",
                            "description": f"Image on page {page_num + 1} (extraction failed)",
                            "extracted_text": f"[Image extraction failed: {str(e)}]",
                            "ocr_applied": False,
                            "image_data": b"",
                        })
                        
        except Exception as e:
            print(f"Error processing PDF images: {e}")
        
        return self._process_images_with_ocr(images_data)
    
    def _get_image_format(self, image_data):
        """
        Detect image format
        """
        try:
            image = PILImage.open(io.BytesIO(image_data))
            return image.format
        except:
            return "unknown"

    def _should_apply_ocr(self, image_bytes):
        """Simple heuristic to skip tiny or low-contrast images before OCR."""
        try:
            with PILImage.open(io.BytesIO(image_bytes)) as img:
                width, height = img.size
                if width < 32 or height < 32 or width * height < 2000:
                    return False
                gray = img.convert("L")
                stats = ImageStat.Stat(gray)
                if stats.stddev[0] < 8:
                    return False
                sample = gray.resize((64, 64))
                pixels = sample.getdata()
                dark_pixels = sum(1 for p in pixels if p < 110)
                if dark_pixels / len(pixels) < 0.01:
                    return False
                return True
        except Exception as exc:
            self._log(f"OCR heuristic fallback to processing: {exc}")
            return True

    def _prepare_image_array_for_ocr(self, image_bytes):
        """Convert bytes to a grayscale numpy array for OCR."""
        with PILImage.open(io.BytesIO(image_bytes)) as image:
            gray = image.convert("L")
            return np.array(gray)

    def _process_images_with_ocr(self, images):
        """Apply OCR to images with simple parallelism and ordering preserved."""
        if not images:
            return []

        if self.throughput_mode or not OCR_CONFIG.get('enabled', True):
            reason = "[OCR disabled in throughput mode]" if self.throughput_mode else "[OCR disabled]"
            for img in images:
                img["extracted_text"] = reason
                img["ocr_applied"] = False
            self._ocr_images_skipped += len(images)
            return images

        if not self.ocr_available or not self._paddle_ocr:
            for img in images:
                img["extracted_text"] = "[OCR not available]"
                img["ocr_applied"] = False
            self._ocr_images_skipped += len(images)
            return images

        workers = min(2, os.cpu_count() or 2)
        futures = {}

        with ThreadPoolExecutor(max_workers=workers) as executor:
            for idx, img in enumerate(images):
                if self._ocr_images_processed + len(futures) >= OCR_MAX_IMAGES_PER_DOC:
                    img["extracted_text"] = "[OCR skipped: max images reached]"
                    img["ocr_applied"] = False
                    self._ocr_images_skipped += 1
                    continue
                if not img.get("image_data"):
                    img["extracted_text"] = "[OCR skipped: no image data]"
                    img["ocr_applied"] = False
                    self._ocr_images_skipped += 1
                    continue
                if not self._should_apply_ocr(img.get("image_data", b"")):
                    img["extracted_text"] = "[OCR skipped: low-text likelihood]"
                    img["ocr_applied"] = False
                    self._ocr_images_skipped += 1
                    continue

                futures[executor.submit(self._perform_ocr, img["image_data"])] = idx

            for future, idx in futures.items():
                extracted = future.result()
                images[idx]["extracted_text"] = extracted
                images[idx]["ocr_applied"] = True
                self._ocr_images_processed += 1

        return images

    def _perform_ocr(self, image_data):
        """
        Perform OCR processing using PaddleOCR.
        """
        start_time = perf_counter()
        try:
            if not self._paddle_ocr:
                return "[OCR not available]"

            image_array = self._prepare_image_array_for_ocr(image_data)
            ocr_result = self._paddle_ocr.ocr(image_array, cls=False)
            texts = []
            for line in ocr_result or []:
                for entry in line:
                    if entry and len(entry) > 1 and entry[1]:
                        texts.append(str(entry[1][0]))
            cleaned_text = self._clean_ocr_text(" ".join(texts))
            return cleaned_text if cleaned_text else "[No text detected in image]"
        except Exception as e:
            print(f"OCR processing failed: {e}")
            return f"[OCR failed: {str(e)}]"
        finally:
            self._record_timing('ocr', perf_counter() - start_time)

    def _clean_ocr_text(self, text):
        """
        Clean up OCR extracted text
        """
        text = text or ""
        # Remove unnecessary spaces and line breaks
        text = re.sub(r'\s+', ' ', text)
        
        # Remove blank spaces at the beginning and end
        text = text.strip()
        
        return text
    
    def _extract_to_json(self, content, filename, file_extension, processing_info, metadata):
        """Extract content to JSON format"""
        json_output = JSON_SCHEMA.copy()
        
        if isinstance(content, bytes):
            content = content.decode('utf-8', errors='ignore')
        
        json_output["document_metadata"]["filename"] = filename
        json_output["document_metadata"]["file_type"] = file_extension
        json_output["document_metadata"]["processing_date"] = datetime.now().isoformat()
        json_output["document_metadata"]["file_size"] = len(content)
        
        json_output["content"]["text"] = content
        json_output["content"]["tables"] = metadata.get('tables', [])
        
        json_output["content"]["images"] = self._extract_image_info(metadata.get('images', []), content)
        
        # 提取章节
        # json_output["content"]["sections"] = self._extract_sections(content)
        
        json_output["processing_info"] = processing_info
        
        return json.dumps(json_output, indent=2, ensure_ascii=False)
    
    def _extract_image_info(self, images_metadata, document_content):
        """
        Extract image information
        """
        images_info = []
        
        for img_meta in images_metadata:
            image_info = {
                "type": img_meta.get("type", "unknown"),
                "description": img_meta.get("description", ""),
                "extracted_text": img_meta.get("extracted_text", ""),
                "ocr_applied": img_meta.get("ocr_applied", False),
                "image_format": img_meta.get("image_format", "unknown")
            }
            
            # If the image data is large, not to include it in JSON
            # or, include Base64 encoded thumbnails
            if "image_data" in img_meta and len(img_meta["image_data"]) < 10000:  # Only includes small images
                try:
                    image = PILImage.open(io.BytesIO(img_meta["image_data"]))
                    # Create Thumbnail 
                    image.thumbnail((100, 100))
                    thumb_buffer = io.BytesIO()
                    image.save(thumb_buffer, format="PNG")
                    image_info["thumbnail"] = base64.b64encode(thumb_buffer.getvalue()).decode('utf-8')
                except:
                    pass  # Ignore thumbnail creation error
            
            images_info.append(image_info)
        
        # Identify image references from document text
        if isinstance(document_content, bytes):
            document_content = document_content.decode('utf-8', errors='ignore')
            
        image_refs = re.findall(r'\[Image:\s*(.*?)\]|\!\[(.*?)\]', document_content)
        for match in image_refs:
            alt_text = match[0] or match[1]
            if alt_text and alt_text not in [img.get("description", "") for img in images_info]:
                images_info.append({
                    "type": "referenced_image",
                    "description": alt_text,
                    "extracted_text": f"Referenced image: {alt_text}",
                    "ocr_applied": False
                })
        
        # remove stc logo
        rtn_images = []
        for image in images_info:
            if image.get("extracted_text").lower() in ["stc","sic"]:
                continue
            rtn_images.append(image)

        return rtn_images
    
    def _extract_tables(self, content):
        """Extract Table Data - From Text Content"""
        if isinstance(content, bytes):
            content = content.decode('utf-8', errors='ignore')
            
        tables = []
        lines = content.split('\n')
        current_table = []
        
        for line in lines:
            if '|' in line:  # Simple table detection
                current_table.append([cell.strip() for cell in line.split('|')])
            elif current_table:
                tables.append(current_table)
                current_table = []
        
        if current_table:
            tables.append(current_table)
        
        return tables
    
    def _extract_sections(self, content):
        """Extract document sections"""
        if isinstance(content, bytes):
            content = content.decode('utf-8', errors='ignore')
            
        sections = []
        lines = content.split('\n')
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if (len(line_stripped) > 0 and 
                (line_stripped.isupper() or 
                 line_stripped.startswith('#') or 
                 line_stripped.startswith('Chapter') or
                 line_stripped.startswith('Section') or
                 (len(line_stripped) < 100 and i > 0 and len(lines[i-1].strip()) == 0))):
                
                content_start = i + 1
                content_preview = ""
                preview_lines = 0
                while content_start < len(lines) and preview_lines < 3:
                    if lines[content_start].strip():
                        content_preview += lines[content_start].strip() + " "
                        preview_lines += 1
                    content_start += 1
                
                sections.append({
                    "title": line_stripped,
                    "content_preview": content_preview.strip(),
                    "position": i
                })
        
        return sections[:20]

##########################

    def _check_pdfplumber(self):
        try:
            import pdfplumber
            return True
        except ImportError:
            print("pdfplumber not available. Install with: pip install pdfplumber")
            return False
    
    def _check_pymupdf(self):
        try:
            import fitz
            return True
        except ImportError:
            print("PyMuPDF not available. Install with: pip install PyMuPDF")
            return False

    def extract_images_with_pdfplumber_locations(self, pdf_path):
        """
        Use pdfplumber to locate images, and then extract them using PyMuPDF
        Return a list containing image data and location information
        """
        if not self.pdfplumber_available or not self.pymupdf_available:
            print("Required libraries not available")
            return []
        
        images_data = []
        
        try:
            # Using pdfplumber to obtain image location information
            with pdfplumber.open(pdf_path) as pdf:
                # Open the same PDF using PyMuPDF for image extraction
                pymupdf_doc = fitz.open(pdf_path)
                
                for page_num, page in enumerate(pdf.pages):
                    ###
                    page_height = page.height
                    header_ratio = PDF_HEADER_RATIO
                    page = page.within_bbox((0, page_height * header_ratio, page.width, page_height * (1 - header_ratio)))
                    
                    if hasattr(page, 'images') and page.images:
                        for img_idx, img_info in enumerate(page.images):
                            try:
                                # Obtain image position and bounding box information
                                bbox = (img_info['x0'], img_info['top'], 
                                       img_info['x1'], img_info['bottom'])
                                
                                # print(f"Page {page_num+1}, Image {img_idx+1}: bbox {bbox}")
                                
                                # Extracting actual image data using PyMuPDF
                                pix = self._extract_image_with_pymupdf(
                                    pymupdf_doc, page_num, img_idx, bbox
                                )
                                
                                if pix:
                                    image_bytes = pix.tobytes("png")
                                    
                                    image_info = {
                                        "page": page_num + 1,
                                        "type": "pdf_embedded_image",
                                        "description": f"Image on page {page_num + 1}",
                                        "image_data": image_bytes,
                                        "image_format": self._get_image_format(image_bytes),
                                        "extracted_text": "",
                                        "ocr_applied": False,
                                    }

                                    images_data.append(image_info)
                                    pix = None  # Clear memory
                                    
                            except Exception as e:
                                print(f"Error processing image {img_idx} on page {page_num}: {e}")
                                continue
                
                pymupdf_doc.close()
                        
        except Exception as e:
            print(f"Error extracting images with pdfplumber locations: {e}")
        
        return self._process_images_with_ocr(images_data)

    def _extract_image_with_pymupdf(self, doc, page_num, img_idx, bbox=None, xref=None):
        """Extract an image region or direct xref using PyMuPDF."""
        try:
            page = doc[page_num]

            if xref is not None:
                pix = fitz.Pixmap(doc, xref)
                try:
                    pix = fitz.Pixmap(fitz.csGRAY, pix)
                except Exception:
                    if pix.n - pix.alpha > 3:  # Change CMYK to RGB as fallback
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                return pix

            if bbox is not None:
                try:
                    rect = fitz.Rect(bbox)
                    pix = page.get_pixmap(
                        matrix=fitz.Matrix(OCR_RENDER_SCALE, OCR_RENDER_SCALE),
                        clip=rect,
                        colorspace=fitz.csGRAY,
                    )
                    return pix
                except Exception:
                    pass

            image_list = page.get_images()
            if img_idx < len(image_list):
                xref = image_list[img_idx][0]
                pix = fitz.Pixmap(doc, xref)
                if pix.n - pix.alpha > 3:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                return pix

        except Exception as e:
            print(f"Error extracting with PyMuPDF: {e}")

        return None


# Create a global processor instance
processor = DocumentProcessor()
