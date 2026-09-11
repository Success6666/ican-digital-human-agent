from __future__ import annotations

import base64
import sys
from pathlib import Path
import unittest
from unittest.mock import patch


SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from app.rag import (  # noqa: E402
    CharacterChunker,
    DocumentParseError,
    DoclingParser,
    DoclingRuntimeConfig,
    InMemoryVectorStore,
    IngestRequest,
    MetadataLimits,
    MetadataLimitError,
    RagService,
    SearchRequest,
    HierarchicalChunker,
)
from app.rag.embeddings import LocalSentenceTransformerEmbeddingProvider, build_embedding_provider  # noqa: E402


class RagTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.service = RagService(
            parser=DoclingParser(),
            chunker=CharacterChunker(max_chars=96, overlap_chars=12),
            store=InMemoryVectorStore(max_chunks=20),
        )

    async def test_markdown_ingest_and_search_without_docling(self) -> None:
        result = await self.service.ingest(
            IngestRequest(
                source_name="guide.md",
                content="# Retrieval\n\nThe agent uses MCP tools and a vector store.",
                metadata={"team": "platform"},
            ),
            owner_id="alice",
        )
        self.assertEqual(result.chunk_count, 1)
        self.assertIn(result.parser, {"docling", "text-fallback"})
        hits = await self.service.search(SearchRequest(query="MCP vector", top_k=3), owner_id="alice")
        self.assertEqual(len(hits.hits), 1)
        self.assertEqual(hits.hits[0].chunk.metadata["owner_id"], "alice")

    async def test_plain_text_content_without_extension_is_not_treated_as_binary(self) -> None:
        result = await self.service.ingest(
            IngestRequest(
                source_name="generated-input",
                content="Generated plain text remains searchable.",
            ),
            owner_id="alice",
        )
        self.assertIn(result.parser, {"docling", "text-fallback"})
        hits = await self.service.search(
            SearchRequest(query="plain text searchable"),
            owner_id="alice",
        )
        self.assertEqual(len(hits.hits), 1)

    async def test_namespace_isolation(self) -> None:
        await self.service.ingest(
            IngestRequest(source_name="a.md", content="private alpha"), owner_id="alice"
        )
        hits = await self.service.search(SearchRequest(query="private alpha"), owner_id="bob")
        self.assertEqual(hits.hits, [])

    async def test_statistics_count_unique_documents_chunks_and_collections_per_owner(self) -> None:
        await self.service.ingest(
            IngestRequest(
                document_id="guide",
                source_name="guide.md",
                collection="manuals",
                content="A" * 180,
            ),
            owner_id="alice",
        )
        await self.service.ingest(
            IngestRequest(source_name="api.md", collection="project", content="API reference"),
            owner_id="alice",
        )
        await self.service.ingest(
            IngestRequest(source_name="private.md", collection="manuals", content="Bob only"),
            owner_id="bob",
        )

        statistics = await self.service.statistics(owner_id="alice")

        self.assertEqual(statistics.documents, 2)
        self.assertGreaterEqual(statistics.chunks, 3)
        self.assertEqual([item.name for item in statistics.collections], ["manuals", "project"])
        self.assertEqual(statistics.collections[0].documents, 1)
        self.assertGreaterEqual(statistics.collections[0].chunks, 2)

    async def test_upsert_replaces_document_and_store_is_bounded(self) -> None:
        request = IngestRequest(document_id="stable", source_name="a.md", content="old text")
        await self.service.ingest(request)
        await self.service.ingest(request.model_copy(update={"content": "new text"}))
        self.assertEqual(await self.service.count(), 1)
        hits = await self.service.search(SearchRequest(query="new"))
        self.assertEqual(hits.hits[0].chunk.document_id, "stable")

    async def test_document_size_limit_is_enforced_before_parsing(self) -> None:
        service = RagService(
            parser=DoclingParser(config=DoclingRuntimeConfig(enabled=False)),
            chunker=CharacterChunker(max_chars=96, overlap_chars=12),
            store=InMemoryVectorStore(max_chunks=20),
            max_document_bytes=4,
        )
        with self.assertRaisesRegex(ValueError, "document exceeds 4 bytes"):
            await service.ingest(IngestRequest(source_name="too-large.md", content="12345"))

    def test_base64_length_is_checked_before_decode(self) -> None:
        request = IngestRequest(
            source_name="large.pdf",
            content_base64=base64.b64encode(b"1234567").decode("ascii"),
        )
        with patch("app.rag.models.base64.b64decode", side_effect=AssertionError("decoded too early")):
            with self.assertRaisesRegex(ValueError, "document exceeds 4 bytes"):
                request.payload(max_bytes=4)

    def test_text_payload_encoding_is_bounded(self) -> None:
        request = IngestRequest(source_name="large.txt", content="中" * 3)
        with self.assertRaisesRegex(ValueError, "document exceeds 4 bytes"):
            request.payload(max_bytes=4)

    def test_metadata_limits_reject_large_nested_input(self) -> None:
        request = IngestRequest(source_name="meta.md", content="ok", metadata={"a": {"b": "x"}})
        with self.assertRaisesRegex(MetadataLimitError, "nesting exceeds 1"):
            request.validate_metadata(MetadataLimits(max_bytes=128, max_items=10, max_depth=1))

    def test_metadata_limits_reject_item_flood(self) -> None:
        request = IngestRequest(source_name="meta.md", content="ok", metadata={"items": list(range(4))})
        with self.assertRaisesRegex(MetadataLimitError, "items exceed 3"):
            request.validate_metadata(MetadataLimits(max_bytes=128, max_items=3, max_depth=6))

    def test_binary_parse_requires_docling(self) -> None:
        parser = DoclingParser(strict_binary=True)
        if parser.available:
            self.skipTest("Docling is installed; binary parser is exercised by integration tests")
        with self.assertRaises(DocumentParseError):
            parser.parse(b"not a pdf", source_name="broken.pdf", document_id="d1")

    def test_binary_parse_error_does_not_reflect_source_or_sdk_detail(self) -> None:
        parser = DoclingParser(
            strict_binary=True,
            config=DoclingRuntimeConfig(enabled=True),
        )
        with patch.object(
            parser,
            "_parse_with_docling",
            side_effect=RuntimeError("C:/private/secret.pdf Authorization=top-secret"),
        ):
            with self.assertRaises(DocumentParseError) as context:
                parser.parse(
                    b"not a pdf",
                    source_name="C:/private/secret.pdf",
                    content_type="application/pdf",
                    document_id="d-safe-error",
                )
        message = str(context.exception)
        self.assertIn("文档解析失败", message)
        self.assertNotIn("secret.pdf", message)
        self.assertNotIn("top-secret", message)

    def test_docling_can_be_disabled_without_breaking_text_fallback(self) -> None:
        parser = DoclingParser(config=DoclingRuntimeConfig(enabled=False))
        parsed = parser.parse(
            b"# Local fallback",
            source_name="note.md",
            document_id="d-disabled",
        )
        self.assertEqual(parsed.metadata["parser"], "text-fallback")
        self.assertFalse(parser.available)

    def test_mime_less_parser_sniffs_utf8_text_but_rejects_pdf_signature(self) -> None:
        self.assertEqual(
            DoclingParser._content_type("README", None, b"plain UTF-8 text"),
            "text/plain",
        )
        self.assertEqual(
            DoclingParser._content_type("README", None, b"%PDF-1.7\n"),
            "application/octet-stream",
        )

    def test_availability_probe_does_not_construct_converter(self) -> None:
        parser = DoclingParser(config=DoclingRuntimeConfig(enabled=True))
        self.assertIsNone(parser._converter)
        _ = parser.available
        self.assertIsNone(parser._converter)

    def test_missing_ocr_runtime_is_reported_before_conversion(self) -> None:
        """A missing onnxruntime must be visible in health, not on first upload."""

        parser = DoclingParser(
            config=DoclingRuntimeConfig(enabled=True, do_ocr=True, ocr_backend="onnxruntime")
        )
        with patch("app.rag.docling_parser.importlib.util.find_spec", return_value=None):
            self.assertFalse(parser.ocr_ready)
            self.assertIn("onnxruntime", parser.ocr_backend_error or "")
        # The probe must stay cheap: no converter is built to answer it.
        self.assertIsNone(parser._converter)

    def test_ocr_probe_is_skipped_when_ocr_is_disabled(self) -> None:
        parser = DoclingParser(
            config=DoclingRuntimeConfig(enabled=True, do_ocr=False, ocr_backend="onnxruntime")
        )
        with patch("app.rag.docling_parser.importlib.util.find_spec", return_value=None):
            self.assertTrue(parser.ocr_ready)
            self.assertIsNone(parser.ocr_backend_error)

    def test_unknown_ocr_backend_is_left_to_docling(self) -> None:
        parser = DoclingParser(
            config=DoclingRuntimeConfig(enabled=True, do_ocr=True, ocr_backend="tesseract")
        )
        with patch("app.rag.docling_parser.importlib.util.find_spec", return_value=None):
            self.assertTrue(parser.ocr_ready)

    def test_ocr_probe_reuses_module_lookup_helper(self) -> None:
        from app.rag.docling_parser import missing_ocr_backend, ocr_backend_module

        self.assertEqual(ocr_backend_module("onnxruntime"), "onnxruntime")
        self.assertEqual(ocr_backend_module(" ONNXRuntime "), "onnxruntime")
        self.assertIsNone(ocr_backend_module("tesseract"))
        with patch("app.rag.docling_parser.importlib.util.find_spec", return_value=object()):
            self.assertIsNone(missing_ocr_backend("onnxruntime"))

    def test_ocr_probe_surfaces_a_native_library_failure(self) -> None:
        """The real failure mode: the package resolves but `import cv2` fails."""

        from app.rag import docling_parser
        import builtins

        parser = DoclingParser(
            config=DoclingRuntimeConfig(enabled=True, do_ocr=True, ocr_backend="onnxruntime")
        )
        real_import = builtins.__import__

        def failing(name, *args, **kwargs):
            if name == "rapidocr":
                raise ImportError("libxcb.so.1: cannot open shared object file")
            return real_import(name, *args, **kwargs)

        with patch("app.rag.docling_parser.importlib.util.find_spec", return_value=object()):
            with patch.object(builtins, "__import__", failing):
                self.assertFalse(parser.ocr_ready)
                self.assertIn("ImportError", parser.ocr_backend_error or "")
                self.assertIn("ImportError", docling_parser.ocr_engine_error("onnxruntime") or "")

    def test_ocr_engine_error_is_quiet_for_unknown_backends(self) -> None:
        from app.rag.docling_parser import ocr_engine_error

        with patch("app.rag.docling_parser.importlib.util.find_spec", return_value=object()):
            self.assertIsNone(ocr_engine_error("tesseract"))

    def test_chunker_bounds_and_overlap(self) -> None:
        chunker = CharacterChunker(max_chars=64, overlap_chars=8)
        chunks = chunker.split("one two three four five six seven eight nine ten eleven twelve")
        self.assertTrue(chunks)
        self.assertTrue(all(len(chunk) <= 64 for chunk in chunks))

    def test_hierarchical_chunker_preserves_parent_context(self) -> None:
        chunker = HierarchicalChunker(max_chars=64, overlap_chars=8, parent_max_chars=160, parent_overlap_chars=16)
        drafts = chunker.split_with_metadata("# 语音设置\n\n数字人支持中文实时播报。" * 12 + "\n\n# 连接配置\n\n连接后才可以进入实时对话。" * 12)
        self.assertGreaterEqual(len(drafts), 2)
        self.assertTrue(all(len(item.text) <= 64 for item in drafts))
        self.assertTrue(all(item.metadata.get("parent_text") for item in drafts))
        self.assertTrue(any("语音设置" in str(item.metadata.get("section_path")) for item in drafts))

    def test_local_embedding_provider_is_the_default_and_hash_is_explicit(self) -> None:
        provider = build_embedding_provider(
            provider="local",
            base_url="",
            api_key="",
            model="BAAI/bge-small-zh-v1.5",
            dimensions=512,
        )
        self.assertIsInstance(provider, LocalSentenceTransformerEmbeddingProvider)
        with self.assertRaises(ValueError):
            build_embedding_provider(
                provider="unsupported",
                base_url="",
                api_key="",
                model="",
                dimensions=512,
            )

    async def test_search_cache_returns_copy_and_invalidates_after_ingest(self) -> None:
        first = await self.service.ingest(IngestRequest(document_id="cached", source_name="a.md", content="旧答案"))
        self.assertEqual(first.chunk_count, 1)
        result = await self.service.search(SearchRequest(query="旧答案"))
        result.hits.clear()
        cached = await self.service.search(SearchRequest(query="旧答案"))
        self.assertEqual(len(cached.hits), 1)
        await self.service.ingest(IngestRequest(document_id="cached", source_name="a.md", content="新答案"))
        refreshed = await self.service.search(SearchRequest(query="新答案"))
        self.assertTrue(refreshed.hits)


if __name__ == "__main__":
    unittest.main()
