"""La partitura de narración: qué se anota y en qué unidades.

Este archivo define el formato en el que se acumula el trabajo de la comunidad.
Es, con diferencia, la decisión de diseño más cara de revertir del proyecto: el
código se reescribe en una tarde, un corpus anotado por miles de personas no.
De ahí tres reglas que conviene no romper:

1. **Unidades neutras.** Milisegundos, semitonos y multiplicadores. Nada de
   `length_scale` ni de `<prosody rate="x-slow">`: eso son mandos de un motor
   concreto y caducan con él. Los semitonos, en particular, se eligen sobre los
   hercios porque son relativos a la voz y por tanto transferibles entre voces
   distintas.

2. **Anclaje al texto, no al troceo.** Las marcas apuntan a desplazamientos de
   carácter sobre el texto normalizado, con su hash al lado. Si mañana cambia el
   segmentador, o el motor, o el idioma de destino, las anotaciones se pueden
   volver a aplicar porque describen *el texto*, no la ejecución de aquel día.

3. **Procedencia explícita.** Cada marca sabe de dónde viene: una regla, una
   persona, un modelo o una lectura humana. Un corpus sin procedencia no se
   puede auditar, ni depurar, ni citar, ni limpiar cuando se descubre que una
   fuente estaba envenenada.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

#: Versión del esquema. Cambia solo con modificaciones incompatibles; los
#: lectores deben rechazar lo que no entiendan en vez de adivinar.
SCHEMA_VERSION = "1.0"

_WHITESPACE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Forma canónica sobre la que se miden los desplazamientos.

    Sin esto, la misma frase con un salto de línea distinto produciría
    desplazamientos distintos y las anotaciones de la comunidad no casarían
    entre una edición del documento y la siguiente.
    """
    return _WHITESPACE.sub(" ", text).strip()


def text_digest(text: str) -> str:
    """Huella del texto normalizado. **Solo para uso local.**

    Identifica una partitura dentro de una instalación sin almacenar la obra. Lo
    que *no* hace —y una versión anterior de este proyecto daba por hecho que
    sí— es proteger la privacidad de quien lee: un SHA-256 de un texto público
    es reversible por diccionario. Medido sobre un libro real, indexar 1257
    párrafos cuesta 0,01 s y reidentifica el 100%.

    Por eso esta huella **nunca sale de la instalación**. Para almacenar o
    correlacionar hay `privacy.crypto.keyed_digest`, que va con clave local; y
    lo que se comparte con la comunidad no lleva identificadores de texto en
    absoluto, sino reglas generalizadas (`hearme.knowledge`).
    """
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


class SpanRole(StrEnum):
    """Qué *es* este tramo dentro de la lectura.

    El rol se anota aparte de los valores numéricos a propósito: es la etiqueta
    que mejor sobrevive al paso del tiempo. Que una frase sea diálogo seguirá
    siendo verdad dentro de diez años; que convenga leerla un 8% más despacio es
    una opinión que los modelos irán refinando.
    """

    NARRATION = "narration"
    DIALOGUE = "dialogue"
    QUOTE = "quote"
    HEADING = "heading"
    LIST_ITEM = "list_item"
    ASIDE = "aside"  # incisos, notas al margen, acotaciones
    TERM = "term"  # tecnicismo o palabra que pide articulación cuidada


class MarkSource(StrEnum):
    """Procedencia de una marca. Determina cuánto pesa y si se puede publicar."""

    RULE = "rule"  # heurística del director base
    MODEL = "model"  # predicción de un director entrenado
    HUMAN = "human"  # corrección aportada y validada por personas
    REFERENCE = "reference"  # extraída de una lectura humana real


#: Cuánto pesa cada procedencia al fusionar partituras. Una corrección humana
#: validada gana siempre a una regla; una lectura humana medida gana a todo,
#: porque es la única evidencia que no es una opinión sobre cómo debería sonar.
_SOURCE_WEIGHT: dict[MarkSource, int] = {
    MarkSource.RULE: 0,
    MarkSource.MODEL: 1,
    MarkSource.HUMAN: 2,
    MarkSource.REFERENCE: 3,
}


