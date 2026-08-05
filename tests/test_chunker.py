"""Tests de segmentación prosódica."""

from __future__ import annotations

import pytest

from hearme.application.chunker import MAX_CHARS, chunk_chapter, split_sentences
from hearme.domain.models import Block, BlockKind, Chapter, NarrationStyle


def test_separa_frases() -> None:
    frases = split_sentences("Primera frase. Segunda frase. ¿Tercera? Sí.")
    assert len(frases) == 4


def test_no_corta_en_abreviaturas() -> None:
    assert len(split_sentences("El Dr. Ramírez llegó tarde.")) == 1


def test_respeta_signos_de_apertura_del_espanol() -> None:
    frases = split_sentences("Llegó. ¿Quién era? ¡Nadie!")
    assert len(frases) == 3


def _chapter(*blocks: Block) -> Chapter:
    return Chapter(title="t", order=0, blocks=list(blocks))


def test_ningun_fragmento_supera_el_limite() -> None:
    largo = " ".join(f"Frase número {i} con contenido." for i in range(200))
    chapter = _chapter(Block(kind=BlockKind.PARAGRAPH, text=largo, order=0))
    utterances = chunk_chapter(chapter)

    assert utterances
    assert all(len(u.text) <= MAX_CHARS for u in utterances)


def test_frase_unica_gigante_se_parte_igualmente() -> None:
    # Sin puntuación terminal: el troceo debe caer al corte por comas / ventana.
    chapter = _chapter(Block(kind=BlockKind.PARAGRAPH, text="palabra " * 500, order=0))
    assert all(len(u.text) <= MAX_CHARS for u in chunk_chapter(chapter))


def test_encabezado_recibe_pausa_larga_y_enfasis() -> None:
    chapter = _chapter(Block(kind=BlockKind.HEADING, text="Capítulo uno", order=0, level=1))
    utterance = chunk_chapter(chapter, style=NarrationStyle.NOVEL)[0]

    assert utterance.pause_after_ms == 1200
    assert utterance.emphasis > 1.0


def test_poesia_pausa_mas_y_lee_mas_lento_que_tecnico() -> None:
    block = Block(kind=BlockKind.PARAGRAPH, text="Un verso suelto.", order=0)
    poesia = chunk_chapter(_chapter(block), style=NarrationStyle.POETRY)[0]
    tecnico = chunk_chapter(_chapter(block), style=NarrationStyle.TECHNICAL)[0]

    assert poesia.pause_after_ms > tecnico.pause_after_ms
    assert poesia.rate < tecnico.rate


def test_omite_codigo_y_ruido() -> None:
    chapter = _chapter(
        Block(kind=BlockKind.CODE, text="print('hola')", order=0),
        Block(kind=BlockKind.PAGE_NUMBER, text="42", order=1),
        Block(kind=BlockKind.PARAGRAPH, text="Texto narrable.", order=2),
    )
    utterances = chunk_chapter(chapter)

    assert len(utterances) == 1
    assert utterances[0].text == "Texto narrable."


def test_usa_la_traduccion_cuando_existe() -> None:
    block = Block(kind=BlockKind.PARAGRAPH, text="Hello world.", order=0)
    block.translated = "Hola mundo."
    assert chunk_chapter(_chapter(block))[0].text == "Hola mundo."


def test_el_orden_es_continuo_entre_capitulos() -> None:
    chapter = _chapter(Block(kind=BlockKind.PARAGRAPH, text="Uno. Dos. Tres.", order=0))
    primero = chunk_chapter(chapter)
    segundo = chunk_chapter(chapter, start_order=len(primero))

    assert [u.order for u in segundo] == list(range(len(primero), len(primero) * 2))


def test_no_corta_en_iniciales() -> None:
    assert len(split_sentences("Leí a J. R. R. Tolkien anoche.")) == 1


def test_las_siglas_no_bloquean_el_corte() -> None:
    # "CIA." sí cierra frase: la A no va precedida de frontera de palabra.
    assert len(split_sentences("Trabajó en la CIA. Luego se retiró.")) == 2


def test_abreviaturas_variadas() -> None:
    assert len(split_sentences("Vive en la Av. Central desde 1990.")) == 1
    assert len(split_sentences("Manzanas, peras, etc. Todo estaba allí.")) == 1


def test_el_estilo_llega_al_motor_de_voz() -> None:
    """El estilo de narración no puede quedarse en el `Utterance`.

    Piper ignoraba `rate` y `emphasis`: los cuatro estilos sonaban idénticos
    salvo por la duración de las pausas. La configuración de síntesis es el
    puente entre el estilo elegido en la interfaz y lo que se oye.
    """
    from hearme.domain.models import Utterance
    from hearme.infrastructure.tts.piper import _MAKEUP_GAIN, PiperEngine

    def utterance(**kwargs) -> Utterance:
        return Utterance(text="hola", order=0, chapter_id="c", block_id="b", **kwargs)

    lenta = PiperEngine._synthesis_config(utterance(rate=0.88))
    normal = PiperEngine._synthesis_config(utterance(rate=1.0))
    if lenta is None:  # Piper no instalado: nada que comprobar
        pytest.skip("piper no está instalado")

    # length_scale es el inverso de la velocidad: más lento = fonemas más largos.
    assert lenta.length_scale > normal.length_scale

    # El énfasis de los títulos tiene que traducirse en volumen…
    titulo = PiperEngine._synthesis_config(utterance(emphasis=1.15))
    assert titulo.volume > normal.volume

    # …y para eso la normalización debe estar desactivada, o se borra.
    assert normal.normalize_audio is False
    assert normal.volume == pytest.approx(_MAKEUP_GAIN)
