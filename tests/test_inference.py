"""Tests del subsistema de optimización de inferencia.

Todo se prueba con hardware y disponibilidad inyectados: las decisiones del
planificador deben ser verificables sin una GPU, sin instalar ningún motor y sin
cargar un solo peso. Si un test necesitara descargar algo, el diseño estaría mal.
"""

from __future__ import annotations

import pytest

from hearme.domain.inference import (
    BackendProfile,
    Capability,
    Measurement,
    Objective,
    Technique,
    WorkloadClass,
)
from hearme.infrastructure.hardware import Accelerator, HardwareProfile
from hearme.infrastructure.inference import backends, planner, runtime
from hearme.infrastructure.inference.telemetry import TelemetryStore
from hearme.infrastructure.inference.tuner import MAX_LEVEL, AdaptiveTuner


def hardware(*, vram_mb: int = 0, cores: int = 8, accelerator: Accelerator = Accelerator.CPU):
    return HardwareProfile(
        accelerator=accelerator,
        device_name="test",
        vram_mb=vram_mb,
        cpu_cores=cores,
        ram_mb=16384,
        arch="x86_64",
        system="Linux",
    )


TARGET_MACHINE = hardware(vram_mb=4096, cores=16, accelerator=Accelerator.CUDA)
BIG_GPU = hardware(vram_mb=24576, cores=16, accelerator=Accelerator.CUDA)

#: Todo instalado: aísla la decisión del planificador de lo que haya en la máquina.
ALL_INSTALLED = dict.fromkeys(backends.PROFILES, True)


# --- Negociación de capacidades: el mecanismo central ---------------------


def test_tecnica_de_cache_kv_no_aplica_a_tts_de_una_pasada():
    """§0 del análisis: paginar una caché KV que no existe es un sinsentido."""
    paged = next(t for t in planner.catalog.CATALOG if t.name == "paged_attention")

    todas = frozenset(Capability)
    assert not paged.is_applicable(WorkloadClass.TTS_FEEDFORWARD, todas)
    assert paged.is_applicable(WorkloadClass.LLM_DECODE, todas)


def test_tecnica_desconocida_por_el_backend_no_se_activa():
    profile = BackendProfile(
        name="minimo",
        capabilities=frozenset({Capability.STATIC_BATCHING}),
        workloads=frozenset({WorkloadClass.LLM_DECODE}),
        license="MIT",
    )
    nombres = {t.name for t in planner.applicable_techniques(profile, WorkloadClass.LLM_DECODE)}
    assert nombres == {"static_batching"}


def test_una_tecnica_nueva_no_obliga_a_tocar_el_planificador():
    """El requisito real del encargo: extensibilidad sin modificar el núcleo."""
    inventada = Technique(
        name="tecnica_de_2027",
        requires=frozenset({Capability.FLASH_ATTENTION}),
        applies_to=frozenset({WorkloadClass.LLM_DECODE}),
        expected_speedup=9.0,
    )
    planner.catalog.register(inventada)
    try:
        profile = BackendProfile(
            name="con_flash",
            capabilities=frozenset({Capability.FLASH_ATTENTION}),
            workloads=frozenset({WorkloadClass.LLM_DECODE}),
            license="MIT",
        )
        activas = planner.applicable_techniques(profile, WorkloadClass.LLM_DECODE)
        assert "tecnica_de_2027" in {t.name for t in activas}
    finally:
        planner.catalog.CATALOG = tuple(
            t for t in planner.catalog.CATALOG if t.name != "tecnica_de_2027"
        )
        del planner.catalog.BY_NAME["tecnica_de_2027"]


def test_int8_queda_anulada_por_int4():
    profile = BackendProfile(
        name="ambas",
        capabilities=frozenset({Capability.QUANTIZATION_INT8, Capability.QUANTIZATION_INT4}),
        workloads=frozenset({WorkloadClass.LLM_DECODE}),
        license="MIT",
    )
    nombres = {t.name for t in planner.applicable_techniques(profile, WorkloadClass.LLM_DECODE)}
    assert "quantization_int4" in nombres
    assert "quantization_int8" not in nombres


