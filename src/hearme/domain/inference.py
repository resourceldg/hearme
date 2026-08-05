"""Vocabulario del subsistema de inferencia.

La pieza central es `Capability`: un backend *declara* lo que sabe hacer y una
técnica *exige* lo que necesita. El planificador solo activa la intersección.
Esa negociación es lo que permite añadir técnicas futuras sin tocar nada más.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class WorkloadClass(StrEnum):
    """Tipo de carga. Determina qué técnicas tienen sentido siquiera.

    La distinción no es cosmética: las técnicas de caché KV solo existen para
    decodificadores autorregresivos. Ver docs/ANALISIS-INFERENCIA.md §0.
    """

    LLM_DECODE = "llm_decode"  # autorregresivo: modo estudio
    SEQ2SEQ = "seq2seq"  # traducción: autorregresivo pero secuencias cortas
    TTS_FEEDFORWARD = "tts_ff"  # Kokoro, Piper: una pasada, sin caché KV
    TTS_AUTOREGRESSIVE = "tts_ar"  # Qwen3-TTS, Chatterbox: sí tienen caché KV
    ASR = "asr"

    @property
    def batches_offline(self) -> bool:
        """¿La carga llega ya troceada en unidades independientes?

        Un capítulo son decenas de párrafos que se pueden sintetizar o traducir
        en cualquier orden: hay lote que formar aunque no haya *ninguna* petición
        concurrente. El modo estudio no: llega una petición cada vez.
        """
        return self is not WorkloadClass.LLM_DECODE


class Capability(StrEnum):
    """Lo que un backend sabe hacer."""

    # --- Colocación y precisión ---
    GPU_OFFLOAD = "gpu_offload"
    PARTIAL_OFFLOAD = "partial_offload"  # capas repartidas CPU/GPU
    QUANTIZATION_INT8 = "quant_int8"
    QUANTIZATION_INT4 = "quant_int4"
    UNIFIED_MEMORY = "unified_memory"  # Apple Silicon

    # --- Programación de peticiones ---
    CONTINUOUS_BATCHING = "continuous_batching"
    STATIC_BATCHING = "static_batching"

    # --- Caché ---
    PREFIX_CACHING = "prefix_caching"  # RadixAttention y equivalentes
    PAGED_ATTENTION = "paged_attention"
    KV_CACHE_COMPRESSION = "kv_compression"
    KV_CACHE_QUANTIZATION = "kv_quantization"

    # --- Atención ---
    FLASH_ATTENTION = "flash_attention"
    SPARSE_ATTENTION = "sparse_attention"

    # --- Decodificación ---
    SPECULATIVE_DECODING = "speculative"
    DYNAMIC_SPECULATIVE = "dynamic_speculative"

    # --- Operativa ---
    STREAMING = "streaming"
    CONCURRENT_REQUESTS = "concurrent"


class Objective(StrEnum):
    """Qué se está optimizando. Lo fija el usuario, no el sistema."""

    LATENCY = "latency"
    BALANCED = "balanced"
    QUALITY = "quality"


@dataclass(frozen=True, slots=True)
class Technique:
    """Una optimización aplicable, descrita de forma declarativa.

    Añadir una técnica de 2027 es instanciar esto y registrarlo. El planificador,
    los backends y el pipeline no cambian.
    """

    name: str
    #: Capacidades que el backend DEBE ofrecer para poder activarla.
    requires: frozenset[Capability]
    #: Clases de carga donde la técnica tiene sentido. Fuera de ellas se ignora.
    applies_to: frozenset[WorkloadClass]
    #: Ganancia esperada en throughput (1.0 = ninguna). Ordena la activación.
    expected_speedup: float = 1.0
    #: Impacto en calidad: negativo degrada. Lo usa el tuner.
    quality_delta: float = 0.0
    #: Coste de memoria relativo (1.0 = neutro).
    memory_factor: float = 1.0
    #: Si solo rinde con varias unidades de trabajo en vuelo. El planificador la
    #: descarta cuando no hay concurrencia ni lote offline que formar.
    needs_concurrency: bool = False
    description: str = ""

    def is_applicable(self, workload: WorkloadClass, available: frozenset[Capability]) -> bool:
        return workload in self.applies_to and self.requires <= available


@dataclass(frozen=True, slots=True)
class BackendProfile:
    """Lo que un backend declara sobre sí mismo, antes de medirlo."""

    name: str
    capabilities: frozenset[Capability]
    workloads: frozenset[WorkloadClass]
    license: str
    #: VRAM mínima utilizable en MB. 0 = corre en CPU pura.
    min_vram_mb: int = 0
    #: Coste fijo del runtime antes de cargar pesos (contexto CUDA, asignador).
    runtime_overhead_mb: int = 0
    #: Escalado con núcleos de CPU (0 = no usa CPU, 1 = lineal).
    cpu_scaling: float = 0.0
    requires_apple_silicon: bool = False
    requires_nvidia: bool = False
    #: Calidad declarada por el motor, 0..1. Es la base que el tuner corrige con
    #: degradación y voto humano. Ver §3 del análisis: NO es una medida objetiva.
    declared_quality: float = 0.7
    #: False para perfiles registrados por decisión de diseño cuyo adaptador aún
    #: no existe. El planificador no puede elegirlos aunque el paquete esté
    #: instalado: no hay código que sepa invocarlos.
    adapter_available: bool = True
    notes: str = ""


@dataclass(slots=True)
class Measurement:
    """Una medición de telemetría de una petición."""

    backend: str
    workload: WorkloadClass
    #: Tiempo hasta el primer token (o primera muestra de audio), en ms.
    ttft_ms: float = 0.0
    tokens_per_second: float = 0.0
    #: Real-Time Factor, solo para cargas de audio.
    rtf: float = 0.0
    total_ms: float = 0.0
    cpu_percent: float = 0.0
    ram_mb: float = 0.0
    vram_mb: float = 0.0
    #: Estimación de calidad 0..1. Ver §3 del análisis: NO es objetiva.
    quality_estimate: float = 0.0
    techniques: tuple[str, ...] = ()
    ok: bool = True
    error: str = ""


@dataclass(slots=True)
class Plan:
    """Resultado del planificador: con qué correr y cómo."""

    backend: str
    workload: WorkloadClass
    techniques: tuple[str, ...]
    quality_level: int  # 0 = máxima calidad, N = más degradado
    parameters: dict[str, object] = field(default_factory=dict)
    reason: str = ""

    def describe(self) -> str:
        techniques = ", ".join(self.techniques) or "ninguna"
        return f"{self.backend} · nivel {self.quality_level} · técnicas: {techniques}"

    def number(self, name: str, default: int = 0) -> int:
        """Parámetro numérico del plan.

        `parameters` es heterogéneo a propósito: cada técnica futura añadirá lo
        suyo sin cambiar el tipo. El acceso tipado se resuelve aquí y no en cada
        consumidor, y un valor ausente o de otro tipo devuelve el de por defecto
        en vez de reventar a mitad de una conversión.
        """
        value = self.parameters.get(name)
        return value if isinstance(value, int) and not isinstance(value, bool) else default
