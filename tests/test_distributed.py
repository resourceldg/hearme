"""Tests de la arquitectura distribuida: sincronización y retención.

El principio que se defiende aquí es uno solo, dicho de dos formas:

> **El servidor orquesta, no almacena.**

En `sync`, que lo que viaje sea conocimiento y no documentos. En `retention`,
que lo que se quede en disco sea la excepción y no lo normal.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hearme.knowledge.knowledge import Effect, KnowledgeBase, RuleKind, Trigger, TriggerType
from hearme.knowledge.sync import (
    MAX_DELTA_BYTES,
    Contribution,
    OutboundQueue,
    Snapshot,
    SyncError,
    apply,
    content_hash,
    diff,
    ingest,
)
from hearme.privacy.retention import (
    Artifact,
    Retention,
    RetentionPolicy,
    expired,
    release,
    sweep,
)

# --- lo que viaja es conocimiento, no documentos -------------------------------


def _base(language: str = "es", *, reglas: int = 4, apoyos: int = 4) -> KnowledgeBase:
    base = KnowledgeBase(language=language)
    for n in range(reglas):
        for p in range(apoyos):
            base.propose(
                kind=RuleKind.PAUSE,
                trigger=Trigger(
                    type=TriggerType.PUNCTUATION, value=f"signo_{n}", language=language
                ),
                effect=Effect(pause_scale=1.2),
                rationale="tras este signo la pausa se alarga",
                contributor=f"persona{p}",
            )
    return base


def test_una_instantanea_completa_pesa_kilobytes_no_megabytes() -> None:
    """Es el argumento entero del módulo, medido en vez de afirmado."""
    snapshot = Snapshot.of(_base(reglas=50))
    assert snapshot.size_bytes < 100_000, "50 reglas no deberían pasar de 100 KB"


def test_una_contribucion_no_puede_llevar_un_documento_dentro() -> None:
    contribucion = Contribution(
        language="es",
        kind=RuleKind.PAUSE,
        trigger_type=TriggerType.PUNCTUATION,
        trigger_value="dos_puntos",
        effect={"pause_scale": 1.3},
        rationale="los dos puntos anuncian",
        contributor="ana",
    )
    assert contribucion.size_bytes < 500

    datos = contribucion.to_dict()
    assert "document" not in datos
    assert "text" not in datos
    assert "text_sha256" not in datos, "ni siquiera el identificador de un texto"


def test_el_efecto_solo_admite_campos_conocidos() -> None:
    """Sin esta comprobación, el efecto sería un saco donde colar cualquier cosa."""
    contribucion = Contribution(
        language="es",
        kind=RuleKind.PAUSE,
        trigger_type=TriggerType.PUNCTUATION,
        trigger_value="coma",
        effect={"pause_scale": 1.1, "documento_entero": "..."},
        rationale="motivo",
        contributor="ana",
    )
    with pytest.raises(SyncError, match="no permitidos"):
        contribucion.to_effect()


# --- direccionado por contenido ------------------------------------------------


def test_el_hash_no_depende_del_orden() -> None:
    """Dos servidores con las mismas reglas deben coincidir aunque las guarden distinto."""
    a = [{"id": "1", "x": 1}, {"id": "2", "x": 2}]
    assert content_hash(a) == content_hash(list(reversed(a)))


def test_una_instantanea_se_verifica_contra_su_hash() -> None:
    snapshot = Snapshot.of(_base())
    assert snapshot.verify()

    manipulada = Snapshot(language="es", digest=snapshot.digest, rules=({"id": "falsa"},))
    assert not manipulada.verify()


def test_sin_cambios_el_delta_esta_vacio() -> None:
    """Si los hashes coinciden, la conversación se corta en un byte."""
    snapshot = Snapshot.of(_base())
    assert diff(snapshot, snapshot).is_empty


def test_un_delta_pesa_mucho_menos_que_la_instantanea() -> None:
    """Es la razón de sincronizar por deltas y no reenviándolo todo."""
    base = _base(reglas=50)
    antes = Snapshot.of(base)

    for p in range(4):
        base.propose(
            kind=RuleKind.PAUSE,
            trigger=Trigger(type=TriggerType.PUNCTUATION, value="nueva", language="es"),
            effect=Effect(pause_scale=1.4),
            rationale="regla añadida después",
            contributor=f"persona{p}",
        )
    despues = Snapshot.of(base)
    delta = diff(antes, despues)

    assert not delta.is_empty
    assert delta.size_bytes < despues.size_bytes / 5


def test_aplicar_un_delta_lleva_al_hash_anunciado() -> None:
    base = _base()
    antes = Snapshot.of(base)
    for p in range(4):
        base.propose(
            kind=RuleKind.EMPHASIS,
            trigger=Trigger(type=TriggerType.SYNTACTIC, value="vocativo", language="es"),
            effect=Effect(emphasis_scale=1.2),
            rationale="el vocativo llama a alguien",
            contributor=f"persona{p}",
        )
    despues = Snapshot.of(base)

    resultado = apply(antes, diff(antes, despues))
    assert resultado.digest == despues.digest


def test_aplicar_dos_veces_el_mismo_delta_da_lo_mismo() -> None:
    """Idempotente: reintentar una sincronización cortada no exige llevar la cuenta."""
    base = _base()
    antes = Snapshot.of(base)
    for p in range(4):
        base.propose(
            kind=RuleKind.RATE,
            trigger=Trigger(type=TriggerType.STRUCTURAL, value="cita_larga", language="es"),
            effect=Effect(rate_scale=0.95),
            rationale="una cita larga pide bajar el ritmo",
            contributor=f"persona{p}",
        )
    delta = diff(antes, Snapshot.of(base))

    una_vez = apply(antes, delta)
    dos_veces = apply(antes, delta)
    assert una_vez.digest == dos_veces.digest


def test_un_delta_de_otra_version_se_rechaza() -> None:
    """Aplicar un delta sobre una base equivocada produciría un estado inventado."""
    a, b = Snapshot.of(_base()), Snapshot.of(_base("en"))
    delta = diff(a, Snapshot.of(_base(reglas=6)))

    with pytest.raises(SyncError, match="sincronización completa"):
        apply(b, delta)


def test_un_delta_corrupto_se_detecta_al_aplicarlo() -> None:
    snapshot = Snapshot.of(_base())
    delta = diff(snapshot, Snapshot.of(_base(reglas=6)))
    from dataclasses import replace

    roto = replace(delta, to_digest="0" * 64)

    with pytest.raises(SyncError, match="incompleta o alterada"):
        apply(snapshot, roto)


def test_una_regla_retirada_desaparece_del_cliente() -> None:
    """Sin esto, revertir una regla no llegaría nunca a quien la aplica."""
    completa = Snapshot.of(_base(reglas=4))
    reducida = Snapshot.of(_base(reglas=2))

    delta = diff(completa, reducida)
    assert delta.removed
    assert apply(completa, delta).digest == reducida.digest


# --- offline primero -----------------------------------------------------------


def test_se_puede_aportar_sin_conexion_y_enviar_despues() -> None:
    cola = OutboundQueue()
    for n in range(3):
        cola.add(
            Contribution(
                language="es",
                kind=RuleKind.PAUSE,
                trigger_type=TriggerType.STRUCTURAL,
                trigger_value=f"posicion_{n}",
                effect={"pause_scale": 1.1},
                rationale="motivo suficiente",
                contributor="ana",
            )
        )
    assert len(cola) == 3

    enviadas = cola.drain()
    assert len(enviadas) == 3
    assert len(cola) == 0, "la cola se vacía solo al confirmar el envío"


def test_la_cola_no_admite_cargas_desmesuradas() -> None:
    with pytest.raises(SyncError, match="más que un delta"):
        OutboundQueue().add(
            Contribution(
                language="es",
                kind=RuleKind.PAUSE,
                trigger_type=TriggerType.PUNCTUATION,
                trigger_value="coma",
                effect={"pause_scale": 1.1},
                rationale="x" * (MAX_DELTA_BYTES + 1),
                contributor="ana",
            )
        )


def test_una_contribucion_mala_no_tumba_el_lote() -> None:
    base = KnowledgeBase(language="es")
    buena = Contribution(
        language="es",
        kind=RuleKind.PAUSE,
        trigger_type=TriggerType.PUNCTUATION,
        trigger_value="punto_y_coma",
        effect={"pause_scale": 1.2},
        rationale="separa más que una coma",
        contributor="ana",
    )
    mala = Contribution(
        language="es",
        kind=RuleKind.PAUSE,
        trigger_type=TriggerType.PUNCTUATION,
        trigger_value="coma",
        effect={"pause_scale": 1.1},
        rationale="   ",  # sin justificación: no es revisable
        contributor="ana",
    )

    aceptadas, rechazos = ingest(base, [buena, mala, buena])
    assert aceptadas == 2
    assert len(rechazos) == 1 and rechazos[0]


# --- el servidor no almacena ---------------------------------------------------


def test_por_defecto_no_se_conserva_ni_el_documento_ni_su_texto() -> None:
    """El cambio de valor por defecto es el punto entero del módulo."""
    politica = RetentionPolicy()
    assert not politica.keeps(Artifact.SOURCE)
    assert not politica.keeps(Artifact.TEXT)


def test_la_politica_se_explica_a_quien_sube_algo() -> None:
    explicacion = RetentionPolicy().explain()
    assert "se borra" in explicacion
    assert "no se guarda" in explicacion


def test_un_artefacto_efimero_se_borra_al_soltarlo(tmp_path) -> None:
    archivo = tmp_path / "documento.pdf"
    archivo.write_bytes(b"x" * 2048)

    informe = release(archivo, Artifact.SOURCE)
    assert not archivo.exists()
    assert informe.bytes_freed == 2048


def test_lo_que_se_conserva_no_se_toca(tmp_path) -> None:
    archivo = tmp_path / "modelo.onnx"
    archivo.write_bytes(b"x" * 100)

    release(archivo, Artifact.CACHE)  # la caché es RETAINED por defecto
    assert archivo.exists()


def test_el_modo_sesion_caduca_solo(tmp_path) -> None:
    """Sin barrido, «se borra a las 24 h» sería una promesa incumplida."""
    viejo = tmp_path / "audio-viejo.m4b"
    viejo.write_bytes(b"x")
    hace_dos_dias = (datetime.now(UTC) - timedelta(days=2)).timestamp()
    import os

    os.utime(viejo, (hace_dos_dias, hace_dos_dias))

    nuevo = tmp_path / "audio-nuevo.m4b"
    nuevo.write_bytes(b"x")

    vencidos = expired([viejo, nuevo], Artifact.AUDIO)
    assert viejo in vencidos
    assert nuevo not in vencidos


def test_el_barrido_es_seguro_de_repetir(tmp_path) -> None:
    (tmp_path / "a.m4b").write_bytes(b"x")
    politica = RetentionPolicy(audio=Retention.EPHEMERAL)

    primero = sweep(tmp_path, Artifact.AUDIO, politica)
    segundo = sweep(tmp_path, Artifact.AUDIO, politica)

    assert primero.artifacts_removed >= 1
    assert segundo.artifacts_removed == 0


def test_conservarlo_todo_es_posible_pero_hay_que_pedirlo() -> None:
    """Es lo que hacía el sistema antes; ahora es una decisión consciente."""
    acumulador = RetentionPolicy(
        source=Retention.RETAINED, text=Retention.RETAINED, audio=Retention.RETAINED
    )
    assert all(acumulador.keeps(a) for a in (Artifact.SOURCE, Artifact.TEXT, Artifact.AUDIO))
    assert expired([], Artifact.SOURCE, acumulador) == []


def test_el_informe_de_limpieza_no_lleva_nombres_de_archivo(tmp_path) -> None:
    """Un nombre de archivo es contenido: «mi-diagnostico.pdf» lo dice todo."""
    archivo = tmp_path / "mi-diagnostico.pdf"
    archivo.write_bytes(b"x")

    informe = release(archivo, Artifact.SOURCE).to_dict()
    assert "mi-diagnostico" not in str(informe)
    assert set(informe) == {"artifacts_removed", "bytes_freed", "failures"}


# --- lo que SÍ se guarda, con su cuenta ---------------------------------------


def test_el_conocimiento_nunca_es_recolectable() -> None:
    """Es la corrección al principio anterior: la reputación no se borra.

    Es lo único que la comunidad construye y no se puede rehacer. El audio se
    regenera reconvirtiendo; una reputación perdida no vuelve.
    """
    from hearme.privacy.storage import COLLECTABLE, Category

    assert Category.KNOWLEDGE not in COLLECTABLE
    assert Category.MODELS not in COLLECTABLE, "descargarlos otra vez cuesta a todos"
    assert Category.AUDIO in COLLECTABLE


def test_el_informe_dice_cuanto_ocupa_y_cuanto_se_puede_soltar(tmp_path) -> None:
    from hearme.privacy.storage import measure

    salida = tmp_path / "output"
    salida.mkdir()
    (salida / "libro.m4b").write_bytes(b"x" * 4096)
    bd = tmp_path / "hearme.db"
    bd.write_bytes(b"x" * 1024)

    informe = measure(
        output_dir=salida,
        uploads_dir=tmp_path / "uploads",
        models_dir=tmp_path / "models",
        cache_dir=tmp_path / "cache",
        database_path=bd,
    )

    assert informe.total_bytes == 5120
    assert informe.collectable_bytes == 4096, "la base de datos no es recolectable"
    assert informe.knowledge_bytes == 1024
    assert "irrecuperable" in informe.explain()


def test_se_puede_ver_que_se_borraria_antes_de_borrarlo(tmp_path) -> None:
    """Un botón de limpiar que no dice qué se lleva no se pulsa, y con razón."""
    import os

    from hearme.privacy.storage import plan_collection

    salida = tmp_path / "output"
    salida.mkdir()
    viejo = salida / "viejo.m4b"
    viejo.write_bytes(b"x" * 2048)
    antiguo = (datetime.now(UTC) - timedelta(days=5)).timestamp()
    os.utime(viejo, (antiguo, antiguo))

    plan = plan_collection(
        output_dir=salida,
        uploads_dir=tmp_path / "uploads",
        cache_dir=tmp_path / "cache",
        keep_recent=0,
    )

    assert viejo in plan.items
    assert plan.bytes_to_free == 2048
    assert "conocimiento" in plan.protected
    assert viejo.exists(), "planificar no borra nada"


def test_lo_reciente_se_protege_aunque_se_pida_limpiar(tmp_path) -> None:
    """Quien acaba de convertir algo lo va a descargar en unos minutos."""
    from hearme.privacy.storage import plan_collection

    salida = tmp_path / "output"
    salida.mkdir()
    (salida / "recien-hecho.m4b").write_bytes(b"x" * 1024)

    plan = plan_collection(output_dir=salida, uploads_dir=tmp_path / "u", cache_dir=tmp_path / "c")
    assert plan.is_empty


def test_un_servidor_poco_usado_no_se_queda_vacio_al_limpiar(tmp_path) -> None:
    """Sin proteger los últimos N, todo sería «antiguo» y se borraría entero."""
    import os

    from hearme.privacy.storage import plan_collection

    salida = tmp_path / "output"
    salida.mkdir()
    antiguo = (datetime.now(UTC) - timedelta(days=30)).timestamp()
    for n in range(8):
        archivo = salida / f"libro{n}.m4b"
        archivo.write_bytes(b"x" * 100)
        os.utime(archivo, (antiguo + n, antiguo + n))

    plan = plan_collection(
        output_dir=salida, uploads_dir=tmp_path / "u", cache_dir=tmp_path / "c", keep_recent=5
    )
    assert len(plan.items) == 3, "los cinco más recientes se conservan"


def test_la_limpieza_solo_borra_lo_que_el_plan_enumero(tmp_path) -> None:
    """Garantiza que se borra lo que se enseñó, no lo aparecido después."""
    from hearme.privacy.storage import CollectionPlan, collect

    a = tmp_path / "a.m4b"
    b = tmp_path / "b.m4b"
    a.write_bytes(b"x" * 512)
    b.write_bytes(b"x" * 512)

    resultado = collect(CollectionPlan(items=(a,), bytes_to_free=512))

    assert not a.exists()
    assert b.exists(), "lo que no estaba en el plan no se toca"
    assert resultado.freed_bytes == 512


def test_los_tamanos_se_muestran_legibles() -> None:
    from hearme.privacy.storage import human

    assert human(512) == "512 B"
    assert human(2048) == "2.0 KB"
    assert human(5 * 1024**3) == "5.0 GB"


# --- compartir narraciones ----------------------------------------------------


def _narracion(**kwargs):
    from hearme.knowledge.lab import Provenance
    from hearme.knowledge.sharing import NarrationPlanRef, SharedNarration

    base = {
        "plan": NarrationPlanRef(
            text_digest="abc123", language="es", voice="ef_dora", engine="kokoro", style="novel"
        ),
        "title": "Antología de Spoon River",
        "attribution": "Edgar Lee Masters, Antología de Spoon River (1915), dominio público",
        "provenance": Provenance.PUBLIC_DOMAIN,
        "duration_s": 16440.0,
        "size_bytes": 131_520_000,
        "contributor": "biblioteca-municipal",
    }
    return SharedNarration(**{**base, **kwargs})


def test_no_se_puede_compartir_una_obra_con_derechos() -> None:
    """Distribuir el audio de una obra con derechos es una obra derivada."""
    from hearme.knowledge.lab import Provenance
    from hearme.knowledge.sharing import ShareError

    with pytest.raises(ShareError, match="dominio público"):
        _narracion(provenance=Provenance.SYNTHETIC)


def test_compartir_exige_atribucion_verificable() -> None:
    """«Dominio público» a secas no permite a nadie comprobar nada."""
    from hearme.knowledge.sharing import ShareError

    with pytest.raises(ShareError, match="atribución"):
        _narracion(attribution="es libre")


def test_la_misma_narracion_no_se_guarda_dos_veces() -> None:
    """Mismo plan y mismo texto dan el mismo audio: duplicarlo es pagar dos veces."""
    from hearme.knowledge.sharing import SharedCatalog

    catalogo = SharedCatalog()
    primera, es_nueva = catalogo.share(_narracion())
    assert es_nueva

    segunda, es_nueva = catalogo.share(_narracion(contributor="otra-biblioteca"))
    assert not es_nueva
    assert segunda is primera
    assert primera.reuses == 1
    assert len(catalogo.items) == 1


def test_compartir_ahorra_trabajo_a_los_demas() -> None:
    """Es la métrica que dice si compartir sirve de algo."""
    from hearme.knowledge.sharing import SharedCatalog

    catalogo = SharedCatalog()
    catalogo.share(_narracion())
    for _ in range(3):
        catalogo.share(_narracion())

    # 274 minutos de audio, reutilizados tres veces.
    assert catalogo.total_cpu_minutes_saved > 800
    assert "evitado" in catalogo.summary()["explanation"]


def test_se_puede_encontrar_una_narracion_ya_hecha() -> None:
    """La consulta que evita reconvertir un clásico que ya narró alguien."""
    from hearme.knowledge.sharing import NarrationPlanRef, SharedCatalog

    catalogo = SharedCatalog()
    compartida = _narracion()
    catalogo.share(compartida)

    mismo = NarrationPlanRef(
        text_digest="abc123", language="es", voice="ef_dora", engine="kokoro", style="novel"
    )
    otro_estilo = NarrationPlanRef(
        text_digest="abc123", language="es", voice="ef_dora", engine="kokoro", style="poetry"
    )

    assert catalogo.find(mismo) is compartida
    assert catalogo.find(otro_estilo) is None, "otro estilo es otra narración"


def test_la_retirada_es_inmediata_y_sin_discusion() -> None:
    """Si alguien reclama derechos, primero se retira y luego se habla."""
    from hearme.knowledge.sharing import SharedCatalog

    catalogo = SharedCatalog()
    compartida = _narracion()
    catalogo.share(compartida)

    assert catalogo.withdraw(compartida.plan.digest, "reclamación de derechos")
    assert not compartida.is_available
    assert catalogo.find(compartida.plan) is None
    assert catalogo.total_bytes == 0


def test_lo_compartido_no_revela_nada_mas_de_quien_comparte() -> None:
    from hearme.knowledge.sharing import SHARING_NOTICE

    datos = _narracion().to_dict()
    assert "document" not in datos
    assert "source_path" not in datos
    # El seudónimo consta porque la declaración de dominio público es suya.
    assert datos["contributor"] == "biblioteca-municipal"
    assert "retirarla en cualquier momento" in SHARING_NOTICE
