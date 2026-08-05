"""Detección de idioma sin dependencias externas.

Un clasificador por palabras funcionales basta: en un documento de miles de
caracteres, la frecuencia de artículos y preposiciones separa los idiomas
europeos con fiabilidad muy alta, y no arrastra un modelo de 100 MB.
"""

from __future__ import annotations

import re
from collections import Counter

#: Palabras funcionales de alta frecuencia y bajo solapamiento entre idiomas.
_MARKERS: dict[str, frozenset[str]] = {
    "es": frozenset(
        [
            "el",
            "la",
            "los",
            "las",
            "de",
            "que",
            "y",
            "en",
            "un",
            "una",
            "por",
            "con",
            "para",
            "no",
            "se",
            "su",
            "al",
            "del",
            "es",
            "son",
            "como",
            "pero",
            "más",
            "este",
            "esta",
            "cuando",
            "muy",
            "sobre",
            "también",
        ]
    ),
    "en": frozenset(
        [
            "the",
            "of",
            "and",
            "to",
            "in",
            "a",
            "is",
            "that",
            "it",
            "for",
            "was",
            "with",
            "as",
            "on",
            "are",
            "this",
            "be",
            "by",
            "an",
            "from",
            "at",
            "or",
            "have",
            "has",
            "not",
            "but",
            "which",
            "their",
            "were",
        ]
    ),
    "pt": frozenset(
        [
            "de",
            "que",
            "os",
            "as",
            "um",
            "uma",
            "para",
            "com",
            "não",
            "por",
            "mais",
            "como",
            "mas",
            "ao",
            "dos",
            "das",
            "seu",
            "sua",
            "são",
            "está",
            "muito",
            "quando",
            "também",
            "sobre",
        ]
    ),
    "fr": frozenset(
        [
            "le",
            "la",
            "les",
            "de",
            "des",
            "un",
            "une",
            "et",
            "en",
            "que",
            "qui",
            "dans",
            "pour",
            "pas",
            "sur",
            "au",
            "aux",
            "ce",
            "est",
            "sont",
            "avec",
            "plus",
            "par",
            "ne",
            "se",
            "cette",
        ]
    ),
    "it": frozenset(
        [
            "il",
            "lo",
            "la",
            "i",
            "gli",
            "le",
            "di",
            "che",
            "e",
            "in",
            "un",
            "una",
            "per",
            "con",
            "non",
            "da",
            "su",
            "come",
            "sono",
            "più",
            "questo",
            "anche",
            "del",
            "della",
            "degli",
        ]
    ),
    "de": frozenset(
        [
            "der",
            "die",
            "das",
            "und",
            "in",
            "den",
            "von",
            "zu",
            "mit",
            "sich",
            "des",
            "auf",
            "für",
            "ist",
            "im",
            "dem",
            "nicht",
            "ein",
            "eine",
            "als",
            "auch",
            "es",
            "an",
            "werden",
        ]
    ),
    "nl": frozenset(
        [
            "de",
            "het",
            "een",
            "van",
            "en",
            "in",
            "te",
            "dat",
            "op",
            "voor",
            "met",
            "zijn",
            "niet",
            "aan",
            "er",
            "die",
            "is",
            "ook",
            "als",
            "maar",
            "om",
            "door",
            "over",
        ]
    ),
    "ca": frozenset(
        [
            "el",
            "la",
            "els",
            "les",
            "de",
            "que",
            "i",
            "en",
            "un",
            "una",
            "amb",
            "per",
            "no",
            "es",
            "va",
            "del",
            "als",
            "però",
            "més",
            "aquest",
            "aquesta",
            "quan",
            "també",
        ]
    ),
}

_WORD = re.compile(r"[a-záéíóúüñàèìòùâêîôûäöëïçãõ]+", re.IGNORECASE)


def detect_language(text: str, *, default: str = "en", sample: int = 20_000) -> str:
    """Devuelve el código ISO-639-1 más probable.

    `sample` acota el coste: 20 000 caracteres ya dan una señal estable y evita
    recorrer un libro entero.
    """
    words = _WORD.findall(text[:sample].lower())
    if len(words) < 15:
        return default

    counts = Counter(words)
    scores = {lang: sum(counts[word] for word in markers) for lang, markers in _MARKERS.items()}
    best, hits = max(scores.items(), key=lambda item: item[1])

    # Sin una densidad mínima de marcadores, la elección sería ruido.
    return best if hits >= len(words) * 0.04 else default
