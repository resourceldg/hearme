"""Segmentación de bloques en `Utterance`s narrables.

Los motores TTS degradan con entradas largas (prosodia que se desmorona, cortes
abruptos). Se trocea por límites de frase, nunca a medio enunciado, y se asignan
pausas según el perfil de narración.
"""

from __future__ import annotations

import re

from hearme.domain.models import (
    Block,
    BlockKind,
    Chapter,
    NarrationStyle,
    Utterance,
)
from hearme.narration.director import NarrationDirector, default_director
from hearme.narration.score import normalize_text

#: Abreviaturas tras las que un punto NO cierra frase (español e inglés).
_ABBREVIATIONS = (
    "Sr",
    "Sra",
    "Srta",
    "Dr",
    "Dra",
    "Prof",
    "Ing",
    "Lic",
    "Av",
    "Avda",
    "etc",
    "Etc",
    "núm",
    "Núm",
    "pág",
    "Pág",
    "cap",
    "Cap",
    "vol",
    "Vol",
    "Mr",
    "Mrs",
    "Ms",
    "Jr",
    "St",
    "vs",
    "cf",
    "ed",
    "Ed",
    "Fig",
    "fig",
)

#: El punto debe ir *dentro* del lookbehind: la posición de corte cae justo
#: después de él, así que comprobar solo "Dr" nunca coincidiría.
_ABBR_GUARD = "".join(rf"(?<!\b{abbr}\.)" for abbr in _ABBREVIATIONS)

#: Fin de frase: puntuación terminal + espacio + mayúscula o signo de apertura.
#: `(?<!\b[A-Z]\.)` protege las iniciales (J. R. R. Tolkien) sin bloquear las
#: siglas, porque en "CIA." la A no va precedida de frontera de palabra.
_SENTENCE_END = re.compile(
    r"(?<!\b[A-Z]\.)" + _ABBR_GUARD + r"(?<=[\.\!\?…])[\"'»”\)]*\s+(?=[¿¡\"'«“\(]?[A-ZÁÉÍÓÚÑÜ0-9])"
)

#: Cualquier racha de espacio en blanco, incluidos saltos de línea.
#: `normalize_text` conserva a propósito el salto que sigue a un punto para no
#: perder la estructura de párrafos, y en un PDF eso pasa en casi cada línea.
#: Pero un salto de línea no se narra: lo que llega al motor tiene que ser una
#: sola línea. Con varias, el fonemizador de espeak devuelve más líneas de las
#: que recibe y aborta con "input=1, output=2".
_WHITESPACE = re.compile(r"\s+")

MAX_CHARS = 420
MIN_CHARS = 40


def flatten(text: str) -> str:
    """Deja el texto en una sola línea, listo para un motor de voz."""
    return _WHITESPACE.sub(" ", text).strip()


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE_END.split(text) if p.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def _pack(sentences: list[str], max_chars: int) -> list[str]:
    """Agrupa frases hasta `max_chars` para no fragmentar la prosodia de más."""
    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        # Una frase que ya excede el límite se parte por comas o a lo bruto.
        if len(sentence) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_long(sentence, max_chars))
            continue

        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= max_chars:
            current = candidate
        else:
            chunks.append(current)
            current = sentence

    if current:
        chunks.append(current)
    return chunks


def _split_long(sentence: str, max_chars: int) -> list[str]:
    pieces = re.split(r"(?<=[,;:])\s+", sentence)
    out: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current} {piece}".strip() if current else piece
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            out.append(current)
        # Último recurso: corte duro por ventana.
        while len(piece) > max_chars:
            out.append(piece[:max_chars])
            piece = piece[max_chars:]
        current = piece
    if current:
        out.append(current)
    return out


#: Respiración corta dentro de un bloque. La pausa larga que decide el director
#: va solo al final; entre fragmentos del mismo párrafo sonaría entrecortado.
BREATH_MS = 120


def chunk_chapter(
    chapter: Chapter,
    *,
    style: NarrationStyle = NarrationStyle.NEUTRAL,
    max_chars: int = MAX_CHARS,
    start_order: int = 0,
    skip_code: bool = True,
    director: NarrationDirector | None = None,
    language: str = "es",
) -> list[Utterance]:
    """Trocea un capítulo en fragmentos narrables con su intención prosódica.

    El *qué* decir lo decide este módulo (dónde cortar sin romper la frase); el
    *cómo* decirlo lo decide el director, que es una pieza sustituible. Las
    tablas de pausas vivían aquí incrustadas: ahora son la implementación por
    reglas de `hearme.narration.director`, y el día que un modelo entrenado por
    la comunidad las mejore, este archivo no se entera.
    """
    director = director or default_director()
    utterances: list[Utterance] = []
    order = start_order

    for block in chapter.blocks:
        if not block.is_narrated:
            continue
        if skip_code and block.kind is BlockKind.CODE:
            continue

        text = block.translated or block.text
        chunks = _pack(split_sentences(text), max_chars)
        if not chunks:
            continue

        score = director.direct(text, kind=block.kind, style=style, language=language)
        normalizado = normalize_text(text)
        mark = score.resolve(0, len(normalizado))

        for index, chunk in enumerate(chunks):
            last = index == len(chunks) - 1
            utterances.append(
                Utterance(
                    text=flatten(chunk),
                    order=order,
                    chapter_id=chapter.id,
                    block_id=block.id,
                    pause_after_ms=(mark.pause_after_ms or 0) if last and mark else BREATH_MS,
                    emphasis=(mark.emphasis if mark and mark.emphasis else 1.0),
                    rate=(mark.rate if mark and mark.rate else 1.0),
                )
            )
            order += 1

    return utterances


def chunk_blocks(
    blocks: list[Block], chapter_id: str, *, style: NarrationStyle = NarrationStyle.NEUTRAL
) -> list[Utterance]:
    """Atajo para trocear bloques sueltos (usado en previsualizaciones)."""
    return chunk_chapter(Chapter(title="", order=0, blocks=blocks, id=chapter_id), style=style)
