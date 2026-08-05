"""Persistencia con SQLAlchemy 2.0 async.

Un único modelo para SQLite y PostgreSQL; lo que cambia es la URL. En SQLite se
activa WAL para que la API pueda leer mientras el worker escribe.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from hearme.config import settings
from hearme.domain.models import JobStatus


class Base(DeclarativeBase):
    pass


class JobRow(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default=JobStatus.PENDING, index=True)
    source_path: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, default="")
    mode: Mapped[str] = mapped_column(String(16), default="audiobook")
    #: JSON serializado: la petición completa, para poder reintentar un trabajo tal cual.
    request: Mapped[str] = mapped_column(Text, default="{}")
    stage: Mapped[str] = mapped_column(String(32), default="")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str] = mapped_column(Text, default="")
    outputs: Mapped[str] = mapped_column(Text, default="[]")
    duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    engine: Mapped[str] = mapped_column(String(32), default="")
    voice: Mapped[str] = mapped_column(String(64), default="")
    language: Mapped[str] = mapped_column(String(8), default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "source_path": self.source_path,
            "title": self.title,
            "mode": self.mode,
            "stage": self.stage,
            "progress": round(self.progress, 4),
            "error": self.error or None,
            "outputs": json.loads(self.outputs or "[]"),
            "duration_s": self.duration_s,
            "engine": self.engine or None,
            "voice": self.voice or None,
            "language": self.language or None,
            "attempts": self.attempts,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class DocumentRow(Base):
    """Historial de documentos procesados. Alimenta la vista de biblioteca."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(Text)
    authors: Mapped[str] = mapped_column(Text, default="[]")
    language: Mapped[str] = mapped_column(String(8), default="")
    source_format: Mapped[str] = mapped_column(String(16), default="")
    chapters: Mapped[int] = mapped_column(Integer, default=0)
    characters: Mapped[int] = mapped_column(Integer, default=0)
    #: El Document canónico serializado, para reexportar sin reparsear.
    payload: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )


class FeedbackRow(Base):
    """Una valoración, tal como se emitió.

    Se guarda la señal cruda —estrellas, pulgar, comentario— y no la reputación
    calculada. La reputación se deriva al leer, por dos motivos: cambiar la
    fórmula no obliga a migrar nada, y siempre se puede reconstruir desde la
    evidencia. Una reputación almacenada sin sus valoraciones sería un número
    que nadie puede auditar.

    El comentario se conserva íntegro junto a las etiquetas extraídas: las
    etiquetas son una ayuda, el original es la verdad.
    """

    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    # Sujeto valorado: una configuración, nunca una obra.
    engine: Mapped[str] = mapped_column(String(32), index=True)
    voice: Mapped[str] = mapped_column(String(64), default="", index=True)
    style: Mapped[str] = mapped_column(String(16), default="")
    language: Mapped[str] = mapped_column(String(8), default="", index=True)
    # Señales. Todas opcionales; al menos una tiene que venir.
    stars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thumbs_up: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    comment: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(Text, default="[]")
    contributor: Mapped[str] = mapped_column(String(64), default="local", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )


class ContributorRow(Base):
    """Reputación de quien aporta, medida y no declarada.

    Es la otra mitad del sistema: sin ella, todas las valoraciones pesarían lo
    mismo y bastaría con insistir para torcer el catálogo. La fiabilidad sale de
    ítems de control, igual que en `narration.contributions`.
    """

    __tablename__ = "contributors"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    reliability: Mapped[float] = mapped_column(Float, default=0.25)
    feedback_given: Mapped[int] = mapped_column(Integer, default=0)
    control_hits: Mapped[int] = mapped_column(Integer, default=0)
    control_total: Mapped[int] = mapped_column(Integer, default=0)
    accredited: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _session_factory
    if _engine is None:
        url = settings.resolved_database_url
        is_sqlite = url.startswith("sqlite")
        _engine = create_async_engine(
            url,
            echo=False,
            future=True,
            # SQLite no soporta pool de conexiones concurrentes de forma útil.
            pool_pre_ping=not is_sqlite,
        )
        if is_sqlite:
            _enable_wal(_engine)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def _enable_wal(engine: AsyncEngine) -> None:
    """WAL + busy_timeout: lecturas concurrentes con el worker escribiendo."""

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragma(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.close()


async def init_db() -> None:
    settings.ensure_dirs()
    engine = get_engine()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    get_engine()
    assert _session_factory is not None
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
