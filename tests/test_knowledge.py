"""Tests de la Community Knowledge Network.

La propiedad que hay que defender aquí es una sola, dicha de muchas formas: **lo
que sale de una instalación no puede contener ni obras ni personas**. Todo lo
demás —el historial, la reversión, el benchmark— es la maquinaria que hace esa
propiedad sostenible en el tiempo.
"""

from __future__ import annotations

import json

import pytest

from hearme.knowledge import (
    K_ANONYMITY,
    BenchmarkItem,
    Effect,
    KnowledgeBase,
    KnowledgeError,
    LabError,
    NarrationBenchmark,
    NarrationLab,
    Provenance,
    ReviewedKnowledge,
    ReviewError,
    RuleKind,
    TextSource,
    Trigger,
    TriggerType,
    dp_noise,
    extract_shareable,
)
from hearme.knowledge.knowledge import merge_effects, rule_id
from hearme.narration.director import RuleBasedDirector
from hearme.narration.score import ProsodyMark, SpanRole
from hearme.privacy.profile import ReadingDNA

# --- lo que nunca puede salir -------------------------------------------------


def test_un_disparador_no_puede_llevar_un_fragmento_de_obra() -> None:
    """El cortafuegos: el único campo con palabras concretas está acotado."""
    with pytest.raises(KnowledgeError, match="fragmento de obra"):
        Trigger(
            type=TriggerType.LEXICAL,
            value="Los días se iban como sombras, los minutos giraban como las estrellas",
            language="es",
        )


def test_un_disparador_lexico_admite_un_lema_pero_no_una_cita() -> None:
    Trigger(type=TriggerType.LEXICAL, value="Sanhueza", language="es")  # bien
    with pytest.raises(KnowledgeError, match="cita"):
        Trigger(type=TriggerType.LEXICAL, value="y entonces él dijo que no", language="es")


def test_los_disparadores_no_lexicos_son_categorias_no_texto() -> None:
    Trigger(type=TriggerType.SYNTACTIC, value="conector_adversativo", language="es")
    with pytest.raises(KnowledgeError, match="categoría"):
        Trigger(type=TriggerType.SYNTACTIC, value="pero él no quiso.", language="es")


def test_lo_publicado_no_lleva_seudonimos() -> None:
    """Publicar quién apoya cada regla permitiría perfilar por el conjunto apoyado."""
    base = KnowledgeBase(language="es")
    for i in range(K_ANONYMITY):
        base.propose(
            kind=RuleKind.PAUSE,
            trigger=Trigger(type=TriggerType.PUNCTUATION, value="dos_puntos", language="es"),
            effect=Effect(pause_scale=1.3),
            rationale="los dos puntos anuncian: la pausa debe dejar espacio a la expectativa",
            contributor=f"persona-{i}",
        )

    publicado = json.dumps(base.publishable(), ensure_ascii=False)
    for i in range(K_ANONYMITY):
        assert f"persona-{i}" not in publicado


def test_el_lexico_personal_nunca_se_contribuye() -> None:
    """El vocabulario delata oficio, salud y procedencia. No sale jamás."""
    dna = ReadingDNA(language="es")
    dna.lexicon["mieloma"] = "mie-lo-ma"
    dna.lexicon["Sanhueza"] = "san-güe-sa"
    original = ProsodyMark(0, 10, role=SpanRole.DIALOGUE, pause_after_ms=400)
    for _ in range(8):
        dna.learn_from(
            original,
            ProsodyMark(0, 10, role=SpanRole.DIALOGUE, pause_after_ms=600),
            role=SpanRole.DIALOGUE,
        )

    candidatas = extract_shareable(dna, contributor="ana", language="es")
    serializado = json.dumps([(t.value, e.to_dict()) for t, e in candidatas], ensure_ascii=False)

    assert "mieloma" not in serializado
    assert "Sanhueza" not in serializado
    assert candidatas, "los ajustes por rol sí deben poder contribuirse"


def test_no_se_contribuye_lo_que_solo_es_idiosincrasia() -> None:
    """Con pocas observaciones, un ajuste es de una persona, no conocimiento."""
    dna = ReadingDNA(language="es")
    original = ProsodyMark(0, 10, role=SpanRole.QUOTE, pause_after_ms=400)
    dna.learn_from(
        original, ProsodyMark(0, 10, role=SpanRole.QUOTE, pause_after_ms=900), role=SpanRole.QUOTE
    )

    assert extract_shareable(dna, contributor="ana", language="es") == []


