"""Reputación: cómo se convierten muchas opiniones en una recomendación honesta.

## El problema que resuelve

Una voz con **una** valoración de 5 estrellas no es mejor que otra con **cuarenta**
de media 4,3. La media aritmética dice que sí, y por eso la media aritmética es
una mala forma de ordenar cosas valoradas por personas: premia lo poco valorado.

Peor aún en un proyecto pequeño: las primeras semanas todo tendrá dos o tres
votos, y quien pase por ahí verá recomendaciones que cambian de arriba abajo
cada vez que alguien pulsa una estrella.

## La solución: encogimiento hacia la media

Se usa una **media bayesiana**, que es la herramienta estándar para esto:

    puntuación = (C · m + Σ valoraciones) / (C + n)

donde `m` es la media previa —lo que se supone de una voz de la que no se sabe
nada— y `C` es cuántas valoraciones hacen falta para empezar a fiarse.

Con pocos votos, el resultado se pega a `m` y la voz no destaca ni se hunde. Con
muchos, `C · m` se vuelve irrelevante y manda la evidencia real. **No hay que
elegir un umbral arbitrario**: la transición es continua y no hay un momento en
que una voz «pasa a contar».

Para el pulgar se usa el **límite inferior del intervalo de Wilson**, que
responde a la pregunta correcta: «dado lo que he visto, ¿cuál es la peor
proporción de aciertos que es razonable suponer?». Con 1 de 1 no da 100%, da
cerca del 20%: exactamente la humildad que hace falta.

## Por qué la reputación es por sujeto y no solo por voz

Una valoración se emite sobre `(motor, voz, estilo, idioma)` y se propaga hacia
arriba. Así se distingue «esta voz es mala» de «esta voz **con este estilo** es
mala», que son cosas distintas y una hunde injustamente a la otra.

## Explicable siempre

Toda puntuación puede decir de qué está hecha: cuántas valoraciones, de qué
tipo, qué etiquetas se repiten y cuánta confianza hay. Una recomendación que no
se puede interrogar es una imposición con buenos modales.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from hearme.feedback.signals import Feedback, Sentiment, Subject, Tag

#: Media previa: la puntuación que se supone de algo sin valoraciones. 3,5 y no
#: 3,0 porque las voces del catálogo ya pasaron un filtro —están instaladas y
#: funcionan— y arrancar en el punto medio absoluto las castigaría de más.
PRIOR_MEAN = 3.5

#: Cuántas valoraciones hacen falta para que la evidencia pese tanto como la
#: media previa. Con 10, cinco votos mueven la puntuación a mitad de camino.
#: Subirlo hace el sistema más conservador; bajarlo, más reactivo y más ruidoso.
PRIOR_WEIGHT = 10.0

#: Confianza del intervalo de Wilson. 1,96 = 95%, que es lo convencional.
WILSON_Z = 1.96

#: Por debajo de esto la puntuación se muestra como provisional. No cambia el
#: cálculo: cambia lo que se le promete a quien lee.
CONFIDENT_SAMPLE = 8

#: Veces que puede contar la misma persona sobre el mismo sujeto. Sin tope, quien
#: valore cuarenta veces su voz favorita decide por todos los demás.
MAX_PER_CONTRIBUTOR = 3


def bayesian_average(
    ratings: list[float], *, prior_mean: float = PRIOR_MEAN, prior_weight: float = PRIOR_WEIGHT
) -> float:
    """Media encogida hacia la previa. Es lo que impide que un voto mande."""
    if not ratings:
        return prior_mean
    return (prior_weight * prior_mean + sum(ratings)) / (prior_weight + len(ratings))


def wilson_lower_bound(positive: int, total: int, *, z: float = WILSON_Z) -> float:
    """Cota inferior del intervalo de Wilson para una proporción.

    Con 1 de 1 devuelve ~0,21, no 1,0. Esa humildad es justo el punto: es la peor
    proporción compatible con lo observado, y ordenar por ella evita que lo poco
    valorado suba por suerte.
    """
    if total <= 0:
        return 0.0
    fraccion = positive / total
    denominador = 1 + z**2 / total
    centro = fraccion + z**2 / (2 * total)
    margen = z * math.sqrt((fraccion * (1 - fraccion) + z**2 / (4 * total)) / total)
    return max(0.0, (centro - margen) / denominador)


@dataclass(frozen=True, slots=True)
class TagSummary:
    tag: Tag
    count: int
    share: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "tag": self.tag.value,
            "label": self.tag.label,
            "count": self.count,
            "share": round(self.share, 3),
            "sentiment": self.tag.sentiment.value,
        }


@dataclass(frozen=True, slots=True)
class Reputation:
    """Lo que se sabe de un sujeto, con su nivel de confianza."""

    subject: Subject
    #: Media bayesiana, 1..5.
    score: float
    #: Cota de Wilson sobre los pulgares, 0..1.
    approval: float
    samples: int
    contributors: int
    stars_given: int
    thumbs_given: int
    comments_given: int
    tags: tuple[TagSummary, ...] = ()

    @property
    def is_confident(self) -> bool:
        return self.samples >= CONFIDENT_SAMPLE

    @property
    def top_tags(self) -> tuple[TagSummary, ...]:
        return self.tags[:3]

    def explain(self) -> str:
        """De qué está hecha esta puntuación, en lenguaje llano.

        Es la respuesta a «¿por qué me recomiendas esto?». Sin ella, una
        recomendación es una imposición con buenos modales.
        """
        if not self.samples:
            return "Todavía nadie la ha valorado, así que se parte de una puntuación neutra."

        piezas = []
        if self.stars_given:
            piezas.append(f"{self.stars_given} con estrellas")
        if self.thumbs_given:
            piezas.append(f"{self.thumbs_given} con pulgar")
        if self.comments_given:
            piezas.append(f"{self.comments_given} con comentario")

        plural_v = "ón" if self.samples == 1 else "ones"
        plural_p = "" if self.contributors == 1 else "s"
        base = (
            f"{self.score:.1f} de 5, a partir de {self.samples} valoraci{plural_v}"
            f" de {self.contributors} persona{plural_p}"
            f" ({', '.join(piezas)})."
        )

        if not self.is_confident:
            base += (
                f" Son pocas todavía: hasta {CONFIDENT_SAMPLE} la puntuación se mantiene"
                " cerca de la media para no exagerar."
            )

        if self.top_tags:
            etiquetas = ", ".join(f"{t.tag.label} ({t.count})" for t in self.top_tags)
            base += f" Lo más repetido: {etiquetas}."

        return base

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject.to_dict(),
            "score": round(self.score, 2),
            "approval": round(self.approval, 3),
            "samples": self.samples,
            "contributors": self.contributors,
            "confident": self.is_confident,
            "tags": [t.to_dict() for t in self.tags],
            "explanation": self.explain(),
        }


@dataclass(slots=True)
class ReputationIndex:
    """Acumula valoraciones y responde puntuaciones por sujeto."""

    entries: dict[str, list[Feedback]] = field(default_factory=dict)

    def add(self, feedback: Feedback) -> None:
        """Registra una valoración en su sujeto y en todos los más generales."""
        for sujeto in feedback.subject.generalize():
            self.entries.setdefault(sujeto.key, []).append(feedback)

    def _limited(self, feedbacks: list[Feedback]) -> list[Feedback]:
        """Aplica el tope por persona.

        Se conservan las primeras de cada quien y se descartan las siguientes: la
        alternativa —quedarse con las últimas— premiaría a quien insiste, que es
        justo lo que el tope quiere evitar.
        """
        vistos: Counter[str] = Counter()
        salida = []
        for f in feedbacks:
            if vistos[f.contributor] < MAX_PER_CONTRIBUTOR:
                salida.append(f)
                vistos[f.contributor] += 1
        return salida

    def of(self, subject: Subject) -> Reputation:
        """Reputación de un sujeto. Sin valoraciones devuelve la previa neutra."""
        crudas = self.entries.get(subject.key, [])
        feedbacks = self._limited(crudas)

        puntuaciones = [f.implicit_stars for f in feedbacks if f.implicit_stars is not None]
        pulgares = [f.thumbs_up for f in feedbacks if f.thumbs_up is not None]

        contador: Counter[Tag] = Counter()
        for f in feedbacks:
            # Una etiqueta por valoración: repetir la idea en la misma frase no
            # la hace más cierta.
            for match in {t.tag for t in f.tags}:
                contador[match] += 1

        total_etiquetas = sum(contador.values()) or 1
        etiquetas = tuple(
            TagSummary(tag=t, count=n, share=n / total_etiquetas) for t, n in contador.most_common()
        )

        return Reputation(
            subject=subject,
            score=bayesian_average([p for p in puntuaciones if p is not None]),
            approval=wilson_lower_bound(sum(1 for p in pulgares if p), len(pulgares)),
            samples=len(feedbacks),
            contributors=len({f.contributor for f in feedbacks}),
            stars_given=sum(1 for f in feedbacks if f.stars is not None),
            thumbs_given=len(pulgares),
            comments_given=sum(1 for f in feedbacks if f.comment.strip()),
            tags=etiquetas,
        )

    def best_for(
        self, candidates: list[Subject], *, prefer_tag: Tag | None = None
    ) -> tuple[Subject, Reputation] | None:
        """Mejor candidato según la evidencia, opcionalmente sesgado a una etiqueta.

        `prefer_tag` permite pedir «la que más gente describe como buena para
        novela» en vez de «la mejor valorada en general», que son preguntas
        distintas y la segunda no responde a la primera.
        """
        if not candidates:
            return None

        def clave(sujeto: Subject) -> tuple[float, float]:
            reputacion = self.of(sujeto)
            afinidad = 0.0
            if prefer_tag is not None:
                afinidad = next((t.share for t in reputacion.tags if t.tag is prefer_tag), 0.0)
            return (afinidad, reputacion.score)

        mejor = max(candidates, key=clave)
        return mejor, self.of(mejor)

    def problems_of(self, subject: Subject) -> list[TagSummary]:
        """Quejas frecuentes. Alimenta al director: son cosas que puede arreglar.

        Que el 40% describa una voz como «va muy rápido» no es una queja sobre la
        voz: es una instrucción para el estilo con el que se está usando.
        """
        reputacion = self.of(subject)
        return [
            t for t in reputacion.tags if t.tag.sentiment is Sentiment.NEGATIVE and t.share >= 0.25
        ]

    def __len__(self) -> int:
        return len(self.entries)


def suggest_adjustment(problems: list[TagSummary]) -> dict[str, float]:
    """Traduce quejas frecuentes en un ajuste concreto de la partitura.

    Es el puente entre «la gente dice que va rápido» y «baja el ritmo un 10%».
    Los pasos son deliberadamente pequeños: una corrección automática que se
    pase de frenada es peor que no corregir, porque nadie sabrá por qué de
    repente todo suena raro.
    """
    ajuste: dict[str, float] = {}
    for problema in problems:
        if problema.tag is Tag.TOO_FAST:
            ajuste["rate_scale"] = 0.9
        elif problema.tag is Tag.TOO_SLOW:
            ajuste["rate_scale"] = 1.1
        elif problema.tag is Tag.BAD_PAUSES:
            ajuste["pause_scale"] = 1.2
        elif problema.tag is Tag.MONOTONE:
            ajuste["emphasis_scale"] = 1.15
    return ajuste
