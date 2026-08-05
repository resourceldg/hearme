"""Señales de retroalimentación: de «me gustó» a datos utilizables.

## Las tres vías, y por qué las tres

| Señal | Coste para quien escucha | Qué aporta |
|---|---|---|
| Pulgar | Un toque | Volumen. Es la única que se usa de verdad a mitad de un capítulo |
| Estrellas | Dos segundos | Gradación. Distingue «pasable» de «excelente» |
| Comentario | Media frase | **El porqué.** Es lo único que dice *qué* falla |

Tener solo pulgares da mucha señal y ninguna explicación. Tener solo comentarios
da explicaciones de las poquísimas personas dispuestas a escribir. Las tres
juntas se cubren los huecos.

## Por qué las etiquetas se extraen con un léxico y no con un modelo

Parece que un modelo de lenguaje sería lo natural para convertir «se oye muy
robótico y va disparado» en `{robotic, too_fast}`. Aquí se hace con un léxico, y
es una decisión, no una limitación de medios:

1. **Explicabilidad por construcción.** El sistema puede señalar *qué palabra*
   produjo cada etiqueta. Un modelo diría «robótico» con 0,87 de confianza y
   nadie podría comprobarlo. Como la reputación que sale de aquí decide qué voz
   se recomienda, tiene que poder auditarse.
2. **Determinismo.** El mismo comentario da siempre las mismas etiquetas. Una
   reputación que cambia porque el modelo se actualizó no es una reputación.
3. **Funciona sin conexión y sin GPU**, que es donde vive este proyecto.
4. **No manda el texto de nadie a ninguna parte.** El comentario se procesa en
   el mismo sitio donde se escribió.

El coste es real y conviene decirlo: un léxico no entiende ironía, ni negación
compleja, ni idiomas para los que nadie haya escrito el léxico. Por eso el
comentario original **se conserva** junto a las etiquetas, y la extracción se
declara como lo que es —una ayuda— y no como la verdad.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class Sentiment(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class Tag(StrEnum):
    """Etiquetas estructuradas que se pueden extraer de un comentario.

    Se eligen porque son **accionables**: cada una apunta a algo que el director
    o el adaptador pueden cambiar. «Bonito» no está porque no dice qué hacer.
    """

    # Calidad percibida de la voz
    NATURAL = "natural"
    ROBOTIC = "robotic"
    # Ritmo
    TOO_FAST = "too_fast"
    TOO_SLOW = "too_slow"
    GOOD_PACE = "good_pace"
    # Prosodia
    MONOTONE = "monotone"
    EXPRESSIVE = "expressive"
    BAD_PAUSES = "bad_pauses"
    GOOD_PAUSES = "good_pauses"
    # Inteligibilidad
    UNCLEAR = "unclear"
    CLEAR = "clear"
    MISPRONOUNCED = "mispronounced"
    # Adecuación a un tipo de texto
    GOOD_FOR_NOVEL = "good_for_novel"
    GOOD_FOR_STUDY = "good_for_study"
    GOOD_FOR_CHILDREN = "good_for_children"
    # Escucha larga
    TIRING = "tiring"
    COMFORTABLE = "comfortable"

    @property
    def sentiment(self) -> Sentiment:
        negativas = {
            Tag.ROBOTIC,
            Tag.TOO_FAST,
            Tag.TOO_SLOW,
            Tag.MONOTONE,
            Tag.BAD_PAUSES,
            Tag.UNCLEAR,
            Tag.MISPRONOUNCED,
            Tag.TIRING,
        }
        positivas = {
            Tag.NATURAL,
            Tag.GOOD_PACE,
            Tag.EXPRESSIVE,
            Tag.GOOD_PAUSES,
            Tag.CLEAR,
            Tag.COMFORTABLE,
            Tag.GOOD_FOR_NOVEL,
            Tag.GOOD_FOR_STUDY,
            Tag.GOOD_FOR_CHILDREN,
        }
        if self in negativas:
            return Sentiment.NEGATIVE
        if self in positivas:
            return Sentiment.POSITIVE
        return Sentiment.NEUTRAL

    @property
    def label(self) -> str:
        """Cómo se muestra en la interfaz."""
        return {
            Tag.NATURAL: "suena natural",
            Tag.ROBOTIC: "suena robótico",
            Tag.TOO_FAST: "va muy rápido",
            Tag.TOO_SLOW: "va muy lento",
            Tag.GOOD_PACE: "buen ritmo",
            Tag.MONOTONE: "monótono",
            Tag.EXPRESSIVE: "expresivo",
            Tag.BAD_PAUSES: "pausas mal puestas",
            Tag.GOOD_PAUSES: "pausas bien puestas",
            Tag.UNCLEAR: "se entiende mal",
            Tag.CLEAR: "se entiende bien",
            Tag.MISPRONOUNCED: "pronuncia mal",
            Tag.GOOD_FOR_NOVEL: "va bien para novela",
            Tag.GOOD_FOR_STUDY: "va bien para estudiar",
            Tag.GOOD_FOR_CHILDREN: "va bien para infantil",
            Tag.TIRING: "cansa al rato",
            Tag.COMFORTABLE: "cómodo de escuchar",
        }[self]


#: Patrones por etiqueta. Español primero; el inglés se acepta porque mucha
#: gente escribe reseñas en inglés aunque escuche en su idioma.
#:
#: Se escriben como expresiones regulares sobre texto ya normalizado (sin
#: tildes, en minúsculas) para que «robótico» y «robotico» coincidan igual.
_PATTERNS: dict[Tag, tuple[str, ...]] = {
    Tag.ROBOTIC: (r"robotic\w*", r"artificial", r"metalic\w*", r"suena a maquina", r"sintetic\w*"),
    Tag.NATURAL: (r"natural\w*", r"suena human\w*", r"parece una persona", r"realista"),
    Tag.TOO_FAST: (
        r"muy rapid\w*",
        r"demasiado rapid\w*",
        r"acelerad\w*",
        r"va disparad\w*",
        r"corre mucho",
        r"too fast",
    ),
    Tag.TOO_SLOW: (r"muy lent\w*", r"demasiado lent\w*", r"arrastr\w* las palabras", r"too slow"),
    Tag.GOOD_PACE: (r"buen ritmo", r"ritmo (adecuad|perfect|correct)\w*", r"good pace"),
    Tag.MONOTONE: (r"monoton\w*", r"plan[oa]\b", r"sin entonacion", r"sin emocion", r"aburrid\w*"),
    Tag.EXPRESSIVE: (r"expresiv\w*", r"con emocion", r"entonacion buena", r"interpretad\w*"),
    Tag.BAD_PAUSES: (
        r"pausas? (mal|rar|extran|corta|larga)\w*",
        r"no respira",
        r"corta (mal|donde no)",
        r"entrecortad\w*",
    ),
    Tag.GOOD_PAUSES: (r"pausas? (buen|bien|adecuad|correct)\w*", r"respira bien"),
    Tag.UNCLEAR: (
        r"no se entiende",
        r"se entiende mal",
        r"confus\w*",
        r"farfull\w*",
        r"ininteligible",
    ),
    Tag.CLEAR: (r"se entiende (bien|perfect)\w*", r"clarit[oa]", r"muy clar[oa]", r"vocaliza bien"),
    Tag.MISPRONOUNCED: (
        r"pronuncia mal",
        r"mal pronunciad\w*",
        r"dice mal",
        r"acentua mal",
        r"se come (las )?letras",
    ),
    Tag.GOOD_FOR_NOVEL: (
        r"(ideal|perfect\w*|buen\w*|va bien) para (una )?novela",
        r"para (leer )?ficcion",
        r"para (un )?relato",
    ),
    Tag.GOOD_FOR_STUDY: (
        r"(ideal|perfect\w*|buen\w*|va bien) para estudiar",
        r"para (los )?apuntes",
        r"para estudio",
    ),
    Tag.GOOD_FOR_CHILDREN: (
        r"(ideal|perfect\w*|buen\w*|va bien) para (los )?ni[nñ]os",
        r"para infantil",
        r"para cuentos",
    ),
    Tag.TIRING: (r"cansa", r"agota", r"fatiga", r"pesad[oa] de escuchar", r"no aguanto"),
    Tag.COMFORTABLE: (
        r"comod[oa] de escuchar",
        r"agradable",
        r"se escucha bien (mucho|rato)",
        r"no cansa",
    ),
}

#: Negaciones que invierten la etiqueta siguiente. Sin esto, «no suena natural»
#: se etiquetaría como NATURAL, que es exactamente lo contrario de lo dicho.
_NEGATIONS = (r"\bno\b", r"\bnada\b", r"\bpoco\b", r"\bapenas\b", r"\bnot\b")

#: Qué etiqueta pasa a ser cuál al negarla. Las que no están aquí simplemente se
#: descartan al negarse: es más honesto no etiquetar que invertir a ciegas.
_NEGATED: dict[Tag, Tag] = {
    Tag.NATURAL: Tag.ROBOTIC,
    Tag.ROBOTIC: Tag.NATURAL,
    Tag.CLEAR: Tag.UNCLEAR,
    Tag.UNCLEAR: Tag.CLEAR,
    Tag.EXPRESSIVE: Tag.MONOTONE,
    Tag.MONOTONE: Tag.EXPRESSIVE,
    Tag.COMFORTABLE: Tag.TIRING,
    Tag.TIRING: Tag.COMFORTABLE,
    Tag.GOOD_PAUSES: Tag.BAD_PAUSES,
    Tag.BAD_PAUSES: Tag.GOOD_PAUSES,
}

#: Ventana de palabras hacia atrás donde una negación afecta a la expresión.
#: Tres es lo que cubre «no me suena natural» sin cruzar a la frase anterior.
_NEGATION_WINDOW = 3

MAX_COMMENT_CHARS = 500


def normalize(text: str) -> str:
    """Minúsculas y sin tildes, para que el léxico no se duplique por acentos."""
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", sin_tildes).strip()


@dataclass(frozen=True, slots=True)
class TagMatch:
    """Una etiqueta y **el fragmento que la produjo**.

    Guardar el fragmento es lo que hace auditable la extracción: se puede
    enseñar «esto se etiquetó como “va muy rápido” por “demasiado rapido”» y
    quien discrepe tiene algo concreto que discutir.
    """

    tag: Tag
    matched: str
    negated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "tag": self.tag.value,
            "label": self.tag.label,
            "matched": self.matched,
            "negated": self.negated,
        }


def extract_tags(comment: str) -> list[TagMatch]:
    """Convierte un comentario libre en etiquetas, guardando la evidencia.

    No pretende entender la frase. Busca expresiones conocidas, comprueba si van
    negadas y devuelve lo que encuentra con su fragmento. Lo que no reconoce, no
    lo inventa: un comentario sin coincidencias devuelve lista vacía y el texto
    original se conserva igual.
    """
    if not comment or not comment.strip():
        return []

    texto = normalize(comment[:MAX_COMMENT_CHARS])
    encontradas: dict[Tag, TagMatch] = {}

    for tag, patrones in _PATTERNS.items():
        for patron in patrones:
            for coincidencia in re.finditer(patron, texto):
                # ¿Hay una negación en las palabras inmediatamente anteriores?
                previo = texto[: coincidencia.start()].split()[-_NEGATION_WINDOW:]
                negado = any(re.search(neg, " ".join(previo)) for neg in _NEGATIONS)

                efectiva = _NEGATED.get(tag) if negado else tag
                if efectiva is None:
                    continue  # negada y sin opuesto claro: mejor no etiquetar

                # La primera coincidencia manda: repetir la misma idea no la
                # hace más cierta, y contar dos veces distorsionaría la reputación.
                encontradas.setdefault(
                    efectiva,
                    TagMatch(tag=efectiva, matched=coincidencia.group(0), negated=negado),
                )
    return list(encontradas.values())


@dataclass(frozen=True, slots=True)
class Subject:
    """Sobre qué se opina. Los tres niveles se puntúan por separado.

    Que la configuración forme parte del sujeto es lo que permite distinguir «esta
    voz es mala» de «esta voz con este estilo es mala». Sin eso, un estilo mal
    ajustado hundiría la reputación de una voz que no tiene la culpa.
    """

    engine: str
    voice: str = ""
    style: str = ""
    language: str = ""

    @property
    def key(self) -> str:
        return "|".join((self.engine, self.voice, self.style, self.language))

    def generalize(self) -> list[Subject]:
        """Del más concreto al más general.

        Una valoración de (piper, sharvard#F, novela, es) también dice algo de
        (piper, sharvard#F) y de (piper). Propagarla hacia arriba es lo que hace
        que un motor recién instalado no empiece sin ninguna información.
        """
        return [
            self,
            Subject(self.engine, self.voice, language=self.language),
            Subject(self.engine, self.voice),
            Subject(self.engine),
        ]

    def to_dict(self) -> dict[str, str]:
        return {
            "engine": self.engine,
            "voice": self.voice,
            "style": self.style,
            "language": self.language,
        }


MIN_STARS, MAX_STARS = 1, 5


@dataclass(slots=True)
class Feedback:
    """Una valoración. Todas las señales son opcionales salvo el sujeto."""

    subject: Subject
    #: 1..5. None si solo se usó el pulgar o el comentario.
    stars: int | None = None
    #: True me gusta, False no me gusta, None sin pulgar.
    thumbs_up: bool | None = None
    #: Texto libre. Se conserva tal cual: las etiquetas son una ayuda, no la verdad.
    comment: str = ""
    #: Seudónimo local. No identifica a nadie fuera de esta instalación.
    contributor: str = "local"
    at: datetime = field(default_factory=lambda: datetime.now(UTC))
    _tags: list[TagMatch] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.stars is not None and not MIN_STARS <= self.stars <= MAX_STARS:
            raise ValueError(f"las estrellas van de {MIN_STARS} a {MAX_STARS}, no {self.stars}")
        if self.stars is None and self.thumbs_up is None and not self.comment.strip():
            raise ValueError(
                "una valoración vacía no aporta nada: falta estrella, pulgar o comentario"
            )

    @property
    def tags(self) -> list[TagMatch]:
        """Etiquetas extraídas del comentario. Se calculan una vez."""
        if self._tags is None:
            self._tags = extract_tags(self.comment)
        return self._tags

    @property
    def implicit_stars(self) -> float | None:
        """Estrellas equivalentes, para poder mezclar señales distintas.

        Un pulgar no es una estrella y convertirlo tiene un coste de precisión.
        Se hace porque tener dos escalas separadas obligaría a elegir cuál mandaba,
        y la conversión es conservadora: un pulgar arriba vale 4, no 5, porque
        «me vale» no es «es excelente».
        """
        if self.stars is not None:
            return float(self.stars)
        if self.thumbs_up is True:
            return 4.0
        if self.thumbs_up is False:
            return 2.0
        # Solo comentario: se deduce del balance de etiquetas.
        if self.tags:
            positivas = sum(1 for t in self.tags if t.tag.sentiment is Sentiment.POSITIVE)
            negativas = sum(1 for t in self.tags if t.tag.sentiment is Sentiment.NEGATIVE)
            if positivas or negativas:
                return 3.0 + 1.5 * (positivas - negativas) / (positivas + negativas)
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject.to_dict(),
            "stars": self.stars,
            "thumbs_up": self.thumbs_up,
            "comment": self.comment,
            "tags": [t.to_dict() for t in self.tags],
            "implicit_stars": self.implicit_stars,
            "contributor": self.contributor,
            "at": self.at.isoformat(),
        }

    def explain_tags(self) -> str:
        """Por qué salieron esas etiquetas. Es la auditoría de la extracción."""
        if not self.tags:
            return "Del comentario no se extrajo ninguna etiqueta conocida."
        partes = [
            f"«{t.matched}» → {t.tag.label}" + (" (negado)" if t.negated else "") for t in self.tags
        ]
        return "Se detectó: " + "; ".join(partes) + "."
