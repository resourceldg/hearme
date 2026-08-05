"""Tests del catálogo de voces, el plan de escucha y el recomendador.

Lo que se defiende aquí es que **los seis conceptos no se vuelvan a mezclar**.
La confusión que este módulo vino a resolver —traducción como casilla en vez de
consecuencia, voz de un idioma distinto al que se escucha— es del tipo que
reaparece en cuanto alguien añade un campo con prisa.
"""

from __future__ import annotations

import pytest

from hearme.domain.models import NarrationStyle
from hearme.narration.director import _PAUSES, _RATES
from hearme.narration.plan import (
    LOW_CONFIDENCE,
    ListeningPlan,
    estimate_minutes,
    plan_to_request_kwargs,
    recommend,
    suggest_style,
    validate,
)
from hearme.narration.voices import (
    Gender,
    Quality,
    VoiceCatalog,
    VoiceProfile,
    parse_kokoro,
    parse_piper,
    sample_text_for,
)

# --- catálogo -----------------------------------------------------------------


def test_los_metadatos_de_kokoro_salen_del_nombre() -> None:
    """`af_heart` es femenina y estadounidense, y eso lo dice su propio nombre."""
    idioma, genero, acento, nombre = parse_kokoro("af_heart")
    assert (idioma, genero, acento, nombre) == ("en", Gender.FEMALE, "estadounidense", "Heart")

    idioma, genero, acento, _ = parse_kokoro("em_alex")
    assert (idioma, genero, acento) == ("es", Gender.MALE, "español")

    # Británica, no estadounidense: la primera letra distingue el acento.
    assert parse_kokoro("bf_emma")[2] == "británico"


def test_los_metadatos_de_piper_salen_del_nombre() -> None:
    idioma, region, calidad, nombre, _ = parse_piper("es_ES-sharvard-medium")
    assert (idioma, region, calidad, nombre) == ("es", "España", Quality.MEDIUM, "Sharvard")

    assert parse_piper("it_IT-riccardo-x_low")[2] is Quality.LOW


def test_un_nombre_que_no_sigue_el_convenio_no_revienta() -> None:
    """Un plugin puede nombrar sus voces como quiera."""
    idioma, region, calidad, nombre, genero = parse_piper("voz-rara")
    assert idioma == "" and region == ""
    assert nombre  # algo legible, no una excepción
    assert genero is Gender.UNKNOWN


def test_el_genero_del_hablante_sale_del_indice_oficial() -> None:
    """No se adivina: `speaker_id_map` de piper-voices lo declara como M y F."""
    assert parse_piper("es_ES-sharvard-medium#F")[4] is Gender.FEMALE
    assert parse_piper("es_ES-sharvard-medium#M")[4] is Gender.MALE
    assert parse_piper("uk_UA-ukrainian_tts-medium#lada")[4] is Gender.FEMALE
    assert parse_piper("uk_UA-ukrainian_tts-medium#mykyta")[4] is Gender.MALE


def test_el_genero_de_un_modelo_de_un_hablante_sale_de_la_tabla_declarada() -> None:
    """Ni el nombre ni el índice oficial lo publican: es una tabla escrita a mano."""
    assert parse_piper("de_DE-thorsten-medium")[4] is Gender.MALE
    assert parse_piper("ca_ES-upc_ona-medium")[4] is Gender.FEMALE


def test_sin_señal_fiable_el_genero_queda_desconocido() -> None:
    """Etiquetar mal a alguien es peor que no etiquetarlo.

    Estas voces no identifican a nadie ni en su nombre ni en su documentación.
    """
    for voz in ("sv_SE-nst-medium", "tr_TR-dfki-medium", "nl_NL-mls-medium"):
        assert parse_piper(voz)[4] is Gender.UNKNOWN, f"'{voz}' no debería tener género"

    perfil = VoiceProfile(id="sv_SE-nst-medium", engine="piper", language="sv", display_name="Nst")
    assert "femenina" not in perfil.describe()
    assert "masculina" not in perfil.describe()


def test_un_modelo_con_dos_hablantes_son_dos_voces() -> None:
    """El español de Piper trae voz masculina y femenina.

    Devolver solo el modelo escondía la mitad del catálogo: se usaba siempre el
    hablante 0 y a la voz femenina no se llegaba nunca.
    """
    import asyncio

    from hearme.infrastructure.tts.piper import PiperEngine

    voces = asyncio.run(PiperEngine(language="es").voices("es"))
    assert len(voces) == 2
    assert {parse_piper(v)[4] for v in voces} == {Gender.FEMALE, Gender.MALE}


def test_el_hablante_elegido_llega_a_la_sintesis() -> None:
    """Sin esto, elegir la voz femenina no cambiaría lo que suena."""
    from hearme.infrastructure.tts.piper import PiperEngine

    assert PiperEngine.speaker_id("es_ES-sharvard-medium#M") == 0
    assert PiperEngine.speaker_id("es_ES-sharvard-medium#F") == 1
    # Un modelo de un solo hablante no lleva índice.
    assert PiperEngine.speaker_id("de_DE-thorsten-medium") is None


