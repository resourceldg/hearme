"""Alta de los adaptadores internos.

Se registra por el mismo mecanismo de `entry_points` que usarían los plugins de
terceros — el núcleo no tiene un camino privilegiado. Los imports son perezosos y
tolerantes a fallo: sin el extra `documents`, el parser de PDF simplemente no
aparece en el registro y el resto sigue funcionando.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hearme.application.plugins import PluginManager

logger = logging.getLogger(__name__)


def register_builtins(manager: PluginManager) -> None:
    _register_parsers(manager)
    _register_tts(manager)
    _register_exporters(manager)
    _register_translators(manager)
    _register_ocr(manager)
    _register_llm(manager)


def _try(kind: str, name: str, register) -> None:
    try:
        register()
    except ImportError as exc:
        logger.debug("%s '%s' no disponible: %s", kind, name, exc)
    except Exception:
        logger.warning("fallo registrando %s '%s'", kind, name, exc_info=True)


def _register_parsers(manager: PluginManager) -> None:
    from hearme.infrastructure.parsers.text import MarkdownParser, PlainTextParser

    # Sin dependencias: siempre disponibles.
    manager.parsers.register("text", PlainTextParser())
    manager.parsers.register("markdown", MarkdownParser())

    def html() -> None:
        from hearme.infrastructure.parsers.html import (
            HTMLParser,
            RSSParser,
            WebArticleParser,
        )

        manager.parsers.register("html", HTMLParser())
        manager.parsers.register("web", WebArticleParser())
        manager.parsers.register("rss", RSSParser())

    def epub() -> None:
        from hearme.infrastructure.parsers.epub import EPUBParser

        manager.parsers.register("epub", EPUBParser())

    def pdf() -> None:
        from hearme.infrastructure.parsers.pdf import PDFParser

        manager.parsers.register("pdf", PDFParser())

    def office() -> None:
        from hearme.infrastructure.parsers.office import (
            DOCXParser,
            ODTParser,
            RTFParser,
        )

        manager.parsers.register("docx", DOCXParser())
        manager.parsers.register("odt", ODTParser())
        manager.parsers.register("rtf", RTFParser())

    for name, fn in (("html", html), ("epub", epub), ("pdf", pdf), ("office", office)):
        _try("parser", name, fn)


def _register_tts(manager: PluginManager) -> None:
    def kokoro() -> None:
        from hearme.infrastructure.tts.kokoro import KokoroEngine

        manager.tts.register("kokoro", KokoroEngine())

    def piper() -> None:
        from hearme.infrastructure.tts.piper import PiperEngine

        manager.tts.register("piper", PiperEngine())

    # Se registran aunque falte la dependencia pesada: el módulo solo importa
    # torch/onnx dentro de los métodos. `is_available()` decide de verdad.
    for name, fn in (("kokoro", kokoro), ("piper", piper)):
        _try("tts", name, fn)


def _register_exporters(manager: PluginManager) -> None:
    from hearme.infrastructure.export.audio import M4BExporter, MP3Exporter
    from hearme.infrastructure.export.text import (
        JSONExporter,
        MarkdownExporter,
        PlainTextExporter,
    )

    manager.exporters.register("mp3", MP3Exporter())
    manager.exporters.register("m4b", M4BExporter(), aliases=("audiobook", "m4a"))
    # Los alias existen porque la gente escribe '-f md', no '-f markdown'.
    manager.exporters.register("markdown", MarkdownExporter(), aliases=("md",))
    manager.exporters.register("txt", PlainTextExporter(), aliases=("text", "plain"))
    manager.exporters.register("json", JSONExporter())

    def epub_out() -> None:
        from hearme.infrastructure.export.text import EPUBExporter

        manager.exporters.register("epub", EPUBExporter())

    _try("exporter", "epub", epub_out)


def _register_translators(manager: PluginManager) -> None:
    def translators() -> None:
        from hearme.infrastructure.translate.marian import (
            MarianTranslator,
            NLLBTranslator,
        )

        manager.translators.register("marian", MarianTranslator())
        manager.translators.register("nllb", NLLBTranslator())

    _try("translator", "marian/nllb", translators)


def _register_ocr(manager: PluginManager) -> None:
    def ocr() -> None:
        from hearme.infrastructure.ocr.ocrmypdf_engine import OCRmyPDFEngine

        manager.ocr.register("ocrmypdf", OCRmyPDFEngine())

    _try("ocr", "ocrmypdf", ocr)


def _register_llm(manager: PluginManager) -> None:
    from hearme.infrastructure.llm.ollama import OllamaProvider

    manager.llm.register("ollama", OllamaProvider())