# --- Descubrimiento: los motores se autodescartan -------------------------


def test_vllm_se_autodescarta_en_una_gpu_de_4gb():
    """No es que rinda peor: es que el runtime no deja VRAM para los pesos."""
    candidatos = {
        c.profile.name: c
        for c in planner.evaluate_backends(
            WorkloadClass.LLM_DECODE, hardware=TARGET_MACHINE, available=ALL_INSTALLED
        )
    }
    assert not candidatos["vllm"].viable
    assert "overhead" in candidatos["vllm"].reason
    # llama.cpp no tiene suelo de VRAM: sobrevive donde vLLM no arranca.
    assert candidatos["llama_cpp"].viable


def test_con_gpu_grande_vllm_y_sglang_se_activan_solos():
    candidatos = {
        c.profile.name: c
        for c in planner.evaluate_backends(
            WorkloadClass.LLM_DECODE, hardware=BIG_GPU, available=ALL_INSTALLED
        )
    }
    assert candidatos["vllm"].viable
    assert candidatos["sglang"].viable
    # SGLang gana: RadixAttention y compresión de caché le dan más técnicas.
    assert candidatos["sglang"].score > candidatos["vllm"].score
    # Y gana también a llama.cpp: con el modelo entero en la GPU, escalar con
    # núcleos de CPU deja de ser una ventaja. Es la decisión de §1 del análisis.
    assert candidatos["sglang"].score > candidatos["llama_cpp"].score


def test_el_planificador_puede_planificar_para_un_motor_ya_elegido():
    """En TTS el motor lo elige `tts.selector`; aquí solo se negocian técnicas."""
    plan = planner.plan(
        WorkloadClass.TTS_FEEDFORWARD,
        backend="piper",
        hardware=TARGET_MACHINE,
        available=ALL_INSTALLED,
    )
    assert plan.backend == "piper"
    assert "static_batching" in plan.techniques


def test_planificar_para_un_motor_no_viable_falla_con_diagnostico():
    with pytest.raises(planner.NoBackendViable) as exc:
        planner.plan(
            WorkloadClass.LLM_DECODE,
            backend="vllm",
            hardware=TARGET_MACHINE,
            available=ALL_INSTALLED,
        )
    assert "vllm" in str(exc.value)


def test_mlx_solo_existe_en_apple_silicon():
    candidatos = {
        c.profile.name: c
        for c in planner.evaluate_backends(
            WorkloadClass.LLM_DECODE, hardware=TARGET_MACHINE, available=ALL_INSTALLED
        )
    }
    assert not candidatos["mlx"].viable
    assert "Apple Silicon" in candidatos["mlx"].reason


def test_un_perfil_sin_adaptador_no_se_elige_aunque_este_instalado():
    candidatos = {
        c.profile.name: c
        for c in planner.evaluate_backends(
            WorkloadClass.TTS_AUTOREGRESSIVE, hardware=BIG_GPU, available=ALL_INSTALLED
        )
    }
    assert not candidatos["qwen3_tts"].viable
    assert "adaptador" in candidatos["qwen3_tts"].reason


def test_sin_ningun_backend_viable_el_error_dice_por_que():
    with pytest.raises(planner.NoBackendViable) as exc:
        planner.plan(
            WorkloadClass.LLM_DECODE,
            hardware=TARGET_MACHINE,
            available=dict.fromkeys(backends.PROFILES, False),
        )
    assert "llama_cpp" in str(exc.value)


# --- La ruta caliente real: TTS y traducción ------------------------------


def test_tts_de_una_pasada_batchea_sin_peticiones_concurrentes():
    """Un capítulo son decenas de párrafos: hay lote aunque no haya concurrencia."""
    plan = planner.plan(
        WorkloadClass.TTS_FEEDFORWARD,
        hardware=TARGET_MACHINE,
        available=ALL_INSTALLED,
        concurrent=False,
    )
    assert "static_batching" in plan.techniques


