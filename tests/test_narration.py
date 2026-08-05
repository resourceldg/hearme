"""Tests del cerebro de estilo: partitura, director, adaptadores y aportaciones.

Lo que se prueba aquí no es «suena bien» —eso lo decide la evaluación a ciegas
con personas— sino las propiedades que hacen que el corpus de la comunidad
sobreviva: que las anotaciones se puedan releer, que la procedencia mande, que
ningún motor finja respetar lo que no respeta y que un puñado de cuentas nuevas
no pueda colar una aportación.
"""

from __future__ import annotations

import pytest

from hearme.application.chunker import chunk_chapter
from hearme.domain.models import Block, BlockKind, Chapter, NarrationStyle
from hearme.narration import (
    KOKORO,
    PIPER,
    SSML_FULL,
    MarkSource,
    NarrationScore,
    ProsodyMark,
    RuleBasedDirector,
    SpanRole,
    capabilities_for,
)
from hearme.narration.contributions import (
    Contribution,
    ContributionKind,
    ContributionStatus,
    Contributor,
    Review,
    ValidationPolicy,
    Verdict,
    update_reliability,
    validate,
)
from hearme.narration.score import SCHEMA_VERSION, normalize_text, text_digest

# --- partitura ----------------------------------------------------------------


def test_la_huella_ignora_el_formato_del_texto() -> None:
    """Un salto de línea distinto no puede invalidar las anotaciones."""
    assert text_digest("Hola  mundo.\n") == text_digest("Hola mundo.")
    assert normalize_text("  a\n\tb  ") == "a b"


def test_la_partitura_va_y_vuelve_de_json() -> None:
    original = NarrationScore.for_text(
        "Capítulo uno.",
        language="es",
        marks=(
            ProsodyMark(0, 13, role=SpanRole.HEADING, pause_after_ms=1000, emphasis=1.15),
            ProsodyMark(0, 5, pitch_semitones=-1.5, source=MarkSource.HUMAN),
        ),
    )
    vuelta = NarrationScore.from_dict(original.to_dict())

    assert vuelta == original
    assert vuelta.matches("Capítulo uno.")


def test_se_rechaza_un_esquema_incompatible() -> None:
    """Malinterpretar una partitura contamina el corpus sin hacer ruido."""
    datos = NarrationScore.for_text("x", language="es").to_dict()
    datos["schema_version"] = "99.0"
    with pytest.raises(ValueError, match="incompatible"):
        NarrationScore.from_dict(datos)


def test_la_correccion_humana_gana_a_la_regla() -> None:
    score = NarrationScore.for_text(
        "Una frase.",
        language="es",
        marks=(
            ProsodyMark(0, 10, pause_after_ms=400, rate=1.0, source=MarkSource.RULE),
            ProsodyMark(0, 10, pause_after_ms=900, source=MarkSource.HUMAN),
        ),
    )
    resuelta = score.resolve(0, 10)

    assert resuelta is not None
    assert resuelta.pause_after_ms == 900  # manda la persona
    assert resuelta.rate == 1.0  # …pero no borra lo que no tocó
    assert resuelta.source is MarkSource.HUMAN


def test_una_lectura_humana_gana_incluso_a_la_correccion() -> None:
    score = NarrationScore.for_text(
        "Una frase.",
        language="es",
        marks=(
            ProsodyMark(0, 10, pause_after_ms=900, source=MarkSource.HUMAN),
            ProsodyMark(0, 10, pause_after_ms=650, source=MarkSource.REFERENCE),
        ),
    )
    resuelta = score.resolve(0, 10)
    assert resuelta is not None and resuelta.pause_after_ms == 650


def test_no_se_fusionan_partituras_de_textos_distintos() -> None:
    a = NarrationScore.for_text("uno", language="es")
    b = NarrationScore.for_text("otro", language="es")
    with pytest.raises(ValueError, match="textos distintos"):
        a.merged_with(b)


