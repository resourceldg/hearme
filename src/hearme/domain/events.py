"""Eventos de dominio.

Todo evento es un dataclass inmutable. El bus los entrega por tipo, así que un
suscriptor se registra contra la clase, no contra un string mágico.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Event:
    job_id: str
    at: datetime = field(default_factory=_now)


@dataclass(frozen=True, slots=True)
class JobStarted(Event):
    stage: str = ""


@dataclass(frozen=True, slots=True)
class JobProgress(Event):
    stage: str = ""
    current: int = 0
    total: int = 0
    detail: str = ""

    @property
    def ratio(self) -> float:
        return self.current / self.total if self.total else 0.0


@dataclass(frozen=True, slots=True)
class JobCompleted(Event):
    outputs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class JobFailed(Event):
    error: str = ""
    stage: str = ""


@dataclass(frozen=True, slots=True)
class DocumentParsed(Event):
    document_id: str = ""
    chapters: int = 0
    characters: int = 0


@dataclass(frozen=True, slots=True)
class OCRApplied(Event):
    pages: int = 0


@dataclass(frozen=True, slots=True)
class ChunkSynthesized(Event):
    index: int = 0
    total: int = 0
    duration_s: float = 0.0
