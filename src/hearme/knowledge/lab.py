"""Laboratorio de narración y benchmark abierto.

## El laboratorio

Probar estilos de narración exige textos. La tentación evidente es usar los que
la gente ya ha subido: están ahí, son variados y son reales. **No se hace, y el
código lo impide.**

Un texto que alguien subió para escucharlo no es material de laboratorio. Usarlo
para experimentar sería exactamente la traición que el módulo de privacidad
existe para evitar, por muy buena que fuera la intención.

El laboratorio solo acepta textos de un registro con procedencia declarada:
dominio público verificado, o sintéticos generados para el caso. `TextSource`
lleva la licencia y el origen, y `NarrationLab.load()` rechaza cualquier cosa que
no venga de ahí. No es una convención documentada: es una comprobación que salta.

## El benchmark

Sin una medida compartida, «esta narración es mejor» es una opinión y las
discusiones no terminan nunca. Un benchmark abierto convierte a la comunidad en
algo más que una fuente de datos: la hace **codefinidora de qué es una buena
narración**, que es una forma mucho más profunda de participar.

Se mide sobre pasajes de dominio público con anotaciones de referencia, y se
publican tres familias de métrica que no miden lo mismo a propósito:

- **Estructural**: ¿coinciden las pausas con los límites sintácticos? Automática
  y barata, pero un texto puede acertar todas las pausas y sonar plano.
- **Preferencia**: en comparación por pares, ¿se prefiere a la referencia?
  Necesita personas, y es la que de verdad importa.
- **Accesibilidad**: comprensión y fatiga en escucha larga, medidas con quienes
  usan esto de verdad. La más cara y la que más suele faltar en los benchmarks
  de voz, que optimizan «naturalidad» para oyentes sin dificultades.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from hearme.narration.director import NarrationDirector
from hearme.narration.score import NarrationScore, ProsodyMark


class Provenance(StrEnum):
    """De dónde viene un texto. Solo dos valores son admisibles en el laboratorio."""

    #: Dominio público verificado, con la fuente citada.
    PUBLIC_DOMAIN = "public_domain"
    #: Generado para pruebas. No procede de ninguna persona.
    SYNTHETIC = "synthetic"
    #: Aportado por alguien para escucharlo. **Prohibido en el laboratorio.**
    USER_PRIVATE = "user_private"


class LabError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class TextSource:
    """Un texto admisible, con su procedencia acreditada."""

    id: str
    text: str
    language: str
    provenance: Provenance
    #: Obra y edición, o cómo se generó si es sintético. Sin esto no hay
    #: verificación posible: «es de dominio público» sin fuente es una promesa.
    attribution: str
    register: str = "neutral"

    def __post_init__(self) -> None:
        if self.provenance is Provenance.USER_PRIVATE:
            raise LabError(
                "el material privado de una persona no entra en el laboratorio. "
                "Se subió para escucharlo, no para experimentar con él."
            )
        if not self.attribution.strip():
            raise LabError(
                f"'{self.id}' no acredita su procedencia: sin fuente citada no se "
                "puede verificar que sea de dominio público"
            )


@dataclass(slots=True)
class NarrationLab:
    """Banco de pruebas. Solo admite lo que puede admitir."""

    sources: dict[str, TextSource] = field(default_factory=dict)

    def load(self, source: TextSource) -> None:
        """Registra un texto. La validación ya ocurrió al construir `TextSource`."""
        self.sources[source.id] = source

    def try_style(
        self, director: NarrationDirector, source_id: str, **kwargs: Any
    ) -> NarrationScore:
        """Aplica un director a un texto del laboratorio y devuelve su partitura."""
        fuente = self.sources.get(source_id)
        if fuente is None:
            raise LabError(f"'{source_id}' no está en el laboratorio")
        return director.direct(fuente.text, language=fuente.language, **kwargs)

    def compare(
        self, a: NarrationDirector, b: NarrationDirector, source_id: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Compara dos directores sobre el mismo texto.

        Devuelve las diferencias en crudo, no un ganador: quién gana lo deciden
        las personas del panel, no una heurística que ya sabe lo que quiere ver.
        """
        score_a = self.try_style(a, source_id, **kwargs)
        score_b = self.try_style(b, source_id, **kwargs)
        return {
            "source": source_id,
            "a": {"director": a.name, "version": a.version, "marks": len(score_a.marks)},
            "b": {"director": b.name, "version": b.version, "marks": len(score_b.marks)},
            "divergence": _divergence(score_a, score_b),
        }


