"""Parsers de texto plano y Markdown. Sin dependencias externas."""

from __future__ import annotations

import re
from pathlib import Path

import anyio

from hearme.application.cleaning import clean_blocks
from hearme.domain.models import (
    Block,
    BlockKind,
    Chapter,
    Document,
    DocumentMeta,
    SourceFormat,
)

_ATX_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_SETEXT_H1 = re.compile(r"^={3,}\s*$")
_SETEXT_H2 = re.compile(r"^-{3,}\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[\.\)])\s+")
_QUOTE = re.compile(r"^\s*>\s?")


def _read(path: Path) -> str:
    raw = path.read_bytes()
    try:
        from charset_normalizer import from_bytes

        if (best := from_bytes(raw).best()) is not None:
            return str(best)
    except ImportError:
        pass
    return raw.decode("utf-8", errors="replace")


class PlainTextParser:
    name = "text"
    formats = frozenset({SourceFormat.TXT})

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower() == ".txt"

    async def parse(self, path: Path) -> Document:
        content = await anyio.to_thread.run_sync(_read, path)
        blocks = [
            Block(kind=BlockKind.PARAGRAPH, text=chunk.strip(), order=i)
            for i, chunk in enumerate(re.split(r"\n\s*\n", content))
            if chunk.strip()
        ]
        chapter = Chapter(title=path.stem, order=0, blocks=clean_blocks(blocks))
        return Document(
            source_path=path,
            source_format=SourceFormat.TXT,
            meta=DocumentMeta(title=path.stem),
            chapters=[chapter],
        )


class MarkdownParser:
    """Markdown a bloques semánticos.

    Se usa un lexer propio en lugar de renderizar a HTML porque necesitamos
    conservar el *nivel* de encabezado para construir capítulos, y el redondeo por
    HTML perdería la distinción entre cita y párrafo.
    """

    name = "markdown"
    formats = frozenset({SourceFormat.MARKDOWN})

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower() in {".md", ".markdown"}

    async def parse(self, path: Path) -> Document:
        lines = (await anyio.to_thread.run_sync(_read, path)).splitlines()
        chapters: list[Chapter] = []
        current = Chapter(title=path.stem, order=0)
        order = 0
        in_fence = False
        buffer: list[str] = []
        buffer_kind = BlockKind.PARAGRAPH

        def flush() -> None:
            nonlocal order, buffer, buffer_kind
            if text := "\n".join(buffer).strip():
                current.blocks.append(Block(kind=buffer_kind, text=text, order=order))
                order += 1
            buffer = []
            buffer_kind = BlockKind.PARAGRAPH

        for index, line in enumerate(lines):
            if _FENCE.match(line):
                if in_fence:
                    flush()
                else:
                    flush()
                    buffer_kind = BlockKind.CODE
                in_fence = not in_fence
                continue

            if in_fence:
                buffer.append(line)
                continue

            if match := _ATX_HEADING.match(line):
                flush()
                level, title = len(match.group(1)), match.group(2).strip()
                # H1/H2 abren capítulo; los niveles menores son secciones internas.
                if level <= 2 and current.blocks:
                    chapters.append(current)
                    current = Chapter(title=title, order=len(chapters), level=level)
                elif level <= 2:
                    current.title = title
                    current.level = level
                current.blocks.append(
                    Block(kind=BlockKind.HEADING, text=title, order=order, level=level)
                )
                order += 1
                continue

            # Setext: el subrayado convierte la línea anterior en encabezado.
            if buffer and (_SETEXT_H1.match(line) or _SETEXT_H2.match(line)):
                title = buffer[-1].strip()
                buffer = buffer[:-1]
                flush()
                level = 1 if _SETEXT_H1.match(line) else 2
                if current.blocks:
                    chapters.append(current)
                    current = Chapter(title=title, order=len(chapters), level=level)
                current.blocks.append(
                    Block(kind=BlockKind.HEADING, text=title, order=order, level=level)
                )
                order += 1
                continue

            if not line.strip():
                flush()
                continue

            if _QUOTE.match(line):
                if buffer_kind is not BlockKind.QUOTE:
                    flush()
                buffer_kind = BlockKind.QUOTE
                buffer.append(_QUOTE.sub("", line))
            elif _LIST_ITEM.match(line):
                flush()
                buffer_kind = BlockKind.LIST_ITEM
                buffer.append(_LIST_ITEM.sub("", line))
                flush()
            else:
                buffer.append(line)

            del index  # solo para claridad del bucle

        flush()
        if current.blocks:
            chapters.append(current)

        for chapter in chapters:
            chapter.blocks = clean_blocks(chapter.blocks)

        title = chapters[0].title if chapters else path.stem
        return Document(
            source_path=path,
            source_format=SourceFormat.MARKDOWN,
            meta=DocumentMeta(title=title),
            chapters=chapters or [Chapter(title=path.stem, order=0)],
        )
