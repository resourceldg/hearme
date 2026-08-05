"""Perfiles de los motores de inferencia y su detección.

Los perfiles reflejan la revisión de docs/ANALISIS-INFERENCIA.md §1 y §5. Un motor
registrado aquí no está "elegido": está *disponible para ser puntuado*. vLLM y
SGLang se autodescartan en una máquina de 4 GB sin que nadie lo codifique.

El registro incluye los motores de la ruta caliente real (TTS y traducción), no
solo los LLM: según §2 del análisis ahí se va el 95 % del tiempo de cómputo, y un
registro que solo conociera LLM dejaría fuera del planificador justo lo que más
importa optimizar.
"""

from __future__ import annotations

import logging
import shutil
from importlib.util import find_spec

from hearme.config import settings
from hearme.domain.inference import BackendProfile
from hearme.domain.inference import Capability as C
from hearme.domain.inference import WorkloadClass as W

logger = logging.getLogger(__name__)

_LLM = frozenset({W.LLM_DECODE})
_TTS_FF = frozenset({W.TTS_FEEDFORWARD})
_TTS_AR = frozenset({W.TTS_AUTOREGRESSIVE})
_SEQ2SEQ = frozenset({W.SEQ2SEQ})
_ASR = frozenset({W.ASR})

#: Perfiles declarados. `min_vram_mb` y `runtime_overhead_mb` provienen de las
#: mediciones citadas en el análisis, no de estimaciones a ojo.
PROFILES: dict[str, BackendProfile] = {
    "llama_cpp": BackendProfile(
        name="llama_cpp",
        license="MIT",
        workloads=_LLM,
        capabilities=frozenset(
            {
                C.GPU_OFFLOAD,
                C.PARTIAL_OFFLOAD,
                C.QUANTIZATION_INT8,
                C.QUANTIZATION_INT4,
                C.STATIC_BATCHING,
                C.CONTINUOUS_BATCHING,
                C.PREFIX_CACHING,
                C.KV_CACHE_QUANTIZATION,
                C.FLASH_ATTENTION,
                C.SPECULATIVE_DECODING,
                C.STREAMING,
                C.CONCURRENT_REQUESTS,
            }
        ),
        min_vram_mb=0,  # corre en CPU pura
        runtime_overhead_mb=120,
        cpu_scaling=0.7,  # 65-75 % de eficiencia por núcleo (medido)
        notes="Sin suelo de VRAM. Offload por capas. GGUF.",
    ),
    "ollama": BackendProfile(
        name="ollama",
        license="MIT",
        workloads=_LLM,
        capabilities=frozenset(
            {
                C.GPU_OFFLOAD,
                C.PARTIAL_OFFLOAD,
                C.QUANTIZATION_INT4,
                C.QUANTIZATION_INT8,
                C.PREFIX_CACHING,
                C.STREAMING,
                C.CONCURRENT_REQUESTS,
                C.FLASH_ATTENTION,
            }
        ),
        min_vram_mb=0,
        runtime_overhead_mb=200,
        cpu_scaling=0.7,
        notes="Envoltorio de llama.cpp con gestión de modelos. Cero fricción.",
    ),
    "vllm": BackendProfile(
        name="vllm",
        license="Apache-2.0",
        workloads=_LLM,
        capabilities=frozenset(
            {
                C.GPU_OFFLOAD,
                C.QUANTIZATION_INT8,
                C.QUANTIZATION_INT4,
                C.CONTINUOUS_BATCHING,
                C.PAGED_ATTENTION,
                C.PREFIX_CACHING,
                C.FLASH_ATTENTION,
                C.SPECULATIVE_DECODING,
                C.KV_CACHE_QUANTIZATION,
                C.STREAMING,
                C.CONCURRENT_REQUESTS,
            }
        ),
        min_vram_mb=6000,
        runtime_overhead_mb=2000,
        cpu_scaling=0.1,
        requires_nvidia=True,
        notes="Motor de centro de datos. 15-20 % más rápido que SGLang en lotes.",
    ),
    "sglang": BackendProfile(
        name="sglang",
        license="Apache-2.0",
        workloads=_LLM,
        capabilities=frozenset(
            {
                C.GPU_OFFLOAD,
                C.QUANTIZATION_INT8,
                C.QUANTIZATION_INT4,
                C.CONTINUOUS_BATCHING,
                C.PAGED_ATTENTION,
                C.PREFIX_CACHING,  # RadixAttention
                C.FLASH_ATTENTION,
                C.SPARSE_ATTENTION,
                C.SPECULATIVE_DECODING,
                C.DYNAMIC_SPECULATIVE,
                C.KV_CACHE_COMPRESSION,
                C.KV_CACHE_QUANTIZATION,
                C.STREAMING,
                C.CONCURRENT_REQUESTS,
            }
        ),
        min_vram_mb=6000,
        runtime_overhead_mb=2000,
        cpu_scaling=0.1,
        requires_nvidia=True,
        notes="+29 % throughput sobre vLLM en H100; hasta 6x en RAG (RadixAttention).",
    ),
    "mlx": BackendProfile(
        name="mlx",
        license="MIT",
        workloads=_LLM,
        capabilities=frozenset(
            {
                C.UNIFIED_MEMORY,
                C.QUANTIZATION_INT4,
                C.QUANTIZATION_INT8,
                C.STATIC_BATCHING,
                C.PREFIX_CACHING,
                C.STREAMING,
            }
        ),
        min_vram_mb=0,
        runtime_overhead_mb=100,
        cpu_scaling=0.3,
        requires_apple_silicon=True,
        notes="Memoria unificada de Apple Silicon: sin copia CPU↔GPU.",
    ),
    # --- TTS de una pasada: la ruta caliente real (§0 y §2 del análisis) ---
    # Sin caché KV que paginar ni prefijo que cachear. La única técnica que les
    # aplica de la lista del encargo es el batching, y es justamente la que más
    # rinde en este proyecto: un capítulo son decenas de párrafos independientes.
    "kokoro": BackendProfile(
        name="kokoro",
        license="Apache-2.0",
        workloads=_TTS_FF,
        capabilities=frozenset(
            {
                C.GPU_OFFLOAD,
                C.STATIC_BATCHING,
                C.STREAMING,
            }
        ),
        min_vram_mb=0,  # 82 M params: corre en CPU sin problema
        runtime_overhead_mb=60,
        cpu_scaling=0.8,  # síntesis por párrafos: paraleliza casi lineal
        declared_quality=0.90,  # naturalness declarada por KokoroEngine
        notes="82 M, VITS/flow de una pasada. La voz más natural del proyecto.",
    ),
    "piper": BackendProfile(
        name="piper",
        license="MIT",
        workloads=_TTS_FF,
        # Sin int8: los sufijos "medium"/"x_low" del índice de voces son niveles
        # de calidad del modelo, no cuantización. Declararla haría que el plan
        # dijese estar aplicando algo que nadie aplica.
        capabilities=frozenset(
            {
                C.STATIC_BATCHING,
                C.STREAMING,
            }
        ),
        min_vram_mb=0,
        runtime_overhead_mb=30,
        cpu_scaling=0.85,
        declared_quality=0.68,  # naturalness declarada por PiperEngine
        notes="20 M ONNX en CPU. Menos natural que Kokoro pero muchísimo más ligero.",
    ),
    # --- TTS autorregresivo: clonación de voz (§5 del análisis) ---
    # Sí tienen caché KV, así que aquí las técnicas de caché vuelven a aplicar.
    "qwen3_tts": BackendProfile(
        name="qwen3_tts",
        license="Apache-2.0",
        workloads=_TTS_AR,
        capabilities=frozenset(
            {
                C.GPU_OFFLOAD,
                C.QUANTIZATION_INT4,
                C.QUANTIZATION_INT8,
                C.STATIC_BATCHING,
                C.KV_CACHE_QUANTIZATION,
                C.FLASH_ATTENTION,
                C.STREAMING,
            }
        ),
        min_vram_mb=3000,  # en int4; en fp16 no cabe en una GPU de 4 GB
        runtime_overhead_mb=600,
        cpu_scaling=0.2,
        declared_quality=0.88,
        adapter_available=False,
        notes="Elegido para clonación: Apache-2.0 y solo 3 s de referencia.",
    ),
    "chatterbox": BackendProfile(
        name="chatterbox",
        license="MIT",
        workloads=_TTS_AR,
        capabilities=frozenset(
            {
                C.GPU_OFFLOAD,
                C.QUANTIZATION_INT8,
                C.STATIC_BATCHING,
                C.KV_CACHE_QUANTIZATION,
                C.FLASH_ATTENTION,
                C.STREAMING,
            }
        ),
        min_vram_mb=4500,  # se autodescarta en 4 GB, como debe
        runtime_overhead_mb=600,
        cpu_scaling=0.2,
        declared_quality=0.92,
        adapter_available=False,
        notes="Alternativa MIT de máxima naturalidad cuando sobra VRAM.",
    ),
    # --- Traducción: autorregresiva pero de secuencias cortas (~50 tokens) ---
    # Por eso solo le amortiza el batching: una caché KV de 50 tokens no merece
    # ni paginarse ni comprimirse.
    "marian": BackendProfile(
        name="marian",
        license="MIT",
        workloads=_SEQ2SEQ,
        # El adaptador corre en fp32: nada de cuantización que declarar.
        capabilities=frozenset(
            {
                C.GPU_OFFLOAD,
                C.STATIC_BATCHING,
            }
        ),
        min_vram_mb=0,
        runtime_overhead_mb=250,  # contexto de torch
        cpu_scaling=0.6,
        declared_quality=0.78,
        notes="75 M por par de idiomas. Uso comercial permitido.",
    ),
    "nllb": BackendProfile(
        name="nllb",
        license="CC-BY-NC-4.0",
        workloads=_SEQ2SEQ,
        # El adaptador usa .half() en CUDA, que es fp16 y no cuantización int8.
        capabilities=frozenset(
            {
                C.GPU_OFFLOAD,
                C.STATIC_BATCHING,
            }
        ),
        min_vram_mb=0,
        runtime_overhead_mb=250,
        cpu_scaling=0.5,
        declared_quality=0.85,
        notes="600 M, 200 idiomas. No comercial: requiere HEARME_ALLOW_NON_COMMERCIAL_MODELS.",
    ),
    # --- ASR: entra por la salvaguarda de clonación (docs/ANALISIS-ASR.md §0) ---
    # El decodificador es autorregresivo, pero de secuencias cortas: como en
    # traducción, solo el batching amortiza.
    "qwen3_asr": BackendProfile(
        name="qwen3_asr",
        license="Apache-2.0",
        workloads=_ASR,
        capabilities=frozenset(
            {
                C.GPU_OFFLOAD,
                C.QUANTIZATION_INT4,
                C.QUANTIZATION_INT8,
                C.STATIC_BATCHING,
                C.KV_CACHE_QUANTIZATION,
                C.FLASH_ATTENTION,
                C.STREAMING,
            }
        ),
        min_vram_mb=600,  # ~0,5 GB en int4; ~2 GB en fp16
        runtime_overhead_mb=400,
        cpu_scaling=0.3,
        declared_quality=0.94,  # WER 5,83 % en 52 idiomas
        adapter_available=False,
        notes="Elegido: Apache-2.0 y misma familia que Qwen3-TTS, que ya usa clonación.",
    ),
    "whisper_cpp": BackendProfile(
        name="whisper_cpp",
        license="MIT",
        workloads=_ASR,
        capabilities=frozenset(
            {
                C.GPU_OFFLOAD,
                C.PARTIAL_OFFLOAD,
                C.QUANTIZATION_INT8,
                C.QUANTIZATION_INT4,
                C.STATIC_BATCHING,
                C.STREAMING,
            }
        ),
        min_vram_mb=0,  # como llama.cpp: corre en CPU pura
        runtime_overhead_mb=80,
        cpu_scaling=0.7,
        declared_quality=0.88,  # 'small': ~95 % de large-v3
        adapter_available=False,
        notes="Fallback sin suelo de VRAM y con los 99 idiomas de Whisper.",
    ),
    "whisper_large": BackendProfile(
        name="whisper_large",
        license="MIT",
        workloads=_ASR,
        capabilities=frozenset(
            {
                C.GPU_OFFLOAD,
                C.QUANTIZATION_INT8,
                C.STATIC_BATCHING,
                C.FLASH_ATTENTION,
            }
        ),
        min_vram_mb=10000,  # se autodescarta en 4 GB, como debe
        runtime_overhead_mb=1000,
        cpu_scaling=0.1,
        declared_quality=0.93,  # WER 7,44 %, pero 99 idiomas
        adapter_available=False,
        notes="El estándar de facto. Solo viable en máquinas con VRAM de sobra.",
    ),
}


