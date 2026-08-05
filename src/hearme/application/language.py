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


# --- normalización de entrada -------------------------------------------------

#: Nombres de idioma aceptados -> código ISO 639-1.
#:
#: Existe porque la interfaz tenía un campo de texto libre para el idioma de
#: destino, y escribir «francés» ahí es lo natural. Llegaba tal cual al traductor
#: —que espera códigos ISO— y fallaba con «Ningún traductor cubre es->frances»,
#: un mensaje que no ayuda a entender que el problema era la palabra.
#:
#: El campo ya es un selector, pero la normalización se queda: la API es pública
#: y alguien la llamará a mano. Aceptar lo razonable es más barato que explicar
#: por qué no se acepta.
_LANGUAGE_ALIASES: dict[str, str] = {
    # español
    "es": "es",
    "esp": "es",
    "spa": "es",
    "espanol": "es",
    "español": "es",
    "castellano": "es",
    "spanish": "es",
    # inglés
    "en": "en",
    "eng": "en",
    "ingles": "en",
    "inglés": "en",
    "english": "en",
    # francés
    "fr": "fr",
    "fra": "fr",
    "fre": "fr",
    "frances": "fr",
    "francés": "fr",
    "french": "fr",
    "francais": "fr",
    "français": "fr",
    # alemán
    "de": "de",
    "ger": "de",
    "deu": "de",
    "aleman": "de",
    "alemán": "de",
    "german": "de",
    "deutsch": "de",
    # italiano
    "it": "it",
    "ita": "it",
    "italiano": "it",
    "italian": "it",
    # portugués
    "pt": "pt",
    "por": "pt",
    "portugues": "pt",
    "portugués": "pt",
    "portuguese": "pt",
    "brasileiro": "pt",
    # catalán
    "ca": "ca",
    "cat": "ca",
    "catalan": "ca",
    "català": "ca",
    # otros con voz disponible
    "nl": "nl",
    "neerlandes": "nl",
    "neerlandés": "nl",
    "dutch": "nl",
    "holandes": "nl",
    "pl": "pl",
    "polaco": "pl",
    "polish": "pl",
    "ru": "ru",
    "ruso": "ru",
    "russian": "ru",
    "uk": "uk",
    "ucraniano": "uk",
    "ukrainian": "uk",
    "tr": "tr",
    "turco": "tr",
    "turkish": "tr",
    "sv": "sv",
    "sueco": "sv",
    "swedish": "sv",
    "da": "da",
    "danes": "da",
    "danés": "da",
    "danish": "da",
    "no": "no",
    "noruego": "no",
    "norwegian": "no",
    "fi": "fi",
    "fines": "fi",
    "finés": "fi",
    "finnish": "fi",
    "el": "el",
    "griego": "el",
    "greek": "el",
    "cs": "cs",
    "checo": "cs",
    "czech": "cs",
    "ro": "ro",
    "rumano": "ro",
    "romanian": "ro",
    "hu": "hu",
    "hungaro": "hu",
    "húngaro": "hu",
    "hungarian": "hu",
    "ar": "ar",
    "arabe": "ar",
    "árabe": "ar",
    "arabic": "ar",
    "zh": "zh",
    "chino": "zh",
    "chinese": "zh",
    "mandarin": "zh",
    "ja": "ja",
    "japones": "ja",
    "japonés": "ja",
    "japanese": "ja",
    "hi": "hi",
    "hindi": "hi",
    "vi": "vi",
    "vietnamita": "vi",
    "vietnamese": "vi",
    "fa": "fa",
    "persa": "fa",
    "persian": "fa",
    "farsi": "fa",
}


class UnknownLanguage(ValueError):
    """Idioma no reconocido. Lleva la lista de lo que sí se acepta."""


def normalize_language(value: str) -> str:
    """Convierte lo que escriba una persona en un código ISO 639-1.

    Acepta el código (`fr`), el nombre en español (`francés`, sin tilde también),
    en inglés (`French`) o en el propio idioma (`français`). También tolera un
    código regional: `es-AR` y `es_ES` se quedan en `es`, porque los modelos de
    traducción y de voz trabajan por idioma, no por variante.
    """
    limpio = value.strip().lower()
    if not limpio:
        raise UnknownLanguage("no se indicó ningún idioma")

    # es-AR, es_ES, pt-BR -> es, es, pt
    base = limpio.replace("_", "-").split("-")[0]

    for candidato in (limpio, base):
        if candidato in _LANGUAGE_ALIASES:
            return _LANGUAGE_ALIASES[candidato]

    raise UnknownLanguage(
        f"No se reconoce el idioma «{value}». Usa su código de dos letras "
        f"(es, en, fr, de…) o su nombre en español."
    )


def try_normalize_language(value: str | None) -> str | None:
    """Como `normalize_language` pero devuelve None en vez de fallar."""
    if not value:
        return None
    try:
        return normalize_language(value)
    except UnknownLanguage:
        return None