# --- umbral de k contribuyentes -----------------------------------------------


def _apoyar(base: KnowledgeBase, cuantos: int, **kwargs) -> None:
    for i in range(cuantos):
        base.propose(
            kind=RuleKind.PAUSE,
            trigger=Trigger(type=TriggerType.STRUCTURAL, value="fin_de_parrafo", language="es"),
            effect=Effect(pause_scale=1.2),
            rationale="el fin de párrafo pide más aire que un punto y seguido",
            contributor=f"p{i}",
            **kwargs,
        )


def test_una_regla_de_una_sola_persona_no_se_publica() -> None:
    """Podría reflejar su idiolecto o su obra rara: es justo la que la señalaría."""
    base = KnowledgeBase(language="es")
    _apoyar(base, 1)

    assert base.publishable() == []
    assert len(base.withheld()) == 1


def test_con_k_personas_independientes_la_regla_se_publica() -> None:
    base = KnowledgeBase(language="es")
    _apoyar(base, K_ANONYMITY)

    assert len(base.publishable()) == 1
    assert base.withheld() == []


def test_la_misma_persona_apoyando_varias_veces_no_alcanza_el_umbral() -> None:
    """El umbral cuenta personas distintas, no envíos."""
    base = KnowledgeBase(language="es")
    for _ in range(20):
        base.propose(
            kind=RuleKind.PAUSE,
            trigger=Trigger(type=TriggerType.STRUCTURAL, value="fin_de_parrafo", language="es"),
            effect=Effect(pause_scale=1.2),
            rationale="motivo suficiente",
            contributor="la-misma-persona",
        )

    assert base.publishable() == []


def test_la_transparencia_alcanza_a_lo_retenido() -> None:
    base = KnowledgeBase(language="es")
    _apoyar(base, 2)
    datos = json.loads(base.to_json())

    assert datos["withheld_count"] == 1
    assert datos["k_anonymity"] == K_ANONYMITY


def test_las_propuestas_equivalentes_convergen_en_la_misma_regla() -> None:
    """Sin esto, los duplicados impedirían para siempre alcanzar el umbral."""
    disparador = Trigger(type=TriggerType.PUNCTUATION, value="raya_dialogo", language="es")
    assert rule_id(disparador, RuleKind.PAUSE) == rule_id(disparador, RuleKind.PAUSE)
    assert rule_id(disparador, RuleKind.PAUSE) != rule_id(disparador, RuleKind.EMPHASIS)


def test_una_regla_sin_justificacion_no_es_revisable() -> None:
    base = KnowledgeBase(language="es")
    with pytest.raises(KnowledgeError, match="justificación"):
        base.propose(
            kind=RuleKind.PAUSE,
            trigger=Trigger(type=TriggerType.STRUCTURAL, value="fin", language="es"),
            effect=Effect(pause_scale=1.1),
            rationale="   ",
            contributor="ana",
        )


def test_no_se_mezclan_idiomas_en_una_base() -> None:
    base = KnowledgeBase(language="es")
    with pytest.raises(KnowledgeError, match="'ca'"):
        base.propose(
            kind=RuleKind.PAUSE,
            trigger=Trigger(type=TriggerType.STRUCTURAL, value="fin", language="ca"),
            effect=Effect(pause_scale=1.1),
            rationale="motivo",
            contributor="ana",
        )


# --- privacidad diferencial ---------------------------------------------------


def test_el_ruido_diferencial_perturba_pero_no_desvia() -> None:
    muestras = [dp_noise(100, epsilon=1.0) for _ in range(400)]
    media = sum(muestras) / len(muestras)

    assert len(set(muestras)) > 1, "debe haber ruido de verdad"
    assert 95 < media < 105, "el ruido debe ser insesgado"


def test_el_ruido_nunca_produce_recuentos_negativos() -> None:
    assert all(dp_noise(0, epsilon=0.5) >= 0 for _ in range(100))


