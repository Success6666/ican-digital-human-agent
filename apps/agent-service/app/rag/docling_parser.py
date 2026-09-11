"""Docling-backed document parsing with a safe text fallback."""

from __future__ import annotations

from html.parser import HTMLParser
from io import BytesIO
import importlib.util
import os
from pathlib import Path, PurePath
import threading
from typing import Any
from dataclasses import dataclass

from .models import ParsedDocument
from .parser_support import infer_content_type, positive_int, public_load_error, truthy


class DocumentParseError(RuntimeError):
    """Raised when a binary document cannot be parsed."""


# Docling ships the RapidOCR ONNX weights but treats the inference runtime as
# an optional extra. Map each backend to the module Docling will import when it
# builds the OCR stage, so a missing runtime can be reported up front instead
# of surfacing as an opaque ImportError on the first real upload.
_OCR_BACKEND_MODULES: dict[str, str] = {
    "onnxruntime": "onnxruntime",
    "openvino": "openvino",
    "paddle": "paddle",
}


def ocr_backend_module(backend: str) -> str | None:
    """Return the runtime module a Docling OCR backend depends on."""

    return _OCR_BACKEND_MODULES.get(backend.strip().lower())


def missing_ocr_backend(backend: str) -> str | None:
    """Return the missing runtime name for a backend, or None when usable.

    Unknown backends return None: Docling is the authority on those and should
    be allowed to raise its own error rather than be pre-empted here.
    """

    module = ocr_backend_module(backend)
    if module is None:
        return None
    try:
        if importlib.util.find_spec(module) is None:
            return module
    except (ImportError, ModuleNotFoundError, ValueError):
        return module
    return None


def ocr_engine_error(backend: str) -> str | None:
    """Report why the configured OCR engine cannot run, or None when it can.

    `find_spec` is not enough on its own: the RapidOCR engine imports `cv2`,
    which links against X11/GL shared libraries that slim base images do not
    ship. The package is present, the module spec resolves, and only the real
    import reveals that `libxcb.so.1` is missing. Docling reports that as
    "RapidOCR is not installed", which sends operators chasing the wrong thing.
    """

    missing = missing_ocr_backend(backend)
    if missing is not None:
        return f"OCR 引擎依赖缺失：{missing}"
    if ocr_backend_module(backend) != "onnxruntime":
        return None
    try:
        from rapidocr import RapidOCR  # type: ignore[import-not-found]  # noqa: F401
    except Exception as exc:
        return f"OCR 引擎不可用：{type(exc).__name__}"
    return None


@dataclass(frozen=True, slots=True)
class DoclingRuntimeConfig:
    """Small environment-backed policy for the local Docling pipeline."""

    enabled: bool = True
    artifacts_path: str | None = None
    ocr_backend: str = "onnxruntime"
    ocr_languages: tuple[str, ...] = ("chinese",)
    do_ocr: bool = True
    do_table_structure: bool = True
    table_mode: str = "accurate"
    max_concurrency: int = 1

    def __post_init__(self) -> None:
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        if self.table_mode not in {"fast", "accurate"}:
            raise ValueError("table_mode must be fast or accurate")
        if not self.ocr_languages:
            raise ValueError("ocr_languages must not be empty")

    @classmethod
    def from_env(cls) -> "DoclingRuntimeConfig":
        raw_languages = os.getenv("DOCLING_OCR_LANG", "chinese")
        languages = tuple(item.strip() for item in raw_languages.split(",") if item.strip())
        return cls(
            enabled=truthy(os.getenv("DOCLING_ENABLED", "true")),
            artifacts_path=os.getenv("DOCLING_ARTIFACTS_PATH") or None,
            ocr_backend=os.getenv("DOCLING_OCR_BACKEND", "onnxruntime").strip().lower(),
            ocr_languages=languages or ("chinese",),
            do_ocr=truthy(os.getenv("DOCLING_DO_OCR", "true")),
            do_table_structure=truthy(os.getenv("DOCLING_DO_TABLE_STRUCTURE", "true")),
            table_mode=os.getenv("DOCLING_TABLE_MODE", "accurate").strip().lower(),
            max_concurrency=positive_int(os.getenv("DOCLING_MAX_CONCURRENCY"), 1),
        )


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


