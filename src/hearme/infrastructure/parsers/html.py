"""Parser HTML: archivos locales, artículos web y feeds RSS.

Requiere el extra `documents` (beautifulsoup4 + lxml).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

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

#: Etiquetas sin valor narrativo: navegación, scripts, publicidad.
_STRIP_TAGS = (
    "script",
    "style",
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "noscript",
    "iframe",
    "svg",
    "button",
)

_TAG_TO_KIND = {
    "p": BlockKind.PARAGRAPH,
    "blockquote": BlockKind.QUOTE,
    "li": BlockKind.LIST_ITEM,
    "pre": BlockKind.CODE,
    "code": BlockKind.CODE,
    "figcaption": BlockKind.CAPTION,
    "table": BlockKind.TABLE,
}

_CONTENT_HINTS = ("article", "main", '[role="main"]', ".post-content", ".entry-content")


def _require_bs4() -> Any:
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover - camino de dependencia ausente
        raise RuntimeError(
            "El parser HTML necesita el extra 'documents': uv pip install 'hearme[documents]'"
        ) from exc
    return BeautifulSoup


def blocks_from_html(html: str) -> tuple[str | None, list[Block]]:
    """Extrae título y bloques semánticos. Reutilizado por el parser EPUB."""
    BeautifulSoup = _require_bs4()
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(_STRIP_TAGS):
        tag.decompose()

    title = soup.title.get_text(strip=True) if soup.title else None

    # Preferimos el contenedor de contenido real; si no hay, todo el body.
    root = next(
        (found for hint in _CONTENT_HINTS if (found := soup.select_one(hint))),
        soup.body or soup,
    )

    blocks: list[Block] = []
    order = 0
    selector = "h1,h2,h3,h4,h5,h6,p,blockquote,li,pre,figcaption,table"

    for element in root.select(selector):
        # Un <p> dentro de <blockquote> ya se narra con su padre: evita duplicar.
        if element.find_parent(["blockquote", "pre", "table"]) is not None:
            continue

        text = element.get_text(" ", strip=True)
        if not text:
            continue

        name = element.name.lower()
        if name.startswith("h") and len(name) == 2 and name[1].isdigit():
            kind, level = BlockKind.HEADING, int(name[1])
        else:
            kind, level = _TAG_TO_KIND.get(name, BlockKind.PARAGRAPH), None

        blocks.append(Block(kind=kind, text=text, order=order, level=level))
        order += 1

    return title, blocks


def blocks_to_chapters(blocks: list[Block], fallback_title: str) -> list[Chapter]:
    """Parte una lista plana de bloques en capítulos usando los encabezados H1/H2."""
    chapters: list[Chapter] = []
    current = Chapter(title=fallback_title, order=0)

    for block in blocks:
        opens_chapter = (
            block.kind is BlockKind.HEADING and (block.level or 9) <= 2 and current.blocks
        )
        if opens_chapter:
            chapters.append(current)
            current = Chapter(title=block.text, order=len(chapters), level=block.level or 1)
        elif block.kind is BlockKind.HEADING and (block.level or 9) <= 2:
            current.title = block.text
        current.blocks.append(block)

    if current.blocks:
        chapters.append(current)
    return chapters or [Chapter(title=fallback_title, order=0)]


class HTMLParser:
    name = "html"
    formats = frozenset({SourceFormat.HTML, SourceFormat.WEB})

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower() in {".html", ".htm", ".xhtml"}

    async def parse(self, path: Path) -> Document:
        raw = await anyio.to_thread.run_sync(path.read_text, "utf-8", "replace")
        title, blocks = await anyio.to_thread.run_sync(blocks_from_html, raw)
        blocks = clean_blocks(blocks)
        name = title or path.stem
        return Document(
            source_path=path,
            source_format=SourceFormat.HTML,
            meta=DocumentMeta(title=name),
            chapters=blocks_to_chapters(blocks, name),
        )


class WebArticleParser:
    """Descarga una URL y la convierte en documento.

    `path` es aquí un fichero `.url` con la dirección, para que la URL entre por el
    mismo pipeline de archivos (carpetas vigiladas incluidas).
    """

    name = "web"
    formats = frozenset({SourceFormat.WEB})

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower() == ".url"

    async def parse(self, path: Path) -> Document:
        import httpx

        url = path.read_text(encoding="utf-8").strip()
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=30,
            headers={"User-Agent": "HearMe/0.1 (+https://github.com/hearme)"},
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

        title, blocks = await anyio.to_thread.run_sync(blocks_from_html, response.text)
        blocks = clean_blocks(blocks)
        name = title or url
        return Document(
            source_path=path,
            source_format=SourceFormat.WEB,
            meta=DocumentMeta(title=name, extra={"url": url}),
            chapters=blocks_to_chapters(blocks, name),
        )


class RSSParser:
    name = "rss"
    formats = frozenset({SourceFormat.RSS})

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower() in {".rss", ".xml", ".atom"}

    async def parse(self, path: Path) -> Document:
        import feedparser

        feed = await anyio.to_thread.run_sync(feedparser.parse, str(path))
        chapters: list[Chapter] = []

        # Cada entrada del feed es un capítulo: así el m4b resultante es navegable.
        for index, entry in enumerate(feed.entries):
            raw = ""
            if content := entry.get("content"):
                raw = content[0].get("value", "")
            raw = raw or entry.get("summary", "")

            if raw:
                _, blocks = await anyio.to_thread.run_sync(blocks_from_html, raw)
            else:
                blocks = []
            entry_title = entry.get("title", f"Entrada {index + 1}")
            blocks.insert(0, Block(kind=BlockKind.HEADING, text=entry_title, order=0, level=1))
            chapters.append(Chapter(title=entry_title, order=index, blocks=clean_blocks(blocks)))

        title = feed.feed.get("title", path.stem) if feed.feed else path.stem
        return Document(
            source_path=path,
            source_format=SourceFormat.RSS,
            meta=DocumentMeta(title=title),
            chapters=chapters or [Chapter(title=title, order=0)],
        )