@dataclass(frozen=True, slots=True)
class ProsodyMark:
    """Una directiva prosódica sobre `[start, end)` del texto normalizado.

    Los campos numéricos son opcionales y se combinan por capas: una marca puede
    decir solo «aquí hay una pausa de 400 ms» sin opinar sobre el ritmo, y otra
    superponer el ritmo sin tocar la pausa. Es lo que permite que la aportación
    de alguien que solo sabe dónde respirar conviva con la de un fonetista.
    """

    start: int
    end: int
    role: SpanRole = SpanRole.NARRATION
    #: Silencio tras el tramo, en milisegundos.
    pause_after_ms: int | None = None
    #: Multiplicador de intensidad. 1.0 = neutro.
    emphasis: float | None = None
    #: Multiplicador de velocidad. <1 lee más despacio.
    rate: float | None = None
    #: Desplazamiento de tono en semitonos. Relativo, luego transferible.
    pitch_semitones: float | None = None
    source: MarkSource = MarkSource.RULE
    #: 0..1. Los directores entrenados la usan para saber dónde dudan.
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError(f"tramo inválido: [{self.start}, {self.end})")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confianza fuera de rango: {self.confidence}")
        for nombre, valor in (("emphasis", self.emphasis), ("rate", self.rate)):
            if valor is not None and valor <= 0:
                raise ValueError(f"{nombre} debe ser positivo, no {valor}")

    @property
    def weight(self) -> int:
        return _SOURCE_WEIGHT[self.source]

    def to_dict(self) -> dict[str, Any]:
        """Solo los campos con valor: el corpus no se llena de nulos."""
        data: dict[str, Any] = {
            "start": self.start,
            "end": self.end,
            "role": self.role.value,
            "source": self.source.value,
        }
        if self.confidence != 1.0:
            data["confidence"] = round(self.confidence, 4)
        for nombre in ("pause_after_ms", "emphasis", "rate", "pitch_semitones"):
            valor = getattr(self, nombre)
            if valor is not None:
                data[nombre] = valor
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProsodyMark:
        return cls(
            start=int(data["start"]),
            end=int(data["end"]),
            role=SpanRole(data.get("role", SpanRole.NARRATION.value)),
            pause_after_ms=data.get("pause_after_ms"),
            emphasis=data.get("emphasis"),
            rate=data.get("rate"),
            pitch_semitones=data.get("pitch_semitones"),
            source=MarkSource(data.get("source", MarkSource.RULE.value)),
            confidence=float(data.get("confidence", 1.0)),
        )


@dataclass(frozen=True, slots=True)
class NarrationScore:
    """Partitura completa de un texto: sus marcas más el contexto que las explica.

    Es la unidad que se aporta, se revisa, se versiona y se publica en el corpus.
    """

    text_sha256: str
    language: str
    marks: tuple[ProsodyMark, ...] = ()
    schema_version: str = SCHEMA_VERSION
    #: Etiqueta libre del registro narrativo (novela, poesía, técnico…). No es un
    #: enum a propósito: la comunidad descubrirá registros que hoy no existen.
    register: str = "neutral"

    @classmethod
    def for_text(
        cls,
        text: str,
        *,
        language: str,
        marks: tuple[ProsodyMark, ...] = (),
        register: str = "neutral",
    ) -> NarrationScore:
        return cls(
            text_sha256=text_digest(text),
            language=language,
            marks=tuple(sorted(marks, key=lambda m: (m.start, m.end))),
            register=register,
        )

    def matches(self, text: str) -> bool:
        """¿Esta partitura corresponde a este texto exacto?"""
        return self.text_sha256 == text_digest(text)

    def resolve(self, start: int, end: int) -> ProsodyMark | None:
        """Marca efectiva para un tramo, fusionando por capas y procedencia.

        Se recorren las marcas que solapan el tramo de menor a mayor peso, de
        forma que las de más autoridad escriben al final y ganan. Cada dimensión
        se resuelve por separado: una corrección humana sobre la pausa no borra
        el ritmo que había propuesto el modelo.
        """
        solapan = [m for m in self.marks if m.start < end and m.end > start]
        if not solapan:
            return None

        solapan.sort(key=lambda m: (m.weight, m.confidence))
        efectiva = replace(solapan[0], start=start, end=end)
        for marca in solapan[1:]:
            cambios = {
                nombre: getattr(marca, nombre)
                for nombre in ("pause_after_ms", "emphasis", "rate", "pitch_semitones")
                if getattr(marca, nombre) is not None
            }
            # El rol lo fija la marca de mayor autoridad que se moje.
            if marca.role is not SpanRole.NARRATION:
                cambios["role"] = marca.role
            cambios["source"] = marca.source
            cambios["confidence"] = marca.confidence
            efectiva = replace(efectiva, **cambios)
        return efectiva

    def merged_with(self, other: NarrationScore) -> NarrationScore:
        """Superpone otra partitura sobre esta. Útil al aplicar correcciones."""
        if other.text_sha256 != self.text_sha256:
            raise ValueError("no se pueden fusionar partituras de textos distintos")
        return replace(
            self, marks=tuple(sorted(self.marks + other.marks, key=lambda m: (m.start, m.end)))
        )

    def by_source(self, source: MarkSource) -> tuple[ProsodyMark, ...]:
        return tuple(m for m in self.marks if m.source is source)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "text_sha256": self.text_sha256,
            "language": self.language,
            "register": self.register,
            "marks": [m.to_dict() for m in self.marks],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NarrationScore:
        version = str(data.get("schema_version", ""))
        # Mejor negarse que interpretar mal: una partitura malinterpretada
        # contamina el corpus en silencio, y eso no se detecta hasta muy tarde.
        if version.split(".")[0] != SCHEMA_VERSION.split(".")[0]:
            raise ValueError(
                f"esquema de partitura incompatible: {version!r} (se esperaba {SCHEMA_VERSION})"
            )
        return cls(
            text_sha256=str(data["text_sha256"]),
            language=str(data["language"]),
            marks=tuple(ProsodyMark.from_dict(m) for m in data.get("marks", ())),
            schema_version=version,
            register=str(data.get("register", "neutral")),
        )


@dataclass(slots=True)
class ScoredSpan:
    """Un tramo de texto con su marca ya resuelta. Lo que consume el sintetizador."""

    text: str
    start: int
    end: int
    mark: ProsodyMark | None = None
    lexicon: dict[str, str] = field(default_factory=dict)
