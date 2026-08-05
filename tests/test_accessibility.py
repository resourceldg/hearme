"""Auditoría de accesibilidad sobre el HTML **realmente renderizado**.

## Por qué sobre el HTML y no sobre el código fuente

Analizar los `.svelte` diría qué escribimos; analizar la salida dice qué recibe
la tecnología de asistencia. Un lector de pantalla no lee componentes: lee el
árbol de accesibilidad que el navegador construye a partir de este HTML. Si
auditamos otra cosa, auditamos nuestras intenciones.

El test levanta el servidor de producción (`node build`), pide la página y la
analiza. Si no hay build, se salta con un aviso claro en vez de fingir que pasó.

## Qué puede y qué no puede comprobar esto

**Puede:** que existan los puntos de referencia, que la jerarquía de encabezados
no salte niveles, que todo control tenga nombre accesible, que no haya ARIA
inventada ni contradictoria, que nada interactivo quede fuera del teclado.

**No puede:** cómo suena. Que un botón tenga `aria-label="Cerrar"` no significa
que en contexto se entienda qué se cierra. El orden de lectura, la verbosidad, si
un anuncio llega tarde o interrumpe: eso solo lo dice una persona usando NVDA,
JAWS, VoiceOver, TalkBack, Narrator u Orca.

Estas comprobaciones son el **suelo**, no el techo. Sirven para que ningún fallo
mecánico llegue a las sesiones de validación con personas y les haga perder el
tiempo en algo que una máquina podía haber cazado. El techo está en
`docs/ASSISTIVE-TECHNOLOGY.md`.
"""

from __future__ import annotations

import itertools
import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

WEB = Path(__file__).parent.parent / "web"
BUILD = WEB / "build" / "index.js"

#: Roles que exponen un control operable. Todos necesitan nombre accesible.
INTERACTIVE_ROLES = {"button", "link", "checkbox", "radio", "switch", "tab", "menuitem"}

