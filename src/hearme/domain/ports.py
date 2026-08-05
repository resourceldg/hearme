"""Puertos: contratos que la infraestructura debe cumplir.

Se definen como `Protocol` (tipado estructural) a propósito. Un plugin de terceros
implementa un motor TTS sin importar nada de HearMe: le basta con tener los
métodos correctos. Eso mantiene el acoplamiento en cero.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from hearme.domain.models import (
    AudioSegment,
    ChapterMark,
    Document,
    SourceFormat,
    Utterance,
)


@runtime_checkable
class DocumentParser(Protocol):
    """Convierte un archivo de un formato concreto en el `Document` canónico."""

    name: str
    formats: frozenset[SourceFormat]

    def can_parse(self, path: Path) -> bool: ...

    async def parse(self, path: Path) -> Document: ...


@runtime_checkable
class TTSEngine(Protocol):
    """Motor de síntesis de voz."""

    name: str
    #: Idiomas soportados (ISO-639-1). Alimenta al selector automático.
    languages: frozenset[str]
    #: Puntuación de naturalidad 0..1, declarada por el motor. Criterio primario
    #: del selector cuando la calidad es la prioridad.
    naturalness: float
    #: Real-Time Factor típico en CPU. Menor es mejor.
    rtf: float
    #: True si su licencia impide uso comercial (XTTS-v2). El selector lo excluye
    #: salvo activación explícita.
    non_commercial: bool

    async def is_available(self) -> bool: ...

    async def voices(self, language: str | None = None) -> Sequence[str]: ...

    async def synthesize(
        self, utterance: Utterance, *, voice: str, out_dir: Path
    ) -> AudioSegment: ...

    async def close(self) -> None:
        """Libera memoria. El pipeline descarga entre etapas para no acumularla."""
        ...


@runtime_checkable
class Translator(Protocol):
    name: str
    non_commercial: bool

    def supports(self, source: str, target: str) -> bool: ...

    async def translate(self, texts: Sequence[str], *, source: str, target: str) -> list[str]: ...

    async def close(self) -> None: ...


@runtime_checkable
class OCREngine(Protocol):
    name: str

    async def needs_ocr(self, path: Path) -> bool: ...

    async def apply(self, path: Path, out_path: Path, *, language: str) -> Path: ...


@runtime_checkable
class Exporter(Protocol):
    """Serializa el resultado a un formato de salida."""

    name: str
    extension: str
    #: True si consume audio sintetizado; False si solo necesita el Document.
    needs_audio: bool

    async def export(
        self,
        document: Document,
        out_path: Path,
        *,
        segments: Sequence[AudioSegment] | None = None,
        marks: Sequence[ChapterMark] | None = None,
    ) -> Path: ...


@runtime_checkable
class LLMProvider(Protocol):
    """Backend de LLM local para el modo estudio."""

    name: str

    async def is_available(self) -> bool: ...

    async def complete(self, prompt: str, *, system: str | None = None) -> str: ...

    def stream(self, prompt: str, *, system: str | None = None) -> AsyncIterator[str]: ...
