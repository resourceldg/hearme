"""API REST con FastAPI.

Es un *adaptador* sobre los casos de uso: no contiene lógica de negocio. El futuro
servidor MCP colgará de los mismos objetos (`ConversionPipeline`, `JobQueue`).
"""

from __future__ import annotations

import json
import logging
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any, BinaryIO

import anyio
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from hearme import __version__
from hearme.application.event_bus import bus
from hearme.application.jobs import JobQueue, WorkerPool
from hearme.application.pipeline import ConversionPipeline, ConversionRequest
from hearme.application.plugins import plugins
from hearme.application.study import StudyService
from hearme.config import settings
from hearme.domain.models import JobStatus, NarrationStyle, ReadingMode
from hearme.infrastructure.hardware import detect
from hearme.infrastructure.persistence.database import dispose, init_db
from hearme.narration.adapters import capabilities_for

logger = logging.getLogger(__name__)

_pool: WorkerPool | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logging.basicConfig(level=settings.log_level)
    settings.ensure_dirs()
    plugins.load()
    await init_db()

    global _pool
    _pool = WorkerPool(size=1)
    await _pool.start()
    logger.info("HearMe %s · %s", __version__, detect().describe())
    try:
        yield
    finally:
        if _pool:
            await _pool.stop()
        await dispose()


app = FastAPI(
    title="HearMe",
    version=__version__,
    description="Plataforma abierta de narración en voz alta de alta calidad",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    # 5173 en desarrollo, 3000 en producción (adapter-node y el perfil `web` de
    # Docker). Ajustable con HEARME_CORS_ORIGINS si la UI se sirve desde otro sitio.
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_queue() -> JobQueue:
    return JobQueue(bus=bus)


QueueDep = Annotated[JobQueue, Depends(get_queue)]


# --- esquemas ---------------------------------------------------------------


class ConversionOptions(BaseModel):
    mode: ReadingMode = ReadingMode.AUDIOBOOK
    formats: list[str] = Field(default_factory=lambda: ["m4b"])
    language: str | None = None
    target_language: str | None = None
    engine: str | None = None
    voice: str | None = None
    style: NarrationStyle = NarrationStyle.NEUTRAL
    quality: str = "high"
    ocr: bool | None = None


def _store_upload(source: BinaryIO, target: Path) -> None:
    """Vuelca la subida a disco. Se ejecuta en un hilo, nunca en el event loop."""
    with target.open("wb") as handle:
        shutil.copyfileobj(source, handle, length=1 << 20)


class SystemInfo(BaseModel):
    version: str
    #: Capacidad del nodo que sirve. Es información de operación del servicio, no
    #: del equipo de quien escucha: la interfaz de lectura no la muestra.
    runtime: dict[str, Any]
    parsers: list[str]
    tts_engines: list[dict[str, Any]]
    exporters: list[str]
    translators: list[str]
    ocr: list[str]
    warnings: list[str]


# --- endpoints --------------------------------------------------------------


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/api/system", response_model=SystemInfo)
async def system_info() -> SystemInfo:
    profile = detect()
    warnings: list[str] = []

    engines: list[dict[str, Any]] = []
    for engine in plugins.tts:
        available = await engine.is_available()
        caps = capabilities_for(engine.name)
        engines.append(
            {
                "name": engine.name,
                "available": available,
                "languages": sorted(engine.languages),
                "naturalness": engine.naturalness,
                "rtf": engine.rtf,
                "non_commercial": engine.non_commercial,
                # Qué dimensiones de la partitura sabe respetar. Quien anota
                # prosodia necesita saberlo: anotar tono para un motor que lo
                # ignora es trabajo que nunca se oye.
                "prosody": {
                    "pause": caps.pause,
                    "rate": caps.rate,
                    "emphasis": caps.emphasis,
                    "pitch": caps.pitch,
                },
            }
        )
    if not any(e["available"] for e in engines):
        warnings.append("Ningún motor TTS instalado: uv pip install 'hearme[tts-kokoro]'")
    if shutil.which("ffmpeg") is None:
        warnings.append("ffmpeg no encontrado: la exportación a mp3/m4b fallará")
    if shutil.which("ocrmypdf") is None:
        warnings.append("ocrmypdf no encontrado: los PDF escaneados no se podrán leer")
    # Sin este aviso, elegir «Traducir» en la interfaz fallaba a mitad de la
    # conversión, cuando ya se había esperado el parseo entero.
    if not plugins.translators.names():
        warnings.append(
            "Traducción no disponible: falta el extra 'translate'. "
            "Con Docker: docker compose build --build-arg "
            "HEARME_EXTRAS=documents,tts-piper,translate"
        )
    # Idiomas que el despliegue puede narrar hoy: es el dato que decide si una
    # biblioteca puede atender a su comunidad, y el único que la interfaz enseña.
    languages = sorted({lang for e in engines if e["available"] for lang in e["languages"]})
    if not languages:
        warnings.append("Sin idiomas disponibles: instala al menos un motor de voz")

    return SystemInfo(
        version=__version__,
        runtime={
            "accelerator": profile.accelerator.value,
            "synthesis_workers": profile.tts_workers,
            "languages": languages,
        },
        parsers=plugins.parsers.names(),
        tts_engines=engines,
        exporters=plugins.exporters.names(),
        translators=plugins.translators.names(),
        ocr=plugins.ocr.names(),
        warnings=warnings,
    )


@app.get("/api/voices")
async def list_voices(language: str = "es") -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for engine in plugins.tts:
        if await engine.is_available():
            result[engine.name] = list(await engine.voices(language))
    return result


@app.post("/api/convert", status_code=202)
async def convert(
    queue: QueueDep,
    file: Annotated[UploadFile, File()],
    options: Annotated[str, Form()] = "{}",
) -> dict[str, str]:
    """Sube un documento y encola su conversión."""
    if not file.filename:
        raise HTTPException(400, "Falta el nombre del archivo")

    try:
        parsed = ConversionOptions(**json.loads(options))
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise HTTPException(400, f"Opciones inválidas: {exc}") from exc

    unknown = [f for f in parsed.formats if f not in plugins.exporters]
    if unknown:
        raise HTTPException(
            400, f"Formatos no soportados: {unknown}. Disponibles: {plugins.exporters.names()}"
        )

    settings.ensure_dirs()
    target = settings.uploads_dir / Path(file.filename).name

    # El formato se comprueba *antes* de escribir: rechazar un PDF de 300 MB
    # después de haberlo copiado entero al disco es tirar minutos a la basura.
    if plugins.parser_for(target.suffix) is None:
        raise HTTPException(415, f"No hay parser para '{target.suffix}'")

    # copyfileobj es síncrono: con un documento grande bloqueaba el event loop
    # durante toda la copia, y con él los SSE de los trabajos en curso y el
    # healthcheck. En un hilo, la subida de un libro largo ya no congela la UI.
    try:
        await anyio.to_thread.run_sync(_store_upload, file.file, target)
    except OSError as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(500, f"No se pudo guardar el archivo: {exc}") from exc

    job_id = await queue.enqueue(
        ConversionRequest(
            source=target,
            mode=parsed.mode,
            formats=parsed.formats,
            language=parsed.language,
            target_language=parsed.target_language,
            engine=parsed.engine,
            voice=parsed.voice,
            style=parsed.style,
            quality=parsed.quality,
            ocr=parsed.ocr,
        )
    )
    return {"job_id": job_id, "status": "pending"}


@app.get("/api/jobs")
async def list_jobs(
    queue: QueueDep, limit: int = 50, status: str | None = None
) -> list[dict[str, Any]]:
    return [row.to_dict() for row in await queue.list(limit=limit, status=status)]


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str, queue: QueueDep) -> dict[str, Any]:
    row = await queue.get(job_id)
    if row is None:
        raise HTTPException(404, "Trabajo no encontrado")
    return row.to_dict()


