"""Catálogo de técnicas de optimización.

Cada entrada es declarativa: qué exige, dónde aplica, qué gana y qué cuesta.
El planificador no contiene ningún `if technique == "..."`. Añadir una técnica
nueva es añadir un objeto a esta lista.
"""

from __future__ import annotations

from hearme.domain.inference import Capability as C
from hearme.domain.inference import Technique
from hearme.domain.inference import WorkloadClass as W

#: Cargas autorregresivas con caché KV: aquí sí aplican las técnicas de caché.
#: El decodificador de ASR también lo es —Whisper y Qwen3-ASR generan token a
#: token—, así que estaba mal clasificado fuera. Ver docs/ANALISIS-ASR.md §3.
_AUTOREGRESSIVE = frozenset({W.LLM_DECODE, W.SEQ2SEQ, W.TTS_AUTOREGRESSIVE, W.ASR})
#: Todas las cargas: técnicas de colocación y precisión.
_ALL = frozenset(W)

CATALOG: tuple[Technique, ...] = (
    # --- Precisión y colocación: aplican a todo ---
    Technique(
        name="quantization_int8",
        requires=frozenset({C.QUANTIZATION_INT8}),
        applies_to=_ALL,
        expected_speedup=1.8,
        quality_delta=-0.02,
        memory_factor=0.5,
        description="Pesos a 8 bits. Degradación de calidad casi nula.",
    ),
    Technique(
        name="quantization_int4",
        requires=frozenset({C.QUANTIZATION_INT4}),
        applies_to=_ALL,
        expected_speedup=2.4,
        quality_delta=-0.08,
        memory_factor=0.28,
        description="Q4_K_M. Reduce a la cuarta parte la memoria que ocupa el modelo.",
    ),
    Technique(
        name="partial_gpu_offload",
        requires=frozenset({C.PARTIAL_OFFLOAD}),
        applies_to=_ALL,
        expected_speedup=1.6,
        memory_factor=1.0,
        description="Reparte capas entre GPU y CPU cuando el modelo no cabe entero.",
    ),
    # --- Programación: solo si hay más de una petición en vuelo ---
    Technique(
        name="continuous_batching",
        requires=frozenset({C.CONTINUOUS_BATCHING, C.CONCURRENT_REQUESTS}),
        applies_to=_AUTOREGRESSIVE,
        expected_speedup=2.5,
        needs_concurrency=True,
        description="Inserta peticiones nuevas sin esperar a que acabe el lote.",
    ),
    Technique(
        name="static_batching",
        requires=frozenset({C.STATIC_BATCHING}),
        applies_to=_ALL,
        expected_speedup=2.0,
        needs_concurrency=True,
        description=(
            "Agrupa entradas de tamaño similar. Es la técnica de mayor retorno "
            "real del proyecto: aplica a TTS y traducción, la ruta caliente."
        ),
    ),
    # --- Caché: solo autorregresivos ---
    Technique(
        name="prefix_caching",
        requires=frozenset({C.PREFIX_CACHING}),
        applies_to=frozenset({W.LLM_DECODE}),
        expected_speedup=3.0,
        description=(
            "Reutiliza el prompt de sistema entre capítulos. Máximo retorno en "
            "modo estudio, donde el sistema es fijo y solo cambia el capítulo."
        ),
    ),
    Technique(
        name="paged_attention",
        requires=frozenset({C.PAGED_ATTENTION}),
        applies_to=_AUTOREGRESSIVE,
        expected_speedup=1.9,
        memory_factor=0.75,
        description="Pagina la caché KV y elimina la fragmentación.",
    ),
    Technique(
        name="kv_cache_quantization",
        requires=frozenset({C.KV_CACHE_QUANTIZATION}),
        applies_to=_AUTOREGRESSIVE,
        expected_speedup=1.15,
        quality_delta=-0.03,
        memory_factor=0.5,
        description="Caché KV a 8 bits: duplica el contexto que cabe en memoria.",
    ),
    Technique(
        name="kv_cache_compression",
        requires=frozenset({C.KV_CACHE_COMPRESSION}),
        applies_to=_AUTOREGRESSIVE,
        expected_speedup=1.1,
        quality_delta=-0.05,
        memory_factor=0.3,
        description="Descarta tokens poco atendidos. Solo rentable en contexto largo.",
    ),
    # --- Atención ---
    Technique(
        name="flash_attention",
        requires=frozenset({C.FLASH_ATTENTION}),
        applies_to=_AUTOREGRESSIVE,
        expected_speedup=2.0,
        description="Atención con uso eficiente del ancho de banda de memoria.",
    ),
    Technique(
        name="sparse_attention",
        requires=frozenset({C.SPARSE_ATTENTION}),
        applies_to=frozenset({W.LLM_DECODE}),
        expected_speedup=1.4,
        quality_delta=-0.06,
        description=(
            "Rompe el O(n²). Solo se activa con contexto >8k: por debajo, el "
            "coste de la máscara supera la ganancia."
        ),
    ),
    # --- Decodificación ---
    Technique(
        name="speculative_decoding",
        requires=frozenset({C.SPECULATIVE_DECODING}),
        applies_to=frozenset({W.LLM_DECODE}),
        expected_speedup=2.2,
        memory_factor=1.3,
        description="Un modelo borrador propone tokens y el grande los verifica.",
    ),
    Technique(
        name="dynamic_speculative_decoding",
        requires=frozenset({C.DYNAMIC_SPECULATIVE}),
        applies_to=frozenset({W.LLM_DECODE}),
        expected_speedup=2.6,
        memory_factor=1.3,
        description=(
            "Ajusta cuántos tokens especula según la tasa de aceptación medida. "
            "Sustituye a speculative_decoding cuando ambas están disponibles."
        ),
    ),
)

#: Técnicas que quedan anuladas si otra está activa (la clave es la superada).
SUPERSEDED_BY: dict[str, str] = {
    "speculative_decoding": "dynamic_speculative_decoding",
    "static_batching": "continuous_batching",
    "quantization_int8": "quantization_int4",
}

BY_NAME: dict[str, Technique] = {t.name: t for t in CATALOG}


def register(technique: Technique, *, supersedes: str | None = None) -> None:
    """Registra una técnica nueva en caliente (plugins de terceros)."""
    global CATALOG
    if technique.name in BY_NAME:
        raise ValueError(f"la técnica '{technique.name}' ya existe")
    CATALOG = (*CATALOG, technique)
    BY_NAME[technique.name] = technique
    if supersedes:
        SUPERSEDED_BY[supersedes] = technique.name
