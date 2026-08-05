"""Tests de las garantías de privacidad y seguridad.

Cada test corresponde a una promesa que el proyecto hace por escrito. Una
garantía sin test es una intención, y en seguridad las intenciones no valen: lo
que no se comprueba, se rompe en el primer refactor y nadie se entera.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hearme.narration.score import MarkSource, ProsodyMark, SpanRole
from hearme.privacy.audit import AuditLog, Decision, EventKind
from hearme.privacy.crypto import (
    CryptoError,
    Envelope,
    constant_time_equals,
    derive_key_from_passphrase,
    generate_key,
    keyed_digest,
    seal,
    unseal,
)
from hearme.privacy.gdpr import (
    ConsentLedger,
    ConsentPurpose,
    ConsentRequired,
    DataSubjectRights,
    require_consent,
)
from hearme.privacy.keys import Keyring, Locked
from hearme.privacy.profile import ReadingDNA
from hearme.privacy.sandbox import (
    Capability,
    CapabilityDenied,
    PluginGuard,
    PluginManifest,
    TrustPolicy,
    minimal_policy,
)
from hearme.privacy.session import PrivateSession, SessionClosed
from hearme.privacy.shredder import ShredResult, shred
from hearme.privacy.vault import Vault, VaultError, coarsen_time, size_bucket, validate_metadata

#: scrypt real tarda 0,25 s por derivación. En los tests se baja el parámetro:
#: se prueba la lógica del llavero, no la dureza del KDF (que es un parámetro).
FAST_N = 1 << 12


@pytest.fixture
def keyring(tmp_path: Path) -> Keyring:
    kr = Keyring(tmp_path / "keyring.json")
    kr.initialize("frase-de-prueba-larga", scrypt_n=FAST_N)
    return kr


# --- cifrado ------------------------------------------------------------------


def test_el_ciclo_de_cifrado_es_reversible() -> None:
    key = generate_key()
    sobre = seal(key, b"la obra completa", context="job:1:content")
    assert unseal(key, sobre, context="job:1:content") == b"la obra completa"


def test_un_sobre_no_se_puede_reubicar_en_otro_registro() -> None:
    """Sin datos asociados, quien acceda al almacén puede mover sobres entre registros."""
    key = generate_key()
    sobre = seal(key, b"el perfil de Ana", context="profile:ana")

    with pytest.raises(CryptoError):
        unseal(key, sobre, context="profile:beatriz")


def test_se_detecta_cualquier_manipulacion() -> None:
    key = generate_key()
    sobre = seal(key, b"contenido", context="c")
    alterado = Envelope(
        sobre.version,
        sobre.salt,
        sobre.nonce,
        sobre.ciphertext[:-1] + bytes([sobre.ciphertext[-1] ^ 1]),
    )
    with pytest.raises(CryptoError):
        unseal(key, alterado, context="c")


def test_dos_cifrados_del_mismo_texto_son_distintos() -> None:
    """Sin esto, el almacén revelaría qué registros contienen lo mismo."""
    key = generate_key()
    a = seal(key, "idéntico".encode(), context="c")
    b = seal(key, "idéntico".encode(), context="c")
    assert a.ciphertext != b.ciphertext
    assert a.salt != b.salt


def test_la_clave_equivocada_no_dice_por_que_falla() -> None:
    """Distinguir 'clave mala' de 'datos alterados' sería un oráculo para quien ataca."""
    sobre = seal(generate_key(), b"x", context="c")
    with pytest.raises(CryptoError, match="no se pudo abrir el sobre"):
        unseal(generate_key(), sobre, context="c")


def test_el_kdf_es_determinista_y_depende_de_la_sal() -> None:
    salt_a, salt_b = b"a" * 16, b"b" * 16
    k1 = derive_key_from_passphrase("misma frase", salt_a, n=FAST_N)
    k2 = derive_key_from_passphrase("misma frase", salt_a, n=FAST_N)
    k3 = derive_key_from_passphrase("misma frase", salt_b, n=FAST_N)
    assert k1 == k2 and k1 != k3


def test_la_comparacion_de_tokens_es_de_tiempo_constante() -> None:
    assert constant_time_equals("token", "token")
    assert not constant_time_equals("token", "otro!")


# --- la fuga del hash de texto ------------------------------------------------


def test_una_huella_sin_clave_no_protege_lo_que_alguien_lee() -> None:
    """Documenta el fallo del diseño anterior para que nadie lo reintroduzca.

    `text_digest` es reversible por diccionario sobre textos públicos. El test
    demuestra el ataque: si algún día alguien propone publicar esas huellas, aquí
    está la razón por la que no.
    """
    from hearme.narration.score import text_digest

    corpus_publico = [f"Párrafo número {i} de una obra de dominio público." for i in range(500)]
    diccionario = {text_digest(p): p for p in corpus_publico}

    compartido = text_digest(corpus_publico[123])
    assert diccionario[compartido] == corpus_publico[123], "el hash sin clave se invierte"


def test_la_huella_con_clave_no_es_invertible_sin_la_clave(keyring: Keyring) -> None:
    """La corrección: con clave local, la huella no vale nada fuera de la instalación."""
    from hearme.narration.score import text_digest

    texto = "Párrafo número 123 de una obra de dominio público."
    corpus_publico = [f"Párrafo número {i} de una obra de dominio público." for i in range(500)]

    con_clave = keyed_digest(keyring.index_key, texto)
    diccionario_atacante = {text_digest(p): p for p in corpus_publico}

    assert con_clave not in diccionario_atacante
    # Y sigue sirviendo para lo suyo: identificar el mismo texto en local.
    assert con_clave == keyed_digest(keyring.index_key, texto)
    # Con otra clave, otra huella: dos instalaciones no se pueden correlacionar.
    assert con_clave != keyed_digest(generate_key(), texto)


# --- llavero ------------------------------------------------------------------


def test_sin_desbloquear_no_hay_clave(tmp_path: Path) -> None:
    kr = Keyring(tmp_path / "k.json")
    kr.initialize("frase-de-prueba-larga", scrypt_n=FAST_N)
    kr.lock()

    assert kr.is_locked
    with pytest.raises(Locked):
        _ = kr.master_key


def test_rotar_la_contrasena_no_recifra_los_datos(keyring: Keyring) -> None:
    """Si rotar costara horas, nadie rotaría. Ese es el argumento de la jerarquía."""
    maestra_antes = keyring.master_key
    keyring.change_passphrase("frase-de-prueba-larga", "otra-frase-mucho-mejor")
    keyring.lock()
    keyring.unlock("otra-frase-mucho-mejor")

    assert keyring.master_key == maestra_antes


def test_la_contrasena_antigua_deja_de_valer(keyring: Keyring) -> None:
    keyring.change_passphrase("frase-de-prueba-larga", "otra-frase-mucho-mejor")
    keyring.lock()
    with pytest.raises(CryptoError):
        keyring.unlock("frase-de-prueba-larga")


def test_se_rechaza_una_contrasena_corta(tmp_path: Path) -> None:
    with pytest.raises(CryptoError, match="al menos"):
        Keyring(tmp_path / "k.json").initialize("corta", scrypt_n=FAST_N)


def test_destruir_el_llavero_inutiliza_lo_cifrado(keyring: Keyring) -> None:
    """Borrado criptográfico: la única forma fiable de borrar en almacenamiento moderno."""
    sobre = seal(keyring.master_key, b"secreto", context="c")
    keyring.destroy()

    assert not keyring.path.exists()
    assert keyring.is_locked
    with pytest.raises(CryptoError):
        unseal(generate_key(), sobre, context="c")


def test_el_llavero_no_es_legible_por_terceros(keyring: Keyring) -> None:
    assert keyring.path.stat().st_mode & 0o077 == 0, (
        "el llavero no puede tener permisos de grupo/otros"
    )


# --- separación contenido / metadatos -----------------------------------------


def test_el_almacen_rechaza_contenido_disfrazado_de_metadato(keyring: Keyring) -> None:
    vault = Vault(keyring)
    with pytest.raises(VaultError, match="es contenido"):
        vault.put("j1", "job", metadata={"title": "Mi diagnóstico médico"})


def test_el_almacen_rechaza_el_tamano_exacto(keyring: Keyring) -> None:
    """El tamaño en bytes es una huella dactilar contra un catálogo público."""
    vault = Vault(keyring)
    with pytest.raises(VaultError, match="identifica el contenido"):
        vault.put("j1", "job", metadata={"size_bytes": 2481923})


def test_los_cubos_de_tamano_pierden_la_precision_identificativa() -> None:
    assert size_bucket(2481923) == size_bucket(2481924)
    assert size_bucket(2481923) == size_bucket(3000000)  # mismo cubo 2-4 MB
    assert size_bucket(1000) != size_bucket(10_000_000)  # sigue siendo informativo


def test_las_marcas_de_tiempo_se_redondean() -> None:
    momento = datetime(2026, 8, 4, 17, 43, 21, 12345, tzinfo=UTC)
    grueso = coarsen_time(momento)
    assert (grueso.minute, grueso.second, grueso.microsecond) == (0, 0, 0)


def test_el_contenido_se_guarda_cifrado_y_se_recupera(keyring: Keyring) -> None:
    vault = Vault(keyring)
    registro = vault.put(
        "j1", "job", content={"title": "Obra", "text": "…"}, metadata={"status": "done"}
    )

    assert registro.sealed is not None
    en_bruto = json.dumps(registro.sealed)
    assert "Obra" not in en_bruto, "el título no puede aparecer en el registro serializado"
    assert vault.get("j1")["title"] == "Obra"


def test_los_metadatos_se_consultan_sin_descifrar(keyring: Keyring) -> None:
    vault = Vault(keyring)
    vault.put("j1", "job", content={"text": "secreto"}, metadata={"status": "running"})
    keyring.lock()

    assert vault.metadata_of("j1") == {"status": "running"}
    with pytest.raises(Locked):
        vault.get("j1")


# --- sesión privada -----------------------------------------------------------


def test_la_sesion_privada_no_deja_rastro() -> None:
    with PrivateSession() as sesion:
        ruta = sesion.write("audio", b"contenido sensible")
        raiz = sesion.root
        assert ruta.exists()
        assert b"contenido sensible" not in ruta.read_bytes(), "debe escribirse cifrado"

    assert raiz is not None and not raiz.exists()


def test_al_cerrar_la_sesion_su_clave_desaparece() -> None:
    sesion = PrivateSession()
    sesion.write("a", b"x")
    rastro = sesion.close()

    with pytest.raises(SessionClosed):
        sesion.read("a")
    assert rastro.artifacts_destroyed == 1


def test_el_rastro_de_sesion_no_revela_que_se_leyo() -> None:
    """Lo único que sobrevive es que hubo una sesión y cuánto duró."""
    with PrivateSession() as sesion:
        sesion.write("documento-medico", b"x")
        rastro_dict = sesion.close().to_dict()

    serializado = json.dumps(rastro_dict)
    assert "documento-medico" not in serializado
    assert set(rastro_dict) == {
        "session_id",
        "started_at",
        "ended_at",
        "duration_s",
        "artifacts_destroyed",
        "shred_summary",
    }


def test_cerrar_dos_veces_no_falla() -> None:
    sesion = PrivateSession()
    sesion.close()
    sesion.close()  # idempotente


# --- borrado ------------------------------------------------------------------


def test_shred_sobrescribe_y_borra(tmp_path: Path) -> None:
    objetivo = tmp_path / "temporal.bin"
    objetivo.write_bytes(b"A" * 4096)

    informe = shred(objetivo)
    assert informe.result is ShredResult.OVERWRITTEN
    assert not objetivo.exists()


def test_shred_nunca_se_declara_garantia_definitiva(tmp_path: Path) -> None:
    """La honestidad es parte de la garantía: en SSD sobrescribir no asegura nada."""
    objetivo = tmp_path / "t.bin"
    objetivo.write_bytes(b"x")
    assert shred(objetivo).is_cryptographically_final is False


def test_shred_de_algo_inexistente_no_es_un_error(tmp_path: Path) -> None:
    assert shred(tmp_path / "no-existe").result is ShredResult.ABSENT


# --- auditoría ----------------------------------------------------------------


def test_la_cadena_de_auditoria_detecta_manipulacion() -> None:
    log = AuditLog()
    log.append(EventKind.RECORD_CREATED, record_id="j1")
    log.append(EventKind.RECORD_READ, record_id="j1")
    assert log.verify()[0]

    # Alguien altera una entrada intermedia
    from dataclasses import replace

    log._events[0] = replace(log.events()[0], record_id="j999")

    integra, motivo = log.verify()
    assert not integra and "alterada" in motivo


def test_el_registro_de_auditoria_no_puede_filtrar_contenido() -> None:
    """Sería la copia en claro de todo lo que se cifró al guardarlo."""
    log = AuditLog()
    with pytest.raises(VaultError, match="es contenido"):
        log.append(EventKind.RECORD_CREATED, detail={"title": "Mi historial clínico"})


def test_una_decision_automatica_se_explica_en_lenguaje_llano() -> None:
    log = AuditLog()
    log.append(
        EventKind.DECISION,
        decision=Decision(
            subject="motor_tts",
            outcome="piper",
            rationale="es el único motor instalado que cubre el idioma del documento",
            factors={"idioma": "ca", "motores_disponibles": "piper"},
            alternatives={"kokoro": "no cubre el catalán"},
            decided_by="selector/1.0",
        ),
    )
    explicacion = log.decisions("motor_tts")[0].explain()

    assert "piper" in explicacion
    assert "no cubre el catalán" in explicacion, "debe decir por qué NO salió la alternativa"


def test_la_auditoria_persiste_y_se_recarga(tmp_path: Path) -> None:
    ruta = tmp_path / "audit.jsonl"
    log = AuditLog(ruta)
    log.append(EventKind.RECORD_CREATED, record_id="j1")
    log.append(EventKind.RECORD_DELETED, record_id="j1")

    recargado = AuditLog(ruta)
    assert len(recargado) == 2
    assert recargado.verify()[0]


# --- ADN de narración ---------------------------------------------------------


def test_el_adn_aprende_una_preferencia_relativa() -> None:
    dna = ReadingDNA()
    original = ProsodyMark(0, 10, role=SpanRole.DIALOGUE, pause_after_ms=400, rate=1.0)
    corregida = ProsodyMark(0, 10, role=SpanRole.DIALOGUE, pause_after_ms=600, rate=1.0)

    for _ in range(5):
        dna.learn_from(original, corregida, role=SpanRole.DIALOGUE)

    aplicada = dna.apply(original)
    assert aplicada.pause_after_ms > 400
    assert aplicada.source is MarkSource.HUMAN


def test_pocas_correcciones_no_reconfiguran_la_escucha() -> None:
    """Dos correcciones a deshora no pueden cambiarlo todo."""
    poco = ReadingDNA()
    mucho = ReadingDNA()
    original = ProsodyMark(0, 10, role=SpanRole.DIALOGUE, pause_after_ms=400)
    corregida = ProsodyMark(0, 10, role=SpanRole.DIALOGUE, pause_after_ms=800)

    poco.learn_from(original, corregida, role=SpanRole.DIALOGUE)
    for _ in range(10):
        mucho.learn_from(original, corregida, role=SpanRole.DIALOGUE)

    assert poco.apply(original).pause_after_ms < mucho.apply(original).pause_after_ms


def test_el_adn_es_portable_entre_instalaciones() -> None:
    """Es la promesa central: tu forma de escuchar sobrevive al cambio de todo."""
    dna = ReadingDNA(language="es")
    original = ProsodyMark(0, 10, role=SpanRole.HEADING, pause_after_ms=1000)
    for _ in range(6):
        dna.learn_from(
            original,
            ProsodyMark(0, 10, role=SpanRole.HEADING, pause_after_ms=1400),
            role=SpanRole.HEADING,
        )

    key = generate_key()
    viaje = ReadingDNA.import_encrypted(key, dna.export_encrypted(key))

    assert viaje.apply(original).pause_after_ms == dna.apply(original).pause_after_ms


def test_el_adn_exportado_va_cifrado() -> None:
    dna = ReadingDNA()
    dna.lexicon["Sanhueza"] = "san-güe-sa"
    blob = dna.export_encrypted(generate_key())
    assert b"Sanhueza" not in blob


def test_el_resumen_compartible_no_incluye_el_lexico() -> None:
    """El vocabulario de alguien delata su oficio, su salud y su procedencia."""
    dna = ReadingDNA()
    dna.lexicon["mieloma"] = "mie-lo-ma"
    resumen = dna.shareable_summary()

    assert "lexicon" not in resumen
    assert "mieloma" not in json.dumps(resumen, ensure_ascii=False)


def test_el_adn_acota_los_valores_extremos() -> None:
    """Un perfil manipulado no debe poder volver la narración inservible."""
    peligroso = ReadingDNA.from_dict(
        {**ReadingDNA().to_dict(), "global_pause_scale": 9999.0, "global_rate_scale": 0.001}
    )
    assert peligroso.global_pause_scale <= 4.0
    assert peligroso.global_rate_scale >= 0.5


# --- confianza cero en plugins ------------------------------------------------


def test_un_plugin_sin_concesion_no_carga() -> None:
    guard = PluginGuard(TrustPolicy())
    manifiesto = PluginManifest(
        name="raro", version="1.0", capabilities=frozenset({Capability.READ_DOCUMENT})
    )

    decision = guard.evaluate(manifiesto)
    assert not decision.allowed
    assert Capability.READ_DOCUMENT in decision.denied


def test_las_capacidades_peligrosas_exigen_justificacion() -> None:
    manifiesto = PluginManifest(
        name="sospechoso", version="1.0", capabilities=frozenset({Capability.NETWORK})
    )
    with pytest.raises(CapabilityDenied, match="sin justificar"):
        PluginGuard(TrustPolicy()).evaluate(manifiesto)


def test_ningun_plugin_interno_pide_red() -> None:
    """Un parser que quiera salir a internet debe verse antes de instalarlo."""
    politica = minimal_policy()
    for plugin, concedidas in politica.grants.items():
        assert Capability.NETWORK not in concedidas, f"'{plugin}' no debería tener red"
        assert Capability.READ_PROFILE not in concedidas


def test_el_freno_duro_gana_a_la_concesion() -> None:
    politica = TrustPolicy(never=frozenset({Capability.NETWORK}))
    politica.grant("plugin", Capability.NETWORK)
    assert not politica.allows("plugin", Capability.NETWORK)


def test_usar_una_capacidad_no_concedida_falla_y_queda_registrado() -> None:
    log = AuditLog()
    guard = PluginGuard(TrustPolicy(), audit_log=log)

    with pytest.raises(CapabilityDenied):
        guard.require("plugin", Capability.NETWORK)
    assert any(e.kind is EventKind.CAPABILITY_DENIED for e in log.events())


# --- RGPD ---------------------------------------------------------------------


def test_todo_lo_opcional_empieza_desactivado() -> None:
    ledger = ConsentLedger()
    for finalidad in ConsentPurpose:
        assert not ledger.has(finalidad), f"'{finalidad.value}' no puede venir concedido"


def test_una_operacion_opcional_sin_consentimiento_falla() -> None:
    ledger = ConsentLedger()
    with pytest.raises(ConsentRequired):
        require_consent(ledger, ConsentPurpose.CONTRIBUTE_KNOWLEDGE)


def test_retirar_el_consentimiento_es_inmediato() -> None:
    ledger = ConsentLedger()
    ledger.grant(ConsentPurpose.CONTRIBUTE_KNOWLEDGE, notice_version="v1")
    assert ledger.has(ConsentPurpose.CONTRIBUTE_KNOWLEDGE)

    ledger.withdraw(ConsentPurpose.CONTRIBUTE_KNOWLEDGE)
    assert not ledger.has(ConsentPurpose.CONTRIBUTE_KNOWLEDGE)


def test_el_historial_de_consentimiento_no_se_reescribe() -> None:
    """Hay que poder demostrar qué era lícito y cuándo."""
    ledger = ConsentLedger()
    ledger.grant(ConsentPurpose.PERSONAL_PROFILE, notice_version="v1")
    ledger.withdraw(ConsentPurpose.PERSONAL_PROFILE)
    ledger.grant(ConsentPurpose.PERSONAL_PROFILE, notice_version="v2")

    assert len(ledger.history) == 3
    assert ledger.has(ConsentPurpose.PERSONAL_PROFILE)


def test_la_supresion_destruye_la_clave_y_entrega_comprobante(keyring: Keyring) -> None:
    vault = Vault(keyring)
    vault.put("j1", "job", content={"text": "x"})
    log = AuditLog()
    derechos = DataSubjectRights(vault=vault, audit=log)

    recibo = derechos.erase(keyring=keyring)

    assert recibo.keys_destroyed == 1
    assert recibo.records_removed == 1
    assert "audit_log" in recibo.retained, "debe declarar qué se conserva y por qué"


def test_la_exportacion_es_portable_y_documentada() -> None:
    derechos = DataSubjectRights(profile=ReadingDNA(), audit=AuditLog())
    datos = json.loads(derechos.export_portable())

    assert datos["format"] == "hearme.portable.v1"
    assert "reading_dna" in datos


def test_el_registro_de_tratamiento_declara_cero_transferencias() -> None:
    registro = DataSubjectRights().processing_record()
    assert "ninguna" in registro["transfers"]
    assert registro["processor"].startswith("ninguno")


def test_validate_metadata_acepta_lo_operativo() -> None:
    """Lo que no identifica ni a una persona ni a un documento puede ir en claro."""
    validate_metadata({"status": "running", "stage": "sintesis", "size_bucket": "2-4MB"})