def test_la_descripcion_es_legible_por_una_persona() -> None:
    perfil = VoiceProfile(
        id="ef_dora",
        engine="kokoro",
        language="es",
        display_name="Dora",
        gender=Gender.FEMALE,
        accent="español",
        quality=Quality.HIGH,
    )
    descripcion = perfil.describe()
    assert "voz femenina" in descripcion
    assert "acento español" in descripcion
    assert "ef_dora" not in descripcion, "el identificador no le dice nada a nadie"


def _catalogo() -> VoiceCatalog:
    catalogo = VoiceCatalog()
    catalogo.add(
        VoiceProfile(
            id="ef_dora",
            engine="kokoro",
            language="es",
            display_name="Dora",
            gender=Gender.FEMALE,
            naturalness=0.9,
        )
    )
    catalogo.add(
        VoiceProfile(
            id="es_ES-sharvard-medium",
            engine="piper",
            language="es",
            display_name="Sharvard",
            naturalness=0.68,
        )
    )
    catalogo.add(
        VoiceProfile(
            id="af_heart",
            engine="kokoro",
            language="en",
            display_name="Heart",
            gender=Gender.FEMALE,
            naturalness=0.9,
        )
    )
    return catalogo


def test_las_voces_se_ordenan_por_naturalidad() -> None:
    voces = _catalogo().for_language("es")
    assert [v.id for v in voces] == ["ef_dora", "es_ES-sharvard-medium"]


def test_se_filtra_por_lo_que_la_gente_pregunta() -> None:
    catalogo = _catalogo()
    assert len(catalogo.filter(language="es")) == 2
    assert len(catalogo.filter(gender=Gender.FEMALE)) == 2
    assert len(catalogo.filter(engine="piper")) == 1


def test_las_voces_no_comerciales_se_excluyen_salvo_permiso() -> None:
    catalogo = _catalogo()
    catalogo.add(
        VoiceProfile(
            id="xtts", engine="xtts", language="es", display_name="Xtts", non_commercial=True
        )
    )
    assert not any(v.non_commercial for v in catalogo.filter(language="es"))
    assert any(v.non_commercial for v in catalogo.filter(language="es", allow_non_commercial=True))


def test_hay_texto_de_muestra_para_cualquier_idioma() -> None:
    assert sample_text_for("es")
    assert sample_text_for("idioma-que-no-existe"), "debe caer a un texto por defecto"


# --- los seis conceptos -------------------------------------------------------


def test_la_traduccion_se_deriva_no_se_elige() -> None:
    """Es la tesis del módulo: sin casilla no hay estados incoherentes."""
    igual = ListeningPlan(document_language="es", playback_language="es")
    distinto = ListeningPlan(document_language="en", playback_language="es")

    assert not igual.needs_translation
    assert distinto.needs_translation
    # Y no existe forma de decir «traducir» con los dos idiomas iguales.
    assert "needs_translation" not in ListeningPlan.__dataclass_fields__


def test_el_plan_se_resume_en_una_frase_comprensible() -> None:
    plan = ListeningPlan(document_language="en", playback_language="es", style=NarrationStyle.NOVEL)
    resumen = plan.describe()
    assert "traducirá de en a es" in resumen
    assert "novel" in resumen


def test_el_plan_se_traduce_a_lo_que_espera_el_pipeline() -> None:
    """El pipeline sigue hablando de language/target_language: la conversión es aquí."""
    catalogo = _catalogo()
    plan = ListeningPlan(document_language="en", playback_language="es", voice="ef_dora")
    kwargs = plan_to_request_kwargs(plan, catalogo)

    assert kwargs["language"] == "en"
    assert kwargs["target_language"] == "es"
    # El motor lo manda la voz: pedir una voz de Kokoro y que el selector elija
    # Piper daría otra voz distinta sin explicación.
    assert kwargs["engine"] == "kokoro"


def test_sin_traduccion_no_se_pasa_idioma_de_destino() -> None:
    kwargs = plan_to_request_kwargs(
        ListeningPlan(document_language="es", playback_language="es"), _catalogo()
    )
    assert kwargs["target_language"] is None


# --- validación con acciones concretas ----------------------------------------


def test_se_detecta_que_falta_el_traductor_antes_de_convertir() -> None:
    """Descubrirlo al final es esperar el parseo de un libro para nada."""
    problemas = validate(
        ListeningPlan(document_language="en", playback_language="es"),
        catalog=_catalogo(),
        translation_available=False,
    )
    assert problemas
    assert "no puede traducir" in problemas[0].message
    assert "Escúchalo en en" in problemas[0].action


