"""Tests de limpieza de ruido editorial."""

from __future__ import annotations

import pytest

from hearme.application.cleaning import (
    clean_blocks,
    detect_running_heads,
    is_page_number,
    normalize_text,
)
from hearme.domain.models import Block, BlockKind


@pytest.mark.parametrize(
    "text",
    ["12", "  42  ", "- 7 -", "[123]", "Página 15", "page 3", "xiv", "12 / 340"],
)
def test_reconoce_numeros_de_pagina(text: str) -> None:
    assert is_page_number(text)


@pytest.mark.parametrize(
    "text",
    ["Capítulo 12", "En 1984 ocurrió algo", "12 personas llegaron", "", "El fin"],
)
def test_no_confunde_texto_con_numero_de_pagina(text: str) -> None:
    assert not is_page_number(text)


def test_une_palabras_cortadas_por_guion() -> None:
    assert "continuación" in normalize_text("conti-\nnuación del texto")


def test_deshace_ligaduras_tipograficas() -> None:
    assert normalize_text("la ﬁgura y el ﬂujo") == "la figura y el flujo"


def test_salto_simple_no_rompe_parrafo() -> None:
    # Un salto de línea sin puntuación es un corte de maquetado, no de frase.
    assert normalize_text("una frase\nque sigue") == "una frase que sigue"


def test_salto_tras_punto_se_conserva_como_parrafo() -> None:
    assert "\n" in normalize_text("Fin de frase.\n\nOtro párrafo.")


def test_detecta_encabezado_repetido_entre_paginas() -> None:
    pages = {n: ["Historia de la ciencia", f"cuerpo {n}", f"{n}"] for n in range(1, 11)}
    heads = detect_running_heads(pages)
    assert "historia de la ciencia" in heads


def test_ignora_numeros_variables_al_comparar_encabezados() -> None:
    # 'Capítulo 3 pág 41' y 'Capítulo 3 pág 42' son el mismo encabezado corriente.
    pages = {n: [f"Capitulo 3 pag {n}", "cuerpo"] for n in range(1, 11)}
    assert "capitulo # pag #" in detect_running_heads(pages)


def test_pocas_paginas_no_generan_falsos_positivos() -> None:
    pages = {n: ["Título", "cuerpo"] for n in range(1, 4)}
    assert detect_running_heads(pages) == set()


def test_clean_blocks_marca_pero_no_borra() -> None:
    blocks = [
        Block(kind=BlockKind.PARAGRAPH, text="Texto real y suficiente.", order=0),
        Block(kind=BlockKind.PARAGRAPH, text="42", order=1),
    ]
    cleaned = clean_blocks(blocks)

    # El ruido sigue presente (el modo lectura lo muestra) pero reclasificado.
    assert len(cleaned) == 2
    assert cleaned[1].kind is BlockKind.PAGE_NUMBER
    assert not cleaned[1].is_narrated
    assert cleaned[0].is_narrated
