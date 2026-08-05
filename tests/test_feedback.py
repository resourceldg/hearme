"""Tests del circuito de retroalimentación.

Lo que se defiende aquí es que **la reputación no se pueda manipular con poco
esfuerzo** y que **todo lo que el sistema afirma se pueda auditar**. Son las dos
propiedades que separan una inteligencia colectiva de un tablón de anuncios.
"""

from __future__ import annotations

import pytest

from hearme.feedback import (
    CONFIDENT_SAMPLE,
    MAX_PER_CONTRIBUTOR,
    PRIOR_MEAN,
    Feedback,
    ReputationIndex,
    Sentiment,
    Subject,
    Tag,
    bayesian_average,
    extract_tags,
    normalize,
    suggest_adjustment,
    wilson_lower_bound,
)

# --- extracción de etiquetas --------------------------------------------------


def test_las_tildes_no_duplican_el_lexico() -> None:
    assert normalize("Robótico") == "robotico"
    assert [t.tag for t in extract_tags("suena robotico")] == [Tag.ROBOTIC]
    assert [t.tag for t in extract_tags("suena robótico")] == [Tag.ROBOTIC]


def test_se_extraen_varias_etiquetas_de_un_comentario() -> None:
    tags = {t.tag for t in extract_tags("Se oye muy robótico y va disparado")}
    assert tags == {Tag.ROBOTIC, Tag.TOO_FAST}


def test_la_negacion_invierte_la_etiqueta() -> None:
    """«No suena natural» es lo contrario de «suena natural», no lo mismo."""
    tags = {t.tag for t in extract_tags("no suena natural")}
    assert Tag.ROBOTIC in tags
    assert Tag.NATURAL not in tags


def test_la_negacion_no_alcanza_a_la_frase_siguiente() -> None:
    """Sin ventana, un «no» al principio contaminaría todo el comentario."""
    tags = {t.tag for t in extract_tags("no me convence la voz. se entiende bien")}
    assert Tag.CLEAR in tags, "la segunda frase no está negada"


def test_una_etiqueta_repetida_cuenta_una_vez() -> None:
    """Insistir en la misma idea no la hace más cierta."""
    tags = extract_tags("muy rapido, demasiado rapido, va disparado")
    assert len([t for t in tags if t.tag is Tag.TOO_FAST]) == 1


def test_lo_que_no_se_reconoce_no_se_inventa() -> None:
    assert extract_tags("buenísimo") == []
    assert extract_tags("") == []


def test_cada_etiqueta_guarda_la_evidencia_que_la_produjo() -> None:
    """Sin el fragmento, la extracción no se puede discutir ni corregir."""
    tags = extract_tags("va demasiado rapido")
    assert tags
    assert tags[0].matched
    assert tags[0].matched in normalize("va demasiado rapido")


def test_la_extraccion_se_explica_en_lenguaje_llano() -> None:
    f = Feedback(subject=Subject("piper"), comment="suena robótico y va muy rápido")
    explicacion = f.explain_tags()
    assert "robótico" in explicacion or "robotico" in explicacion
    assert "→" in explicacion


def test_toda_etiqueta_tiene_rotulo_y_sentimiento() -> None:
    for tag in Tag:
        assert tag.label.strip(), f"'{tag.value}' no tiene rótulo legible"
        assert tag.sentiment in {Sentiment.POSITIVE, Sentiment.NEGATIVE, Sentiment.NEUTRAL}


# --- señales ------------------------------------------------------------------


def test_una_valoracion_vacia_se_rechaza() -> None:
    with pytest.raises(ValueError, match="no aporta nada"):
        Feedback(subject=Subject("piper"))


def test_las_estrellas_van_de_uno_a_cinco() -> None:
    with pytest.raises(ValueError, match="estrellas"):
        Feedback(subject=Subject("piper"), stars=7)


def test_el_pulgar_se_convierte_a_estrellas_de_forma_conservadora() -> None:
    """«Me vale» no es «es excelente»: un pulgar arriba vale 4, no 5."""
    assert Feedback(subject=Subject("p"), thumbs_up=True).implicit_stars == 4.0
    assert Feedback(subject=Subject("p"), thumbs_up=False).implicit_stars == 2.0