def test_los_tramos_invalidos_se_rechazan_al_construir() -> None:
    with pytest.raises(ValueError, match="tramo inválido"):
        ProsodyMark(10, 4)
    with pytest.raises(ValueError, match="rate debe ser positivo"):
        ProsodyMark(0, 4, rate=0.0)


def test_el_esquema_declara_su_version() -> None:
    assert NarrationScore.for_text("x", language="es").schema_version == SCHEMA_VERSION


# --- director -----------------------------------------------------------------


def test_el_director_por_reglas_marca_su_procedencia_y_duda() -> None:
    """Debe ser fácil de sobrescribir: es una heurística, no una autoridad."""
    score = RuleBasedDirector().direct(
        "Un párrafo cualquiera.", kind=BlockKind.PARAGRAPH, style=NarrationStyle.NEUTRAL
    )
    marca = score.resolve(0, len(normalize_text("Un párrafo cualquiera.")))

    assert marca is not None
    assert marca.source is MarkSource.RULE
    assert marca.confidence < 0.5


def test_el_director_reconoce_el_dialogo() -> None:
    texto = 'Ella se giró. —No pienso volver— dijo. Luego "se marchó" sin más.'
    score = RuleBasedDirector().direct(texto, kind=BlockKind.PARAGRAPH)

    dialogos = [m for m in score.marks if m.role is SpanRole.DIALOGUE]
    assert dialogos, "la raya y las comillas deben anotarse como diálogo"
    normalizado = normalize_text(texto)
    for marca in dialogos:
        assert normalizado[marca.start] in '—"«“'


def test_el_director_diferencia_los_registros() -> None:
    director = RuleBasedDirector()
    poesia = director.direct("Un verso.", kind=BlockKind.PARAGRAPH, style=NarrationStyle.POETRY)
    tecnico = director.direct("Un verso.", kind=BlockKind.PARAGRAPH, style=NarrationStyle.TECHNICAL)

    p = poesia.resolve(0, 9)
    t = tecnico.resolve(0, 9)
    assert p is not None and t is not None
    assert p.pause_after_ms > t.pause_after_ms
    assert p.rate < t.rate


def test_el_director_cumple_el_protocolo() -> None:
    from hearme.narration.director import NarrationDirector

    assert isinstance(RuleBasedDirector(), NarrationDirector)


def test_el_texto_vacio_no_produce_marcas() -> None:
    assert RuleBasedDirector().direct("   ", kind=BlockKind.PARAGRAPH).marks == ()


# --- adaptadores --------------------------------------------------------------


def test_un_motor_sin_tono_declara_lo_que_pierde() -> None:
    """El fallo que este módulo existe para evitar: descartar en silencio."""
    marca = ProsodyMark(0, 5, pause_after_ms=400, rate=0.9, pitch_semitones=-2.0)

    plan = PIPER.plan(marca)
    assert plan.rate == 0.9
    assert "pitch" in plan.dropped
    assert not plan.is_faithful

    completo = SSML_FULL.plan(marca)
    assert completo.pitch_semitones == -2.0
    assert completo.is_faithful


def test_no_se_pierde_lo_que_nadie_pidio() -> None:
    """Un motor sin tono no 'pierde' tono en un texto donde nadie lo anotó."""
    plan = KOKORO.plan(ProsodyMark(0, 5, pause_after_ms=300))
    assert plan.is_faithful


def test_un_motor_desconocido_se_asume_conservador() -> None:
    caps = capabilities_for("motor-de-un-plugin")
    assert caps.pause and not caps.rate and not caps.emphasis and not caps.pitch

    plan = caps.plan(ProsodyMark(0, 5, rate=0.8))
    assert plan.rate == 1.0  # no finge aplicarlo…
    assert "rate" in plan.dropped  # …y lo dice


