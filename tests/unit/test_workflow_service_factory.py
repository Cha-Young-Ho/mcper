"""Unit tests for make_default_workflow_service factory — covers service.py lines 97-113."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.workflow.service import (
    WorkflowIndexingService,
    make_default_workflow_service,
)


class TestFactory:
    def test_make_default_wires_dependencies(self):
        db = MagicMock()
        with patch("app.services.embeddings.embed_texts") as mock_embed, \
             patch("app.spec.chunking.HeadingAwareParentChildChunker") as mock_chunker, \
             patch("app.workflow.repository.SqlAlchemyWorkflowChunkRepository") as mock_repo_cls:
            mock_embed.return_value = [[0.0] * 384]
            svc = make_default_workflow_service(db)

        assert isinstance(svc, WorkflowIndexingService)
        mock_chunker.assert_called_once_with()
        mock_repo_cls.assert_called_once_with(db)

    def test_embedding_adapter_delegates_to_embed_texts(self):
        """The internal _EmbeddingAdapter.embed_texts must call embed_texts()."""
        db = MagicMock()
        with patch("app.services.embeddings.embed_texts") as mock_embed, \
             patch("app.spec.chunking.HeadingAwareParentChildChunker"), \
             patch("app.workflow.repository.SqlAlchemyWorkflowChunkRepository"):
            mock_embed.return_value = [[1.0] * 384, [2.0] * 384]
            svc = make_default_workflow_service(db)

        # grab the embedding adapter and exercise its embed_texts method
        # svc._embedding is the _EmbeddingAdapter instance (private attr)
        adapter = svc._embedding
        result = adapter.embed_texts(["hello", "world"])
        mock_embed.assert_called_once_with(["hello", "world"])
        assert result == [[1.0] * 384, [2.0] * 384]