def _divergence(a: NarrationScore, b: NarrationScore) -> dict[str, float]:
    """Cuánto se separan dos partituras. Descriptivo, no valorativo."""

    def resumen(score: NarrationScore, campo: str) -> float:
        valores = [getattr(m, campo) for m in score.marks if getattr(m, campo) is not None]
        return sum(valores) / len(valores) if valores else 0.0

    return {
        campo: round(abs(resumen(a, campo) - resumen(b, campo)), 4)
        for campo in ("pause_after_ms", "rate", "emphasis")
    }


# --- benchmark ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BenchmarkItem:
    """Un pasaje con su prosodia de referencia, anotada por la comunidad."""

    source: TextSource
    #: Marcas de referencia. Idealmente extraídas de lecturas humanas medidas,
    #: no de opiniones: es la diferencia entre «así sonó» y «así debería sonar».
    reference: tuple[ProsodyMark, ...]
    annotators: int = 0

    @property
    def is_reliable(self) -> bool:
        """Un solo anotador no es una referencia, es una preferencia."""
        return self.annotators >= 3


@dataclass(slots=True)
class NarrationBenchmark:
    """Benchmark abierto. Textos públicos, anotaciones comunitarias, métricas claras."""

    name: str = "hearme-bench"
    version: str = "0.1"
    items: list[BenchmarkItem] = field(default_factory=list)
    #: Tolerancia al comparar una pausa con su referencia. 150 ms es
    #: aproximadamente el umbral por debajo del cual una diferencia de silencio
    #: deja de percibirse al escuchar de corrido.
    pause_tolerance_ms: int = 150

    def add(self, item: BenchmarkItem) -> None:
        if item.source.provenance is Provenance.USER_PRIVATE:
            raise LabError("el benchmark es público: no puede contener material privado")
        self.items.append(item)

    def evaluate(self, director: NarrationDirector, **kwargs: Any) -> dict[str, Any]:
        """Métrica estructural, automática. Es una parte, no el veredicto.

        Un director puede acertar el 100% de las pausas y sonar a metrónomo. Por
        eso el informe declara explícitamente lo que **no** ha medido: sin esa
        advertencia, un número alto se lee como «suena bien» y no lo es.
        """
        fiables = [i for i in self.items if i.is_reliable]
        if not fiables:
            return {
                "director": director.name,
                "error": "sin ítems fiables: hacen falta al menos 3 anotadores por pasaje",
            }

        aciertos = fallos = 0
        for item in fiables:
            score = director.direct(item.source.text, language=item.source.language, **kwargs)
            for referencia in item.reference:
                if referencia.pause_after_ms is None:
                    continue
                obtenida = score.resolve(referencia.start, referencia.end)
                propuesta = (obtenida.pause_after_ms if obtenida else None) or 0
                if abs(propuesta - referencia.pause_after_ms) <= self.pause_tolerance_ms:
                    aciertos += 1
                else:
                    fallos += 1

        total = aciertos + fallos
        return {
            "benchmark": f"{self.name}/{self.version}",
            "director": f"{director.name}/{director.version}",
            "items_evaluated": len(fiables),
            "items_skipped": len(self.items) - len(fiables),
            "pause_accuracy": round(aciertos / total, 4) if total else 0.0,
            "comparisons": total,
            "not_measured": [
                "preferencia humana en comparación por pares",
                "fatiga de escucha en sesiones largas",
                "comprensión en personas con dislexia o baja visión",
            ],
            "caveat": (
                "métrica estructural: mide coincidencia con la referencia, no que "
                "suene bien. Una puntuación alta no sustituye a la evaluación con personas."
            ),
        }

    def to_json(self) -> str:
        return json.dumps(
            {
                "format": "hearme.benchmark.v1",
                "name": self.name,
                "version": self.version,
                "published_at": datetime.now(UTC).isoformat(),
                "license": "CC0-1.0",
                "items": [
                    {
                        "id": i.source.id,
                        "language": i.source.language,
                        "provenance": i.source.provenance.value,
                        "attribution": i.source.attribution,
                        "register": i.source.register,
                        "annotators": i.annotators,
                        "reference_marks": len(i.reference),
                    }
                    for i in self.items
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
