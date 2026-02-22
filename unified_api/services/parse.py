"""
Document parsing service for HTML, PDF, and other formats

Imported from Edgar BD project and adapted for unified platform.
"""
import re
import signal
from contextlib import contextmanager
from io import BytesIO
from typing import Optional, Tuple

import pdfplumber
from bs4 import BeautifulSoup
from lxml import html as lxml_html
from readability import Document as ReadabilityDocument
import structlog

logger = structlog.get_logger(__name__)

# Timeout for PDF parsing (in seconds)
PDF_PARSE_TIMEOUT = 120  # 2 minutes


class TimeoutException(Exception):
    """Raised when an operation times out"""
    pass


@contextmanager
def timeout(seconds: int, error_message: str = "Operation timed out"):
    """Context manager to timeout long-running operations using SIGALRM"""
    def timeout_handler(signum, frame):
        raise TimeoutException(error_message)

    # Set the signal handler
    old_handler = signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(seconds)

    try:
        yield
    finally:
        # Restore the old handler and cancel the alarm
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


class DocumentParser:
    """Parse documents into clean text"""

    @staticmethod
    def parse_html(content: bytes | str) -> Tuple[str, dict]:
        """
        Parse HTML content into clean text

        Args:
            content: HTML content as bytes or string

        Returns:
            Tuple of (text, metadata_dict)
        """
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="ignore")

        try:
            # Use readability to extract main content
            doc = ReadabilityDocument(content)
            title = doc.title()
            html_content = doc.summary()

            # Parse with BeautifulSoup
            soup = BeautifulSoup(html_content, "lxml")

            # Remove script and style elements
            for script in soup(["script", "style", "meta", "link"]):
                script.decompose()

            # Get text
            text = soup.get_text(separator="\n", strip=True)

            # Clean up whitespace
            text = re.sub(r"\n\s*\n", "\n\n", text)  # Multiple newlines to double
            text = re.sub(r" +", " ", text)  # Multiple spaces to single

            metadata = {
                "title": title,
                "length": len(text),
            }

            logger.debug("HTML parsed successfully", title=title, length=len(text))
            return text, metadata

        except Exception as e:
            logger.error("HTML parsing failed", error=str(e))
            # Fallback: basic text extraction
            soup = BeautifulSoup(content, "lxml")
            text = soup.get_text(separator="\n", strip=True)
            return text, {"title": None, "length": len(text)}

    @staticmethod
    def parse_pdf(content: bytes) -> Tuple[str, dict]:
        """
        Parse PDF content into text

        Args:
            content: PDF content as bytes

        Returns:
            Tuple of (text, metadata_dict)
        """
        try:
            text_parts = []
            metadata = {}

            # Wrap PDF parsing in a timeout to prevent hanging on problematic files
            with timeout(PDF_PARSE_TIMEOUT, f"PDF parsing timed out after {PDF_PARSE_TIMEOUT} seconds"):
                with pdfplumber.open(BytesIO(content)) as pdf:
                    metadata["page_count"] = len(pdf.pages)

                    # Extract PDF metadata
                    if pdf.metadata:
                        metadata["title"] = pdf.metadata.get("Title")
                        metadata["author"] = pdf.metadata.get("Author")
                        metadata["subject"] = pdf.metadata.get("Subject")

                    # Extract text from each page
                    for page_num, page in enumerate(pdf.pages, start=1):
                        try:
                            page_text = page.extract_text()
                            if page_text:
                                text_parts.append(page_text)
                        except Exception as e:
                            logger.warning(f"Failed to extract text from page {page_num}", error=str(e))
                            continue

            # Combine all pages
            text = "\n\n".join(text_parts)

            # Clean up
            text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)  # Multiple newlines to double
            text = re.sub(r" +", " ", text)  # Multiple spaces to single

            metadata["length"] = len(text)
            metadata["pages_extracted"] = len(text_parts)

            logger.debug(
                "PDF parsed successfully",
                pages=metadata["page_count"],
                length=len(text),
            )

            return text, metadata

        except TimeoutException as e:
            logger.error("PDF parsing timed out", error=str(e))
            return "", {"error": str(e), "timeout": True}
        except Exception as e:
            logger.error("PDF parsing failed", error=str(e))
            return "", {"error": str(e)}

    @staticmethod
    def parse_pdf_with_ocr(content: bytes) -> Tuple[str, dict]:
        """
        Parse PDF using OCR (for scanned documents)

        This is a placeholder for OCR functionality using Tesseract.

        Args:
            content: PDF content as bytes

        Returns:
            Tuple of (text, metadata_dict)
        """
        # TODO: Implement OCR pipeline
        logger.warning("OCR not yet implemented, returning empty text")
        return "", {"ocr": False, "error": "OCR not implemented"}

    @staticmethod
    def extract_sections(text: str) -> list[Tuple[str, str]]:
        """
        Extract sections from structured text (e.g., SEC filings)

        SEC 8-K filings have sections like:
        - Item 1.01 Entry into a Material Definitive Agreement
        - Item 2.01 Completion of Acquisition or Disposition of Assets
        - Item 8.01 Other Events

        Args:
            text: Full document text

        Returns:
            List of (section_name, section_text) tuples
        """
        sections = []

        # Pattern for SEC Item headings
        item_pattern = r"(?:^|\n)\s*(ITEM\s+\d+(?:\.\d+)?[:\s].*?)(?=\n\s*ITEM\s+\d+(?:\.\d+)?|$)"

        matches = re.finditer(item_pattern, text, re.IGNORECASE | re.MULTILINE | re.DOTALL)

        for match in matches:
            section_text = match.group(1).strip()

            header_match = re.match(r"(ITEM\s+\d+(?:\.\d+)?)[:\s]*(.*?)$", section_text, re.IGNORECASE | re.MULTILINE)

            if header_match:
                section_num = header_match.group(1).strip()
                section_title = header_match.group(2).strip()

                content_start = header_match.end()
                remaining_text = section_text[content_start:].strip()

                if not section_title and remaining_text:
                    lines = remaining_text.split('\n', 1)
                    if lines:
                        section_title = lines[0].strip()
                        content = lines[1].strip() if len(lines) > 1 else ""
                    else:
                        content = ""
                else:
                    content = remaining_text

                if not content and section_title:
                    content = section_title

                section_name = f"{section_num}: {section_title}" if section_title else section_num
                sections.append((section_name, content))

        if sections:
            logger.debug("Extracted sections from document", count=len(sections))
        else:
            # No sections found, treat whole document as one section
            sections = [("Full Document", text)]

        return sections

    @staticmethod
    def detect_language(text: str) -> str:
        """
        Detect document language (simple heuristic)

        Args:
            text: Document text

        Returns:
            Language code (e.g., 'en', 'unknown')
        """
        if not text:
            return "unknown"

        english_words = {
            "the", "be", "to", "of", "and", "a", "in", "that", "have", "i",
            "it", "for", "not", "on", "with", "he", "as", "you", "do", "at",
        }

        words = re.findall(r"\b[a-z]+\b", text.lower())
        if not words:
            return "unknown"

        english_count = sum(1 for word in words[:200] if word in english_words)
        english_ratio = english_count / min(len(words), 200)

        return "en" if english_ratio > 0.1 else "unknown"


