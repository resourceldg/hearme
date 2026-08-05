"""Tests del pipeline, el event bus y el registro de plugins."""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

from hearme.application.event_bus import EventBus
from hearme.application.pipeline import ConversionPipeline, ConversionRequest
from hearme.application.plugins import PluginManager
from hearme.domain.events import JobCompleted, JobProgress
from hearme.domain.inference import WorkloadClass
from hearme.domain.models import AudioSegment, ReadingMode, Utterance
from hearme.infrastructure.registry import register_builtins

SAMPLE_RATE = 22_050


class SilentEngine:
    """Motor TTS que genera silencio. Permite probar el pipeline completo sin modelos."""

    name = "silent"
    languages = frozenset({"es", "en"})
    naturalness = 0.99
    rtf = 0.0
    non_commercial = False

    def __init__(self) -> None:
        self.language = "es"
        self.calls = 0

    async def is_available(self) -> bool:
        return True

    async def voices(self, language: str | None = None) -> tuple[str, ...]:
        return ("silencio",)

    def default_voice(self, language: str) -> str:
        return "silencio"

    async def synthesize(self, utterance: Utterance, *, voice: str, out_dir: Path) -> AudioSegment:
        self.calls += 1
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{utterance.order:06d}.wav"
        frames = int(SAMPLE_RATE * 0.1)
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(b"\x00\x00" * frames)
        return AudioSegment(
            utterance_id=utterance.id,
            path=path,
            duration_s=0.1,
            sample_rate=SAMPLE_RATE,
            order=utterance.order,
        )

    async def close(self) -> None:
        return None


@pytest.fixture
def manager() -> PluginManager:
    manager = PluginManager()
    register_builtins(manager)
    manager.tts.register("silent", SilentEngine(), override=True)
    manager._loaded = True  # evita que load() vuelva a descubrir entry points
    return manager


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "documento.md"
    path.write_text(
        "# Mi documento\n\n"
        "## Capítulo uno\n\nEste es el primer capítulo del documento de prueba.\n\n"
        "## Capítulo dos\n\nY este es el segundo capítulo, con más texto todavía.\n",
        encoding="utf-8",
    )
    return path


async def test_exporta_solo_texto_sin_tocar_el_tts(
    manager: PluginManager, source: Path, tmp_path: Path
) -> None:
    pipeline = ConversionPipeline(plugins=manager, bus=EventBus())
    engine = manager.tts.get("silent")

    result = await pipeline.run(
        ConversionRequest(
            source=source,
            mode=ReadingMode.READ,
            formats=["md", "json"],
            out_dir=tmp_path / "out",
        ),
        job_id="t1",
    )

    assert len(result.outputs) == 2
    assert all(path.exists() for path in result.outputs)
    assert engine.calls == 0  # el modo lectura no sintetiza


async def test_los_alias_de_formato_resuelven(
    manager: PluginManager, source: Path, tmp_path: Path
) -> None:
    pipeline = ConversionPipeline(plugins=manager, bus=EventBus())
    result = await pipeline.run(
        ConversionRequest(
            source=source,
            mode=ReadingMode.READ,
            formats=["md", "text"],
            out_dir=tmp_path / "out",
        ),
        job_id="t2",
    )
    assert {p.suffix for p in result.outputs} == {".md", ".txt"}


async def test_formato_desconocido_falla_con_mensaje_util(
    manager: PluginManager, source: Path, tmp_path: Path
) -> None:
    pipeline = ConversionPipeline(plugins=manager, bus=EventBus())
    with pytest.raises(LookupError, match="Disponibles"):
        await pipeline.run(
            ConversionRequest(source=source, formats=["ogg"], out_dir=tmp_path / "out"),
            job_id="t3",
        )


async def test_emite_eventos_de_progreso(
    manager: PluginManager, source: Path, tmp_path: Path
) -> None:
    bus = EventBus()
    stages: list[str] = []
    completed: list[JobCompleted] = []

    async def on_progress(event) -> None:
        stages.append(event.stage)

    async def on_completed(event) -> None:
        completed.append(event)

    bus.subscribe(JobProgress, on_progress)
    bus.subscribe(JobCompleted, on_completed)

    pipeline = ConversionPipeline(plugins=manager, bus=bus)
    await pipeline.run(
        ConversionRequest(
            source=source, mode=ReadingMode.READ, formats=["md"], out_dir=tmp_path / "o"
        ),
        job_id="t4",
    )

    assert "parseo" in stages
    assert len(completed) == 1


async def test_un_handler_roto_no_tumba_el_pipeline(
    manager: PluginManager, source: Path, tmp_path: Path
) -> None:
    bus = EventBus()

    async def explota(event) -> None:
        raise RuntimeError("handler defectuoso")

    bus.subscribe(JobProgress, explota)
    pipeline = ConversionPipeline(plugins=manager, bus=bus)

    result = await pipeline.run(
        ConversionRequest(
            source=source, mode=ReadingMode.READ, formats=["md"], out_dir=tmp_path / "o"
        ),
        job_id="t5",
    )
    assert result.outputs