def test_sin_marca_el_plan_es_neutro() -> None:
    plan = PIPER.plan(None)
    assert (plan.rate, plan.emphasis, plan.pause_after_ms) == (1.0, 1.0, 0)
    assert plan.is_faithful


# --- integración con el segmentador -------------------------------------------


def test_el_segmentador_usa_el_director() -> None:
    """El estilo debe llegar al fragmento a través del director, no de tablas sueltas."""
    capitulo = Chapter(
        title="t",
        order=0,
        blocks=[Block(kind=BlockKind.HEADING, text="Capítulo uno", order=0, level=1)],
    )
    utterance = chunk_chapter(capitulo, style=NarrationStyle.NOVEL)[0]

    assert utterance.pause_after_ms == 1200
    assert utterance.emphasis > 1.0


def test_se_puede_inyectar_otro_director() -> None:
    """Es la prueba de que el motor de estilo es sustituible sin tocar el pipeline."""

    class DirectorLento:
        name = "lento"
        version = "test"

        def direct(self, text, *, kind, style, language):
            return NarrationScore.for_text(
                text,
                language=language,
                marks=(ProsodyMark(0, len(normalize_text(text)), pause_after_ms=5000, rate=0.5),),
            )

    capitulo = Chapter(
        title="t",
        order=0,
        blocks=[Block(kind=BlockKind.PARAGRAPH, text="Una frase.", order=0)],
    )
    utterance = chunk_chapter(capitulo, director=DirectorLento())[0]

    assert utterance.pause_after_ms == 5000
    assert utterance.rate == 0.5


# --- aportaciones y abuso -----------------------------------------------------


def _aportacion(**kwargs) -> Contribution:
    base = {
        "id": "c1",
        "kind": ContributionKind.CORRECTION,
        "contributor": Contributor(id="ana", reliability=0.5),
        "language": "es",
        "text_sha256": text_digest("Una frase."),
    }
    return Contribution(**{**base, **kwargs})


def test_hacen_falta_varios_revisores_aunque_sobre_el_peso() -> None:
    """Una sola cuenta de confianza no puede validar: sería una llave maestra."""
    experto = Contributor(id="pro", reliability=1.0, accredited=True)
    aportacion = _aportacion(reviews=[Review(reviewer=experto, verdict=Verdict.APPROVE)])

    resultado = validate(aportacion)
    assert resultado.status is ContributionStatus.PENDING
    assert "falta" in resultado.reason


def test_un_cuorum_ponderado_acepta() -> None:
    aportacion = _aportacion(
        reviews=[
            Review(reviewer=Contributor(id="b", reliability=0.6), verdict=Verdict.APPROVE),
            Review(reviewer=Contributor(id="c", reliability=0.6), verdict=Verdict.APPROVE),
        ]
    )
    assert validate(aportacion).status is ContributionStatus.ACCEPTED


def test_las_cuentas_nuevas_no_alcanzan_el_cuorum_solas() -> None:
    """Fabricar identidades tiene que salir caro: es el ataque barato por excelencia."""
    nuevas = [
        Review(reviewer=Contributor(id=f"sock{i}"), verdict=Verdict.APPROVE) for i in range(3)
    ]
    resultado = validate(_aportacion(reviews=nuevas))

    assert resultado.status is ContributionStatus.PENDING
    assert resultado.approve_weight < ValidationPolicy().approve_weight


def test_nadie_valida_lo_suyo() -> None:
    ana = Contributor(id="ana", reliability=0.9)
    aportacion = _aportacion(
        contributor=ana,
        reviews=[
            Review(reviewer=ana, verdict=Verdict.APPROVE),
            Review(reviewer=Contributor(id="otro", reliability=0.9), verdict=Verdict.APPROVE),
        ],
    )
    assert validate(aportacion).status is ContributionStatus.QUARANTINED


