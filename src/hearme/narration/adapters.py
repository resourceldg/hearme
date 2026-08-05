"""De la partitura a los mandos de cada motor.

Aquí es donde el desacoplamiento deja de ser una intención y se vuelve código.
El director escribe en unidades neutras; cada motor entiende las suyas y ninguno
las entiende todas. Este módulo traduce lo que se puede y **declara lo que no**.

Esa declaración importa más de lo que parece. Un sistema que descarta en
silencio la mitad de la partitura parece funcionar: suena, no falla, nadie
protesta. Y mientras tanto la comunidad anota tono durante meses sin que se oiga
nunca, porque el motor de turno no sabe hacerlo. `RenderPlan.dropped` existe
para que esa pérdida sea visible desde el primer día.
"""

from __future__ import annotations

from dataclasses import dataclass

from hearme.narration.score import ProsodyMark

#: Dimensiones prosódicas que puede tener una marca.
DIMENSIONS = ("pause", "emphasis", "rate", "pitch")


@dataclass(frozen=True, slots=True)
class RenderPlan:
    """Lo que un motor concreto va a aplicar, y lo que se ha quedado por el camino."""

    pause_after_ms: int = 0
    emphasis: float = 1.0
    rate: float = 1.0
    pitch_semitones: float = 0.0
    #: Dimensiones que la partitura pedía y este motor no sabe respetar.
    dropped: tuple[str, ...] = ()

    @property
    def is_faithful(self) -> bool:
        return not self.dropped


@dataclass(frozen=True, slots=True)
class EngineCapabilities:
    """Qué dimensiones prosódicas sabe respetar un motor.

    Se declara por motor en vez de preguntárselo en tiempo de ejecución porque es
    información estable y queremos poder razonar sobre ella —y avisar al que
    aporta— sin tener el motor instalado.
    """

    name: str
    rate: bool = False
    emphasis: bool = False
    pitch: bool = False
    #: Casi cualquier motor admite pausas: se insertan como silencio al montar.
    pause: bool = True

    def supports(self, dimension: str) -> bool:
        return bool(getattr(self, dimension, False))

    def plan(self, mark: ProsodyMark | None) -> RenderPlan:
        """Traduce una marca a mandos concretos, anotando lo que se pierde."""
        if mark is None:
            return RenderPlan()

        pedido = {
            "pause": mark.pause_after_ms,
            "emphasis": mark.emphasis,
            "rate": mark.rate,
            "pitch": mark.pitch_semitones,
        }
        # Solo cuenta como pérdida lo que la partitura pedía de verdad: un motor
        # sin tono no «pierde» nada en un texto donde nadie anotó tono.
        neutro = {"pause": 0, "emphasis": 1.0, "rate": 1.0, "pitch": 0.0}
        dropped = tuple(
            dim
            for dim in DIMENSIONS
            if not self.supports(dim) and pedido[dim] is not None and pedido[dim] != neutro[dim]
        )

        return RenderPlan(
            pause_after_ms=int(pedido["pause"] or 0) if self.pause else 0,
            emphasis=float(pedido["emphasis"] or 1.0) if self.emphasis else 1.0,
            rate=float(pedido["rate"] or 1.0) if self.rate else 1.0,
            pitch_semitones=float(pedido["pitch"] or 0.0) if self.pitch else 0.0,
            dropped=dropped,
        )


#: Piper aplica velocidad (`length_scale`) y volumen; no expone tono.
PIPER = EngineCapabilities(name="piper", rate=True, emphasis=True, pitch=False)

#: Kokoro acepta `speed` y admite ganancia sobre las muestras; tampoco tono.
KOKORO = EngineCapabilities(name="kokoro", rate=True, emphasis=True, pitch=False)

#: Referencia para motores con SSML completo. Es el objetivo al que apunta el
#: esquema de la partitura: si un motor lo cumple, no se pierde nada anotado.
SSML_FULL = EngineCapabilities(name="ssml", rate=True, emphasis=True, pitch=True)

_REGISTRY: dict[str, EngineCapabilities] = {c.name: c for c in (PIPER, KOKORO, SSML_FULL)}


def capabilities_for(engine_name: str) -> EngineCapabilities:
    """Capacidades declaradas de un motor.

    Un motor desconocido —el de un plugin de terceros— se asume conservador: solo
    pausas. Suena plano pero nunca miente sobre lo que ha aplicado, que es
    justo el error que este módulo existe para evitar.
    """
    return _REGISTRY.get(engine_name, EngineCapabilities(name=engine_name))


def register_capabilities(capabilities: EngineCapabilities) -> None:
    """Permite a un plugin declarar lo que su motor sabe hacer."""
    _REGISTRY[capabilities.name] = capabilities
