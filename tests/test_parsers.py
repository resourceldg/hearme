"""Tests de parsers y detección de idioma."""

from __future__ import annotations

from pathlib import Path

import pytest

from hearme.application.language import detect_language
from hearme.domain.models import BlockKind, SourceFormat
from hearme.infrastructure.parsers.text import MarkdownParser, PlainTextParser

MARKDOWN = """# Título del libro

Párrafo introductorio con suficiente longitud.

## Capítulo primero

El contenido del primer capítulo.

> Una cita memorable.

- Punto uno
- Punto dos

```python
print("no se narra")
```

## Capítulo segundo

Más contenido aquí.
"""


@pytest.fixture
def md_file(tmp_path: Path) -> Path:
    path = tmp_path / "libro.md"
    path.write_text(MARKDOWN, encoding="utf-8")
    return path


async def test_markdown_construye_capitulos(md_file: Path) -> None:
    document = await MarkdownParser().parse(md_file)

    assert document.source_format is SourceFormat.MARKDOWN
    titles = [c.title for c in document.chapters]
    assert "Capítulo primero" in titles
    assert "Capítulo segundo" in titles


async def test_markdown_preserva_tipos_semanticos(md_file: Path) -> None:
    kinds = {block.kind for block in (await MarkdownParser().parse(md_file)).blocks}

    assert BlockKind.HEADING in kinds
    assert BlockKind.QUOTE in kinds
    assert BlockKind.LIST_ITEM in kinds
    assert BlockKind.CODE in kinds


async def test_el_codigo_no_cuenta_como_narrable(md_file: Path) -> None:
    document = await MarkdownParser().parse(md_file)
    code = [b for b in document.blocks if b.kind is BlockKind.CODE]

    assert code
    assert 'print("no se narra")' in code[0].text


async def test_texto_plano_divide_por_parrafos(tmp_path: Path) -> None:
    path = tmp_path / "nota.txt"
    path.write_text("Primer párrafo.\n\nSegundo párrafo.\n\nTercero.", encoding="utf-8")

    document = await PlainTextParser().parse(path)

    assert len(document.chapters) == 1
    assert len(document.chapters[0].blocks) == 3
    assert document.meta.title == "nota"


async def test_documento_calcula_duracion_estimada(md_file: Path) -> None:
    document = await MarkdownParser().parse(md_file)
    assert document.estimated_duration_s() > 0


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "El tiempo se bifurca perpetuamente hacia innumerables futuros y en uno "
            "de ellos soy su enemigo, pero en la mayoría de los casos no lo soy.",
            "es",
        ),
        (
            "The time forks perpetually toward innumerable futures and in one of "
            "them I am your enemy, but in most of the cases I am not.",
            "en",
        ),
        (
            "Le temps se ramifie perpétuellement vers d'innombrables futurs et dans "
            "l'un de ces futurs je suis votre ennemi, mais pas dans les autres.",
            "fr",
        ),
    ],
)
def test_detecta_idioma(text: str, expected: str) -> None:
    assert detect_language(text) == expected


def test_texto_demasiado_corto_devuelve_el_valor_por_defecto() -> None:
    assert detect_language("Hola.", default="es") == "es"