def test_un_comentario_solo_tambien_puntua() -> None:
    """Quien se molesta en escribir aporta señal aunque no pulse nada."""
    bueno = Feedback(subject=Subject("p"), comment="muy natural y se entiende bien")
    malo = Feedback(subject=Subject("p"), comment="robótico, monótono y cansa")
    assert bueno.implicit_stars is not None and bueno.implicit_stars > 3.5
    assert malo.implicit_stars is not None and malo.implicit_stars < 3.5


# --- que pocos votos no manden ------------------------------------------------


def test_un_voto_perfecto_no_supera_a_cuarenta_buenos() -> None:
    """Es el fallo clásico de ordenar por media: premia lo poco valorado."""
    uno = bayesian_average([5.0])
    cuarenta = bayesian_average([4.3] * 40)
    assert uno < cuarenta
    assert uno < 4.0, "un solo voto no puede acercarse al máximo"


def test_sin_valoraciones_se_parte_de_la_media_previa() -> None:
    assert bayesian_average([]) == PRIOR_MEAN


def test_la_evidencia_acaba_ganando_a_la_previa() -> None:
    """Con muchos votos la media previa se vuelve irrelevante, como debe."""
    assert bayesian_average([5.0] * 200) > 4.8


def test_wilson_es_humilde_con_una_sola_muestra() -> None:
    assert wilson_lower_bound(1, 1) < 0.4, "1 de 1 no es 100% de aprobación"
    assert wilson_lower_bound(38, 40) > 0.75


def test_wilson_sin_muestras_no_revienta() -> None:
    assert wilson_lower_bound(0, 0) == 0.0


def test_una_persona_no_puede_votar_sin_limite() -> None:
    """Sin tope, quien insista decide por todos los demás."""
    idx = ReputationIndex()
    sujeto = Subject("piper", "voz")
    for _ in range(20):
        idx.add(Feedback(subject=sujeto, stars=5, contributor="el-insistente"))

    reputacion = idx.of(sujeto)
    assert reputacion.samples == MAX_PER_CONTRIBUTOR
    assert reputacion.contributors == 1


def test_muchas_personas_pesan_mas_que_una_insistente() -> None:
    idx = ReputationIndex()
    a, b = Subject("piper", "insistente"), Subject("piper", "consensuada")
    for _ in range(20):
        idx.add(Feedback(subject=a, stars=5, contributor="uno-solo"))
    for i in range(15):
        idx.add(Feedback(subject=b, stars=4, contributor=f"persona{i}"))

    assert idx.of(b).score > idx.of(a).score


# --- reputación por sujeto ----------------------------------------------------


def test_la_valoracion_se_propaga_a_los_sujetos_mas_generales() -> None:
    """Valorar (motor, voz, estilo) también dice algo del motor."""
    idx = ReputationIndex()
    idx.add(Feedback(subject=Subject("piper", "voz", "novel", "es"), stars=5, contributor="ana"))
    assert idx.of(Subject("piper")).samples == 1
    assert idx.of(Subject("piper", "voz")).samples == 1


def test_un_estilo_malo_no_hunde_a_la_voz_en_los_demas_estilos() -> None:
    """«Esta voz es mala» y «esta voz con este estilo es mala» son cosas distintas."""
    idx = ReputationIndex()
    for i in range(10):
        idx.add(
            Feedback(subject=Subject("piper", "voz", "poetry", "es"), stars=1, contributor=f"p{i}")
        )
    # El sujeto concreto se hunde…
    assert idx.of(Subject("piper", "voz", "poetry", "es")).score < 2.5
    # …pero otro estilo de la misma voz no tiene esas valoraciones.
    assert idx.of(Subject("piper", "voz", "novel", "es")).samples == 0


# --- explicabilidad -----------------------------------------------------------


def test_toda_reputacion_puede_decir_de_que_esta_hecha() -> None:
    """Una recomendación que no se puede interrogar es una imposición."""
    idx = ReputationIndex()
    sujeto = Subject("piper", "voz")
    for i in range(5):
        idx.add(Feedback(subject=sujeto, stars=4, comment="muy natural", contributor=f"p{i}"))

    explicacion = idx.of(sujeto).explain()
    assert "5 valoraciones" in explicacion
    assert "personas" in explicacion
    assert "natural" in explicacion


