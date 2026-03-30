"""문서 파싱 서비스: 업로드 파일 및 URL fetch → 텍스트 추출.

MCPER_DOC_PARSE_ENABLED=true 시 pdfminer.six / python-docx / beautifulsoup4 사용.
미설치 시 graceful fallback (plain text / UTF-8 decode만).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_DOC_PARSE_ENABLED = os.environ.get("MCPER_DOC_PARSE_ENABLED", "false").lower() in (
    "1", "true", "yes"
)


def _try_import_pdf():
    try:
        from pdfminer.high_level import extract_text  # type: ignore
        return extract_text
    except ImportError:
        return None


def _try_import_docx():
    try:
        import docx  # type: ignore
        return docx
    except ImportError:
        return None


def _try_import_bs4():
    try:
        from bs4 import BeautifulSoup  # type: ignore
        return BeautifulSoup
    except ImportError:
        return None


def parse_uploaded_file(filename: str, content: bytes) -> str:
    """
    업로드된 파일 바이트 → 텍스트 추출.

    지원 형식:
    - .txt, .md → UTF-8 디코드
    - .pdf → pdfminer.six (MCPER_DOC_PARSE_ENABLED=true)
    - .docx → python-docx (MCPER_DOC_PARSE_ENABLED=true)
    - 기타 → UTF-8 디코드 시도 (실패 시 latin-1)
    """
    ext = Path(filename).suffix.lower()

    if ext in (".txt", ".md"):
        return content.decode("utf-8", errors="replace")

    if ext == ".pdf":
        if not _DOC_PARSE_ENABLED:
            logger.warning(
                "PDF parsing requires MCPER_DOC_PARSE_ENABLED=true and pdfminer.six installed"
            )
            return content.decode("utf-8", errors="replace")
        extract_text = _try_import_pdf()
        if extract_text is None:
            raise ImportError(
                "pdfminer.six is not installed. "
                "Add 'pdfminer.six' to requirements.txt and set MCPER_DOC_PARSE_ENABLED=true"
            )
        import io
        return extract_text(io.BytesIO(content))

    if ext == ".docx":
        if not _DOC_PARSE_ENABLED:
            logger.warning(
                "DOCX parsing requires MCPER_DOC_PARSE_ENABLED=true and python-docx installed"
            )
            return content.decode("utf-8", errors="replace")
        docx_mod = _try_import_docx()
        if docx_mod is None:
            raise ImportError(
                "python-docx is not installed. "
                "Add 'python-docx' to requirements.txt and set MCPER_DOC_PARSE_ENABLED=true"
            )
        import io
        doc = docx_mod.Document(io.BytesIO(content))
        return "\n".join(para.text for para in doc.paragraphs)

    # fallback
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("latin-1")


async def fetch_url_as_text(url: str) -> str:
    """
    URL → 텍스트 추출.
    MCPER_DOC_PARSE_ENABLED=true 시 beautifulsoup4로 HTML 파싱,
    아니면 raw 텍스트 반환.
    """
    import httpx

    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        raw = resp.text

    if not _DOC_PARSE_ENABLED:
        return raw

    BeautifulSoup = _try_import_bs4()
    if BeautifulSoup is None:
        logger.warning("beautifulsoup4 not installed — returning raw HTML")
        return raw

    soup = BeautifulSoup(raw, "html.parser")
    # script/style 제거
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)