def test_el_modo_estudio_no_batchea_si_no_hay_concurrencia():
    """Contraste con el anterior: el LLM recibe una petición cada vez."""
    plan = planner.plan(
        WorkloadClass.LLM_DECODE,
        hardware=TARGET_MACHINE,
        available=ALL_INSTALLED,
        concurrent=False,
    )
    assert "static_batching" not in plan.techniques
    assert "continuous_batching" not in plan.techniques


def test_el_modo_estudio_activa_prefix_caching():
    """La técnica de mayor retorno del proyecto para LLM: el prompt fijo."""
    plan = planner.plan(WorkloadClass.LLM_DECODE, hardware=TARGET_MACHINE, available=ALL_INSTALLED)
    assert "prefix_caching" in plan.techniques


def test_el_traductor_no_comercial_requiere_permiso_explicito(monkeypatch):
    from hearme.config import settings

    monkeypatch.setattr(settings, "allow_non_commercial_models", False)
    assert backends.detect_available()["nllb"] is False


# --- ASR ------------------------------------------------------------------


def test_el_decodificador_de_asr_cuenta_como_autorregresivo():
    """Genera token a token y tiene caché KV: estaba mal clasificado fuera."""
    kv = next(t for t in planner.catalog.CATALOG if t.name == "kv_cache_quantization")
    assert kv.is_applicable(WorkloadClass.ASR, frozenset(Capability))


def test_whisper_large_se_autodescarta_en_4gb_y_qwen3_asr_no():
    candidatos = {
        c.profile.name: c
        for c in planner.evaluate_backends(
            WorkloadClass.ASR, hardware=TARGET_MACHINE, available=ALL_INSTALLED
        )
    }
    # Ambos esperan adaptador, así que ninguno es viable todavía; lo que se
    # comprueba es que el motivo del descarte sea el correcto para cada uno.
    assert candidatos["whisper_large"].profile.min_vram_mb > TARGET_MACHINE.vram_mb
    assert candidatos["qwen3_asr"].profile.min_vram_mb < TARGET_MACHINE.vram_mb


def test_los_motores_de_asr_declaran_licencia_permisiva():
    """El proyecto excluye lo no comercial: Parakeet y Canary quedaron fuera."""
    for name in ("qwen3_asr", "whisper_cpp", "whisper_large"):
        assert backends.PROFILES[name].license in {"Apache-2.0", "MIT"}


def test_asr_sigue_sin_adaptador_y_lo_dice_asi():
    candidatos = planner.evaluate_backends(
        WorkloadClass.ASR, hardware=TARGET_MACHINE, available=ALL_INSTALLED
    )
    assert candidatos, "ASR ya no debe quedarse sin perfiles registrados"
    assert all("adaptador" in c.reason for c in candidatos)


# --- Filtros de rentabilidad ----------------------------------------------


def test_la_atencion_dispersa_no_se_activa_con_contexto_corto():
    # Fijamos SGLang (único motor con atención dispersa) y nivel 1 (degrada
    # calidad), para aislar la regla de contexto de la de calidad.
    def con(context_tokens: int) -> tuple[str, ...]:
        return planner.plan(
            WorkloadClass.LLM_DECODE,
            backend="sglang",
            hardware=BIG_GPU,
            available=ALL_INSTALLED,
            quality_level=1,
            context_tokens=context_tokens,
        ).techniques

    assert "sparse_attention" not in con(2048)
    assert "sparse_attention" in con(16384)


def test_a_maxima_calidad_no_se_activan_tecnicas_que_degraden():
    """Nivel 0 = el usuario no ha pedido velocidad: nada que se oiga o se note."""
    plan = planner.plan(
        WorkloadClass.LLM_DECODE,
        backend="sglang",
        hardware=BIG_GPU,
        available=ALL_INSTALLED,
        quality_level=0,
        context_tokens=16384,
    )
    assert "sparse_attention" not in plan.techniques


