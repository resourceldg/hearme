"""Caso de uso central: de un archivo a un audiolibro (o a texto traducido).

Esta clase no conoce HTTP, ni la base de datos, ni Typer. Es la razón por la que
exponer MCP más adelante será escribir un adaptador y no reescribir lógica.
"""

from __future__ import annotations

import logging
import shutil
import time
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

import anyio

from hearme.application.chunker import chunk_chapter
from hearme.application.event_bus import EventBus
from hearme.application.event_bus import bus as default_bus
from hearme.application.language import detect_language
from hearme.application.plugins import PluginManager
from hearme.application.plugins import plugins as default_plugins
from hearme.config import Settings
from hearme.config import settings as default_settings
from hearme.domain.events import (
    ChunkSynthesized,
    DocumentParsed,
    JobCompleted,
    JobFailed,
    JobProgress,
    JobStarted,
    OCRApplied,
)
from hearme.domain.inference import WorkloadClass
from hearme.domain.models import (
    AudioSegment,
    Document,
    NarrationStyle,
    ReadingMode,
    Utterance,
)
from hearme.infrastructure.hardware import detect

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ConversionRequest:
    source: Path
    mode: ReadingMode = ReadingMode.AUDIOBOOK
    formats: list[str] = field(default_factory=lambda: ["m4b"])
    language: str | None = None  # None -> autodetección
    target_language: str | None = None  # activa la traducción
    engine: str | None = None  # None/"auto" -> selector
    voice: str | None = None
    style: NarrationStyle = NarrationStyle.NEUTRAL
    quality: str = "high"
    out_dir: Path | None = None
    ocr: bool | None = None  # None -> decide la heurística
    keep_wavs: bool = False


@dataclass(slots=True)
class ConversionResult:
    document: Document
    outputs: list[Path] = field(default_factory=list)
    duration_s: float = 0.0
    engine: str = ""
    voice: str = ""
    language: str = ""
    selection_reason: str = ""


