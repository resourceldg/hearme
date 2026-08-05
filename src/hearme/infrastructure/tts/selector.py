"""Selección automática de motor TTS por idioma.

Implementa la decisión de docs/ANALISIS-COMPARATIVO.md §1: no hay un motor fijo,
hay una función de puntuación sobre los motores registrados. Añadir un motor nuevo
no requiere tocar este archivo — solo registrarlo con sus capacidades declaradas.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from hearme.domain.ports import TTSEngine

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Selection:
    engine: TTSEngine
    voice: str
    language: str
    reason: str


class NoEngineAvailable(RuntimeError):
    pass


async def select_engine(
    engines: list[TTSEngine],
    *,
    language: str,
    quality: str = "high",
    allow_non_commercial: bool = False,
    preferred: str | None = None,
    voice: str | None = None,
) -> Selection:
    """Elige el mejor motor disponible para un idioma.

    Orden de criterios:
      1. Motor pedido explícitamente, si existe y está disponible.
      2. Filtro por licencia: los no comerciales se excluyen salvo activación.
      3. Filtro por idioma soportado.
      4. quality='draft' -> gana el RTF más bajo; 'high' -> gana la naturalidad.
    """
    language = (language or "en").split("-")[0].lower()

    available: list[TTSEngine] = []
    for engine in engines:
        if await engine.is_available():
            available.append(engine)
        else:
            logger.debug("motor '%s' no disponible (falta dependencia)", engine.name)

    if not available:
        raise NoEngineAvailable(
            "Ningún motor TTS instalado. Prueba: uv pip install 'hearme[tts-kokoro]'"
        )

    if preferred and preferred != "auto":
        match = next((e for e in available if e.name == preferred), None)
        if match is None:
            raise NoEngineAvailable(
                f"El motor '{preferred}' no está disponible. "
                f"Instalados: {[e.name for e in available]}"
            )
        return Selection(
            engine=match,
            voice=voice or _default_voice(match, language),
            language=language,
            reason=f"motor '{preferred}' solicitado explícitamente",
        )

    candidates = [
        e
        for e in available
        if (allow_non_commercial or not e.non_commercial) and language in e.languages
    ]

    if not candidates:
        # Sin cobertura para el idioma: mejor narrar con un motor genérico que fallar.
        fallback = [e for e in available if allow_non_commercial or not e.non_commercial]
        if not fallback:
            raise NoEngineAvailable(
                "Solo hay motores con licencia no comercial. Activa "
                "HEARME_ALLOW_NON_COMMERCIAL_MODELS=true para usarlos."
            )
        chosen = max(fallback, key=lambda e: e.naturalness)
        return Selection(
            engine=chosen,
            voice=voice or _default_voice(chosen, language),
            language=language,
            reason=(
                f"ningún motor declara soporte para '{language}'; "
                f"se usa '{chosen.name}' como aproximación"
            ),
        )

    if quality == "draft":
        chosen = min(candidates, key=lambda e: e.rtf)
        reason = f"modo borrador: '{chosen.name}' es el más rápido (RTF {chosen.rtf})"
    else:
        chosen = max(candidates, key=lambda e: (e.naturalness, -e.rtf))
        reason = (
            f"máxima calidad para '{language}': '{chosen.name}' (naturalidad {chosen.naturalness})"
        )

    return Selection(
        engine=chosen,
        voice=voice or _default_voice(chosen, language),
        language=language,
        reason=reason,
    )


def _default_voice(engine: TTSEngine, language: str) -> str:
    getter = getattr(engine, "default_voice", None)
    if callable(getter):
        return str(getter(language))
    return ""
