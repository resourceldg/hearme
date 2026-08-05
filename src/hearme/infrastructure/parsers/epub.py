"""Parser EPUB. Usa el spine (orden de lectura real) y el NCX/NAV para los títulos."""

from __future__ import annotations

from pathlib import Path

import anyio

from hearme.application.cleaning import clean_blocks
from hearme.domain.models import (
    BlockKind,
    Chapter,
    Document,
    DocumentMeta,
    SourceFormat,
)
from hearme.infrastructure.parsers.html import blocks_from_html


class EPUBParser:
    name = "epub"
    formats = frozenset({SourceFormat.EPUB})

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower() == ".epub"

    async def parse(self, path: Path) -> Document:
        return await anyio.to_thread.run_sync(self._parse_sync, path)

    def _parse_sync(self, path: Path) -> Document:
        import ebooklib
        from ebooklib import epub

        book = epub.read_epub(str(path), options={"ignore_ncx": False})
        meta = self._read_meta(book, path)

        # El TOC da los títulos legibles; el spine da el orden correcto de lectura.
        toc_titles = self._toc_titles(book)

        chapters: list[Chapter] = []
        for item_id, _ in book.spine:
            item = book.get_item_with_id(item_id)
            if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
                continue

            doc_title, blocks = blocks_from_html(item.get_content().decode("utf-8", "replace"))
            blocks = clean_blocks(blocks)
            if not any(b.is_narrated for b in blocks):
                continue  # portadas, páginas de créditos vacías

            title = (
                toc_titles.get(item.get_name())
                or next(
                    (b.text for b in blocks if b.kind is BlockKind.HEADING),
                    None,
                )
                or doc_title
                or f"Sección {len(chapters) + 1}"
            )
            chapters.append(Chapter(title=title, order=len(chapters), blocks=blocks))

        return Document(
            source_path=path,
            source_format=SourceFormat.EPUB,
            meta=meta,
            chapters=chapters or [Chapter(title=meta.title, order=0)],
        )

    @staticmethod
    def _toc_titles(book: object) -> dict[str, str]:
        """Aplana el TOC (que es un árbol con tuplas anidadas) a href -> título."""
        titles: dict[str, str] = {}

        def walk(nodes: object) -> None:
            if isinstance(nodes, (list, tuple)):
                for node in nodes:
                    walk(node)
                return
            href = getattr(nodes, "href", None)
            title = getattr(nodes, "title", None)
            if href and title:
                titles[href.split("#")[0]] = title

        walk(getattr(book, "toc", []))
        return titles

    @staticmethod
    def _read_meta(book: object, path: Path) -> DocumentMeta:
        def field(name: str) -> list[str]:
            values = book.get_metadata("DC", name)  # type: ignore[attr-defined]
            return [v[0] for v in values if v and v[0]]

        titles = field("title")
        cover: bytes | None = None
        try:
            import ebooklib

            covers = list(book.get_items_of_type(ebooklib.ITEM_COVER))  # type: ignore[attr-defined]
            if covers:
                cover = covers[0].get_content()
        except Exception:
            cover = None

        languages = field("language")
        return DocumentMeta(
            title=titles[0] if titles else path.stem,
            authors=field("creator"),
            language=languages[0].split("-")[0].lower() if languages else None,
            publisher=next(iter(field("publisher")), None),
            published=next(iter(field("date")), None),
            isbn=next(iter(field("identifier")), None),
            cover=cover,
        )
