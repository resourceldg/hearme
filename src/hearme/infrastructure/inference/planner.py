"""Planificador: elige backend y negocia técnicas.

No contiene ninguna rama por nombre de motor ni de técnica. Todo sale de los
perfiles declarados y del catálogo. Ese es el requisito de "añadir técnicas
futuras sin tocar el resto".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from hearme.domain.inference import (
    BackendProfile,
    Capability,
    Objective,
    Plan,
    Technique,
    WorkloadClass,
)
from hearme.infrastructure.hardware import Accelerator, HardwareProfile, detect
from hearme.infrastructure.inference import techniques as catalog
from hearme.infrastructure.inference.backends import PROFILES, detect_available
from hearme.infrastructure.inference.telemetry import TelemetryStore, telemetry

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Candidate:
    profile: BackendProfile
    score: float
    viable: bool
    reason: str


class NoBackendViable(RuntimeError):
    pass


def _vram_budget(hardware: HardwareProfile, profile: BackendProfile) -> int:
    """VRAM realmente utilizable tras descontar el overhead del runtime.

    Es la comprobación que descarta vLLM/SGLang en una GPU de 4 GB: 2 GB se van
    en contexto CUDA y asignador antes de cargar un solo peso.
    """
    return hardware.vram_mb - profile.runtime_overhead_mb


def evaluate_backends(
    workload: WorkloadClass,
    *,
    hardware: HardwareProfile | None = None,
    available: dict[str, bool] | None = None,
    store: TelemetryStore | None = None,
) -> list[Candidate]:
    """Puntúa cada backend para una carga. Devuelve ordenado, mejor primero."""
    hardware = hardware or detect()
    available = available if available is not None else detect_available()
    store = store or telemetry

    candidates: list[Candidate] = []

    for name, profile in PROFILES.items():
        if workload not in profile.workloads:
            continue

        # Antes que la detección: un paquete instalado sin adaptador que sepa
        # invocarlo no es un backend utilizable, y decir "no instalado" sería
        # un diagnóstico falso.
        if not profile.adapter_available:
            candidates.append(Candidate(profile, 0.0, False, "adaptador aún no implementado"))
            continue

        if not available.get(name, False):
            candidates.append(Candidate(profile, 0.0, False, "no instalado en este sistema"))
            continue

        if profile.requires_apple_silicon and hardware.accelerator is not Accelerator.MPS:
            candidates.append(Candidate(profile, 0.0, False, "requiere Apple Silicon"))
            continue

        if profile.requires_nvidia and hardware.accelerator is not Accelerator.CUDA:
            candidates.append(Candidate(profile, 0.0, False, "requiere GPU NVIDIA"))
            continue

        if profile.min_vram_mb:
            budget = _vram_budget(hardware, profile)
            if budget < profile.min_vram_mb:
                candidates.append(
                    Candidate(
                        profile,
                        0.0,
                        False,
                        (
                            f"necesita {profile.min_vram_mb} MB útiles pero solo hay "
                            f"{max(budget, 0)} MB tras {profile.runtime_overhead_mb} MB "
                            "de overhead del runtime"
                        ),
                    )
                )
                continue

        score, reason = _score(profile, hardware, workload, store)
        candidates.append(Candidate(profile, score, True, reason))

    candidates.sort(key=lambda c: (c.viable, c.score), reverse=True)
    return candidates


def _score(
    profile: BackendProfile,
    hardware: HardwareProfile,
    workload: WorkloadClass,
    store: TelemetryStore,
) -> tuple[float, str]:
    """Puntuación heurística, corregida por telemetría real si existe.

    La medición siempre gana a la declaración: si ya hemos ejecutado el backend,
    su rendimiento observado domina el cálculo.
    """
    reasons: list[str] = []

    # Base: ganancia esperada de las técnicas que este backend puede activar.
    applicable = applicable_techniques(profile, workload)
    score = 1.0
    for technique in applicable:
        score *= technique.expected_speedup**0.5  # raíz: no son multiplicativas de verdad
    reasons.append(f"{len(applicable)} técnicas aplicables")

    # Aporte de la CPU: relevante cuando la CPU hace de verdad el trabajo.
    # Si hay GPU utilizable y el motor sabe descargar en ella, el modelo vive en
    # la GPU y premiar los núcleos a pleno haría ganar a un motor de CPU en una
    # máquina de centro de datos — justo lo contrario de la decisión de §1.
    if profile.cpu_scaling:
        on_gpu = hardware.can_run_on_gpu and Capability.GPU_OFFLOAD in profile.capabilities
        weight = 0.25 if on_gpu else 1.0
        cpu_factor = 1.0 + profile.cpu_scaling * weight * (hardware.cpu_cores / 8.0)
        score *= cpu_factor
        reasons.append(f"escala con {hardware.cpu_cores} núcleos (x{cpu_factor:.2f})")

    # Aporte de la GPU, proporcional a la VRAM útil.
    if hardware.can_run_on_gpu and Capability.GPU_OFFLOAD in profile.capabilities:
        budget = max(_vram_budget(hardware, profile), 0)
        score *= 1.0 + min(budget / 8000.0, 1.5)
        reasons.append(f"{budget} MB de VRAM útiles")

    # Corrección por telemetría observada.
    if (stats := store.stats(profile.name)) and stats.count >= 3:
        if stats.rtf:
            # En audio la métrica es el RTF: 0,05 significa sintetizar 20x más
            # rápido que la reproducción. Menos es mejor, al revés que tok/s.
            observed = 1.0 / max(stats.rtf, 0.001) / 10.0
            score = score * 0.4 + observed * 0.6
            reasons.append(f"medido: RTF {stats.rtf} en {stats.count} muestras")
        elif stats.tokens_per_second:
            observed = 1.0 + stats.tokens_per_second / 50.0
            score = score * 0.4 + observed * 0.6
            reasons.append(f"medido: {stats.tokens_per_second} tok/s en {stats.count} muestras")
        if stats.failures:
            penalty = 1.0 / (1.0 + stats.failures)
            score *= penalty
            reasons.append(f"{stats.failures} fallos previos")

    return round(score, 3), "; ".join(reasons)


#: Tamaño de lote de referencia por carga, calibrado para 8 núcleos. La traducción
#: admite lotes grandes porque sus secuencias son de ~50 tokens; el TTS
#: autorregresivo no, porque cada muestra arrastra su propia caché KV.
_BASE_BATCH: dict[WorkloadClass, int] = {
    WorkloadClass.SEQ2SEQ: 16,
    WorkloadClass.TTS_FEEDFORWARD: 4,
    WorkloadClass.TTS_AUTOREGRESSIVE: 2,
    WorkloadClass.ASR: 4,
    WorkloadClass.LLM_DECODE: 8,
}


def execution_parameters(
    workload: WorkloadClass,
    techniques: tuple[str, ...],
    hardware: HardwareProfile,
    *,
    quality_level: int = 0,
) -> dict[str, object]:
    """Traduce un plan a los números que el pipeline necesita de verdad.

    Sin esto el plan sería una lista de nombres bonitos: aquí es donde "batching
    activado" se convierte en un tamaño de lote que sale de la máquina medida y
    no de una constante escrita a mano.

    `quality_level` es lo que el tuner ha decidido tras medir. Se aplica a la
    **memoria en vuelo** —lote y paralelismo— y no a cómo suena la voz: es la
    respuesta correcta al motivo por el que el tuner sube de nivel casi siempre,
    que es un fallo por falta de memoria. Cada nivel parte por dos.
    """
    batching = any("batching" in name for name in techniques)

    if not batching:
        batch_size = 1
    else:
        # Escala con núcleos pero con tope: pasado 2x el lote deja de amortizar y
        # empieza a costar memoria y latencia del primer resultado.
        factor = min(hardware.cpu_cores / 8.0, 2.0)
        batch_size = max(1, int(_BASE_BATCH[workload] * factor))

    relief = 2 ** max(quality_level, 0)
    return {
        "batch_size": max(1, batch_size // relief),
        "workers": max(1, hardware.tts_workers // relief),
    }


def applicable_techniques(
    profile: BackendProfile,
    workload: WorkloadClass,
    *,
    extra_capabilities: frozenset[Capability] = frozenset(),
) -> list[Technique]:
    """Intersección entre lo que la carga admite y lo que el backend ofrece."""
    capabilities = profile.capabilities | extra_capabilities
    found = [t for t in catalog.CATALOG if t.is_applicable(workload, capabilities)]

    # Una técnica superada por otra activa no se aplica dos veces
    # (int8 sobra si hay int4; batching estático sobra si hay continuo).
    active = {t.name for t in found}
    return [t for t in found if catalog.SUPERSEDED_BY.get(t.name) not in active]


def plan(
    workload: WorkloadClass,
    *,
    backend: str | None = None,
    objective: Objective = Objective.BALANCED,
    quality_level: int = 0,
    context_tokens: int = 2048,
    concurrent: bool = False,
    hardware: HardwareProfile | None = None,
    available: dict[str, bool] | None = None,
    store: TelemetryStore | None = None,
) -> Plan:
    """Produce el plan de ejecución para una carga.

    Con `backend` se planifica *para un motor ya elegido* y solo se negocian las
    técnicas. Es el camino de TTS: quién sintetiza lo decide `tts.selector` por
    idioma, naturalidad y licencia, y que dos componentes eligieran motor con
    criterios distintos sería una contradicción esperando a ocurrir.
    """
    hardware = hardware or detect()
    candidates = evaluate_backends(workload, hardware=hardware, available=available, store=store)
    viable = [c for c in candidates if c.viable]

    if backend is not None:
        viable = [c for c in viable if c.profile.name == backend]

    if not viable:
        rejected = "; ".join(f"{c.profile.name}: {c.reason}" for c in candidates) or "ninguno"
        target = f" con backend '{backend}'" if backend else ""
        raise NoBackendViable(
            f"Ningún backend viable para '{workload.value}'{target}. Descartados -> {rejected}"
        )

    best = viable[0]
    chosen = applicable_techniques(best.profile, workload)

    # Filtros contextuales: una técnica aplicable no siempre es rentable.
    chosen = [t for t in chosen if _is_worth_it(t, workload, context_tokens, concurrent, objective)]

    # Degradación por nivel de calidad: el tuner sube el nivel para ganar
    # velocidad, lo que habilita técnicas con quality_delta negativo.
    if quality_level == 0:
        chosen = [t for t in chosen if t.quality_delta >= -0.03]

    chosen.sort(key=lambda t: t.expected_speedup, reverse=True)
    names = tuple(t.name for t in chosen)

    return Plan(
        backend=best.profile.name,
        workload=workload,
        techniques=names,
        quality_level=quality_level,
        parameters={
            "objective": objective.value,
            "context_tokens": context_tokens,
            "license": best.profile.license,
            **execution_parameters(workload, names, hardware, quality_level=quality_level),
        },
        reason=f"{best.profile.name} (puntuación {best.score}): {best.reason}",
    )


def _is_worth_it(
    technique: Technique,
    workload: WorkloadClass,
    context_tokens: int,
    concurrent: bool,
    objective: Objective,
) -> bool:
    """Reglas de rentabilidad que no caben en el modelo declarativo."""
    # La atención dispersa solo compensa por encima de ~8k: bajo eso, construir
    # la máscara cuesta más de lo que ahorra.
    if technique.name == "sparse_attention" and context_tokens < 8192:
        return False
    # La compresión de caché KV no tiene sentido con contexto corto.
    if technique.name == "kv_cache_compression" and context_tokens < 4096:
        return False
    # El batching necesita varias unidades de trabajo, pero no necesariamente
    # varias *peticiones*: un capítulo ya trae sus párrafos troceados, y ahí es
    # donde esta técnica rinde de verdad (§2 del análisis).
    if technique.needs_concurrency and not (concurrent or workload.batches_offline):
        return False
    # En modo calidad no se aceptan técnicas que degraden de forma apreciable.
    return not (objective is Objective.QUALITY and technique.quality_delta < -0.03)
