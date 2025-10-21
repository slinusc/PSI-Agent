"""
PDF text extraction using PyMuPDF or pdfplumber.
Requires: pip install pymupdf (or pdfplumber)
"""
import logging
from pathlib import Path

try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False

logger = logging.getLogger("psi.chainlit.pdf")


def extract_pdf_text(pdf_path: Path, max_pages: int = None) -> str:
    """
    Extract text from a PDF file.

    Args:
        pdf_path: Path to the PDF file
        max_pages: Maximum number of pages to extract (None = all pages)

    Returns:
        Extracted text content
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    if PYMUPDF_AVAILABLE:
        return _extract_with_pymupdf(pdf_path, max_pages)
    elif PDFPLUMBER_AVAILABLE:
        return _extract_with_pdfplumber(pdf_path, max_pages)
    else:
        raise ImportError("Neither pymupdf nor pdfplumber installed. Run: pip install pymupdf")


def _extract_with_pymupdf(pdf_path: Path, max_pages: int = None) -> str:
    """Extract text using PyMuPDF (fitz)."""
    logger.info("Extracting text from PDF using PyMuPDF: %s", pdf_path.name)

    doc = fitz.open(str(pdf_path))
    total_pages = len(doc)
    pages_to_process = min(total_pages, max_pages) if max_pages else total_pages

    all_text = []

    for page_num in range(pages_to_process):
        page = doc[page_num]
        text = page.get_text()
        all_text.append(f"\n--- Page {page_num + 1} ---\n{text}")

    doc.close()

    extracted_text = "\n".join(all_text)

    if max_pages and total_pages > max_pages:
        extracted_text += f"\n\n[Note: Only extracted first {max_pages} of {total_pages} pages]"

    logger.info("Extracted %d characters from %d pages of %s",
                len(extracted_text), pages_to_process, pdf_path.name)

    return extracted_text


def _extract_with_pdfplumber(pdf_path: Path, max_pages: int = None) -> str:
    """Extract text using pdfplumber."""
    logger.info("Extracting text from PDF using pdfplumber: %s", pdf_path.name)

    all_text = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        total_pages = len(pdf.pages)
        pages_to_process = min(total_pages, max_pages) if max_pages else total_pages

        for page_num in range(pages_to_process):
            page = pdf.pages[page_num]
            text = page.extract_text() or ""
            all_text.append(f"\n--- Page {page_num + 1} ---\n{text}")

    extracted_text = "\n".join(all_text)

    if max_pages and total_pages > max_pages:
        extracted_text += f"\n\n[Note: Only extracted first {max_pages} of {total_pages} pages]"

    logger.info("Extracted %d characters from %d pages of %s",
                len(extracted_text), pages_to_process, pdf_path.name)

    return extracted_text


def extract_pdf_text_safe(pdf_path: Path, max_pages: int = None) -> str:
    """
    Safe wrapper that returns error message instead of raising exceptions.

    Args:
        pdf_path: Path to the PDF file
        max_pages: Maximum number of pages to extract

    Returns:
        Extracted text or error message
    """
    try:
        return extract_pdf_text(pdf_path, max_pages)
    except Exception as exc:
        error_msg = f"[PDF file: {pdf_path.name}. Extraction failed: {exc}]"
        logger.warning(error_msg)
        return error_msg
