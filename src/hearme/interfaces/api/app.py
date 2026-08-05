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
from hearme.application.language import (
    UnknownLanguage,
    detect_language,
    normalize_language,
)
from hearme.application.pipeline import ConversionPipeline, ConversionRequest
from hearme.application.plugins import plugins
from hearme.application.study import StudyService
from hearme.config import settings
from hearme.domain.models import JobStatus, NarrationStyle, ReadingMode, Utterance
from hearme.feedback import Feedback, ReputationIndex, Subject, suggest_adjustment
from hearme.infrastructure.hardware import detect
from hearme.infrastructure.persistence.database import dispose, init_db
from hearme.narration.adapters import capabilities_for
from hearme.narration.plan import (
    DocumentAnalysis,
    ListeningPlan,
    estimate_minutes,
    recommend,
    suggest_style,
)
from hearme.narration.plan import validate as validate_plan_domain
from hearme.narration.voices import Gender, build_catalog, sample_text_for
from hearme.privacy.crypto import keyed_digest, random_token

logger = logging.getLogger(__name__)

_pool: WorkerPool | None = None

#: Reputación acumulada en memoria.
#:
#: En memoria a propósito, de momento: persistirla exige decidir dónde vive el
#: conocimiento compartido, y eso lo resuelve `knowledge.sync` cuando exista el
#: servicio de sincronización. Mientras tanto es útil dentro de una sesión y no
#: promete más de lo que puede cumplir.
_reputation = ReputationIndex()


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


class ListeningPlanIn(BaseModel):
    """Los seis conceptos, explícitos y separados.

    `needs_translation` no está: se deriva de que los dos idiomas difieran. Si
    fuera un campo, existirían estados incoherentes —«traducir» marcado con los
    dos idiomas iguales— y alguien tendría que resolverlos.
    """

    document_language: str = ""
    playback_language: str = ""
    voice: str | None = None
    style: NarrationStyle = NarrationStyle.NEUTRAL
    engine: str | None = None
    keep_original: bool = False

    def to_domain(self) -> ListeningPlan:
        return ListeningPlan(
            document_language=self.document_language,
            playback_language=self.playback_language,
            voice=self.voice,
            style=self.style,
            engine=self.engine,
            keep_original=self.keep_original,
        )


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
async def list_voices(
    language: str | None = None,
    gender: str | None = None,
    engine: str | None = None,
) -> dict[str, Any]:
    """Catálogo de voces con metadatos, para poder elegir sin adivinar.

    Antes devolvía listas de identificadores (`ef_dora`, `es_ES-sharvard-medium`),
    que no responden a lo que pregunta quien elige: de dónde suena, si es de
    hombre o mujer, cuál va a sonar mejor. Ahora cada voz viene descrita.
    """
    catalogo = await build_catalog(plugins.tts)

    if language or gender or engine:
        genero = Gender(gender) if gender in {g.value for g in Gender} else None
        voces = catalogo.filter(
            language=language,
            gender=genero,
            engine=engine,
            allow_non_commercial=settings.allow_non_commercial_models,
        )
        return {"voices": [v.to_dict() for v in voces], "total": len(voces)}

    return {
        "by_language": catalogo.grouped_by_language(),
        "languages": catalogo.languages(),
        "total": len(catalogo),
    }


@app.post("/api/voices/{engine_name}/{voice_id}/sample")
async def voice_sample(engine_name: str, voice_id: str, language: str = "es") -> FileResponse:
    """Genera una muestra corta de una voz.

    Escuchar antes de elegir es la diferencia entre decidir y apostar. La muestra
    es de dos frases: suficiente para juzgar, lo bastante rápida para no
    desincentivar la comparación entre varias.
    """
    motor = next((e for e in plugins.tts if e.name == engine_name), None)
    if motor is None or not await motor.is_available():
        raise HTTPException(404, f"El motor '{engine_name}' no está disponible")

    if hasattr(motor, "language"):
        motor.language = language
    if preparar := getattr(motor, "prepare", None):
        await preparar(language)

    settings.ensure_dirs()
    destino = settings.cache_dir / "samples" / engine_name
    destino.mkdir(parents=True, exist_ok=True)

    # La muestra se cachea: comparar seis voces no debería sintetizar seis veces
    # cada vez que alguien vuelve a abrir el selector.
    marca = keyed_digest(voice_id.encode(), sample_text_for(language))[:16]
    cacheada = destino / f"{marca}.wav"
    if not cacheada.exists():
        utterance = Utterance(
            text=sample_text_for(language),
            order=0,
            chapter_id="sample",
            block_id="sample",
        )
        try:
            segmento = await motor.synthesize(utterance, voice=voice_id, out_dir=destino)
        except Exception as exc:
            logger.warning("no se pudo generar la muestra de %s: %s", voice_id, exc)
            raise HTTPException(
                503,
                f"No se pudo generar la muestra de esta voz. Puede que el modelo "
                f"aún se esté descargando; inténtalo en unos segundos. ({exc})",
            ) from exc
        segmento.path.replace(cacheada)

    return FileResponse(cacheada, media_type="audio/wav", filename=f"{voice_id}.wav")