def test_en_modo_calidad_no_se_aceptan_tecnicas_que_degraden():
    plan = planner.plan(
        WorkloadClass.LLM_DECODE,
        hardware=BIG_GPU,
        available=ALL_INSTALLED,
        objective=Objective.QUALITY,
        context_tokens=16384,
    )
    degradantes = {t.name for t in planner.catalog.CATALOG if t.quality_delta < -0.03}
    assert not degradantes & set(plan.techniques)


# --- Puente con el pipeline -----------------------------------------------


def test_un_motor_de_plugin_desconocido_no_rompe_la_conversion():
    """Optimizar no puede romper lo que ya funcionaba: plan neutro y a seguir."""
    plan = runtime.plan_for(
        "motor_inventado_de_un_tercero",
        default_workload=WorkloadClass.TTS_FEEDFORWARD,
        hardware=TARGET_MACHINE,
    )
    assert plan.techniques == ()
    assert plan.number("batch_size") == 1
    assert plan.workload is WorkloadClass.TTS_FEEDFORWARD


def test_un_motor_registrado_pero_no_viable_tambien_da_plan_neutro():
    plan = runtime.plan_for(
        "chatterbox",  # sin adaptador todavía
        default_workload=WorkloadClass.TTS_AUTOREGRESSIVE,
        hardware=TARGET_MACHINE,
    )
    assert plan.techniques == ()


def test_la_carga_sale_del_perfil_y_no_de_lo_que_suponga_quien_llama():
    # Quien llama propone TTS de una pasada; el perfil de Chatterbox dice que es
    # autorregresivo, y manda el perfil.
    assert (
        runtime.workload_for("chatterbox", default=WorkloadClass.TTS_FEEDFORWARD)
        is WorkloadClass.TTS_AUTOREGRESSIVE
    )
    assert (
        runtime.workload_for("desconocido", default=WorkloadClass.TTS_FEEDFORWARD)
        is WorkloadClass.TTS_FEEDFORWARD
    )


def test_el_modo_borrador_optimiza_latencia_y_el_normal_calidad():
    assert runtime.objective_for("draft") is Objective.LATENCY
    assert runtime.objective_for("high") is Objective.QUALITY


def test_el_lote_sale_de_la_maquina_medida_y_no_de_una_constante():
    grande = planner.execution_parameters(
        WorkloadClass.SEQ2SEQ, ("static_batching",), hardware(cores=32)
    )
    pequena = planner.execution_parameters(
        WorkloadClass.SEQ2SEQ, ("static_batching",), hardware(cores=2)
    )
    assert grande["batch_size"] > pequena["batch_size"]


def test_sin_batching_el_lote_es_uno():
    params = planner.execution_parameters(
        WorkloadClass.SEQ2SEQ, ("quantization_int8",), hardware(cores=16)
    )
    assert params["batch_size"] == 1


def test_el_lote_no_crece_sin_limite_con_los_nucleos():
    """Pasado 2x deja de amortizar y empieza a costar memoria y latencia."""
    params = planner.execution_parameters(
        WorkloadClass.SEQ2SEQ, ("static_batching",), hardware(cores=256)
    )
    assert params["batch_size"] == 32


def test_un_parametro_ausente_o_de_otro_tipo_devuelve_el_de_por_defecto():
    plan = runtime.neutral_plan("x", WorkloadClass.TTS_FEEDFORWARD, "prueba")
    plan.parameters["raro"] = "no soy un número"
    assert plan.number("no_existe", 7) == 7
    assert plan.number("raro", 7) == 7


def test_registrar_una_sintesis_calcula_el_rtf():
    store = TelemetryStore()
    runtime.record_audio(
        "kokoro",
        WorkloadClass.TTS_FEEDFORWARD,
        elapsed_s=0.5,
        audio_s=10.0,
        store=store,
    )
    stats = store.stats("kokoro")
    assert stats is not None
    assert stats.rtf == pytest.approx(0.05)


def test_una_sintesis_de_duracion_cero_no_divide_entre_cero():
    store = TelemetryStore()
    medicion = runtime.record_audio(
        "kokoro", WorkloadClass.TTS_FEEDFORWARD, elapsed_s=0.5, audio_s=0.0, store=store
    )
    assert medicion.rtf == 0.0


