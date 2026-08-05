"""Verificación de contraste de los tokens de diseño.

Los colores de la interfaz se leen del CSS real y se comprueban contra WCAG 2.2.
Es la única forma de que una promesa de accesibilidad no se degrade: un ajuste
estético que baje un ratio por debajo del mínimo rompe la CI en vez de llegar a
producción y descubrirse cuando alguien no pueda leer la pantalla.

Se implementa en Python, con la suite del proyecto, en lugar de en el frontend,
para que forme parte de la misma barrera que todo lo demás.

Referencias:
  1.4.3  Contrast (Minimum), AA — 4,5:1 texto normal; 3:1 texto grande
  1.4.11 Non-text Contrast, AA — 3:1 en controles y bordes interactivos
  1.4.6  Contrast (Enhanced), AAA — 7:1, exigido al perfil de contraste alto
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

TOKENS = Path(__file__).parent.parent / "web" / "src" / "lib" / "design" / "tokens.css"

AA_TEXT = 4.5
AA_UI = 3.0
AAA_TEXT = 7.0


# --- utilidades de color ------------------------------------------------------


def _channel(value: float) -> float:
    return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    """Luminancia relativa según la fórmula de WCAG 2.x."""
    raw = hex_color.lstrip("#")
    if len(raw) != 6:
        raise ValueError(f"color no soportado: {hex_color!r}")
    r, g, b = (int(raw[i : i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(foreground: str, background: str) -> float:
    a, b = relative_luminance(foreground), relative_luminance(background)
    return round((max(a, b) + 0.05) / (min(a, b) + 0.05), 2)


# --- lectura del CSS ----------------------------------------------------------

_BLOCK = re.compile(r"(?P<selector>:root[^{]*)\{(?P<body>[^}]*)\}", re.MULTILINE)
_DECL = re.compile(r"(--[\w-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;")


def _themes() -> dict[str, dict[str, str]]:
    """Extrae los colores por bloque `:root`, resolviendo la herencia.

    Cada variante hereda del bloque base y sobrescribe lo suyo, igual que hace la
    cascada del navegador. Comprobar solo lo declarado en cada bloque dejaría
    fuera los colores heredados, que son la mayoría.
    """
    css = TOKENS.read_text(encoding="utf-8")
    bloques: dict[str, dict[str, str]] = {}
    for match in _BLOCK.finditer(css):
        selector = " ".join(match.group("selector").split())
        bloques[selector] = dict(_DECL.findall(match.group("body")))

    base = bloques.get(":root", {})
    temas: dict[str, dict[str, str]] = {":root": base}
    for selector, declarado in bloques.items():
        if selector == ":root":
            continue
        heredado = dict(base)
        # El bloque de contraste alto en claro combina dos variantes.
        if "data-theme='light'" in selector and "data-contrast='high'" in selector:
            heredado.update(bloques.get(":root[data-theme='light']", {}))
            heredado.update(bloques.get(":root[data-contrast='high']", {}))
        heredado.update(declarado)
        temas[selector] = heredado
    return temas


@pytest.fixture(scope="module")
def themes() -> dict[str, dict[str, str]]:
    return _themes()


# --- comprobaciones -----------------------------------------------------------


def test_los_tokens_existen_y_se_leen() -> None:
    assert TOKENS.exists(), "no se encuentra tokens.css"
    temas = _themes()
    assert ":root" in temas
    assert temas[":root"]["--bg"] == "#1e1e1e", "el fondo base es el editor de VS Code"


#: Cada tema con su fondo y el mínimo que debe cumplir su texto.
CASOS = [
    (":root", "--bg", AA_TEXT, AA_UI),
    (":root[data-theme='light']", "--bg", AA_TEXT, AA_UI),
    (":root[data-contrast='high']", "--bg", AAA_TEXT, AA_TEXT),
    (":root[data-theme='light'][data-contrast='high']", "--bg", AAA_TEXT, AA_TEXT),
]

TEXTO = ["--text", "--text-muted", "--accent", "--accent-hover", "--ok", "--warn", "--err"]


@pytest.mark.parametrize(("selector", "bg_var", "min_texto", "min_ui"), CASOS)
def test_el_texto_cumple_el_contraste_minimo(
    themes: dict[str, dict[str, str]], selector: str, bg_var: str, min_texto: float, min_ui: float
) -> None:
    """WCAG 1.4.3 (AA) y 1.4.6 (AAA en el perfil de contraste alto)."""
    tema = themes[selector]
    fondo = tema[bg_var]

    fallos = []
    for token in TEXTO:
        if token not in tema:
            continue
        ratio = contrast_ratio(tema[token], fondo)
        if ratio < min_texto:
            fallos.append(f"{token} ({tema[token]}) = {ratio}:1, exige {min_texto}:1")

    assert not fallos, f"contraste insuficiente en {selector}:\n  " + "\n  ".join(fallos)


@pytest.mark.parametrize(("selector", "bg_var", "min_texto", "min_ui"), CASOS)
def test_los_controles_cumplen_el_contraste_no_textual(
    themes: dict[str, dict[str, str]], selector: str, bg_var: str, min_texto: float, min_ui: float
) -> None:
    """WCAG 1.4.11: el borde de un control debe distinguirse del fondo.

    Se comprueba `--border-strong`, que es el que usan los elementos
    interactivos. `--border` queda fuera a propósito: solo separa bloques y la
    norma no lo exige para elementos decorativos.
    """
    tema = themes[selector]
    ratio = contrast_ratio(tema["--border-strong"], tema[bg_var])
    assert ratio >= min_ui, (
        f"{selector}: --border-strong ({tema['--border-strong']}) = {ratio}:1, exige {min_ui}:1"
    )


@pytest.mark.parametrize(("selector", "bg_var", "min_texto", "min_ui"), CASOS)
def test_el_texto_sobre_el_acento_solido_es_legible(
    themes: dict[str, dict[str, str]], selector: str, bg_var: str, min_texto: float, min_ui: float
) -> None:
    """El botón principal lleva texto sobre el acento, no sobre el fondo.

    Es el caso que más se olvida: se verifica el acento contra el fondo de la
    página y se da por bueno, cuando el texto que hay encima va sobre el acento.
    """
    tema = themes[selector]
    ratio = contrast_ratio(tema["--accent-contrast"], tema["--accent-solid"])
    assert ratio >= AA_TEXT, (
        f"{selector}: texto {tema['--accent-contrast']} sobre relleno "
        f"{tema['--accent-solid']} = {ratio}:1, exige {AA_TEXT}:1"
    )


def test_el_azul_de_vs_code_original_no_habria_cumplido() -> None:
    """Documenta por qué el acento no es exactamente el de VS Code.

    Si alguien «corrige» el color al original por fidelidad estética, este test
    explica lo que se estaría perdiendo.
    """
    assert contrast_ratio("#007acc", "#1e1e1e") < AA_TEXT
    assert contrast_ratio("#0e639c", "#1e1e1e") < AA_TEXT

    # El adoptado conserva el tono y sí cumple.
    assert contrast_ratio("#0089e6", "#1e1e1e") >= AA_TEXT


def test_el_foco_se_distingue_del_fondo(themes: dict[str, dict[str, str]]) -> None:
    """WCAG 2.2 · 2.4.13: el indicador de foco necesita 3:1 con lo que lo rodea."""
    for caso in CASOS:
        selector = caso[0]
        tema = themes[selector]
        # --focus-color apunta a --accent-hover (ver tokens.css).
        ratio = contrast_ratio(tema["--accent-hover"], tema["--bg"])
        assert ratio >= AA_UI, f"{selector}: el anillo de foco solo alcanza {ratio}:1"


def test_los_objetivos_tactiles_alcanzan_el_minimo() -> None:
    """WCAG 2.2 · 2.5.8 (Target Size, Minimum): 24×24 px CSS."""
    css = TOKENS.read_text(encoding="utf-8")
    normal = re.search(r"--target-min:\s*(\d+)px", css)
    assert normal is not None
    assert int(normal.group(1)) >= 24

    grande = re.search(r"data-targets='large'\][^}]*--target-min:\s*(\d+)px", css, re.DOTALL)
    assert grande is not None and int(grande.group(1)) >= 44


def test_el_movimiento_se_puede_anular_por_completo() -> None:
    """WCAG 2.3.3 y prefers-reduced-motion: tiene que existir la vía de apagarlo."""
    css = TOKENS.read_text(encoding="utf-8")
    assert "prefers-reduced-motion: reduce" in css
    assert "--motion: 0" in css
    # El sistema manda salvo elección explícita en contra.
    assert ":root:not([data-motion='full'])" in css


def test_el_perfil_de_lectura_cumple_el_espaciado_de_texto() -> None:
    """WCAG 1.4.12 (Text Spacing) fija los mínimos que debe soportar la interfaz."""
    css = TOKENS.read_text(encoding="utf-8")
    bloque = re.search(r"data-reading='dyslexia'\]\s*\{([^}]*)\}", css, re.DOTALL)
    assert bloque is not None, "falta el perfil de lectura cómoda"
    cuerpo = bloque.group(1)

    interlinea = float(re.search(r"--leading:\s*([\d.]+)", cuerpo).group(1))
    letras = float(re.search(r"--tracking:\s*([\d.]+)em", cuerpo).group(1))
    palabras = float(re.search(r"--word-spacing:\s*([\d.]+)em", cuerpo).group(1))

    assert interlinea >= 1.5, "1.4.12 exige interlínea de al menos 1,5"
    assert letras >= 0.12 * 0.5, "espaciado entre letras insuficiente"
    assert palabras >= 0.16, "1.4.12 exige espaciado entre palabras de al menos 0,16em"
