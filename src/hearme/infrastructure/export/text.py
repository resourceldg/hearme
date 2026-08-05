"""Exportadores de texto: Markdown, TXT, JSON y EPUB."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from hearme.domain.models import (
    AudioSegment,
    BlockKind,
    ChapterMark,
    Document,
)


class MarkdownExporter:
    name = "markdown"
    extension = ".md"
    needs_audio = False

    async def export(
        self,
        document: Document,
        out_path: Path,
        *,
        segments: Sequence[AudioSegment] | None = None,
        marks: Sequence[ChapterMark] | None = None,
    ) -> Path:
        lines: list[str] = [f"# {document.meta.title}", ""]
        if document.meta.authors:
            lines += [f"*{', '.join(document.meta.authors)}*", ""]

        for chapter in document.chapters:
            for block in chapter.blocks:
                if block.kind in {BlockKind.PAGE_NUMBER, BlockKind.HEADER_FOOTER}:
                    continue
                text = block.text
                match block.kind:
                    case BlockKind.HEADING:
                        lines.append(f"{'#' * min((block.level or 2) + 1, 6)} {text}")
                    case BlockKind.QUOTE:
                        lines.append("\n".join(f"> {ln}" for ln in text.splitlines()))
                    case BlockKind.LIST_ITEM:
                        lines.append(f"- {text}")
                    case BlockKind.CODE:
                        lines += ["```", text, "```"]
                    case _:
                        lines.append(text)

                # Vista comparada original / traducción, si existe.
                if block.translated:
                    lines += ["", f"> **→** {block.translated}"]
                lines.append("")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(lines), encoding="utf-8")
        return out_path


class PlainTextExporter:
    name = "txt"
    extension = ".txt"
    needs_audio = False

    async def export(
        self,
        document: Document,
        out_path: Path,
        *,
        segments: Sequence[AudioSegment] | None = None,
        marks: Sequence[ChapterMark] | None = None,
    ) -> Path:
        parts: list[str] = [document.meta.title, "=" * len(document.meta.title), ""]
        for chapter in document.chapters:
            parts += [chapter.title, "-" * len(chapter.title), "", chapter.text, ""]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(parts), encoding="utf-8")
        return out_path


class JSONExporter:
    """Volcado estructural completo. Es el formato de intercambio para la UI y MCP."""

    name = "json"
    extension = ".json"
    needs_audio = False

    async def export(
        self,
        document: Document,
        out_path: Path,
        *,
        segments: Sequence[AudioSegment] | None = None,
        marks: Sequence[ChapterMark] | None = None,
    ) -> Path:
        payload = {
            "id": document.id,
            "source_format": document.source_format.value,
            "created_at": document.created_at.isoformat(),
            "meta": {
                **{key: value for key, value in asdict(document.meta).items() if key != "cover"},
                "has_cover": document.meta.cover is not None,
            },
            "stats": {
                "chapters": len(document.chapters),
                "characters": document.char_count,
                "estimated_duration_s": round(document.estimated_duration_s(), 1),
            },
            "chapters": [
                {
                    "id": chapter.id,
                    "title": chapter.title,
                    "order": chapter.order,
                    "blocks": [
                        {
                            "id": block.id,
                            "kind": block.kind.value,
                            "text": block.text,
                            "translated": block.translated,
                            "page": block.page,
                            "level": block.level,
                        }
                        for block in chapter.blocks
                    ],
                }
                for chapter in document.chapters
            ],
        }
        if marks:
            payload["chapter_marks"] = [asdict(mark) for mark in marks]

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return out_path


class EPUBExporter:
    """Genera un EPUB limpio a partir del documento canónico.

    Útil sobre todo para convertir un PDF maquetado (o su traducción) en algo
    legible en un lector de tinta electrónica.
    """

    name = "epub"
    extension = ".epub"
    needs_audio = False

    async def export(
        self,
        document: Document,
        out_path: Path,
        *,
        segments: Sequence[AudioSegment] | None = None,
        marks: Sequence[ChapterMark] | None = None,
    ) -> Path:
        from ebooklib import epub

        book = epub.EpubBook()
        book.set_identifier(document.id)
        book.set_title(document.meta.title)
        book.set_language(document.meta.language or "es")
        for author in document.meta.authors:
            book.add_author(author)
        if document.meta.cover:
            book.set_cover("cover.jpg", document.meta.cover)

        items = []
        for index, chapter in enumerate(document.chapters):
            html = [f"<h1>{_esc(chapter.title)}</h1>"]
            for block in chapter.blocks:
                if block.kind in {BlockKind.PAGE_NUMBER, BlockKind.HEADER_FOOTER}:
                    continue
                text = _esc(block.text)
                match block.kind:
                    case BlockKind.HEADING:
                        level = min((block.level or 2) + 1, 6)
                        html.append(f"<h{level}>{text}</h{level}>")
                    case BlockKind.QUOTE:
                        html.append(f"<blockquote><p>{text}</p></blockquote>")
                    case BlockKind.LIST_ITEM:
                        html.append(f"<ul><li>{text}</li></ul>")
                    case BlockKind.CODE:
                        html.append(f"<pre><code>{text}</code></pre>")
                    case _:
                        html.append(f"<p>{text}</p>")
                if block.translated:
                    html.append(f'<p class="translated"><em>{_esc(block.translated)}</em></p>')

            item = epub.EpubHtml(
                title=chapter.title,
                file_name=f"chap_{index:04d}.xhtml",
                lang=document.meta.language or "es",
            )
            item.content = "".join(html)
            book.add_item(item)
            items.append(item)

        book.toc = tuple(items)
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = ["nav", *items]

        out_path.parent.mkdir(parents=True, exist_ok=True)
        epub.write_epub(str(out_path), book)
        return out_path


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
