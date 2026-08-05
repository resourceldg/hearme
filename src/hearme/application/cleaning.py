"""Limpieza de ruido editorial: encabezados, pies, números de página, guionado.

Lógica pura, sin dependencias externas: es la parte más fácil de romper y la más
barata de testear.
"""

from __future__ import annotations

import re
from collections import Counter

from hearme.domain.models import Block, BlockKind

#: Un número suelto, con adornos: "12", "- 12 -", "[12]", "Página 12", "12 / 340"
_PAGE_NUMBER = re.compile(
    r"^\s*(?:p[áa]g(?:ina)?\.?\s*|page\s*)?[\[\(\-–—\s]*"
    r"(?:\d{1,4}|[ivxlcdm]{1,7})"
    r"[\]\)\-–—\s]*(?:/\s*\d{1,4})?\s*$",
    re.IGNORECASE,
)

#: Palabra cortada por guion al final de línea: "conti-\nnuación" -> "continuación".
_HYPHEN_BREAK = re.compile(r"(\w)[-‐‑]\s*\n\s*(\w)")

_MULTI_SPACE = re.compile(r"[ \t ]+")
_MULTI_NEWLINE = re.compile(r"\n{3,}")

#: Ligaduras tipográficas que los extractores de PDF suelen dejar pasar.
_LIGATURES = str.maketrans(
    {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "​": "", "﻿": ""}
)


def is_page_number(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and len(stripped) <= 20 and _PAGE_NUMBER.match(stripped) is not None


def normalize_text(text: str) -> str:
    """Normalización segura: no altera el contenido, solo su representación."""
    text = text.translate(_LIGATURES)
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    # Salto simple dentro de un párrafo = corte de línea del PDF, no fin de frase.
    text = re.sub(r"(?<![\.\!\?\:;])\n(?!\n)", " ", text)
    text = _MULTI_SPACE.sub(" ", text)
    text = _MULTI_NEWLINE.sub("\n\n", text)
    return text.strip()


def detect_running_heads(
    lines_by_page: dict[int, list[str]], *, min_ratio: float = 0.4
) -> set[str]:
    """Encuentra encabezados y pies repetidos comparando entre páginas.

    Un encabezado corriente es, por definición, la misma línea corta apareciendo
    en la parte alta o baja de muchas páginas. Con menos de 4 páginas no hay
    evidencia suficiente y no se elimina nada.
    """
    pages = len(lines_by_page)
    if pages < 4:
        return set()

    candidates: Counter[str] = Counter()
    for lines in lines_by_page.values():
        if not lines:
            continue
        # Solo las 2 primeras y 2 últimas líneas pueden ser encabezado/pie.
        edges = {*lines[:2], *lines[-2:]}
        for line in edges:
            norm = _normalize_for_compare(line)
            if norm and len(norm) <= 120:
                candidates[norm] += 1

    threshold = max(3, int(pages * min_ratio))
    return {text for text, count in candidates.items() if count >= threshold}


def _normalize_for_compare(line: str) -> str:
    """Colapsa dígitos para que 'Capítulo 3 — pág 41' y '... pág 42' se igualen."""
    return re.sub(r"\d+", "#", line.strip().lower())


def clean_blocks(blocks: list[Block], running_heads: set[str] | None = None) -> list[Block]:
    """Marca (no borra) el ruido, y normaliza el texto útil.

    Se marca en vez de borrar para que el modo lectura pueda mostrarlo y solo el
    modo audiolibro lo omita. Perder información en el parser es irreversible.
    """
    heads = running_heads or set()
    cleaned: list[Block] = []

    for block in blocks:
        text = block.text.strip()
        if not text:
            continue

        if is_page_number(text):
            block.kind = BlockKind.PAGE_NUMBER
        elif _normalize_for_compare(text) in heads:
            block.kind = BlockKind.HEADER_FOOTER
        else:
            block.text = normalize_text(text)
            if not block.text:
                continue

        cleaned.append(block)

    return cleaned
