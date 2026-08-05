"""Tuner adaptativo: mantiene la mejor relación calidad/velocidad.

Se eligió un controlador de **niveles discretos con histéresis** en lugar de uno
continuo (PID). Razón práctica, no teórica: en TTS un parámetro que oscila se
*oye*, y una voz que cambia de timbre a mitad de capítulo es peor que una voz
uniformemente algo peor. Ver docs/ANALISIS-INFERENCIA.md §3.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from hearme.domain.inference import Measurement, Objective, WorkloadClass

logger = logging.getLogger(__name__)

#: Nivel 0 = máxima calidad. Subir nivel = más rápido y algo peor.
MAX_LEVEL = 3

#: Presupuesto de latencia por objetivo, en ms (TTFT para LLM).
_BUDGET_MS: dict[Objective, float] = {
    Objective.LATENCY: 400.0,
    Objective.BALANCED: 1500.0,
    Objective.QUALITY: 8000.0,
}

#: Cuántas mediciones consecutivas fuera de presupuesto antes de mover el nivel.
#: La histéresis evita bailar de nivel por un pico puntual.
_PATIENCE_UP = 3  # degradar (reacción rápida: el usuario está esperando)
_PATIENCE_DOWN = 8  # recuperar calidad (reacción lenta: no arriesgar)


@dataclass(slots=True)
class TunerState:
    level: int = 0
    over_budget: int = 0
    under_budget: int = 0
    #: Realimentación humana acumulada. Es la única señal real de calidad.
    votes_up: int = 0
    votes_down: int = 0


@dataclass(slots=True)
class AdaptiveTuner:
    """Ajusta el nivel de calidad por clase de carga."""

    objective: Objective = Objective.BALANCED
    _states: dict[WorkloadClass, TunerState] = field(default_factory=dict)

    def state(self, workload: WorkloadClass) -> TunerState:
        return self._states.setdefault(workload, TunerState())

    def level(self, workload: WorkloadClass) -> int:
        return self.state(workload).level

    def observe(self, measurement: Measurement) -> int:
        """Registra una medición y devuelve el nivel de calidad resultante."""
        state = self.state(measurement.workload)

        if not measurement.ok:
            # Un fallo suele ser falta de memoria: degradar libera memoria.
            state.level = min(state.level + 1, self._ceiling(state))
            state.over_budget = state.under_budget = 0
            logger.info("fallo detectado; nivel de calidad -> %d", state.level)
            return state.level

        budget = _BUDGET_MS[self.objective]
        latency = self._latency_signal(measurement)

        if latency > budget:
            state.over_budget += 1
            state.under_budget = 0
        elif latency < budget * 0.5:
            # Solo se recupera calidad con holgura clara, no rozando el umbral.
            state.under_budget += 1
            state.over_budget = 0
        else:
            state.over_budget = state.under_budget = 0

        if state.over_budget >= _PATIENCE_UP and state.level < self._ceiling(state):
            state.level += 1
            state.over_budget = 0
            logger.info(
                "latencia %.0f ms > presupuesto %.0f ms; nivel -> %d",
                latency,
                budget,
                state.level,
            )
        elif state.under_budget >= _PATIENCE_DOWN and state.level > 0:
            state.level -= 1
            state.under_budget = 0
            logger.info("holgura sostenida; nivel -> %d", state.level)

        return state.level

    @staticmethod
    def _latency_signal(measurement: Measurement) -> float:
        """Qué latencia vigilar según el tipo de carga.

        En audio el TTFT es irrelevante: lo que importa es si la síntesis va más
        rápida que la reproducción (RTF < 1). Se normaliza a ms comparables.
        """
        if measurement.rtf:
            return measurement.rtf * 1000
        return measurement.ttft_ms

    def vote(self, workload: WorkloadClass, *, positive: bool) -> None:
        """Realimentación del usuario sobre la calidad percibida.

        Es la única señal de calidad que no es una estimación. Un voto negativo
        recupera calidad de inmediato aunque la latencia sea aceptable: la
        percepción del usuario manda sobre el presupuesto.
        """
        state = self.state(workload)
        if positive:
            state.votes_up += 1
            return

        state.votes_down += 1
        if state.level > 0:
            state.level -= 1
            state.under_budget = state.over_budget = 0
            logger.info("voto negativo del usuario; nivel -> %d", state.level)

    @staticmethod
    def _ceiling(state: TunerState) -> int:
        """Hasta dónde se permite degradar.

        Cada voto negativo lo baja un nivel: si el usuario ya ha dicho que no le
        gusta cómo suena, el sistema no puede volver a degradar hasta donde
        estaba por mucho que le apriete el presupuesto de latencia. La percepción
        humana manda sobre la métrica.
        """
        return max(0, MAX_LEVEL - state.votes_down)

    def perceived_quality(self, workload: WorkloadClass, base: float) -> float:
        """Estimación compuesta de calidad percibida, en 0..1.

        Explícitamente una *estimación*: combina la calidad declarada del motor,
        la penalización por degradación y el voto humano, que pesa más cuanto
        más se acumula.
        """
        state = self.state(workload)
        estimate = base - state.level * 0.06

        total_votes = state.votes_up + state.votes_down
        if total_votes:
            human = state.votes_up / total_votes
            # El peso humano crece con la evidencia y se satura en 0.6.
            weight = min(0.6, total_votes / 20.0)
            estimate = estimate * (1 - weight) + human * weight

        return round(max(0.0, min(1.0, estimate)), 3)


#: Tuner por defecto de la aplicación.
tuner = AdaptiveTuner()
