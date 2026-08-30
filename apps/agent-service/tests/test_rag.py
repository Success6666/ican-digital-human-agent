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
)


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

    def test_chunker_bounds_and_overlap(self) -> None:
        chunker = CharacterChunker(max_chars=64, overlap_chars=8)
        chunks = chunker.split("one two three four five six seven eight nine ten eleven twelve")
        self.assertTrue(chunks)
        self.assertTrue(all(len(chunk) <= 64 for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