class DoclingParser:
    """Use Docling when available and retain a deterministic text fallback.

    Imports and converter construction are lazy so health checks and mock
    conversations do not pay the Docling startup cost.
    """

    _CONTENT_TYPES = {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/html",
        "text/markdown",
        "text/plain",
    }

    def __init__(
        self,
        *,
        strict_binary: bool = True,
        config: DoclingRuntimeConfig | None = None,
    ) -> None:
        self.strict_binary = strict_binary
        self.config = config or DoclingRuntimeConfig.from_env()
        self._converter: Any = None
        self._converter_error: str | None = None
        self._lock = threading.Lock()
        self._conversion_slots = threading.BoundedSemaphore(self.config.max_concurrency)

    @property
    def available(self) -> bool:
        """Report dependency availability without constructing the pipeline."""

        if not self.config.enabled:
            return False
        try:
            return importlib.util.find_spec("docling.document_converter") is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            return False

    @property
    def ocr_backend_error(self) -> str | None:
        """Name of the missing OCR runtime, if the configured one is unusable.

        The converter builds its OCR stage lazily, so a missing runtime only
        blows up during the first conversion. Probing the module here lets
        health surfaces warn before a user uploads anything.
        """

        if not self.config.enabled or not self.config.do_ocr:
            return None
        return ocr_engine_error(self.config.ocr_backend)

    @property
    def ocr_ready(self) -> bool:
        """Whether the configured OCR engine can actually be constructed."""

        return self.ocr_backend_error is None

    @property
    def converter_error(self) -> str | None:
        self._load_converter()
        return public_load_error(self._converter_error)

    @property
    def loaded(self) -> bool:
        """Whether the converter has been constructed without triggering load."""

        return self._converter is not None

    @property
    def load_error(self) -> str | None:
        """Return a cached load error without constructing the converter."""

        return public_load_error(self._converter_error)

    def reset(self) -> None:
        """Drop the converter so a changed model directory can be reloaded."""

        with self._lock:
            self._converter = None
            self._converter_error = None

    def reconfigure(self, config: DoclingRuntimeConfig) -> None:
        """Apply a new parser policy and force lazy converter reconstruction."""

        config.__post_init__()
        with self._lock:
            self.config = config
            self._converter = None
            self._converter_error = None
            self._conversion_slots = threading.BoundedSemaphore(config.max_concurrency)

    def parse(
        self,
        payload: bytes,
        *,
        source_name: str,
        content_type: str | None = None,
        document_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> ParsedDocument:
        if not payload:
            raise DocumentParseError("document payload is empty")
        normalized_type = self._content_type(source_name, content_type, payload)
        details = dict(metadata or {})
        details.update({"source_name": source_name, "content_type": normalized_type})
        try:
            content = self._parse_with_docling(payload, source_name)
            details["parser"] = "docling"
        except Exception as exc:
            if normalized_type in {"text/plain", "text/markdown", "text/html"}:
                content = self._text_fallback(payload, normalized_type)
                details["parser"] = "text-fallback"
                details["parser_warning"] = type(exc).__name__
            elif not self.strict_binary:
                content = payload.decode("utf-8", errors="replace")
                details["parser"] = "lossy-binary-fallback"
                details["parser_warning"] = type(exc).__name__
            else:
                # Source names are user-controlled and can contain local
                # paths, credentials, or other sensitive context. Keep the
                # diagnostic category while leaving the raw detail in the
                # exception chain for server-side debugging only.
                raise DocumentParseError(f"文档解析失败（{type(exc).__name__}）") from exc
        if not content.strip():
            raise DocumentParseError("文档解析结果为空")
        return ParsedDocument(
            document_id=document_id,
            source_name=source_name,
            content=content,
            content_type=normalized_type,
            metadata=details,
        )

    def _parse_with_docling(self, payload: bytes, source_name: str) -> str:
        converter = self._load_converter()
        if converter is None:
            raise RuntimeError(self._converter_error or "docling is unavailable")
        from docling.datamodel.base_models import DocumentStream  # type: ignore[import-not-found]

        source = DocumentStream(name=PurePath(source_name).name, stream=BytesIO(payload))
        # Docling conversion is CPU/memory heavy. Keep the limit inside the
        # parser as a second line of defence for callers that bypass RagService.
        with self._conversion_slots:
            result = converter.convert(source)
        document = getattr(result, "document", result)
        export = getattr(document, "export_to_markdown", None)
        if export is None:
            raise RuntimeError("installed Docling version lacks export_to_markdown")
        return str(export())

    def _load_converter(self) -> Any:
        if self._converter is not None or self._converter_error is not None:
            return self._converter
        with self._lock:
            if self._converter is not None or self._converter_error is not None:
                return self._converter
            if not self.config.enabled:
                self._converter_error = "docling disabled by configuration"
                return None
            try:
                from docling.document_converter import (  # type: ignore[import-not-found]
                    DocumentConverter,
                    ImageFormatOption,
                    InputFormat,
                    PdfFormatOption,
                )
                from docling.datamodel.pipeline_options import (  # type: ignore[import-not-found]
                    PdfPipelineOptions,
                    RapidOcrOptions,
                    TableFormerMode,
                    TableStructureOptions,
                )

                pipeline_options = PdfPipelineOptions(
                    artifacts_path=Path(self.config.artifacts_path) if self.config.artifacts_path else None,
                    do_ocr=self.config.do_ocr,
                    do_table_structure=self.config.do_table_structure,
                    do_picture_classification=False,
                    do_picture_description=False,
                    do_code_enrichment=False,
                    do_formula_enrichment=False,
                )
                if self.config.do_ocr:
                    pipeline_options.ocr_options = RapidOcrOptions(
                        lang=list(self.config.ocr_languages),
                        backend=self.config.ocr_backend,
                    )
                if self.config.do_table_structure:
                    mode = TableFormerMode.FAST if self.config.table_mode == "fast" else TableFormerMode.ACCURATE
                    pipeline_options.table_structure_options = TableStructureOptions(
                        do_cell_matching=True,
                        mode=mode,
                    )
                format_options = {
                    InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
                    InputFormat.IMAGE: ImageFormatOption(pipeline_options=pipeline_options),
                }
                self._converter = DocumentConverter(format_options=format_options)
            except Exception as exc:  # optional dependency/configuration
                self._converter_error = f"{type(exc).__name__}: {exc}"
        return self._converter

    @staticmethod
    def _content_type(source_name: str, content_type: str | None, payload: bytes | None = None) -> str:
        return infer_content_type(source_name, content_type, payload)

    @staticmethod
    def _text_fallback(payload: bytes, content_type: str) -> str:
        text = payload.decode("utf-8", errors="replace")
        if content_type == "text/html":
            parser = _HTMLTextExtractor()
            parser.feed(text)
            return "\n".join(parser.parts)
        return text