def detect_available() -> dict[str, bool]:
    """Qué motores están realmente instalados en esta máquina.

    Detecta el paquete, no el adaptador: que un perfil esté instalado no implica
    que el planificador pueda elegirlo (ver `BackendProfile.adapter_available`).
    """
    transformers = find_spec("transformers") is not None

    return {
        # LLM
        "llama_cpp": find_spec("llama_cpp") is not None or shutil.which("llama-server") is not None,
        "ollama": shutil.which("ollama") is not None,
        "vllm": find_spec("vllm") is not None,
        "sglang": find_spec("sglang") is not None,
        "mlx": find_spec("mlx_lm") is not None,
        # TTS
        "kokoro": find_spec("kokoro") is not None,
        "piper": find_spec("piper") is not None,
        "qwen3_tts": transformers,
        "chatterbox": find_spec("chatterbox") is not None,
        # ASR
        "qwen3_asr": transformers,
        "whisper_cpp": find_spec("pywhispercpp") is not None
        or shutil.which("whisper-cli") is not None,
        "whisper_large": transformers,
        # Traducción
        "marian": transformers,
        # La licencia no comercial es una condición de uso, no de instalación:
        # sin el permiso explícito del usuario el motor no está disponible.
        "nllb": transformers and settings.allow_non_commercial_models,
    }
