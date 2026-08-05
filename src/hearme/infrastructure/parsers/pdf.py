"""Parser PDF.

Combina dos librerías por una razón concreta (ver docs/ANALISIS-COMPARATIVO.md §3):
  - pypdfium2 (Apache-2.0): TOC nativo y número de páginas, muy rápido.
  - pdfminer.six (MIT): tamaño y peso de fuente, imprescindibles para inferir
    encabezados cuando el PDF no trae marcadores.

Se evita PyMuPDF en el núcleo por su licencia AGPL-3.0.
"""

from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from hearme.application.cleaning import (
    clean_blocks,
    detect_running_heads,
)
from hearme.domain.models import (
    Block,
    BlockKind,
    Chapter,
    Document,
    DocumentMeta,
    SourceFormat,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _Line:
    text: str
    page: int
    size: float
    bold: bool


class PDFParser:
    name = "pdf"
    formats = frozenset({SourceFormat.PDF})

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower() == ".pdf"

    async def parse(self, path: Path) -> Document:
        import anyio

        # pdfminer es síncrono y pesado: fuera del event loop.
        lines = await anyio.to_thread.run_sync(self._extract_lines, path)
        meta = await anyio.to_thread.run_sync(self._extract_meta, path)
        outline = await anyio.to_thread.run_sync(self._extract_outline, path)

        lines_by_page: dict[int, list[str]] = defaultdict(list)
        for line in lines:
            lines_by_page[line.page].append(line.text)
        running_heads = detect_running_heads(lines_by_page)

        blocks = self._lines_to_blocks(lines)
        blocks = clean_blocks(blocks, running_heads)
        chapters = self._build_chapters(blocks, outline, meta.title)

        return Document(
            source_path=path,
            source_format=SourceFormat.PDF,
            meta=meta,
            chapters=chapters,
        )

    # --- extracción ---------------------------------------------------------

    @staticmethod
    def _extract_lines(path: Path) -> list[_Line]:
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LAParams, LTChar, LTTextContainer

        lines: list[_Line] = []
        params = LAParams(line_margin=0.5, char_margin=2.0, boxes_flow=0.5)

        for page_no, layout in enumerate(extract_pages(str(path), laparams=params), start=1):
            for element in layout:
                if not isinstance(element, LTTextContainer):
                    continue
                for text_line in element:
                    chars = [c for c in getattr(text_line, "_objs", []) if isinstance(c, LTChar)]
                    text = text_line.get_text().strip() if hasattr(text_line, "get_text") else ""
                    if not text or not chars:
                        continue
                    size = statistics.median(c.size for c in chars)
                    # pdfminer expone el nombre de la fuente; "Bold"/"Black" es la
                    # señal más fiable de énfasis tipográfico.
                    bold = (
                        sum(
                            1
                            for c in chars
                            if "bold" in c.fontname.lower() or "black" in c.fontname.lower()
                        )
                        > len(chars) / 2
                    )
                    lines.append(_Line(text=text, page=page_no, size=round(size, 1), bold=bold))
        return lines

    @staticmethod
    def _extract_meta(path: Path) -> DocumentMeta:
        title = path.stem
        authors: list[str] = []
        pages = None
        try:
            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(str(path))
        except Exception:
            logger.debug("no se pudieron leer metadatos del PDF", exc_info=True)
            return DocumentMeta(title=title, authors=authors, page_count=pages)
        try:
            pages = len(pdf)
            raw = pdf.get_metadata_dict() or {}
            title = (raw.get("Title") or "").strip() or path.stem
            if author := (raw.get("Author") or "").strip():
                authors = [a.strip() for a in author.replace(";", ",").split(",") if a.strip()]
        finally:
            pdf.close()
        return DocumentMeta(title=title, authors=authors, page_count=pages)

    @staticmethod
    def _extract_outline(path: Path) -> list[tuple[str, int]]:
        """Marcadores nativos -> [(título, nivel)]. Es el índice más fiable si existe."""
        try:
            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(str(path))
        except Exception:
            logger.debug("PDF sin marcadores utilizables", exc_info=True)
            return []
        try:
            entries = [
                (item.get_title().strip(), (item.get_count() and 1) or 1)
                for item in pdf.get_toc()
                if item.get_title()
            ]
            return entries
        except Exception:
            logger.debug("PDF sin marcadores utilizables", exc_info=True)
            return []
        finally:
            pdf.close()

    # --- estructura ---------------------------------------------------------

    @staticmethod
    def _lines_to_blocks(lines: list[_Line]) -> list[Block]:
        """Agrupa líneas en bloques e infiere encabezados por tamaño de fuente.

        Criterio: una línea es encabezado si su cuerpo es notablemente mayor que el
        tamaño modal del documento (el del texto corrido), o si es negrita y corta.
        """
        if not lines:
            return []

        body_size = statistics.mode([line.size for line in lines])
        heading_threshold = body_size * 1.15

        blocks: list[Block] = []
        buffer: list[_Line] = []
        order = 0

        def flush() -> None:
            nonlocal order, buffer
            if not buffer:
                return
            text = " ".join(line.text for line in buffer).strip()
            if text:
                blocks.append(
                    Block(
                        kind=BlockKind.PARAGRAPH,
                        text=text,
                        order=order,
                        page=buffer[0].page,
                        font_size=buffer[0].size,
                    )
                )
                order += 1
            buffer = []

        for line in lines:
            is_heading = line.size >= heading_threshold or (
                line.bold and len(line.text) < 90 and not line.text.endswith((".", ","))
            )
            if is_heading:
                flush()
                level = 1 if line.size >= body_size * 1.5 else 2
                blocks.append(
                    Block(
                        kind=BlockKind.HEADING,
                        text=line.text,
                        order=order,
                        page=line.page,
                        level=level,
                        font_size=line.size,
                        bold=line.bold,
                    )
                )
                order += 1
                continue

            buffer.append(line)
            # Fin de párrafo: puntuación terminal.
            if line.text.endswith((".", "!", "?", "»", "”", ":")):
                flush()

        flush()
        return blocks

    @staticmethod
    def _build_chapters(
        blocks: list[Block], outline: list[tuple[str, int]], fallback: str
    ) -> list[Chapter]:
        outline_titles = {title.lower() for title, _ in outline}
        chapters: list[Chapter] = []
        current = Chapter(title=fallback, order=0)

        for block in blocks:
            # Si el PDF trae marcadores, solo esos abren capítulo: evita que un
            # subtítulo en negrita fragmente el libro en cien trozos.
            opens = block.kind is BlockKind.HEADING and (
                block.text.lower() in outline_titles if outline_titles else (block.level or 9) == 1
            )
            if opens and current.blocks:
                chapters.append(current)
                current = Chapter(title=block.text, order=len(chapters))
            elif opens:
                current.title = block.text
            current.blocks.append(block)

        if current.blocks:
            chapters.append(current)
        return chapters or [Chapter(title=fallback, order=0)]
