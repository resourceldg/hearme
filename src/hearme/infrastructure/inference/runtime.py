"""Puente entre el planificador y el pipeline.

El pipeline no debe razonar sobre capacidades ni puntuaciones: pide un plan para
el motor que *ya* ha elegido y recibe números.

La regla que gobierna este módulo es que **optimizar no puede romper la
conversión**. Un motor de un plugin de terceros no está en el registro, y un
subsistema de optimización que abortara por eso sería mucho peor que uno que no
optimiza: se devuelve un plan neutro y el pipeline sigue con sus valores por
defecto.
"""

from __future__ import annotations

import logging

from hearme.domain.inference import Measurement, Objective, Plan, WorkloadClass
from hearme.infrastructure.hardware import HardwareProfile, detect
from hearme.infrastructure.inference import planner
from hearme.infrastructure.inference.backends import PROFILES
from hearme.infrastructure.inference.telemetry import TelemetryStore, telemetry
from hearme.infrastructure.inference.tuner import AdaptiveTuner, tuner

logger = logging.getLogger(__name__)


def objective_for(quality: str) -> Objective:
    """Traduce la calidad pedida por el usuario al objetivo de optimización."""
    return Objective.LATENCY if quality == "draft" else Objective.QUALITY


def workload_for(backend: str, *, default: WorkloadClass) -> WorkloadClass:
    """Clase de carga de un motor conocido; `default` si no está registrado."""
    profile = PROFILES.get(backend)
    if profile is None or not profile.workloads:
        return default
    if default in profile.workloads:
        return default
    return next(iter(profile.workloads))


def neutral_plan(
    backend: str, workload: WorkloadClass, reason: str, *, quality_level: int = 0
) -> Plan:
    """Plan sin técnicas: el pipeline usará sus valores por defecto.

    `batch_size=1` no significa "no agrupes", significa "el planificador no
    opina": quien lo consume decide si conserva su propio valor.
    """
    return Plan(
        backend=backend,
        workload=workload,
        techniques=(),
        quality_level=quality_level,
        parameters={"batch_size": 1, "workers": 0},
        reason=reason,
    )


def plan_for(
    backend: str,
    *,
    default_workload: WorkloadClass,
    quality: str = "high",
    concurrent: bool = False,
    hardware: HardwareProfile | None = None,
    available: dict[str, bool] | None = None,
    quality_level: int | None = None,
    adaptive: AdaptiveTuner | None = None,
) -> Plan:
    """Plan de ejecución para un motor ya elegido. Nunca lanza.

    `quality_level` a `None` significa "pregúntaselo al tuner": es el eslabón
    que convierte lo medido en la ejecución anterior en cómo se ejecuta esta.
    """
    workload = workload_for(backend, default=default_workload)
    if quality_level is None:
        quality_level = (adaptive or tuner).level(workload)
    try:
        return planner.plan(
            workload,
            backend=backend,
            objective=objective_for(quality),
            concurrent=concurrent,
            hardware=hardware or detect(),
            available=available,
            quality_level=quality_level,
        )
    except planner.NoBackendViable as exc:
        # Caso normal, no excepcional: motor de plugin, o registrado pero
        # descartado en esta máquina. Se sigue sin optimizar.
        logger.debug("sin plan para '%s': %s", backend, exc)
        return neutral_plan(
            backend, workload, f"sin perfil aplicable: {exc}", quality_level=quality_level
        )


def _observe(
    measurement: Measurement, store: TelemetryStore | None, adaptive: AdaptiveTuner | None
) -> Measurement:
    """Una medición alimenta a los dos: al histórico y al bucle de control.

    El almacén corrige la puntuación de motores entre ejecuciones; el tuner
    decide el nivel de degradación de la siguiente. Registrar solo en uno de los
    dos dejaba el bucle abierto, que es como estaba antes.
    """
    (store or telemetry).record(measurement)
    (adaptive or tuner).observe(measurement)
    return measurement


def record_audio(
    backend: str,
    workload: WorkloadClass,
    *,
    elapsed_s: float,
    audio_s: float,
    plan: Plan | None = None,
    store: TelemetryStore | None = None,
    adaptive: AdaptiveTuner | None = None,
) -> Measurement:
    """Registra una síntesis. La métrica de audio es el RTF, no los tokens/s."""
    return _observe(
        Measurement(
            backend=backend,
            workload=workload,
            total_ms=elapsed_s * 1000,
            rtf=elapsed_s / audio_s if audio_s > 0 else 0.0,
            techniques=plan.techniques if plan else (),
        ),
        store,
        adaptive,
    )


def record_failure(
    backend: str,
    workload: WorkloadClass,
    error: str,
    *,
    store: TelemetryStore | None = None,
    adaptive: AdaptiveTuner | None = None,
) -> Measurement:
    return _observe(
        Measurement(backend=backend, workload=workload, ok=False, error=error), store, adaptive
    )