def test_una_voz_de_otro_idioma_se_rechaza_con_su_arreglo() -> None:
    problemas = validate(
        ListeningPlan(document_language="es", playback_language="es", voice="af_heart"),
        catalog=_catalogo(),
        translation_available=True,
    )
    assert problemas and problemas[0].field == "voice"
    assert problemas[0].action == "Elige una voz de es."


def test_todo_problema_trae_una_accion() -> None:
    """Un error que solo describe el problema deja el trabajo a medias."""
    casos = [
        ListeningPlan(),
        ListeningPlan(document_language="en", playback_language="es"),
        ListeningPlan(document_language="es", playback_language="ca"),
    ]
    for plan in casos:
        for problema in validate(plan, catalog=_catalogo(), translation_available=False):
            assert problema.action.strip(), f"sin acción: {problema.message}"


def test_un_plan_correcto_no_tiene_problemas() -> None:
    problemas = validate(
        ListeningPlan(document_language="es", playback_language="es", voice="ef_dora"),
        catalog=_catalogo(),
        translation_available=True,
    )
    assert problemas == []


# --- recomendaciones transparentes --------------------------------------------


def test_toda_recomendacion_lleva_su_motivo() -> None:
    """Una sugerencia sin motivo visible es una decisión tomada por el sistema."""
    recomendaciones = recommend(
        detected_language="es",
        detection_confidence=0.9,
        catalog=_catalogo(),
        translation_available=True,
    )
    assert recomendaciones
    for nombre, r in recomendaciones.items():
        assert r.reason.strip(), f"'{nombre}' sugiere sin explicar"


def test_se_prefiere_escuchar_el_original_si_hay_voz() -> None:
    r = recommend(
        detected_language="es",
        detection_confidence=0.9,
        catalog=_catalogo(),
        translation_available=True,
    )["playback_language"]
    assert r.value == "es"
    assert r.is_confident


def test_sin_voz_para_el_original_se_propone_traducir() -> None:
    r = recommend(
        detected_language="de",
        detection_confidence=0.9,
        catalog=_catalogo(),
        translation_available=True,
        interface_language="es",
    )["playback_language"]
    assert r.value == "es"
    assert "traduciría" in r.reason


def test_una_deteccion_dudosa_no_se_presenta_como_segura() -> None:
    """Con confianza baja la interfaz pregunta en vez de preseleccionar."""
    r = recommend(
        detected_language="es",
        detection_confidence=0.3,
        catalog=_catalogo(),
        translation_available=True,
    )["playback_language"]
    assert not r.is_confident
    assert r.confidence < LOW_CONFIDENCE


def test_la_voz_favorita_gana_a_la_mas_natural() -> None:
    r = recommend(
        detected_language="es",
        detection_confidence=0.9,
        catalog=_catalogo(),
        translation_available=True,
        preferred_voices={"es": "es_ES-sharvard-medium"},
    )["voice"]
    assert r.value == "es_ES-sharvard-medium"
    assert "sueles usar" in r.reason


def test_sin_ninguna_voz_instalada_se_dice_claramente() -> None:
    r = recommend(
        detected_language="es",
        detection_confidence=0.9,
        catalog=VoiceCatalog(),
        translation_available=False,
    )["playback_language"]
    assert r.value == ""
    assert not r.is_confident


def test_el_estilo_sugerido_es_conservador_ante_la_duda() -> None:
    """Poesía en un manual técnico se nota mucho más que un neutro de más."""
    assert suggest_style("").value == "neutral"
    assert suggest_style("Poemas completos").value == "poetry"
    assert suggest_style("Manual de instalación").value == "technical"
    assert suggest_style("Cuento infantil").value == "children"


# --- estilos narrativos -------------------------------------------------------


def test_todos_los_estilos_tienen_prosodia() -> None:
    """Añadir un estilo sin darle prosodia revienta al trocear."""
    faltan = [e.value for e in NarrationStyle if e not in _PAUSES or e not in _RATES]
    assert not faltan, f"estilos sin prosodia definida: {faltan}"


def test_los_estilos_nuevos_se_distinguen_del_neutro() -> None:
    """Un estilo que suena igual que otro no es un estilo, es una etiqueta."""
    for estilo in (NarrationStyle.ACADEMIC, NarrationStyle.CHILDREN, NarrationStyle.LECTURE):
        distinto_ritmo = _RATES[estilo] != _RATES[NarrationStyle.NEUTRAL]
        distintas_pausas = _PAUSES[estilo] != _PAUSES[NarrationStyle.NEUTRAL]
        assert distinto_ritmo or distintas_pausas, f"'{estilo.value}' es indistinguible del neutro"


# --- estimación ---------------------------------------------------------------


def test_la_duracion_estimada_es_proporcional_al_texto() -> None:
    assert estimate_minutes(0) == 0
    assert estimate_minutes(9000) == pytest.approx(10, abs=0.1)
    # Más lento, más minutos.
    assert estimate_minutes(9000, rate=0.5) > estimate_minutes(9000)
