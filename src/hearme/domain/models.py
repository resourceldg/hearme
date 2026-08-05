"""Entidades del dominio.

Esta capa no importa nada de infraestructura: ni SQLAlchemy, ni FastAPI, ni torch.
Es la definición de qué *es* un documento, independiente de cómo se guarda o se sirve.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path


def _uid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class SourceFormat(StrEnum):
    PDF = "pdf"
    EPUB = "epub"
    DOCX = "docx"
    ODT = "odt"
    MARKDOWN = "md"
    TXT = "txt"
    HTML = "html"
    RTF = "rtf"
    WEB = "web"
    RSS = "rss"


class BlockKind(StrEnum):
    """Tipo semántico de un bloque de contenido.

    Determina cómo se narra: un HEADING lleva pausa larga y énfasis, un CODE
    normalmente se omite en audio, una FOOTNOTE se relega al final del capítulo.
    """

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    QUOTE = "quote"
    LIST_ITEM = "list_item"
    CODE = "code"
    TABLE = "table"
    FOOTNOTE = "footnote"
    CAPTION = "caption"
    PAGE_NUMBER = "page_number"
    HEADER_FOOTER = "header_footer"


#: Bloques que por defecto no se envían al sintetizador.
NON_NARRATED: frozenset[BlockKind] = frozenset({BlockKind.PAGE_NUMBER, BlockKind.HEADER_FOOTER})


class ReadingMode(StrEnum):
    READ = "read"
    AUDIOBOOK = "audiobook"
    STUDY = "study"
    TRANSLATE = "translate"


class NarrationStyle(StrEnum):
    """Perfil prosódico. Ajusta pausas, velocidad y tratamiento de puntuación.

    Añadir un estilo obliga a darle entrada en las tablas de
    `hearme.narration.director`: sin ella, elegirlo reventaría al trocear. El
    test `test_todos_los_estilos_tienen_prosodia` lo comprueba.
    """

    NEUTRAL = "neutral"
    NOVEL = "novel"
    POETRY = "poetry"
    TECHNICAL = "technical"
    ACADEMIC = "academic"
    CHILDREN = "children"
    LECTURE = "lecture"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class Block:
    """Unidad mínima de contenido con semántica preservada."""

    kind: BlockKind
    text: str
    order: int
    page: int | None = None
    level: int | None = None  # nivel de encabezado (1..6)
    font_size: float | None = None  # pista tipográfica del parser
    bold: bool = False
    translated: str | None = None
    id: str = field(default_factory=_uid)

    @property
    def is_narrated(self) -> bool:
        return self.kind not in NON_NARRATED and bool(self.text.strip())


@dataclass(slots=True)
class Chapter:
    title: str
    order: int
    blocks: list[Block] = field(default_factory=list)
    level: int = 1
    id: str = field(default_factory=_uid)

    @property
    def text(self) -> str:
        return "\n\n".join(b.text for b in self.blocks if b.is_narrated)

    @property
    def char_count(self) -> int:
        return sum(len(b.text) for b in self.blocks if b.is_narrated)


@dataclass(slots=True)
class DocumentMeta:
    title: str
    authors: list[str] = field(default_factory=list)
    language: str | None = None  # BCP-47, ej. "es", "en-US"
    publisher: str | None = None
    published: str | None = None
    isbn: str | None = None
    cover: bytes | None = None
    page_count: int | None = None
    extra: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class Document:
    """Representación canónica: la salida de *cualquier* parser."""

    source_path: Path
    source_format: SourceFormat
    meta: DocumentMeta
    chapters: list[Chapter] = field(default_factory=list)
    id: str = field(default_factory=_uid)
    created_at: datetime = field(default_factory=_now)

    @property
    def blocks(self) -> list[Block]:
        return [b for ch in self.chapters for b in ch.blocks]

    @property
    def char_count(self) -> int:
        return sum(ch.char_count for ch in self.chapters)

    def estimated_duration_s(self, chars_per_second: float = 14.0) -> float:
        """Duración aproximada del audio. ~14 car/s ≈ 150 palabras/min."""
        return self.char_count / chars_per_second


@dataclass(slots=True)
class Utterance:
    """Fragmento listo para sintetizar: texto + intención prosódica.

    Es lo que el `NarrationEditor` permite ajustar a mano antes de renderizar.
    """

    text: str
    order: int
    chapter_id: str
    block_id: str
    pause_after_ms: int = 0
    emphasis: float = 1.0  # multiplicador; 1.0 = neutro
    rate: float = 1.0
    lexicon: dict[str, str] = field(default_factory=dict)  # palabra -> pronunciación
    id: str = field(default_factory=_uid)


@dataclass(slots=True)
class AudioSegment:
    """Audio sintetizado de una Utterance."""

    utterance_id: str
    path: Path
    duration_s: float
    sample_rate: int
    order: int


@dataclass(slots=True)
class ChapterMark:
    """Marca de capítulo para contenedores con índice (m4b)."""

    title: str
    start_s: float
    end_s: float