#: Elementos que son interactivos por naturaleza, sin necesidad de rol explícito.
INTERACTIVE_TAGS = {"a", "button", "input", "select", "textarea", "summary", "details"}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def rendered_html() -> str:
    """HTML de la portada, servido por el build de producción."""
    pytest.importorskip("bs4", reason="se necesita beautifulsoup4 para auditar el DOM")
    if not BUILD.exists():
        pytest.skip("no hay build del frontend: ejecuta `npm run build` en web/")
    if shutil.which("node") is None:
        pytest.skip("node no está disponible")

    import urllib.error
    import urllib.request

    port = _free_port()
    proceso = subprocess.Popen(
        ["node", "build"],
        cwd=WEB,
        env={**os.environ, "PORT": str(port), "HOST": "127.0.0.1"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        # El arranque de adapter-node es rápido, pero no instantáneo.
        for _ in range(50):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1) as r:
                    return r.read().decode("utf-8")
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                time.sleep(0.2)
        pytest.skip("el servidor del frontend no respondió a tiempo")
    finally:
        proceso.terminate()
        proceso.wait(timeout=10)


@pytest.fixture(scope="module")
def soup(rendered_html: str):
    from bs4 import BeautifulSoup

    return BeautifulSoup(rendered_html, "html.parser")


# --- utilidades ---------------------------------------------------------------


def accessible_name(element, soup) -> str:
    """Nombre accesible aproximado, siguiendo el orden de precedencia de ARIA.

    Es una aproximación: el algoritmo real (accname) es considerablemente más
    complejo. Cubre los casos que de verdad se dan aquí y, sobre todo, detecta
    el fallo habitual —un control sin nombre ninguno—, que es el que deja a
    alguien oyendo «botón, botón, botón» sin saber qué hace cada uno.
    """
    if labelledby := element.get("aria-labelledby"):
        textos = []
        for ref in labelledby.split():
            if destino := soup.find(id=ref):
                textos.append(destino.get_text(" ", strip=True))
        if textos:
            return " ".join(textos)

    if etiqueta := element.get("aria-label"):
        return etiqueta.strip()

    if element.name == "input":
        if element.get("id") and (lab := soup.find("label", attrs={"for": element["id"]})):
            return lab.get_text(" ", strip=True)
        if padre := element.find_parent("label"):
            return padre.get_text(" ", strip=True)
        if element.get("type") in {"submit", "button"}:
            return (element.get("value") or "").strip()

    if element.name == "img":
        return (element.get("alt") or "").strip()

    # Texto propio, ignorando lo marcado como decorativo.
    copia = element.__copy__()
    for oculto in copia.find_all(attrs={"aria-hidden": "true"}):
        oculto.decompose()
    return copia.get_text(" ", strip=True)


# --- documento ----------------------------------------------------------------


def test_el_documento_declara_su_idioma(soup) -> None:
    """WCAG 3.1.1. Sin esto, un lector de pantalla puede leer español con voz inglesa."""
    html = soup.find("html")
    assert html is not None and html.get("lang"), "falta el atributo lang en <html>"
    assert re.match(r"^[a-z]{2}(-[A-Za-z]{2,})?$", html["lang"]), (
        f"lang mal formado: {html['lang']!r}"
    )


def test_el_documento_tiene_titulo(soup) -> None:
    """WCAG 2.4.2. Es lo primero que anuncia un lector al cargar la página."""
    titulo = soup.find("title")
    assert titulo is not None and titulo.get_text(strip=True)


def test_existen_los_puntos_de_referencia(soup) -> None:
    """WCAG 1.3.6 y 2.4.1: navegar por landmarks es el atajo principal de un lector.

    Sin ellos, la única forma de recorrer la página es leerla entera, y en una
    interfaz con tres secciones eso significa escuchar la cabecera cada vez.
    """
    assert soup.find("main") or soup.find(attrs={"role": "main"}), "falta el landmark main"
    assert soup.find("header") or soup.find(attrs={"role": "banner"}), "falta la cabecera"


def test_hay_un_solo_encabezado_de_nivel_uno(soup) -> None:
    """Dos h1 dejan sin respuesta la pregunta «¿de qué va esta página?»."""
    h1s = soup.find_all("h1")
    assert len(h1s) == 1, f"se esperaba un solo <h1>, hay {len(h1s)}"


def test_la_jerarquia_de_encabezados_no_salta_niveles(soup) -> None:
    """WCAG 1.3.1: saltar de h1 a h3 rompe la navegación por encabezados."""
    niveles = [int(h.name[1]) for h in soup.find_all(re.compile(r"^h[1-6]$"))]
    assert niveles, "la página no tiene encabezados"

    for anterior, actual in itertools.pairwise(niveles):
        assert actual <= anterior + 1, (
            f"salto de h{anterior} a h{actual}: la jerarquía debe descender de uno en uno"
        )


def test_existe_un_enlace_para_saltar_al_contenido(soup) -> None:
    """WCAG 2.4.1 (Bypass Blocks) y su destino debe existir de verdad."""
    salto = soup.find("a", href=re.compile(r"^#"))
    assert salto is not None, "falta el enlace de salto al contenido"

    destino = salto["href"][1:]
    assert soup.find(id=destino) is not None, (
        f"el enlace de salto apunta a #{destino}, que no existe en la página"
    )


# --- controles ----------------------------------------------------------------


def test_todo_control_tiene_nombre_accesible(soup) -> None:
    """WCAG 4.1.2. Es el fallo que más incapacita: «botón» sin decir cuál.

    Se excluyen los controles ocultos a la tecnología de asistencia, que por
    definición no se anuncian.
    """
    sin_nombre = []
    for elemento in soup.find_all(["button", "a", "select", "textarea"]):
        if elemento.get("aria-hidden") == "true":
            continue
        if elemento.find_parent(attrs={"aria-hidden": "true"}):
            continue
        if elemento.name == "a" and not elemento.get("href"):
            continue
        if not accessible_name(elemento, soup):
            sin_nombre.append(str(elemento)[:120])

    assert not sin_nombre, "controles sin nombre accesible:\n  " + "\n  ".join(sin_nombre)


def test_todo_campo_de_formulario_esta_etiquetado(soup) -> None:
    """WCAG 3.3.2. Un campo sin etiqueta se anuncia como «edición, en blanco»."""
    sin_etiqueta = []
    for campo in soup.find_all("input"):
        if campo.get("type") in {"hidden", "submit", "button", "reset"}:
            continue
        if not accessible_name(campo, soup):
            sin_etiqueta.append(str(campo)[:120])

    assert not sin_etiqueta, "campos sin etiqueta:\n  " + "\n  ".join(sin_etiqueta)


def test_los_iconos_decorativos_se_ocultan(soup) -> None:
    """Un SVG sin `aria-hidden` ni título se anuncia como «gráfico» y estorba.

    Cada icono decorativo audible es una interrupción; en una lista de diez
    trabajos, diez interrupciones.
    """
    ruidosos = []
    for svg in soup.find_all("svg"):
        oculto = svg.get("aria-hidden") == "true" or svg.find_parent(attrs={"aria-hidden": "true"})
        tiene_nombre = svg.get("aria-label") or svg.find("title")
        if not oculto and not tiene_nombre:
            ruidosos.append(str(svg)[:100])

    assert not ruidosos, (
        "SVG que se anunciarán sin aportar nada. Ponles aria-hidden='true' "
        "o dales un nombre:\n  " + "\n  ".join(ruidosos)
    )


# --- ARIA ---------------------------------------------------------------------

#: Roles usados en la interfaz. Inventar un rol lo deja sin efecto y engaña al
#: siguiente que lea el código creyendo que hace algo.
VALID_ROLES = {
    "alert",
    "banner",
    "button",
    "checkbox",
    "complementary",
    "contentinfo",
    "dialog",
    "document",
    "form",
    "group",
    "heading",
    "img",
    "link",
    "list",
    "listitem",
    "main",
    "menu",
    "menuitem",
    "navigation",
    "none",
    "presentation",
    "progressbar",
    "radio",
    "radiogroup",
    "region",
    "search",
    "separator",
    "status",
    "switch",
    "tab",
    "tablist",
    "tabpanel",
    "textbox",
    "toolbar",
}


def test_no_hay_roles_inventados(soup) -> None:
    invalidos = {
        r for e in soup.find_all(attrs={"role": True}) for r in e["role"].split()
    } - VALID_ROLES
    assert not invalidos, f"roles ARIA que no existen: {sorted(invalidos)}"


def test_las_referencias_aria_apuntan_a_algo_real(soup) -> None:
    """Un `aria-labelledby` roto no degrada: deja el elemento sin nombre.

    Y falla en silencio, que es lo peor: la interfaz se ve bien y solo quien
    depende del lector descubre que ese botón no dice nada.
    """
    rotas = []
    for atributo in ("aria-labelledby", "aria-describedby", "aria-controls"):
        for elemento in soup.find_all(attrs={atributo: True}):
            for ref in elemento[atributo].split():
                if soup.find(id=ref) is None:
                    rotas.append(f"{atributo}='{ref}' en <{elemento.name}>")

    assert not rotas, "referencias ARIA que no llevan a ningún sitio:\n  " + "\n  ".join(rotas)


def test_los_estados_aria_son_validos(soup) -> None:
    """`aria-expanded="0"` no es válido y se ignora. Solo valen true y false."""
    invalidos = []
    for atributo in ("aria-expanded", "aria-checked", "aria-pressed", "aria-modal", "aria-hidden"):
        for elemento in soup.find_all(attrs={atributo: True}):
            valor = elemento[atributo]
            if valor not in {"true", "false", "mixed", "undefined"}:
                invalidos.append(f"{atributo}='{valor}' en <{elemento.name}>")

    assert not invalidos, "estados ARIA no válidos:\n  " + "\n  ".join(invalidos)


def test_las_barras_de_progreso_declaran_su_rango(soup) -> None:
    """Sin `aria-valuemin`/`max`, un lector no puede decir «al 40%»."""
    for barra in soup.find_all(attrs={"role": "progressbar"}):
        assert barra.get("aria-valuemin") is not None, "progressbar sin aria-valuemin"
        assert barra.get("aria-valuemax") is not None, "progressbar sin aria-valuemax"
        assert accessible_name(barra, soup), "progressbar sin nombre accesible"


def test_existe_una_region_viva_para_los_cambios_de_estado(soup) -> None:
    """WCAG 4.1.3: un cambio que no mueve el foco tiene que anunciarse igual.

    `polite` y no `assertive`: un progreso que interrumpe cada dos segundos es
    peor que no anunciarlo.
    """
    vivas = soup.find_all(attrs={"aria-live": True})
    assert vivas, "no hay ninguna región aria-live"
    assert any(v["aria-live"] == "polite" for v in vivas), (
        "las actualizaciones de progreso deben ser 'polite', nunca 'assertive'"
    )


# --- teclado ------------------------------------------------------------------


def test_nada_interactivo_queda_fuera_del_teclado(soup) -> None:
    """WCAG 2.1.1: `tabindex='-1'` fuera de un patrón de foco móvil aísla el control."""
    aislados = []
    for elemento in soup.find_all(attrs={"tabindex": True}):
        if elemento.get("tabindex") != "-1":
            continue
        # Legítimo dentro de radiogroup/tablist (roving tabindex) y en destinos
        # de foco programático.
        if elemento.get("role") in {"radio", "tab", "option"}:
            continue
        if elemento.name in INTERACTIVE_TAGS or elemento.get("role") in INTERACTIVE_ROLES:
            aislados.append(str(elemento)[:120])

    assert not aislados, "controles inalcanzables por teclado:\n  " + "\n  ".join(aislados)


def test_no_se_fuerza_el_orden_de_tabulacion(soup) -> None:
    """Un `tabindex` positivo rompe el orden natural del documento.

    Se desincroniza del orden visual en cuanto alguien reordena algo, y a partir
    de ahí el recorrido por teclado deja de tener sentido.
    """
    positivos = [
        str(e)[:100]
        for e in soup.find_all(attrs={"tabindex": True})
        if e["tabindex"].lstrip("-").isdigit() and int(e["tabindex"]) > 0
    ]
    assert not positivos, "tabindex positivo:\n  " + "\n  ".join(positivos)


def test_un_grupo_de_radios_solo_tiene_un_punto_de_entrada(soup) -> None:
    """Patrón de foco móvil: se entra una vez y se recorre con flechas.

    Con cinco opciones tabulables, atravesar un grupo cuesta cinco pulsaciones.
    Es la fricción que hace abandonar la navegación por teclado.
    """
    for grupo in soup.find_all(attrs={"role": "radiogroup"}):
        radios = grupo.find_all(attrs={"role": "radio"})
        if not radios:
            continue
        tabulables = [r for r in radios if r.get("tabindex") != "-1"]
        assert len(tabulables) == 1, (
            f"un radiogroup con {len(radios)} opciones tiene {len(tabulables)} "
            "puntos de tabulación; debe tener exactamente uno"
        )


def test_los_controles_que_despliegan_declaran_su_estado(soup) -> None:
    """Sin `aria-expanded`, quien no ve la pantalla no sabe si ya está abierto."""
    for boton in soup.find_all("button", attrs={"aria-controls": True}):
        assert boton.get("aria-expanded") is not None, (
            f"<button aria-controls='{boton['aria-controls']}'> sin aria-expanded"
        )


# --- comprobación de que la auditoría no se está engañando --------------------


def test_la_auditoria_analiza_la_pagina_de_verdad(soup) -> None:
    """Red de seguridad: si el HTML llegara vacío, todo lo anterior pasaría solo."""
    assert soup.find("h1") is not None
    assert len(soup.find_all("button")) >= 3, "la portada tiene varios botones; algo falla"
    assert "HearMe" in soup.get_text()