async def test_la_sintesis_alimenta_la_telemetria_con_rtf_real(
    manager: PluginManager, source: Path, tmp_path: Path, monkeypatch
) -> None:
    """El planificador solo mejora si el pipeline le devuelve mediciones."""
    from hearme.infrastructure.inference import runtime
    from hearme.infrastructure.inference.telemetry import TelemetryStore
    from hearme.infrastructure.inference.tuner import AdaptiveTuner

    store = TelemetryStore()
    # El tuner por defecto es un singleton: sin aislarlo, este test dejaría
    # estado pegado a los demás.
    adaptive = AdaptiveTuner()
    monkeypatch.setattr(runtime, "telemetry", store)
    monkeypatch.setattr(runtime, "tuner", adaptive)

    pipeline = ConversionPipeline(plugins=manager, bus=EventBus())
    await pipeline.run(
        ConversionRequest(
            source=source,
            mode=ReadingMode.AUDIOBOOK,
            formats=["mp3"],
            engine="silent",
            out_dir=tmp_path / "audio",
        ),
        job_id="t6",
    )

    stats = store.stats("silent")
    assert stats is not None
    assert stats.count > 0
    assert stats.rtf > 0  # sintetizar tardó algo y el audio dura algo

    # El bucle cierra: lo medido llegó también al tuner, no solo al histórico.
    estado = adaptive.state(WorkloadClass.TTS_FEEDFORWARD)
    assert estado.under_budget > 0  # el motor mudo va sobradísimo de presupuesto


def test_el_registro_rechaza_duplicados() -> None:
    manager = PluginManager()
    manager.tts.register("x", SilentEngine())
    with pytest.raises(ValueError, match="ya está registrado"):
        manager.tts.register("x", SilentEngine())


def test_el_registro_permite_sobrescribir_explicitamente() -> None:
    manager = PluginManager()
    manager.tts.register("x", SilentEngine())
    manager.tts.register("x", SilentEngine(), override=True)
    assert len(manager.tts) == 1


def test_resuelve_parser_por_extension() -> None:
    manager = PluginManager()
    register_builtins(manager)

    assert manager.parser_for(".md") is not None
    assert manager.parser_for(".txt") is not None
    assert manager.parser_for(".xyz") is None


async def test_los_eventos_por_fragmento_van_limitados(
    manager: PluginManager, tmp_path: Path
) -> None:
    """Un libro largo no puede emitir un evento SSE por cada fragmento.

    Con miles de fragmentos, el stream saturaba la conexión del navegador. El
    límite tiene que cubrir también ChunkSynthesized, no solo JobProgress.
    """
    from hearme.domain.events import ChunkSynthesized

    # Documento con bastantes frases: suficiente para pasar del límite de 10.
    source = tmp_path / "largo.md"
    frases = " ".join(f"Esta es la frase numero {n} del documento." for n in range(400))
    source.write_text(f"# Libro largo\n\n{frases}\n", encoding="utf-8")

    bus = EventBus()
    chunks: list[ChunkSynthesized] = []

    async def on_chunk(event) -> None:
        chunks.append(event)

    bus.subscribe(ChunkSynthesized, on_chunk)

    pipeline = ConversionPipeline(plugins=manager, bus=bus)
    result = await pipeline.run(
        ConversionRequest(
            source=source,
            formats=["mp3"],
            engine="silent",
            out_dir=tmp_path / "out",
        ),
        job_id="t-throttle",
    )

    total = result.document.char_count
    assert total > 0
    sintetizados = manager.tts.get("silent").calls
    assert sintetizados > 10, "el documento debe generar bastantes fragmentos"
    # Uno de cada diez, más el último: nunca uno por fragmento.
    assert len(chunks) <= sintetizados // 10 + 1


async def test_una_etapa_lenta_sigue_dando_senales_de_vida() -> None:
    """Sin latido, el OCR y el parseo de un PDF largo parecen colgados."""
    import anyio

    bus = EventBus()
    latidos: list[JobProgress] = []

    async def on_progress(event) -> None:
        latidos.append(event)

    bus.subscribe(JobProgress, on_progress)
    pipeline = ConversionPipeline(bus=bus)

    async with pipeline._heartbeat("t-beat", "parseo", "libro.pdf", interval=0.2):
        await anyio.sleep(0.75)

    assert len(latidos) >= 3, "la etapa lenta debe emitir latidos periódicos"
    assert all(evento.stage == "parseo" for evento in latidos)

    # Y al terminar la etapa, el latido para: si no, seguiría emitiendo para siempre.
    antes = len(latidos)
    await anyio.sleep(0.5)
    assert len(latidos) == antes