# --- El bucle cerrado: medir -> decidir -> ejecutar distinto --------------


def test_una_medicion_alimenta_al_historico_y_al_tuner():
    """Registrar en uno solo de los dos dejaba el bucle abierto."""
    store = TelemetryStore()
    adaptive = AdaptiveTuner()
    runtime.record_failure(
        "kokoro", WorkloadClass.TTS_FEEDFORWARD, "OOM", store=store, adaptive=adaptive
    )

    assert store.stats("kokoro") is None  # solo hay una medición fallida
    assert adaptive.level(WorkloadClass.TTS_FEEDFORWARD) == 1


def test_degradar_reduce_la_memoria_en_vuelo_y_no_toca_el_timbre():
    """El motivo casi siempre es falta de memoria, así que se responde con memoria."""
    sin_degradar = planner.execution_parameters(
        WorkloadClass.SEQ2SEQ, ("static_batching",), hardware(cores=16), quality_level=0
    )
    degradado = planner.execution_parameters(
        WorkloadClass.SEQ2SEQ, ("static_batching",), hardware(cores=16), quality_level=2
    )
    assert degradado["batch_size"] == sin_degradar["batch_size"] // 4
    assert degradado["workers"] < sin_degradar["workers"]


def test_la_degradacion_nunca_deja_el_lote_ni_los_hilos_en_cero():
    params = planner.execution_parameters(
        WorkloadClass.SEQ2SEQ, ("static_batching",), hardware(cores=2), quality_level=MAX_LEVEL
    )
    assert params["batch_size"] >= 1
    assert params["workers"] >= 1


def test_un_fallo_hace_que_la_siguiente_ejecucion_pida_menos_memoria():
    """La prueba de que el bucle cierra de verdad, de punta a punta."""
    adaptive = AdaptiveTuner()
    antes = runtime.plan_for(
        "marian",
        default_workload=WorkloadClass.SEQ2SEQ,
        hardware=TARGET_MACHINE,
        available=ALL_INSTALLED,
        adaptive=adaptive,
    )

    runtime.record_failure(
        "marian",
        WorkloadClass.SEQ2SEQ,
        "CUDA out of memory",
        store=TelemetryStore(),
        adaptive=adaptive,
    )

    despues = runtime.plan_for(
        "marian",
        default_workload=WorkloadClass.SEQ2SEQ,
        hardware=TARGET_MACHINE,
        available=ALL_INSTALLED,
        adaptive=adaptive,
    )
    assert despues.quality_level == 1
    assert despues.number("batch_size") < antes.number("batch_size")


# --- Telemetría y adaptación ----------------------------------------------


def test_la_medicion_gana_a_la_declaracion():
    """Un backend que rinde mal medido debe caer por debajo del que rinde bien."""
    store = TelemetryStore()
    for _ in range(5):
        store.record(
            Measurement(
                backend="llama_cpp",
                workload=WorkloadClass.LLM_DECODE,
                tokens_per_second=90.0,
            )
        )
        store.record(
            Measurement(
                backend="ollama",
                workload=WorkloadClass.LLM_DECODE,
                tokens_per_second=5.0,
            )
        )

    candidatos = {
        c.profile.name: c
        for c in planner.evaluate_backends(
            WorkloadClass.LLM_DECODE,
            hardware=TARGET_MACHINE,
            available=ALL_INSTALLED,
            store=store,
        )
    }
    assert candidatos["llama_cpp"].score > candidatos["ollama"].score
    assert "tok/s" in candidatos["llama_cpp"].reason


def test_en_audio_la_correccion_usa_rtf_y_no_tokens():
    store = TelemetryStore()
    for _ in range(5):
        store.record(
            Measurement(backend="kokoro", workload=WorkloadClass.TTS_FEEDFORWARD, rtf=0.05)
        )
    candidatos = {
        c.profile.name: c
        for c in planner.evaluate_backends(
            WorkloadClass.TTS_FEEDFORWARD,
            hardware=TARGET_MACHINE,
            available=ALL_INSTALLED,
            store=store,
        )
    }
    assert "RTF" in candidatos["kokoro"].reason