def test_se_avisa_cuando_hay_pocas_valoraciones() -> None:
    idx = ReputationIndex()
    sujeto = Subject("piper", "voz")
    idx.add(Feedback(subject=sujeto, stars=5, contributor="ana"))

    reputacion = idx.of(sujeto)
    assert not reputacion.is_confident
    assert "pocas" in reputacion.explain()


def test_sin_valoraciones_se_dice_claramente() -> None:
    explicacion = ReputationIndex().of(Subject("piper")).explain()
    assert "nadie la ha valorado" in explicacion


def test_con_suficientes_valoraciones_deja_de_ser_provisional() -> None:
    idx = ReputationIndex()
    sujeto = Subject("piper", "voz")
    for i in range(CONFIDENT_SAMPLE):
        idx.add(Feedback(subject=sujeto, stars=4, contributor=f"p{i}"))
    assert idx.of(sujeto).is_confident


# --- del comentario al ajuste -------------------------------------------------


def test_una_queja_frecuente_se_convierte_en_ajuste_concreto() -> None:
    """Es el puente entre «dicen que va rápido» y «baja el ritmo un 10%»."""
    idx = ReputationIndex()
    sujeto = Subject("piper", "voz", "novel", "es")
    for i in range(8):
        idx.add(Feedback(subject=sujeto, stars=3, comment="va muy rapido", contributor=f"p{i}"))

    problemas = idx.problems_of(sujeto)
    assert any(p.tag is Tag.TOO_FAST for p in problemas)
    assert suggest_adjustment(problemas) == {"rate_scale": 0.9}


def test_una_queja_aislada_no_dispara_ajustes() -> None:
    """Un comentario entre veinte no es una señal, es una opinión."""
    idx = ReputationIndex()
    sujeto = Subject("piper", "voz", "novel", "es")
    idx.add(Feedback(subject=sujeto, stars=2, comment="va muy rapido", contributor="ana"))
    for i in range(19):
        idx.add(Feedback(subject=sujeto, stars=5, comment="muy natural", contributor=f"p{i}"))

    assert suggest_adjustment(idx.problems_of(sujeto)) == {}


def test_los_ajustes_son_pequenos() -> None:
    """Una corrección automática que se pase de frenada es peor que ninguna."""
    from hearme.feedback.reputation import TagSummary

    for tag in (Tag.TOO_FAST, Tag.TOO_SLOW, Tag.BAD_PAUSES, Tag.MONOTONE):
        ajuste = suggest_adjustment([TagSummary(tag=tag, count=10, share=0.5)])
        for valor in ajuste.values():
            assert 0.85 <= valor <= 1.25, f"{tag.value} propone un salto excesivo: {valor}"


def test_se_puede_elegir_la_mejor_para_un_uso_concreto() -> None:
    """«La mejor para novela» y «la mejor en general» son preguntas distintas."""
    idx = ReputationIndex()
    general = Subject("kokoro", "generalista")
    novelesca = Subject("piper", "novelera")

    for i in range(10):
        idx.add(Feedback(subject=general, stars=5, contributor=f"g{i}"))
    for i in range(10):
        idx.add(
            Feedback(subject=novelesca, stars=4, comment="ideal para novela", contributor=f"n{i}")
        )

    mejor_general, _ = idx.best_for([general, novelesca])
    mejor_novela, _ = idx.best_for([general, novelesca], prefer_tag=Tag.GOOD_FOR_NOVEL)

    assert mejor_general == general
    assert mejor_novela == novelesca


# --- privacidad ---------------------------------------------------------------


def test_la_valoracion_no_lleva_ni_documento_ni_texto() -> None:
    """El sujeto es una configuración, nunca una obra."""
    f = Feedback(subject=Subject("piper", "voz", "novel", "es"), stars=4, comment="bien")
    datos = f.to_dict()

    assert set(datos["subject"]) == {"engine", "voice", "style", "language"}
    assert "document" not in datos
    assert "text" not in datos


def test_el_comentario_original_se_conserva_junto_a_las_etiquetas() -> None:
    """Las etiquetas son una ayuda, no la verdad: el original manda."""
    original = "va rapidísimo pero me encanta el timbre"
    f = Feedback(subject=Subject("piper"), stars=4, comment=original)
    assert f.to_dict()["comment"] == original