class ConversionPipeline:
    def __init__(
        self,
        *,
        plugins: PluginManager | None = None,
        bus: EventBus | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.plugins = plugins or default_plugins
        self.bus = bus or default_bus
        self.settings = settings or default_settings
        self.plugins.load()

    async def run(self, request: ConversionRequest, *, job_id: str) -> ConversionResult:
        try:
            return await self._run(request, job_id)
        except Exception as exc:
            logger.exception("el trabajo %s falló", job_id)
            await self.bus.publish(JobFailed(job_id=job_id, error=str(exc)))
            raise
        finally:
            self.bus.close_stream(job_id)

    async def _run(self, request: ConversionRequest, job_id: str) -> ConversionResult:
        self.settings.ensure_dirs()
        await self.bus.publish(JobStarted(job_id=job_id, stage="inicio"))

        source = await self._maybe_ocr(request, job_id)
        document = await self._parse(source, job_id)
        language = self._resolve_language(request, document)
        document.meta.language = language

        if request.target_language and request.target_language != language:
            await self._translate(document, language, request.target_language, job_id)
            # A partir de aquí se narra en el idioma de destino.
            language = request.target_language

        out_dir = request.out_dir or (self.settings.output_dir / _slug(document.meta.title))
        out_dir.mkdir(parents=True, exist_ok=True)

        result = ConversionResult(document=document, language=language)

        text_formats = [fmt for fmt in request.formats if not self._exporter(fmt).needs_audio]
        audio_formats = [fmt for fmt in request.formats if self._exporter(fmt).needs_audio]

        # Los exportadores de texto no dependen de la síntesis: se resuelven antes
        # para que el usuario tenga algo utilizable cuanto antes.
        for fmt in text_formats:
            result.outputs.append(await self._export(document, fmt, out_dir, None, None))

        needs_audio = bool(audio_formats) and request.mode in {
            ReadingMode.AUDIOBOOK,
            ReadingMode.TRANSLATE,
        }
        if needs_audio:
            try:
                segments, marks, meta = await self._synthesize(
                    document, request, language, out_dir, job_id
                )
                result.engine, result.voice, result.selection_reason = meta
                result.duration_s = sum(segment.duration_s for segment in segments)
                for fmt in audio_formats:
                    result.outputs.append(
                        await self._export(document, fmt, out_dir, segments, marks)
                    )
            finally:
                if not request.keep_wavs:
                    shutil.rmtree(out_dir / "wav", ignore_errors=True)

        await self.bus.publish(
            JobCompleted(job_id=job_id, outputs=tuple(str(p) for p in result.outputs))
        )
        return result

    # --- etapas -------------------------------------------------------------

    @asynccontextmanager
    async def _heartbeat(
        self, job_id: str, stage: str, detail: str, *, interval: float = 3.0
    ) -> AsyncIterator[None]:
        """Late mientras corre una etapa larga y opaca.

        El OCR y el parseo de un PDF de mil páginas tardan minutos sin emitir un
        solo evento: la barra se queda a cero y el usuario concluye —con razón—
        que se ha colgado. Un latido con el tiempo transcurrido no acelera nada,
        pero distingue «trabajando» de «muerto», que es justo lo que faltaba.
        """
        async with anyio.create_task_group() as group:

            async def beat() -> None:
                elapsed = 0.0
                while True:
                    await anyio.sleep(interval)
                    elapsed += interval
                    await self.bus.publish(
                        JobProgress(job_id=job_id, stage=stage, detail=f"{detail} · {elapsed:.0f}s")
                    )

            group.start_soon(beat)
            try:
                yield
            finally:
                group.cancel_scope.cancel()

    async def _maybe_ocr(self, request: ConversionRequest, job_id: str) -> Path:
        if request.ocr is False or request.source.suffix.lower() != ".pdf":
            return request.source
        if "ocrmypdf" not in self.plugins.ocr:
            return request.source

        engine = self.plugins.ocr.get("ocrmypdf")
        should = request.ocr is True or await engine.needs_ocr(request.source)
        if not should:
            return request.source

        await self.bus.publish(JobProgress(job_id=job_id, stage="ocr", detail="aplicando OCR"))
        target = self.settings.cache_dir / f"{request.source.stem}.ocr.pdf"
        try:
            async with self._heartbeat(job_id, "ocr", "aplicando OCR"):
                result = await engine.apply(
                    request.source, target, language=self.settings.ocr_language
                )
        except RuntimeError as exc:
            # OCR ausente no debe abortar la conversión: se avisa y se sigue.
            logger.warning("OCR omitido: %s", exc)
            return request.source

        await self.bus.publish(OCRApplied(job_id=job_id))
        return result

    async def parse(self, source: Path) -> Document:
        """Parsea sin emitir eventos. Útil para previsualizar o para el modo estudio."""
        parser = self.plugins.parser_for(source.suffix)
        if parser is None:
            raise LookupError(f"No hay parser para '{source.suffix}'")
        return await parser.parse(source)

    async def _parse(self, source: Path, job_id: str) -> Document:
        await self.bus.publish(JobProgress(job_id=job_id, stage="parseo", detail=source.name))
        parser = self.plugins.parser_for(source.suffix)
        if parser is None:
            known = sorted({f.value for p in self.plugins.parsers for f in p.formats})
            raise LookupError(
                f"No hay parser para '{source.suffix}'. Formatos disponibles: {known}"
            )

        async with self._heartbeat(job_id, "parseo", source.name):
            document = await parser.parse(source)
        await self.bus.publish(
            DocumentParsed(
                job_id=job_id,
                document_id=document.id,
                chapters=len(document.chapters),
                characters=document.char_count,
            )
        )
        return document

    @staticmethod
    def _resolve_language(request: ConversionRequest, document: Document) -> str:
        if request.language:
            return request.language.split("-")[0].lower()
        if document.meta.language:
            return document.meta.language.split("-")[0].lower()
        sample = "\n".join(chapter.text for chapter in document.chapters[:3])
        return detect_language(sample)

    async def _translate(self, document: Document, source: str, target: str, job_id: str) -> None:
        from hearme.infrastructure.inference import runtime
        from hearme.infrastructure.translate.marian import select_translator

        translator = select_translator(
            list(self.plugins.translators),
            source,
            target,
            allow_non_commercial=self.settings.allow_non_commercial_models,
        )
        blocks = [b for b in document.blocks if b.is_narrated]
        total = len(blocks)
        await self.bus.publish(
            JobProgress(
                job_id=job_id,
                stage="traduccion",
                total=total,
                detail=f"{source}->{target} con '{translator.name}'",
            )
        )

        # Por lotes de párrafos: mantiene la alineación 1:1 original/traducción
        # y hace el progreso visible en vez de un bloque opaco de minutos.
        # El tamaño lo decide el planificador a partir de la máquina medida; si
        # el traductor viene de un plugin y no tiene perfil, se queda el de antes.
        plan = runtime.plan_for(
            translator.name,
            default_workload=WorkloadClass.SEQ2SEQ,
            quality=self.settings.tts_quality,
        )
        batch = 16
        if plan.techniques:
            batch = max(1, plan.number("batch_size", batch))
        logger.info("traducción: %s (lote de %d)", plan.describe(), batch)
        for start in range(0, total, batch):
            window = blocks[start : start + batch]
            translated = await translator.translate(
                [b.text for b in window], source=source, target=target
            )
            for block, text in zip(window, translated, strict=False):
                block.translated = text
            await self.bus.publish(
                JobProgress(
                    job_id=job_id,
                    stage="traduccion",
                    current=min(start + batch, total),
                    total=total,
                )
            )

        await translator.close()

    async def _synthesize(
        self,
        document: Document,
        request: ConversionRequest,
        language: str,
        out_dir: Path,
        job_id: str,
    ) -> tuple[list[AudioSegment], list, tuple[str, str, str]]:
        from hearme.infrastructure.export.audio import build_chapter_marks
        from hearme.infrastructure.inference import runtime
        from hearme.infrastructure.tts.selector import select_engine

        selection = await select_engine(
            list(self.plugins.tts),
            language=language,
            quality=request.quality,
            allow_non_commercial=self.settings.allow_non_commercial_models,
            preferred=request.engine or self.settings.tts_engine,
            voice=request.voice or self.settings.tts_voice,
        )
        logger.info("motor TTS: %s (%s)", selection.engine.name, selection.reason)

        # El motor se configura para el idioma efectivo del documento.
        if hasattr(selection.engine, "language"):
            selection.engine.language = language

        utterances: list[Utterance] = []
        for chapter in document.chapters:
            chunks = await anyio.to_thread.run_sync(
                partial(chunk_chapter, chapter, style=request.style, start_order=len(utterances))
            )
            utterances.extend(chunks)

        if not utterances:
            raise ValueError("El documento no tiene texto narrable.")

        # Descarga/carga del modelo *antes* de abrir el pool: si no, N hilos
        # intentan inicializarlo a la vez y se pisan.
        if prepare := getattr(selection.engine, "prepare", None):
            await self.bus.publish(
                JobProgress(job_id=job_id, stage="sintesis", detail="preparando modelo de voz")
            )
            await prepare(language)

        wav_dir = out_dir / "wav"
        wav_dir.mkdir(parents=True, exist_ok=True)

        # Quién sintetiza ya lo decidió `select_engine`; el planificador solo dice
        # *cómo* ejecutarlo. Que ambos eligieran motor con criterios distintos
        # sería una contradicción: ver docs/ANALISIS-INFERENCIA.md §4.
        plan = runtime.plan_for(
            selection.engine.name,
            default_workload=WorkloadClass.TTS_FEEDFORWARD,
            quality=request.quality,
            concurrent=True,
        )
        logger.info("plan de síntesis: %s", plan.describe())

        workers = self.settings.max_workers or plan.number("workers") or detect().tts_workers
        segments: list[AudioSegment] = []
        done = 0
        total = len(utterances)
        limiter = anyio.CapacityLimiter(workers)
        lock = anyio.Lock()
        #: Serializa los reintentos: si dos fragmentos fallan por la misma
        #: carrera, reintentarlos a la vez la reproduce.
        retry_lock = anyio.Lock()

        await self.bus.publish(
            JobProgress(
                job_id=job_id,
                stage="sintesis",
                total=total,
                detail=f"{selection.engine.name}/{selection.voice} · {workers} hilos",
            )
        )

        async def synth_once(utterance: Utterance) -> AudioSegment:
            started = time.perf_counter()
            try:
                segment = await selection.engine.synthesize(
                    utterance, voice=selection.voice, out_dir=wav_dir
                )
            except Exception as exc:
                # Un fallo aquí suele ser falta de memoria, y es justo la
                # señal que el tuner necesita para degradar la próxima vez.
                runtime.record_failure(selection.engine.name, plan.workload, str(exc))
                raise
            runtime.record_audio(
                selection.engine.name,
                plan.workload,
                elapsed_s=time.perf_counter() - started,
                audio_s=segment.duration_s,
                plan=plan,
            )
            return segment

        async def synth(utterance: Utterance) -> None:
            nonlocal done
            async with limiter:
                try:
                    segment = await synth_once(utterance)
                except Exception as exc:
                    # Que tres fragmentos de mil tumben el libro entero no es
                    # aceptable, y menos cuando el fallo es intermitente: el
                    # mismo documento que revienta durante la carga del modelo
                    # se convierte sin problema al reintentarlo. El reintento va
                    # en serie —sin el resto del pool encima— porque las carreras
                    # de inicialización son justo lo que hace fallar al primero.
                    logger.warning(
                        "fragmento %d falló (%s); reintentando en serie",
                        utterance.order,
                        exc,
                    )
                    async with retry_lock:
                        await anyio.sleep(0.5)
                        segment = await synth_once(utterance)
            async with lock:
                segments.append(segment)
                done += 1
                # Un evento por fragmento saturaría el SSE en libros largos, y el
                # throttle tiene que cubrir *los dos* eventos: publicar solo uno de
                # cada diez JobProgress no sirve de nada si ChunkSynthesized sigue
                # saliendo en cada uno de los miles de fragmentos de un libro.
                if done % 10 == 0 or done == total:
                    await self.bus.publish(
                        JobProgress(job_id=job_id, stage="sintesis", current=done, total=total)
                    )
                    await self.bus.publish(
                        ChunkSynthesized(
                            job_id=job_id,
                            index=done,
                            total=total,
                            duration_s=segment.duration_s,
                        )
                    )

        async with anyio.create_task_group() as group:
            for utterance in utterances:
                group.start_soon(synth, utterance)

        await selection.engine.close()  # libera memoria antes de exportar

        segments.sort(key=lambda s: s.order)
        marks = build_chapter_marks(document, segments, {u.id: u.chapter_id for u in utterances})
        return segments, marks, (selection.engine.name, selection.voice, selection.reason)

    # --- exportación --------------------------------------------------------

    def _exporter(self, name: str):
        return self.plugins.exporters.get(name)

    async def _export(
        self,
        document: Document,
        fmt: str,
        out_dir: Path,
        segments: Sequence[AudioSegment] | None,
        marks: Sequence | None,
    ) -> Path:
        exporter = self._exporter(fmt)
        out_path = out_dir / f"{_slug(document.meta.title)}{exporter.extension}"
        logger.info("exportando %s -> %s", fmt, out_path)
        return await exporter.export(document, out_path, segments=segments, marks=marks)


def _slug(text: str, limit: int = 80) -> str:
    import re
    import unicodedata

    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode()
    slug = re.sub(r"[^\w\s-]", "", ascii_text).strip().lower()
    slug = re.sub(r"[\s_-]+", "-", slug)
    return slug[:limit] or "documento"
