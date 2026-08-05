"""El director de narración: de texto a partitura.

Un director recibe texto y devuelve intención prosódica. No sintetiza, no conoce
ningún motor y no produce audio: produce *criterio*. Esa frontera es lo que
permite cambiar de motor sin perder lo aprendido.

Hoy hay una implementación por reglas, que es deliberadamente humilde: tablas de
pausas por tipo de bloque y poco más. Su valor no está en ser buena, sino en ser
la línea base medible contra la que se compara todo lo que venga después, y en
fijar el contrato que cumplirá el director entrenado.

El plan de sustitución está en `docs/COMMUNITY-NARRATION-TRAINING.md`: mismo
`Protocol`, mismo formato de salida, y una evaluación a ciegas que decide si el
modelo entra o se queda fuera.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from hearme.domain.models import BlockKind, NarrationStyle
from hearme.narration.score import (
    MarkSource,
    NarrationScore,
    ProsodyMark,
    SpanRole,
    normalize_text,
)


@runtime_checkable
class NarrationDirector(Protocol):
    """Contrato de un director. Un modelo entrenado encaja aquí sin tocar nada más."""

    name: str
    #: Identifica la versión del criterio que produjo una partitura. Sin esto no
    #: se puede reproducir una lectura ni atribuir una mejora a quien la aportó.
    version: str

    def direct(
        self,
        text: str,
        *,
        kind: BlockKind,
        style: NarrationStyle,
        language: str,
    ) -> NarrationScore: ...


# --- director por reglas ------------------------------------------------------

#: Pausa en ms tras cada tipo de bloque, por estilo. Heredado del segmentador
#: original: son las tablas que la comunidad va a jubilar con evidencia.
_PAUSES: dict[NarrationStyle, dict[BlockKind, int]] = {
    NarrationStyle.NOVEL: {
        BlockKind.HEADING: 1200,
        BlockKind.PARAGRAPH: 450,
        BlockKind.QUOTE: 600,
        BlockKind.LIST_ITEM: 300,
    },
    NarrationStyle.POETRY: {
        # El verso vive de los silencios: pausas largas, ritmo más lento.
        BlockKind.HEADING: 1500,
        BlockKind.PARAGRAPH: 900,
        BlockKind.QUOTE: 900,
        BlockKind.LIST_ITEM: 700,
    },
    NarrationStyle.TECHNICAL: {
        # Cadencia sostenida: el oyente sigue una estructura, no una historia.
        BlockKind.HEADING: 900,
        BlockKind.PARAGRAPH: 350,
        BlockKind.QUOTE: 400,
        BlockKind.LIST_ITEM: 400,
        BlockKind.CODE: 500,
    },
    NarrationStyle.ACADEMIC: {
        # La cita y la nota piden aire: son la voz de otra persona dentro del texto.
        BlockKind.HEADING: 1000,
        BlockKind.PARAGRAPH: 500,
        BlockKind.QUOTE: 800,
        BlockKind.LIST_ITEM: 450,
        BlockKind.FOOTNOTE: 700,
    },
    NarrationStyle.CHILDREN: {
        # Pausas amplias para dejar sitio a la imaginación y a las preguntas.
        BlockKind.HEADING: 1400,
        BlockKind.PARAGRAPH: 700,
        BlockKind.QUOTE: 800,
        BlockKind.LIST_ITEM: 600,
    },
    NarrationStyle.LECTURE: {
        # Cadencia de exposición oral: el encabezado marca el cambio de tema.
        BlockKind.HEADING: 1600,
        BlockKind.PARAGRAPH: 550,
        BlockKind.QUOTE: 600,
        BlockKind.LIST_ITEM: 500,
    },
    NarrationStyle.NEUTRAL: {
        BlockKind.HEADING: 1000,
        BlockKind.PARAGRAPH: 400,
        BlockKind.QUOTE: 500,
        BlockKind.LIST_ITEM: 300,
    },
}

_RATES: dict[NarrationStyle, float] = {
    NarrationStyle.NOVEL: 1.0,
    NarrationStyle.POETRY: 0.88,
    NarrationStyle.TECHNICAL: 0.95,
    # Más lento: se escucha para entender, no para avanzar.
    NarrationStyle.ACADEMIC: 0.92,
    NarrationStyle.CHILDREN: 0.85,
    NarrationStyle.LECTURE: 0.95,
    NarrationStyle.NEUTRAL: 1.0,
}

_ROLES: dict[BlockKind, SpanRole] = {
    BlockKind.HEADING: SpanRole.HEADING,
    BlockKind.QUOTE: SpanRole.QUOTE,
    BlockKind.LIST_ITEM: SpanRole.LIST_ITEM,
    BlockKind.FOOTNOTE: SpanRole.ASIDE,
    BlockKind.CAPTION: SpanRole.ASIDE,
}

#: Diálogo en español y en inglés: raya, comillas latinas y comillas altas.
#: Detectarlo es la regla con mejor relación entre coste y mejora percibida —y
#: la primera candidata a que un modelo la haga mucho mejor.
_DIALOGUE = re.compile(r"(?:^|\s)(?:—[^—\n]+|«[^»\n]+»|\"[^\"\n]+\"|“[^”\n]+”)")

#: Énfasis por defecto de un encabezado. El mismo valor que usaba el segmentador.
_HEADING_EMPHASIS = 1.15


@dataclass(slots=True)
class RuleBasedDirector:
    """Director base: reglas tipográficas, cero aprendizaje.

    Es honesto sobre lo poco que sabe. Marca sus salidas con `MarkSource.RULE` y
    con una confianza baja precisamente para que cualquier aportación humana o
    de un modelo entrenado la sobrescriba sin discusión.
    """

    name: str = "rules"
    version: str = "1.0"
    #: Baja a propósito: es la prioridad más débil de todas las procedencias.
    confidence: float = 0.3

    def direct(
        self,
        text: str,
        *,
        kind: BlockKind = BlockKind.PARAGRAPH,
        style: NarrationStyle = NarrationStyle.NEUTRAL,
        language: str = "es",
    ) -> NarrationScore:
        normalizado = normalize_text(text)
        if not normalizado:
            return NarrationScore.for_text(text, language=language, register=style.value)

        pausas = _PAUSES[style]
        marcas: list[ProsodyMark] = [
            ProsodyMark(
                start=0,
                end=len(normalizado),
                role=_ROLES.get(kind, SpanRole.NARRATION),
                pause_after_ms=pausas.get(kind, 300),
                rate=_RATES[style],
                emphasis=_HEADING_EMPHASIS if kind is BlockKind.HEADING else 1.0,
                source=MarkSource.RULE,
                confidence=self.confidence,
            )
        ]

        # El diálogo se anota como rol, sin tocar todavía los números: decir
        # «esto es diálogo» es un hecho, decidir cómo suena es lo que aprenderá
        # el director entrenado a partir de las aportaciones.
        if kind is BlockKind.PARAGRAPH:
            for coincidencia in _DIALOGUE.finditer(normalizado):
                inicio = coincidencia.start(0)
                # `finditer` incluye el espacio previo del separador; se descuenta
                # para que la marca empiece en la raya o la comilla, no antes.
                while inicio < coincidencia.end(0) and normalizado[inicio].isspace():
                    inicio += 1
                marcas.append(
                    ProsodyMark(
                        start=inicio,
                        end=coincidencia.end(0),
                        role=SpanRole.DIALOGUE,
                        source=MarkSource.RULE,
                        confidence=self.confidence,
                    )
                )

        return NarrationScore.for_text(
            text, language=language, marks=tuple(marcas), register=style.value
        )


#: Director en uso. Se sustituye por el entrenado cuando gane la evaluación a
#: ciegas, sin que nada más del sistema tenga que enterarse.
def default_director() -> NarrationDirector:
    return RuleBasedDirector()
