"""Cola de trabajos respaldada por la base de datos.

Sin Redis, sin Celery (ver docs/ANALISIS-COMPARATIVO.md §6). Los trabajos viven en
la tabla `jobs`; un pool de workers asyncio los reclama. Sobrevive a reinicios: al
arrancar, los trabajos que quedaron en RUNNING se devuelven a PENDING.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, update

from hearme.application.event_bus import EventBus
from hearme.application.event_bus import bus as default_bus
from hearme.application.pipeline import (
    ConversionPipeline,
    ConversionRequest,
)
from hearme.domain.events import Event, JobProgress
from hearme.domain.models import JobStatus, NarrationStyle, ReadingMode
from hearme.infrastructure.persistence.database import (
    DocumentRow,
    JobRow,
    session_scope,
)

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2


def _serialize(request: ConversionRequest) -> str:
    data = asdict(request)
    data["source"] = str(request.source)
    data["out_dir"] = str(request.out_dir) if request.out_dir else None
    data["mode"] = request.mode.value
    data["style"] = request.style.value
    return json.dumps(data)


def _deserialize(raw: str) -> ConversionRequest:
    data: dict[str, Any] = json.loads(raw)
    return ConversionRequest(
        source=Path(data["source"]),
        mode=ReadingMode(data.get("mode", "audiobook")),
        formats=data.get("formats") or ["m4b"],
        language=data.get("language"),
        target_language=data.get("target_language"),
        engine=data.get("engine"),
        voice=data.get("voice"),
        style=NarrationStyle(data.get("style", "neutral")),
        quality=data.get("quality", "high"),
        out_dir=Path(data["out_dir"]) if data.get("out_dir") else None,
        ocr=data.get("ocr"),
        keep_wavs=bool(data.get("keep_wavs", False)),
    )


class JobQueue:
    def __init__(self, *, bus: EventBus | None = None) -> None:
        self.bus = bus or default_bus

    async def enqueue(self, request: ConversionRequest) -> str:
        job_id = uuid.uuid4().hex
        async with session_scope() as session:
            session.add(
                JobRow(
                    id=job_id,
                    status=JobStatus.PENDING,
                    source_path=str(request.source),
                    title=request.source.stem,
                    mode=request.mode.value,
                    request=_serialize(request),
                )
            )
        logger.info("trabajo %s encolado: %s", job_id, request.source.name)
        return job_id

    async def claim(self) -> JobRow | None:
        """Reclama un trabajo pendiente de forma atómica.

        La actualización condicional (`WHERE status='pending'`) hace de bloqueo
        optimista: dos workers no pueden reclamar la misma fila.
        """
        async with session_scope() as session:
            row = (
                await session.execute(
                    select(JobRow)
                    .where(JobRow.status == JobStatus.PENDING)
                    .order_by(JobRow.created_at)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is None:
                return None

            result = await session.execute(
                update(JobRow)
                .where(JobRow.id == row.id, JobRow.status == JobStatus.PENDING)
                .values(
                    status=JobStatus.RUNNING,
                    attempts=JobRow.attempts + 1,
                    updated_at=datetime.now(UTC),
                )
            )
            if result.rowcount == 0:  # type: ignore[attr-defined]
                return None  # otro worker se adelantó
            await session.refresh(row)
            return row

    async def get(self, job_id: str) -> JobRow | None:
        async with session_scope() as session:
            return await session.get(JobRow, job_id)

    async def list(self, *, limit: int = 50, status: str | None = None) -> list[JobRow]:
        async with session_scope() as session:
            query = select(JobRow).order_by(JobRow.created_at.desc()).limit(limit)
            if status:
                query = query.where(JobRow.status == status)
            return list((await session.execute(query)).scalars())

    async def cancel(self, job_id: str) -> bool:
        async with session_scope() as session:
            result = await session.execute(
                update(JobRow)
                .where(JobRow.id == job_id, JobRow.status == JobStatus.PENDING)
                .values(status=JobStatus.CANCELLED, updated_at=datetime.now(UTC))
            )
            return result.rowcount > 0  # type: ignore[attr-defined]

    async def update(self, job_id: str, **values: Any) -> None:
        async with session_scope() as session:
            await session.execute(
                update(JobRow)
                .where(JobRow.id == job_id)
                .values(updated_at=datetime.now(UTC), **values)
            )

    async def requeue_stale(self) -> int:
        """Devuelve a la cola los trabajos que un reinicio dejó a medias."""
        async with session_scope() as session:
            result = await session.execute(
                update(JobRow)
                .where(JobRow.status == JobStatus.RUNNING, JobRow.attempts < MAX_ATTEMPTS)
                .values(status=JobStatus.PENDING, stage="", progress=0.0)
            )
            # Los que ya agotaron intentos se marcan fallidos en vez de reintentar
            # eternamente un documento que rompe el parser.
            await session.execute(
                update(JobRow)
                .where(JobRow.status == JobStatus.RUNNING)
                .values(
                    status=JobStatus.FAILED,
                    error="interrumpido y sin reintentos disponibles",
                )
            )
            return int(result.rowcount)  # type: ignore[attr-defined]


class Worker:
    """Consume la cola. Varias instancias pueden correr en paralelo."""

    def __init__(
        self,
        *,
        queue: JobQueue | None = None,
        pipeline: ConversionPipeline | None = None,
        poll_interval: float = 1.0,
    ) -> None:
        self.queue = queue or JobQueue()
        self.pipeline = pipeline or ConversionPipeline(bus=self.queue.bus)
        self.poll_interval = poll_interval
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="hearme-worker")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                row = await self.queue.claim()
            except Exception:
                logger.exception("error reclamando trabajo")
                row = None

            if row is None:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=self.poll_interval)
                continue

            await self._process(row)

    async def _process(self, row: JobRow) -> None:
        job_id = row.id
        request = _deserialize(row.request)

        # Persiste el progreso que emite el pipeline, para que la UI sobreviva a
        # una recarga de página sin perder el estado.
        async def on_progress(event: Event) -> None:
            if isinstance(event, JobProgress):
                await self.queue.update(job_id, stage=event.stage, progress=event.ratio)

        unsubscribe = self.bus_subscribe(on_progress)
        try:
            result = await self.pipeline.run(request, job_id=job_id)
            await self.queue.update(
                job_id,
                status=JobStatus.COMPLETED,
                progress=1.0,
                stage="completado",
                title=result.document.meta.title,
                outputs=json.dumps([str(p) for p in result.outputs]),
                duration_s=result.duration_s,
                engine=result.engine,
                voice=result.voice,
                language=result.language,
            )
            await self._save_document(job_id, result)
        except Exception as exc:
            logger.exception("trabajo %s fallido", job_id)
            await self.queue.update(
                job_id, status=JobStatus.FAILED, error=str(exc)[:2000], stage="error"
            )
        finally:
            unsubscribe()

    def bus_subscribe(self, handler):
        return self.queue.bus.subscribe(JobProgress, handler)

    @staticmethod
    async def _save_document(job_id: str, result: Any) -> None:
        document = result.document
        async with session_scope() as session:
            session.add(
                DocumentRow(
                    id=document.id,
                    job_id=job_id,
                    title=document.meta.title,
                    authors=json.dumps(document.meta.authors),
                    language=result.language,
                    source_format=document.source_format.value,
                    chapters=len(document.chapters),
                    characters=document.char_count,
                    payload=json.dumps(
                        {
                            "chapters": [
                                {
                                    "id": chapter.id,
                                    "title": chapter.title,
                                    "blocks": [
                                        {
                                            "kind": block.kind.value,
                                            "text": block.text,
                                            "translated": block.translated,
                                        }
                                        for block in chapter.blocks
                                    ],
                                }
                                for chapter in document.chapters
                            ]
                        },
                        ensure_ascii=False,
                    ),
                )
            )


class WorkerPool:
    def __init__(self, size: int = 1, *, queue: JobQueue | None = None) -> None:
        self.queue = queue or JobQueue()
        # Un solo worker por defecto: la síntesis ya paraleliza internamente y dos
        # conversiones a la vez solo se roban CPU entre ellas.
        self.workers = [Worker(queue=self.queue) for _ in range(max(1, size))]

    async def start(self) -> None:
        requeued = await self.queue.requeue_stale()
        if requeued:
            logger.info("%d trabajo(s) reencolado(s) tras reinicio", requeued)
        for worker in self.workers:
            await worker.start()

    async def stop(self) -> None:
        for worker in self.workers:
            await worker.stop()