@app.delete("/api/jobs/{job_id}")
async def cancel_job(job_id: str, queue: QueueDep) -> dict[str, bool]:
    return {"cancelled": await queue.cancel(job_id)}


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str) -> StreamingResponse:
    """Progreso en vivo por Server-Sent Events.

    Se eligió SSE sobre WebSocket porque el flujo es unidireccional y SSE
    reconecta solo desde el navegador.
    """

    async def generator() -> AsyncIterator[str]:
        async for event in bus.stream(job_id):
            payload = {"type": type(event).__name__, **asdict(event)}
            payload["at"] = event.at.isoformat()
            yield f"data: {json.dumps(payload, default=str)}\n\n"

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/jobs/{job_id}/download/{index}")
async def download(job_id: str, index: int, queue: QueueDep) -> FileResponse:
    row = await queue.get(job_id)
    if row is None:
        raise HTTPException(404, "Trabajo no encontrado")

    outputs = json.loads(row.outputs or "[]")
    if not 0 <= index < len(outputs):
        raise HTTPException(404, "Salida no encontrada")

    path = Path(outputs[index])
    # El índice viene del cliente: se comprueba que la ruta siga dentro del
    # directorio de salida antes de servirla.
    try:
        path.resolve().relative_to(settings.output_dir.resolve())
    except ValueError:
        raise HTTPException(403, "Ruta fuera del directorio de salida") from None
    if not path.exists():
        raise HTTPException(404, "El archivo ya no existe")

    return FileResponse(path, filename=path.name)


@app.post("/api/study/{job_id}")
async def study(job_id: str, queue: QueueDep, chapter: int = 0) -> dict[str, Any]:
    """Genera material de estudio para un capítulo de un trabajo terminado."""
    row = await queue.get(job_id)
    if row is None:
        raise HTTPException(404, "Trabajo no encontrado")
    if row.status != JobStatus.COMPLETED:
        raise HTTPException(400, "El trabajo no está completado")

    source = Path(row.source_path)
    if not source.exists():
        raise HTTPException(404, "El archivo original ya no está disponible")

    try:
        document = await ConversionPipeline().parse(source)
    except Exception as exc:
        logger.exception("no se pudo reparsear el documento para estudio")
        raise HTTPException(500, f"No se pudo leer el documento: {exc}") from exc

    if not 0 <= chapter < len(document.chapters):
        raise HTTPException(404, "Capítulo no encontrado")

    service = StudyService(plugins.llm.get("ollama"))
    pack = await service.build(document.chapters[chapter])
    return asdict(pack)