def test_epsilon_no_valido_se_rechaza() -> None:
    with pytest.raises(KnowledgeError):
        dp_noise(10, epsilon=0)


def test_la_publicacion_con_ruido_se_declara_como_tal() -> None:
    """Quien lea la publicación debe saber que los recuentos están perturbados."""
    base = KnowledgeBase(language="es")
    _apoyar(base, K_ANONYMITY)
    publicado = base.publishable(epsilon=1.0)

    assert publicado[0]["noised"] is True
    assert "noised" not in base.publishable()[0]


# --- revisión, historial y reversión ------------------------------------------


def _base_con_regla() -> tuple[ReviewedKnowledge, str]:
    revisada = ReviewedKnowledge(KnowledgeBase(language="es"))
    regla = revisada.propose(
        kind=RuleKind.PAUSE,
        trigger=Trigger(type=TriggerType.PUNCTUATION, value="punto_y_coma", language="es"),
        effect=Effect(pause_scale=1.2),
        rationale="el punto y coma separa más que una coma y menos que un punto",
        contributor="ana",
    )
    return revisada, regla.id


def test_ningun_cambio_ocurre_sin_dejar_constancia() -> None:
    revisada, rule = _base_con_regla()
    assert len(revisada.ledger.entries) == 1

    revisada.dispute(rule, actor="beatriz", reason="en lectura rápida suena entrecortado")
    assert len(revisada.ledger.entries) == 2


def test_sustituir_una_regla_exige_motivo() -> None:
    """Cambia lo que la gente ya oía: no puede hacerse en silencio."""
    revisada, rule = _base_con_regla()
    with pytest.raises(ReviewError, match="exige un motivo"):
        revisada.supersede(
            rule, effect=Effect(pause_scale=2.0), rationale="nueva", contributor="ana", reason=""
        )


def test_se_puede_revertir_a_la_version_anterior() -> None:
    revisada, rule = _base_con_regla()
    nueva = revisada.supersede(
        rule,
        effect=Effect(pause_scale=3.0),
        rationale="probamos pausas muy largas",
        contributor="ana",
        reason="experimento de cadencia",
    )
    assert nueva.effect.pause_scale == 3.0

    previa = revisada.revert(nueva.id, actor="moderacion", reason="sonaba artificial en pruebas")

    assert previa.effect.pause_scale == 1.2
    assert nueva.id not in revisada.base.rules


def test_revertir_conserva_el_rastro_de_lo_revertido() -> None:
    """Repetir un error ya cometido es la forma más cara de aprender."""
    revisada, rule = _base_con_regla()
    nueva = revisada.supersede(
        rule, effect=Effect(pause_scale=3.0), rationale="r", contributor="ana", reason="prueba"
    )
    revisada.revert(nueva.id, actor="mod", reason="sonaba mal")

    historial = revisada.ledger.history_of(rule)
    revertidos = [e for e in historial if e.change.value == "reverted"]
    assert revertidos and revertidos[0].previous is not None
    assert revertidos[0].previous["effect"]["pause_scale"] == 3.0


def test_no_se_puede_revertir_lo_que_no_sustituye_a_nada() -> None:
    revisada, rule = _base_con_regla()
    with pytest.raises(ReviewError, match="no hay a dónde volver"):
        revisada.revert(rule, actor="mod", reason="porque sí")


def test_el_historial_explica_por_que_suena_asi() -> None:
    revisada, rule = _base_con_regla()
    explicacion = revisada.ledger.explain(revisada.base.rules[rule])

    assert "punto_y_coma" in explicacion
    assert "separa más que una coma" in explicacion
    assert "Retenida" in explicacion, "debe decir que aún no llega al umbral"


# --- laboratorio --------------------------------------------------------------


def test_el_laboratorio_rechaza_material_privado() -> None:
    """Se subió para escucharlo, no para experimentar con ello."""
    with pytest.raises(LabError, match="no entra en el laboratorio"):
        TextSource(
            id="x",
            text="Informe médico de una persona",
            language="es",
            provenance=Provenance.USER_PRIVATE,
            attribution="documento subido por alguien",
        )