def test_el_desacuerdo_real_sube_a_decision_editorial() -> None:
    """Un texto que divide a revisores fiables suele ser una duda legítima."""
    aportacion = _aportacion(
        reviews=[
            Review(reviewer=Contributor(id="a", reliability=0.8), verdict=Verdict.APPROVE),
            Review(reviewer=Contributor(id="b", reliability=0.8), verdict=Verdict.APPROVE),
            Review(reviewer=Contributor(id="c", reliability=0.8), verdict=Verdict.REJECT),
            Review(reviewer=Contributor(id="d", reliability=0.8), verdict=Verdict.REJECT),
        ]
    )
    resultado = validate(aportacion)

    assert resultado.contested
    assert resultado.status is ContributionStatus.PENDING


def test_una_mayoria_clara_no_es_vetada_por_la_minoria() -> None:
    """Dos revisores fiables a favor pesan más que uno en contra."""
    aportacion = _aportacion(
        reviews=[
            Review(reviewer=Contributor(id="a", reliability=0.8), verdict=Verdict.APPROVE),
            Review(reviewer=Contributor(id="b", reliability=0.8), verdict=Verdict.APPROVE),
            Review(reviewer=Contributor(id="c", reliability=0.8), verdict=Verdict.REJECT),
        ]
    )
    assert validate(aportacion).status is ContributionStatus.ACCEPTED


def test_el_rechazo_claro_no_necesita_debate() -> None:
    aportacion = _aportacion(
        reviews=[
            Review(reviewer=Contributor(id="a", reliability=0.8), verdict=Verdict.REJECT),
            Review(reviewer=Contributor(id="b", reliability=0.8), verdict=Verdict.REJECT),
        ]
    )
    assert validate(aportacion).status is ContributionStatus.REJECTED


def test_la_abstencion_no_cuenta_para_el_cuorum() -> None:
    aportacion = _aportacion(
        reviews=[
            Review(reviewer=Contributor(id="a", reliability=0.9), verdict=Verdict.APPROVE),
            Review(reviewer=Contributor(id="b", reliability=0.9), verdict=Verdict.ABSTAIN),
        ]
    )
    resultado = validate(aportacion)
    assert resultado.reviewers == 1
    assert resultado.status is ContributionStatus.PENDING


def test_revisar_dos_veces_no_duplica_el_voto() -> None:
    a = Contributor(id="a", reliability=0.9)
    aportacion = _aportacion(
        reviews=[
            Review(reviewer=a, verdict=Verdict.APPROVE),
            Review(reviewer=a, verdict=Verdict.APPROVE),
        ]
    )
    resultado = validate(aportacion)
    assert resultado.reviewers == 1
    assert resultado.approve_weight == pytest.approx(a.weight)


def test_la_confianza_cuesta_tiempo() -> None:
    """Tres aciertos afortunados no pueden dar peso máximo."""
    novato = Contributor(id="n")
    con_tres = update_reliability(novato, control_hits=3, control_total=3)
    con_muchos = update_reliability(novato, control_hits=40, control_total=40)

    assert con_tres.reliability < 0.7
    assert con_muchos.reliability > con_tres.reliability
    assert con_muchos.reliability <= 1.0


def test_la_acreditacion_sube_el_peso_pero_no_lo_desborda() -> None:
    normal = Contributor(id="a", reliability=0.6)
    acreditado = Contributor(id="b", reliability=0.6, accredited=True)

    assert acreditado.weight > normal.weight
    assert Contributor(id="c", reliability=1.0, accredited=True).weight == 1.0


def test_el_recuento_de_control_incoherente_se_rechaza() -> None:
    with pytest.raises(ValueError, match="inconsistente"):
        update_reliability(Contributor(id="a"), control_hits=5, control_total=2)


def test_la_aportacion_se_serializa_para_auditoria() -> None:
    datos = _aportacion(director_version="rules/1.0").to_dict()

    assert datos["director_version"] == "rules/1.0"
    assert datos["text_sha256"] == text_digest("Una frase.")
    assert datos["status"] == "pending"
