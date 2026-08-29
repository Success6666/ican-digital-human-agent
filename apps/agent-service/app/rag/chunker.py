"""Deterministic text chunking with bounded overlap."""

from __future__ import annotations

import re
from collections.abc import Sequence


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