def parse_document(
    content: bytes,
    mime_type: str,
) -> Tuple[str, dict]:
    """
    Parse document based on MIME type

    Args:
        content: Document content as bytes
        mime_type: MIME type (e.g., 'text/html', 'application/pdf')

    Returns:
        Tuple of (text, metadata_dict)
    """
    parser = DocumentParser()

    try:
        if mime_type in ("text/html", "application/xhtml+xml"):
            return parser.parse_html(content)

        elif mime_type == "application/pdf":
            text, metadata = parser.parse_pdf(content)

            # If PDF parsing returned empty text, try OCR
            if not text or len(text) < 100:
                logger.info("PDF text extraction yielded little text, attempting OCR")
                text_ocr, metadata_ocr = parser.parse_pdf_with_ocr(content)
                if text_ocr:
                    return text_ocr, metadata_ocr

            return text, metadata

        elif mime_type in ("text/plain", "text/xml"):
            # Plain text, no parsing needed
            text = content.decode("utf-8", errors="ignore")
            metadata = {"length": len(text)}
            return text, metadata

        else:
            logger.warning(f"Unsupported MIME type: {mime_type}")
            # Try to decode as text anyway
            try:
                text = content.decode("utf-8", errors="ignore")
                return text, {"length": len(text), "unsupported_mime": True}
            except Exception:
                return "", {"error": "Unsupported MIME type", "mime": mime_type}

    except Exception as e:
        logger.error("Document parsing failed", mime_type=mime_type, error=str(e))
        return "", {"error": str(e), "mime": mime_type}