@app.post("/api/analyze")
async def analyze(
    file: Annotated[UploadFile, File()],
    interface_language: str = "es",
) -> dict[str, Any]:
    """Analiza un documento **sin convertirlo** y propone un plan de escucha.

    Es lo que permite que el asistente sugiera algo con fundamento en vez de
    preguntar a ciegas. Cuesta segundos, no los minutos de una conversión, y el
    documento se descarta al terminar: no se encola nada.
    """
    if not file.filename:
        raise HTTPException(400, "Falta el nombre del archivo")

    settings.ensure_dirs()
    temporal = settings.cache_dir / f"analisis-{random_token(8)}{Path(file.filename).suffix}"
    if plugins.parser_for(temporal.suffix) is None:
        raise HTTPException(415, f"No hay parser para '{temporal.suffix}'")

    try:
        await anyio.to_thread.run_sync(_store_upload, file.file, temporal)
        documento = await ConversionPipeline().parse(temporal)
    except Exception as exc:
        logger.exception("fallo al analizar el documento")
        raise HTTPException(422, f"No se pudo leer el documento: {exc}") from exc
    finally:
        # Se analiza y se olvida: quien solo quería una sugerencia no ha pedido
        # que guardemos su documento.
        temporal.unlink(missing_ok=True)

    muestra = "\n".join(c.text for c in documento.chapters[:3])
    idioma = documento.meta.language or detect_language(muestra)
    # La detección no expone confianza, así que se aproxima por cuánto texto se
    # ha visto: con dos párrafos, cualquier detector acierta poco.
    confianza = 0.9 if len(muestra) > 2000 else 0.6 if len(muestra) > 400 else 0.3

    analisis = DocumentAnalysis(
        detected_language=idioma,
        confidence=confianza,
        chapters=len(documento.chapters),
        characters=documento.char_count,
        title=documento.meta.title,
        estimated_minutes=estimate_minutes(documento.char_count),
    )

    catalogo = await build_catalog(plugins.tts)
    traduccion = bool(plugins.translators.names())
    recomendaciones = recommend(
        detected_language=idioma,
        detection_confidence=confianza,
        catalog=catalogo,
        translation_available=traduccion,
        interface_language=interface_language,
    )
    recomendaciones["style"] = suggest_style(documento.meta.title)

    return {
        "analysis": analisis.to_dict(),
        "recommendations": {k: v.to_dict() for k, v in recomendaciones.items()},
        "translation_available": traduccion,
        "languages_with_voice": catalogo.languages(),
    }


@app.post("/api/plan/validate")
async def validate_plan(plan: ListeningPlanIn) -> dict[str, Any]:
    """Comprueba un plan antes de convertir y devuelve problemas accionables.

    Detectar aquí que falta el traductor o que la voz es de otro idioma ahorra
    esperar el parseo completo de un libro para descubrirlo al final.
    """
    catalogo = await build_catalog(plugins.tts)
    problemas = validate_plan_domain(
        plan.to_domain(),
        catalog=catalogo,
        translation_available=bool(plugins.translators.names()),
    )
    return {
        "valid": not problemas,
        "problems": [p.to_dict() for p in problemas],
        "summary": plan.to_domain().describe(),
    }


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

    # Los idiomas se normalizan en la puerta: «francés», «French» y «fr» son lo
    # mismo, y llegaban tal cual al traductor produciendo «Ningún traductor cubre
    # es->frances», un mensaje que no ayudaba a ver que el problema era la palabra.
    for campo in ("language", "target_language"):
        crudo = getattr(parsed, campo)
        if not crudo:
            continue
        try:
            setattr(parsed, campo, normalize_language(crudo))
        except UnknownLanguage as exc:
            raise HTTPException(400, str(exc)) from exc

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


class FeedbackIn(BaseModel):
    """Una valoración. Las tres señales son opcionales, pero alguna hace falta."""

    engine: str
    voice: str = ""
    style: str = ""
    language: str = ""
    stars: int | None = None
    thumbs_up: bool | None = None
    comment: str = ""
    contributor: str = "local"


@app.post("/api/feedback", status_code=201)
async def submit_feedback(payload: FeedbackIn) -> dict[str, Any]:
    """Registra una valoración y devuelve qué se entendió de ella.

    Devolver las etiquetas extraídas no es cortesía: es la única forma de que
    quien escribe pueda comprobar que se le entendió, y de corregir si no.
    """
    try:
        valoracion = Feedback(
            subject=Subject(
                engine=payload.engine,
                voice=payload.voice,
                style=payload.style,
                language=payload.language,
            ),
            stars=payload.stars,
            thumbs_up=payload.thumbs_up,
            comment=payload.comment,
            contributor=payload.contributor,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    _reputation.add(valoracion)
    reputacion = _reputation.of(valoracion.subject)

    return {
        "recorded": True,
        "understood": [t.to_dict() for t in valoracion.tags],
        "explanation": valoracion.explain_tags(),
        "reputation": reputacion.to_dict(),
    }


@app.get("/api/reputation")
async def get_reputation(
    engine: str, voice: str = "", style: str = "", language: str = ""
) -> dict[str, Any]:
    """Reputación de una configuración, con su explicación.

    Siempre responde: sin valoraciones devuelve la puntuación previa y lo dice.
    Un hueco es información, y ocultarlo obligaría a la interfaz a adivinar.
    """
    sujeto = Subject(engine=engine, voice=voice, style=style, language=language)
    reputacion = _reputation.of(sujeto)
    problemas = _reputation.problems_of(sujeto)

    return {
        **reputacion.to_dict(),
        "frequent_problems": [p.to_dict() for p in problemas],
        # La sugerencia se devuelve, nunca se aplica sola.
        "suggested_adjustment": suggest_adjustment(problemas),
    }


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
