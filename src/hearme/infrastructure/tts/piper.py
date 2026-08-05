"""Motor Piper — cobertura de idiomas y modo borrador.

MIT, ONNX, RTF ~0.02 en CPU. Cubre 50+ idiomas donde Kokoro no llega, y es el
motor elegido cuando se pide `quality=draft`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import wave
from pathlib import Path
from typing import Any

import httpx

from hearme.config import settings
from hearme.domain.models import AudioSegment, Utterance

logger = logging.getLogger(__name__)

_HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

#: Ganancia fija que compensa desactivar la normalización de Piper.
#: Medido sobre 25 fragmentos reales: los picos caen entre 0.34 y 0.56. Con 1.4 el
#: nivel típico sube a ~0.58 y el fragmento más fuerte con énfasis se queda en
#: 0.91, por debajo del recorte. Al ser constante, no aplana la dinámica.
_MAKEUP_GAIN = 1.4

#: Voz recomendada por idioma -> ruta relativa en el repositorio de voces.
#: Modelos con varios hablantes, con el mapa que declara el propio índice de
#: `rhasspy/piper-voices` (campo `speaker_id_map` de su voices.json).
#:
#: Esto no es una suposición: es el dato oficial. Y arregla una limitación que
#: pasaba desapercibida —el modelo español trae voz masculina y femenina, y
#: HearMe usaba siempre el hablante 0, así que a la femenina no se llegaba nunca.
_SPEAKERS: dict[str, dict[str, int]] = {
    "es_ES-sharvard-medium": {"M": 0, "F": 1},
    "uk_UA-ukrainian_tts-medium": {"lada": 0, "mykyta": 1, "tetiana": 2},
    # nl_NL-mls-medium tiene 52 hablantes identificados solo por número de
    # LibriVox. Exponerlos sería una lista ilegible sin ninguna información útil,
    # así que se usa el que trae por defecto.
}

#: Separador entre el modelo y el hablante: `es_ES-sharvard-medium#F`.
SPEAKER_SEP = "#"

_VOICE_INDEX: dict[str, str] = {
    "es": "es/es_ES/sharvard/medium/es_ES-sharvard-medium",
    "en": "en/en_US/lessac/medium/en_US-lessac-medium",
    "fr": "fr/fr_FR/siwis/medium/fr_FR-siwis-medium",
    "de": "de/de_DE/thorsten/medium/de_DE-thorsten-medium",
    "it": "it/it_IT/riccardo/x_low/it_IT-riccardo-x_low",
    "pt": "pt/pt_BR/faber/medium/pt_BR-faber-medium",
    "nl": "nl/nl_NL/mls/medium/nl_NL-mls-medium",
    "pl": "pl/pl_PL/darkman/medium/pl_PL-darkman-medium",
    "ru": "ru/ru_RU/dmitri/medium/ru_RU-dmitri-medium",
    "uk": "uk/uk_UA/ukrainian_tts/medium/uk_UA-ukrainian_tts-medium",
    "tr": "tr/tr_TR/dfki/medium/tr_TR-dfki-medium",
    "sv": "sv/sv_SE/nst/medium/sv_SE-nst-medium",
    "da": "da/da_DK/talesyntese/medium/da_DK-talesyntese-medium",
    "no": "no/no_NO/talesyntese/medium/no_NO-talesyntese-medium",
    "fi": "fi/fi_FI/harri/medium/fi_FI-harri-medium",
    "el": "el/el_GR/rapunzelina/low/el_GR-rapunzelina-low",
    "cs": "cs/cs_CZ/jirka/medium/cs_CZ-jirka-medium",
    "ro": "ro/ro_RO/mihai/medium/ro_RO-mihai-medium",
    "hu": "hu/hu_HU/anna/medium/hu_HU-anna-medium",
    "ca": "ca/ca_ES/upc_ona/medium/ca_ES-upc_ona-medium",
    "ar": "ar/ar_JO/kareem/medium/ar_JO-kareem-medium",
    "zh": "zh/zh_CN/huayan/medium/zh_CN-huayan-medium",
    "vi": "vi/vi_VN/vais1000/medium/vi_VN-vais1000-medium",
    "fa": "fa/fa_IR/amir/medium/fa_IR-amir-medium",
    "hi": "hi/hi_IN/pratham/medium/hi_IN-pratham-medium",
}


class PiperEngine:
    name = "piper"
    languages = frozenset(_VOICE_INDEX)
    naturalness = 0.68
    rtf = 0.02
    non_commercial = False

    def __init__(self, *, language: str = "es", models_dir: Path | None = None) -> None:
        self.language = language
        self.models_dir = models_dir or (settings.resolved_models_dir / "piper")
        self._voices: dict[str, Any] = {}
        # Sin este cerrojo, N hilos de síntesis descargan el mismo modelo a la vez
        # y se pisan el archivo temporal.
        self._lock = asyncio.Lock()
        self._load_lock = threading.Lock()

    async def is_available(self) -> bool:
        try:
            import piper  # noqa: F401
        except ImportError:
            return False
        return True

    async def voices(self, language: str | None = None) -> tuple[str, ...]:
        """Voces disponibles, una por hablante si el modelo tiene varios.

        Un modelo con dos hablantes son dos voces para quien elige, no una.
        Devolver solo el modelo escondía la mitad del catálogo.
        """
        key = language or self.language
        if key not in _VOICE_INDEX:
            return ()
        modelo = _VOICE_INDEX[key].rsplit("/", 1)[-1]
        hablantes = _SPEAKERS.get(modelo)
        if not hablantes:
            return (modelo,)
        return tuple(f"{modelo}{SPEAKER_SEP}{nombre}" for nombre in hablantes)

    @staticmethod
    def split_voice(voice: str) -> tuple[str, str | None]:
        """`es_ES-sharvard-medium#F` -> (`es_ES-sharvard-medium`, `F`)."""
        modelo, _, hablante = voice.partition(SPEAKER_SEP)
        return modelo, hablante or None

    @staticmethod
    def speaker_id(voice: str) -> int | None:
        """Índice del hablante dentro del modelo, o None si es de uno solo."""
        modelo, hablante = PiperEngine.split_voice(voice)
        if hablante is None:
            return None
        return _SPEAKERS.get(modelo, {}).get(hablante)

    def default_voice(self, language: str) -> str:
        path = _VOICE_INDEX.get(language) or _VOICE_INDEX["en"]
        return path.rsplit("/", 1)[-1]

    async def prepare(self, language: str) -> None:
        """Descarga el modelo antes de arrancar el pool de síntesis."""
        await self.ensure_model(language)

    async def ensure_model(self, language: str) -> Path:
        """Descarga el modelo ONNX y su config si aún no están en disco."""
        relative = _VOICE_INDEX.get(language)
        if relative is None:
            raise LookupError(f"Piper no tiene voz registrada para el idioma '{language}'")

        name = relative.rsplit("/", 1)[-1]
        model_path = self.models_dir / f"{name}.onnx"
        config_path = self.models_dir / f"{name}.onnx.json"
        if model_path.exists() and config_path.exists():
            return model_path

        async with self._lock:
            # Otro hilo pudo completar la descarga mientras esperábamos el cerrojo.
            if model_path.exists() and config_path.exists():
                return model_path

            self.models_dir.mkdir(parents=True, exist_ok=True)
            async with httpx.AsyncClient(follow_redirects=True, timeout=600) as client:
                for url, target in (
                    (f"{_HF_BASE}/{relative}.onnx", model_path),
                    (f"{_HF_BASE}/{relative}.onnx.json", config_path),
                ):
                    if target.exists():
                        continue
                    logger.info("descargando voz Piper: %s", target.name)
                    # Nombre temporal único: dos procesos concurrentes no colisionan.
                    tmp = target.with_name(f"{target.name}.{os.getpid()}.part")
                    try:
                        async with client.stream("GET", url) as response:
                            response.raise_for_status()
                            with tmp.open("wb") as handle:
                                async for chunk in response.aiter_bytes(1 << 16):
                                    handle.write(chunk)
                        tmp.replace(target)  # atómico: nunca un modelo a medias
                    finally:
                        tmp.unlink(missing_ok=True)
        return model_path

    def _voice(self, language: str, model_path: Path) -> Any:
        # Se ejecuta dentro de hilos de trabajo: la carga necesita cerrojo propio,
        # el asyncio.Lock de arriba no protege aquí.
        with self._load_lock:
            if language not in self._voices:
                from piper import PiperVoice

                self._voices[language] = PiperVoice.load(str(model_path))
            return self._voices[language]

    async def synthesize(self, utterance: Utterance, *, voice: str, out_dir: Path) -> AudioSegment:
        import anyio

        model_path = await self.ensure_model(self.language)
        out_path = out_dir / f"{utterance.order:06d}_{utterance.id[:8]}.wav"
        speaker = self.speaker_id(voice)
        rate, duration = await anyio.to_thread.run_sync(
            self._synthesize_sync, utterance, model_path, out_path, speaker
        )
        return AudioSegment(
            utterance_id=utterance.id,
            path=out_path,
            duration_s=duration,
            sample_rate=rate,
            order=utterance.order,
        )

    @staticmethod
    def _synthesis_config(utterance: Utterance, speaker: int | None = None) -> Any | None:
        """Traduce el estilo de narración a parámetros de Piper.

        Sin esto, `rate` y `emphasis` —lo que distingue «poesía» de «técnico»— se
        quedaban en el `Utterance` sin llegar al motor, y los cuatro estilos
        sonaban exactamente igual salvo por la duración de las pausas.

        `normalize_audio=False` es obligatorio para que `volume` sobreviva: la
        normalización reescala cada clip al pico máximo y borraría el énfasis.
        Además arregla un defecto audible por sí solo: normalizada una a una, la
        interjección de una palabra salía tan fuerte como el párrafo entero, y el
        volumen del audiolibro bombeaba fragmento a fragmento. `_MAKEUP_GAIN`
        devuelve el nivel perdido sin volver a aplanar la dinámica.
        """
        try:
            from piper import SynthesisConfig
        except ImportError:
            return None  # Piper < 1.3: sin control de estilo, se narra plano.

        return SynthesisConfig(
            # length_scale es el inverso de la velocidad: >1 alarga los fonemas.
            length_scale=1.0 / utterance.rate if utterance.rate else 1.0,
            volume=_MAKEUP_GAIN * utterance.emphasis,
            normalize_audio=False,
            # Sin esto, elegir la voz femenina de un modelo con dos hablantes no
            # cambiaba nada: siempre sonaba el hablante 0.
            speaker_id=speaker,
        )

    def _synthesize_sync(
        self,
        utterance: Utterance,
        model_path: Path,
        out_path: Path,
        speaker: int | None = None,
    ) -> tuple[int, float]:
        voice = self._voice(self.language, model_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        with wave.open(str(out_path), "wb") as wav:
            # La API de Piper cambió en 1.3: se soportan ambas formas.
            if hasattr(voice, "synthesize_wav"):
                config = self._synthesis_config(utterance, speaker)
                if config is None:
                    voice.synthesize_wav(utterance.text, wav)
                else:
                    voice.synthesize_wav(utterance.text, wav, syn_config=config)
            else:
                voice.synthesize(utterance.text, wav)

        with wave.open(str(out_path), "rb") as wav:
            rate = wav.getframerate()
            frames = wav.getnframes()
            width = wav.getsampwidth()
            channels = wav.getnchannels()
            wav.setpos(0)
            pcm = wav.readframes(frames)

        if utterance.pause_after_ms:
            silence = b"\x00" * int(rate * width * channels * utterance.pause_after_ms / 1000)
            with wave.open(str(out_path), "wb") as wav:
                wav.setnchannels(channels)
                wav.setsampwidth(width)
                wav.setframerate(rate)
                wav.writeframes(pcm + silence)
            frames += len(silence) // (width * channels)

        return rate, frames / rate

    async def close(self) -> None:
        self._voices.clear()
