"""Backward compatibility shim for documents module.

DEPRECATED: Use app.tools.documents instead.
This module re-exports from documents for backward compatibility.
"""

from __future__ import annotations

# Re-export all public symbols from documents
from app.tools.documents import (
    _ilike_pattern,
    _normalize_related_files,
    register_document_tools as register_spec_tools,
    search_documents_impl as search_spec_and_code_impl,
    upload_document_impl as upload_spec_to_db_impl,
)

__all__ = [
    "register_spec_tools",
    "upload_spec_to_db_impl",
    "search_spec_and_code_impl",
    "_normalize_related_files",
    "_ilike_pattern",
]
