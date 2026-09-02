"""Deterministic text chunking with bounded overlap."""

from __future__ import annotations

import re
from dataclasses import dataclass
from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    """A child chunk plus bounded parent context for answer synthesis."""

    text: str
    metadata: dict[str, object]


class CharacterChunker:
    """Split paragraphs into bounded chunks while preserving readable context."""

    def __init__(self, max_chars: int = 1200, overlap_chars: int = 120) -> None:
        if max_chars < 64:
            raise ValueError("max_chars must be at least 64")
        if overlap_chars < 0 or overlap_chars >= max_chars:
            raise ValueError("overlap_chars must be in [0, max_chars)")
        self.max_chars = max_chars
        self.overlap_chars = overlap_chars

    def split(self, text: str, *, metadata: dict | None = None) -> Sequence[str]:
        normalized = self._normalize(text)
        if not normalized:
            return []
        units = self._paragraphs(normalized)
        pieces: list[str] = []
        current = ""
        for unit in units:
            for part in self._bounded(unit):
                candidate = f"{current}\n\n{part}" if current else part
                if len(candidate) <= self.max_chars:
                    current = candidate
                    continue
                if current:
                    pieces.append(current)
                overlap = current[-self.overlap_chars :] if self.overlap_chars else ""
                current = f"{overlap}\n\n{part}".strip() if overlap else part
                if len(current) > self.max_chars:
                    pieces.extend(self._bounded(current))
                    current = ""
        if current:
            pieces.append(current)
        return [piece.strip() for piece in pieces if piece.strip()]

    def _bounded(self, text: str) -> list[str]:
        if len(text) <= self.max_chars:
            return [text]
        words = re.split(r"\s+", text)
        result: list[str] = []
        current = ""
        for word in words:
            if not word:
                continue
            if len(word) > self.max_chars:
                if current:
                    result.append(current)
                    current = ""
                result.extend(
                    word[index : index + self.max_chars]
                    for index in range(0, len(word), self.max_chars)
                )
                continue
            candidate = f"{current} {word}".strip()
            if len(candidate) <= self.max_chars:
                current = candidate
            else:
                result.append(current)
                current = word
        if current:
            result.append(current)
        return result

    @staticmethod
    def _normalize(text: str) -> str:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _paragraphs(text: str) -> list[str]:
        return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]


class HierarchicalChunker(CharacterChunker):
    """Structure-aware parent/child chunker for knowledge-base retrieval."""

    _HEADING_RE = re.compile(r"^(?:#{1,6}\s+|第[一二三四五六七八九十百千万0-9]+[章节篇]\s*|[一二三四五六七八九十百千万0-9]+[、.])")

    def __init__(self, max_chars: int = 720, overlap_chars: int = 80, *, parent_max_chars: int = 2400, parent_overlap_chars: int = 160) -> None:
        super().__init__(max_chars=max_chars, overlap_chars=overlap_chars)
        if parent_max_chars < max_chars or parent_overlap_chars < 0 or parent_overlap_chars >= parent_max_chars:
            raise ValueError("parent chunk bounds are invalid")
        self.parent_max_chars = parent_max_chars
        self.parent_overlap_chars = parent_overlap_chars

    def split_with_metadata(self, text: str, *, metadata: dict | None = None) -> Sequence[ChunkDraft]:
        normalized = self._normalize(text)
        if not normalized:
            return []
        parents: list[str] = []
        current = ""
        for section in self._sections(normalized):
            for part in self._bounded_with_limit(section, self.parent_max_chars):
                candidate = f"{current}\n\n{part}" if current else part
                if len(candidate) <= self.parent_max_chars:
                    current = candidate
                    continue
                if current:
                    parents.append(current.strip())
                overlap = current[-self.parent_overlap_chars:] if self.parent_overlap_chars else ""
                current = f"{overlap}\n\n{part}".strip() if overlap else part
                if len(current) > self.parent_max_chars:
                    parents.extend(self._bounded_with_limit(current, self.parent_max_chars))
                    current = ""
        if current:
            parents.append(current.strip())
        drafts: list[ChunkDraft] = []
        for parent_index, parent in enumerate(parents):
            children = self._bounded_with_limit(parent, self.max_chars, self.overlap_chars)
            section_path = self._section_path(parent)
            for child_index, child in enumerate(children):
                drafts.append(ChunkDraft(child.strip(), {
                    "parent_index": parent_index,
                    "child_index": child_index,
                    "section_path": section_path,
                    "parent_text": parent[: self.parent_max_chars],
                }))
        return drafts

    def split(self, text: str, *, metadata: dict | None = None) -> Sequence[str]:
        return [draft.text for draft in self.split_with_metadata(text, metadata=metadata)]

    def _bounded_with_limit(self, text: str, limit: int, overlap: int = 0) -> list[str]:
        if len(text) <= limit:
            return [text]
        units = re.split(r"(?<=[。！？；.!?;])|\n+|\s+", text)
        result: list[str] = []
        current = ""
        for unit in units:
            unit = unit.strip()
            if not unit:
                continue
            candidate = f"{current} {unit}".strip()
            if len(candidate) <= limit:
                current = candidate
                continue
            if current:
                result.append(current)
            carry = current[-overlap:] if overlap else ""
            current = f"{carry} {unit}".strip() if carry else unit
            if len(current) > limit:
                result.extend(current[index:index + limit] for index in range(0, len(current), limit))
                current = ""
        if current:
            result.append(current)
        return result

    @classmethod
    def _sections(cls, text: str) -> list[str]:
        sections: list[str] = []
        current: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped and cls._HEADING_RE.match(stripped) and current:
                sections.append("\n".join(current).strip())
                current = []
            if stripped:
                current.append(stripped)
        if current:
            sections.append("\n".join(current).strip())
        return sections or [text]

    @classmethod
    def _section_path(cls, parent: str) -> str:
        return " / ".join(line.strip() for line in parent.splitlines() if cls._HEADING_RE.match(line.strip()))[:512]