def test_los_fallos_penalizan_al_backend():
    store = TelemetryStore()
    for _ in range(5):
        store.record(Measurement(backend="llama_cpp", workload=WorkloadClass.LLM_DECODE, ok=False))
        store.record(
            Measurement(
                backend="llama_cpp",
                workload=WorkloadClass.LLM_DECODE,
                tokens_per_second=90.0,
            )
        )
    stats = store.stats("llama_cpp")
    assert stats is not None
    assert stats.failures == 5


# --- Tuner ----------------------------------------------------------------


def test_el_tuner_degrada_tras_latencias_sostenidas_no_por_un_pico():
    tuner = AdaptiveTuner(objective=Objective.LATENCY)
    lenta = Measurement(backend="x", workload=WorkloadClass.LLM_DECODE, ttft_ms=5000.0)

    assert tuner.observe(lenta) == 0  # un pico no mueve nada
    tuner.observe(lenta)
    assert tuner.observe(lenta) == 1  # tres seguidas sí


def test_un_fallo_degrada_de_inmediato():
    """Un fallo suele ser falta de memoria: degradar la libera."""
    tuner = AdaptiveTuner()
    fallo = Measurement(backend="x", workload=WorkloadClass.LLM_DECODE, ok=False, error="OOM")
    assert tuner.observe(fallo) == 1


def test_el_tuner_no_degrada_indefinidamente():
    tuner = AdaptiveTuner()
    fallo = Measurement(backend="x", workload=WorkloadClass.LLM_DECODE, ok=False)
    for _ in range(20):
        tuner.observe(fallo)
    assert tuner.level(WorkloadClass.LLM_DECODE) == MAX_LEVEL


def test_en_audio_el_tuner_vigila_el_rtf_y_no_el_ttft():
    tuner = AdaptiveTuner(objective=Objective.BALANCED)
    # RTF 2.0 = sintetizar tarda el doble que reproducir: inaceptable, aunque el
    # TTFT sea excelente.
    mala = Measurement(backend="x", workload=WorkloadClass.TTS_FEEDFORWARD, ttft_ms=1.0, rtf=2.0)
    for _ in range(3):
        nivel = tuner.observe(mala)
    assert nivel == 1


def test_el_voto_humano_recupera_calidad_aunque_la_latencia_aguante():
    tuner = AdaptiveTuner()
    fallo = Measurement(backend="x", workload=WorkloadClass.LLM_DECODE, ok=False)
    tuner.observe(fallo)
    assert tuner.level(WorkloadClass.LLM_DECODE) == 1

    tuner.vote(WorkloadClass.LLM_DECODE, positive=False)
    assert tuner.level(WorkloadClass.LLM_DECODE) == 0


def test_los_votos_negativos_bajan_el_techo_de_degradacion():
    """El usuario que dice 'suena mal' limita cuánto puede degradar el sistema."""
    tuner = AdaptiveTuner(objective=Objective.LATENCY)
    for _ in range(MAX_LEVEL):
        tuner.vote(WorkloadClass.TTS_FEEDFORWARD, positive=False)

    lenta = Measurement(backend="x", workload=WorkloadClass.TTS_FEEDFORWARD, rtf=5.0)
    for _ in range(20):
        tuner.observe(lenta)

    # Sin votos habría llegado a MAX_LEVEL; con tres votos negativos, a ninguno.
    assert tuner.level(WorkloadClass.TTS_FEEDFORWARD) == 0


def test_la_calidad_percibida_pesa_mas_el_voto_humano_segun_se_acumula():
    tuner = AdaptiveTuner()
    base = 0.9
    sin_votos = tuner.perceived_quality(WorkloadClass.TTS_FEEDFORWARD, base)

    for _ in range(20):
        tuner.vote(WorkloadClass.TTS_FEEDFORWARD, positive=False)
    con_votos = tuner.perceived_quality(WorkloadClass.TTS_FEEDFORWARD, base)

    assert sin_votos == pytest.approx(base, abs=0.01)
    assert con_votos < sin_votos