def test_el_laboratorio_exige_acreditar_la_procedencia() -> None:
    """«Es de dominio público» sin fuente citada es una promesa, no una verificación."""
    with pytest.raises(LabError, match="procedencia"):
        TextSource(
            id="x", text="…", language="es", provenance=Provenance.PUBLIC_DOMAIN, attribution=""
        )


def test_se_pueden_comparar_dos_directores_sobre_texto_publico() -> None:
    lab = NarrationLab()
    lab.load(
        TextSource(
            id="spoon-1",
            text="Los días se iban como sombras. Nadie recordaba ya los nombres.",
            language="es",
            provenance=Provenance.PUBLIC_DOMAIN,
            attribution="Edgar Lee Masters, Antología de Spoon River (1915), dominio público",
        )
    )

    class DirectorLento:
        name, version = "lento", "0.1"

        def direct(self, text, *, kind=None, style=None, language="es"):
            from hearme.narration.score import NarrationScore, normalize_text

            return NarrationScore.for_text(
                text,
                language=language,
                marks=(ProsodyMark(0, len(normalize_text(text)), pause_after_ms=2000, rate=0.6),),
            )

    from hearme.domain.models import BlockKind, NarrationStyle

    comparacion = lab.compare(
        RuleBasedDirector(),
        DirectorLento(),
        "spoon-1",
        kind=BlockKind.PARAGRAPH,
        style=NarrationStyle.NEUTRAL,
    )
    assert comparacion["divergence"]["pause_after_ms"] > 0
    assert "winner" not in comparacion, "quién gana lo deciden las personas, no una heurística"


# --- benchmark ----------------------------------------------------------------


def _fuente_publica() -> TextSource:
    return TextSource(
        id="b1",
        text="Los días se iban como sombras.",
        language="es",
        provenance=Provenance.PUBLIC_DOMAIN,
        attribution="Edgar Lee Masters, Antología de Spoon River (1915), dominio público",
    )


def test_el_benchmark_no_admite_material_privado() -> None:
    bench = NarrationBenchmark()
    fuente = _fuente_publica()
    object.__setattr__(fuente, "provenance", Provenance.USER_PRIVATE)

    with pytest.raises(LabError, match="público"):
        bench.add(BenchmarkItem(source=fuente, reference=(), annotators=5))


def test_un_solo_anotador_no_es_una_referencia() -> None:
    """Con un anotador no hay referencia, hay una preferencia."""
    bench = NarrationBenchmark()
    bench.add(BenchmarkItem(source=_fuente_publica(), reference=(), annotators=1))

    resultado = bench.evaluate(RuleBasedDirector())
    assert "error" in resultado


def test_el_benchmark_declara_lo_que_no_mide() -> None:
    """Un número alto sin esta advertencia se lee como «suena bien», y no lo es."""
    from hearme.domain.models import BlockKind, NarrationStyle

    bench = NarrationBenchmark()
    bench.add(
        BenchmarkItem(
            source=_fuente_publica(),
            reference=(ProsodyMark(0, 30, pause_after_ms=400),),
            annotators=4,
        )
    )
    informe = bench.evaluate(
        RuleBasedDirector(), kind=BlockKind.PARAGRAPH, style=NarrationStyle.NEUTRAL
    )

    assert "pause_accuracy" in informe
    assert any("dislexia" in m for m in informe["not_measured"])
    assert "no sustituye" in informe["caveat"]


def test_el_benchmark_se_publica_en_abierto() -> None:
    bench = NarrationBenchmark()
    bench.add(BenchmarkItem(source=_fuente_publica(), reference=(), annotators=4))
    datos = json.loads(bench.to_json())

    assert datos["license"] == "CC0-1.0"
    assert datos["items"][0]["attribution"].startswith("Edgar Lee Masters")
    # El texto en sí no viaja en el índice: solo su referencia y procedencia.
    assert "text" not in datos["items"][0]


# --- composición de reglas ----------------------------------------------------


def test_las_reglas_se_combinan_ponderando_por_confianza() -> None:
    base = KnowledgeBase(language="es")
    _apoyar(base, K_ANONYMITY)
    reglas = list(base.rules.values())

    combinado = merge_effects(reglas)
    assert combinado.pause_scale == pytest.approx(1.2)


def test_combinar_una_lista_vacia_es_neutro() -> None:
    assert merge_effects([]).pause_scale is None
