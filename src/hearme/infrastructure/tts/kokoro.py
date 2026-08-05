"""Motor Kokoro-82M — el camino de calidad por defecto.

82 M de parámetros, Apache-2.0, RTF ~0.05 en CPU. Elegido como motor primario
(ver docs/ANALISIS-COMPARATIVO.md §1): deja el acelerador libre para el traductor
o el LLM, lo que permite servir en nodos modestos.
"""

from __future__ import annotations

import logging
import threading
import wave
from pathlib import Path
from typing import Any

from hearme.domain.models import AudioSegment, Utterance

logger = logging.getLogger(__name__)

SAMPLE_RATE = 24_000

#: Kokoro identifica el idioma con una sola letra, no con ISO-639.
_LANG_CODES: dict[str, str] = {
    "en": "a",  # inglés americano
    "es": "e",
    "fr": "f",
    "hi": "h",
    "it": "i",
    "pt": "p",
    "ja": "j",
    "zh": "z",
}

#: Voz por defecto por idioma. Prefijo: [idioma][género].
_DEFAULT_VOICES: dict[str, str] = {
    "en": "af_heart",
    "es": "ef_dora",
    "fr": "ff_siwis",
    "hi": "hf_alpha",
    "it": "if_sara",
    "pt": "pf_dora",
    "ja": "jf_alpha",
    "zh": "zf_xiaobei",
}

_VOICES_BY_LANG: dict[str, tuple[str, ...]] = {
    "en": ("af_heart", "af_bella", "af_nicole", "am_michael", "am_fenrir", "bf_emma"),
    "es": ("ef_dora", "em_alex", "em_santa"),
    "fr": ("ff_siwis",),
    "hi": ("hf_alpha", "hf_beta", "hm_omega"),
    "it": ("if_sara", "im_nicola"),
    "pt": ("pf_dora", "pm_alex"),
    "ja": ("jf_alpha", "jf_gongitsune", "jm_kumo"),
    "zh": ("zf_xiaobei", "zf_xiaoni", "zm_yunjian"),
}


class KokoroEngine:
    name = "kokoro"
    languages = frozenset(_LANG_CODES)
    naturalness = 0.90
    rtf = 0.05
    non_commercial = False

    def __init__(self, *, language: str = "en", device: str | None = None) -> None:
        self.language = language if language in _LANG_CODES else "en"
        self.device = device
        # Una pipeline por idioma: cambiar de idioma no debe recargar el modelo.
        self._pipelines: dict[str, Any] = {}
        # Sin este cerrojo, los N hilos del pool entran a la vez en _pipeline()
        # y cada uno carga su propio modelo: N veces la memoria de una.
        self._load_lock = threading.Lock()

    async def is_available(self) -> bool:
        try:
            import kokoro  # noqa: F401
        except ImportError:
            return False
        return True

    async def voices(self, language: str | None = None) -> tuple[str, ...]:
        return _VOICES_BY_LANG.get(language or self.language, ())

    def default_voice(self, language: str) -> str:
        return _DEFAULT_VOICES.get(language, _DEFAULT_VOICES["en"])

    async def prepare(self, language: str) -> None:
        """Carga el modelo antes de que se abra el pool de síntesis.

        Además de evitar la carrera entre hilos, deja la descarga y la carga
        *fuera* de la primera síntesis. Si no, el RTF medido de ese fragmento
        incluiría el modelo entero y falsearía la telemetría del motor.
        """
        import anyio

        await anyio.to_thread.run_sync(self._pipeline, language)

    def _pipeline(self, language: str) -> Any:
        code = _LANG_CODES.get(language, "a")
        with self._load_lock:
            if code not in self._pipelines:
                from kokoro import KPipeline

                logger.info("cargando Kokoro para idioma '%s' (code=%s)", language, code)
                kwargs: dict[str, Any] = {"lang_code": code}
                if self.device:
                    kwargs["device"] = self.device
                self._pipelines[code] = KPipeline(**kwargs)
        return self._pipelines[code]

    async def synthesize(self, utterance: Utterance, *, voice: str, out_dir: Path) -> AudioSegment:
        import anyio

        out_path = out_dir / f"{utterance.order:06d}_{utterance.id[:8]}.wav"
        duration = await anyio.to_thread.run_sync(self._synthesize_sync, utterance, voice, out_path)
        return AudioSegment(
            utterance_id=utterance.id,
            path=out_path,
            duration_s=duration,
            sample_rate=SAMPLE_RATE,
            order=utterance.order,
        )

    def _synthesize_sync(self, utterance: Utterance, voice: str, out_path: Path) -> float:
        import numpy as np

        pipeline = self._pipeline(self.language)
        chunks: list[Any] = []
        for result in pipeline(utterance.text, voice=voice, speed=utterance.rate):
            audio = result[2] if isinstance(result, tuple) else getattr(result, "audio", None)
            if audio is not None:
                chunks.append(np.asarray(audio, dtype=np.float32).reshape(-1))

        samples = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)

        if utterance.emphasis != 1.0 and samples.size:
            # Énfasis como ganancia acotada; evita clipping en encabezados.
            samples = np.clip(samples * utterance.emphasis, -1.0, 1.0)

        if utterance.pause_after_ms:
            silence = np.zeros(int(SAMPLE_RATE * utterance.pause_after_ms / 1000), dtype=np.float32)
            samples = np.concatenate([samples, silence])

        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(pcm.tobytes())

        return len(pcm) / SAMPLE_RATE

    async def close(self) -> None:
        self._pipelines.clear()
