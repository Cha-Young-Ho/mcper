"""문서 파싱 서비스: 업로드 파일 및 URL fetch → 텍스트 추출.

지원 형식:
- .txt, .md  → UTF-8 디코드
- .pdf       → pdfminer.six
- .docx      → python-docx
- URL        → httpx fetch + beautifulsoup4 HTML 파싱
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _sanitize_text(text: str) -> str:
    """PostgreSQL text 타입에 저장 불가능한 NUL(0x00) 문자 제거."""
    return text.replace("\x00", "")


def parse_uploaded_file(filename: str, content: bytes) -> str:
    """
    업로드된 파일 바이트 → 텍스트 추출.

    반환값은 항상 NUL 바이트가 제거된 안전한 문자열.
    라이브러리 미설치 시 ImportError를 그대로 raise — 호출부에서 처리.
    """
    ext = Path(filename).suffix.lower()

    if ext in (".txt", ".md"):
        return _sanitize_text(content.decode("utf-8", errors="replace"))

    if ext == ".pdf":
        try:
            from pdfminer.high_level import extract_text  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "pdfminer.six가 설치되지 않았습니다. "
                "requirements.txt에 'pdfminer.six'를 추가하고 이미지를 재빌드하세요."
            ) from exc
        return _sanitize_text(extract_text(io.BytesIO(content)))

    if ext == ".docx":
        try:
            import docx  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "python-docx가 설치되지 않았습니다. "
                "requirements.txt에 'python-docx'를 추가하고 이미지를 재빌드하세요."
            ) from exc
        doc = docx.Document(io.BytesIO(content))
        return _sanitize_text("\n".join(para.text for para in doc.paragraphs))

    # 기타 텍스트 기반 파일 fallback
    try:
        return _sanitize_text(content.decode("utf-8"))
    except UnicodeDecodeError:
        return _sanitize_text(content.decode("latin-1"))


async def fetch_url_as_text(url: str) -> str:
    """
    URL → 텍스트 추출.
    beautifulsoup4로 HTML 파싱, script/style 등 노이즈 제거.
    """
    import httpx

    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        raw = resp.text

    try:
        from bs4 import BeautifulSoup  # type: ignore
    except ImportError:
        logger.warning("beautifulsoup4 미설치 — raw HTML 그대로 반환")
        return raw

    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)
