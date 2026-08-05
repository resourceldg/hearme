"""OCR con OCRmyPDF.

La parte interesante no es invocar el OCR, es *decidir cuándo*. Ver
docs/ANALISIS-COMPARATIVO.md §4: se muestrean páginas repartidas por el documento
y se mide la densidad de caracteres de la capa de texto.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Any

from hearme.config import settings

logger = logging.getLogger(__name__)

#: Por encima de este umbral, la capa de texto se considera sana.
GOOD_COVERAGE = 500
#: Páginas muestreadas como máximo. Suficiente para decidir, barato de calcular.
SAMPLE_PAGES = 12


class OCRmyPDFEngine:
    name = "ocrmypdf"

    def __init__(self, *, language: str | None = None) -> None:
        self.language = language or settings.ocr_language

    @staticmethod
    def _binary_available() -> bool:
        return shutil.which("ocrmypdf") is not None and shutil.which("tesseract") is not None

    async def coverage(self, path: Path) -> float:
        """Caracteres por página en la capa de texto existente."""
        import anyio

        return await anyio.to_thread.run_sync(self._coverage_sync, path)

    @staticmethod
    def _coverage_sync(path: Path) -> float:
        try:
            import pypdfium2 as pdfium
        except ImportError:
            logger.warning("pypdfium2 ausente: no se puede evaluar la capa de texto")
            return float(GOOD_COVERAGE)

        pdf: Any | None = None
        try:
            pdf = pdfium.PdfDocument(str(path))
            total = len(pdf)
            if total == 0:
                return 0.0
            # Muestreo repartido: un libro escaneado con portada digital no debe
            # engañar a la heurística.
            step = max(1, total // SAMPLE_PAGES)
            indices = list(range(0, total, step))[:SAMPLE_PAGES]

            chars = 0
            for index in indices:
                page = pdf[index]
                textpage = page.get_textpage()
                chars += len(textpage.get_text_range().strip())
                textpage.close()
                page.close()
            return chars / len(indices)
        finally:
            if pdf is not None:
                pdf.close()

    async def needs_ocr(self, path: Path) -> bool:
        if path.suffix.lower() != ".pdf" or not settings.ocr_enabled:
            return False
        if not self._binary_available():
            logger.warning(
                "OCR desactivado: faltan binarios. sudo apt install ocrmypdf tesseract-ocr"
            )
            return False

        density = await self.coverage(path)
        logger.info(
            "densidad de texto: %.0f car/página (umbral %d)",
            density,
            settings.ocr_char_threshold,
        )
        return density < GOOD_COVERAGE

    async def apply(self, path: Path, out_path: Path, *, language: str | None = None) -> Path:
        if not self._binary_available():
            raise RuntimeError(
                "ocrmypdf/tesseract no instalados. "
                "sudo apt install ocrmypdf tesseract-ocr tesseract-ocr-spa"
            )

        density = await self.coverage(path)
        # Sin capa de texto: --force-ocr crea una capa nueva.
        # Capa parcial: --redo-ocr respeta el texto bueno y solo rehace lo que falta.
        # Capa sana: no deberíamos llegar aquí (needs_ocr descarta >= GOOD_COVERAGE).
        if density < settings.ocr_char_threshold:
            mode = "--force-ocr"
        elif density < GOOD_COVERAGE:
            mode = "--redo-ocr"
        else:
            mode = "--skip-text"

        out_path.parent.mkdir(parents=True, exist_ok=True)
        args = [
            "ocrmypdf",
            mode,
            "--language",
            language or self.language,
            "--optimize",
            "1",
            "--jobs",
            str(max(1, (settings.max_workers or 4))),
            "--quiet",
            str(path),
            str(out_path),
        ]
        logger.info("ejecutando OCR (%s) sobre %s", mode, path.name)

        process = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(
                f"ocrmypdf falló ({process.returncode}): {stderr.decode(errors='replace')[-800:]}"
            )
        return out_path
