"""Tests del selector automático de motor TTS.

Se usan motores falsos: la lógica de selección debe ser verificable sin descargar
ni un solo modelo.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hearme.domain.models import AudioSegment, Utterance
from hearme.infrastructure.tts.selector import NoEngineAvailable, select_engine


class FakeEngine:
    def __init__(
        self,
        name: str,
        languages: set[str],
        naturalness: float,
        rtf: float,
        *,
        non_commercial: bool = False,
        available: bool = True,
    ) -> None:
        self.name = name
        self.languages = frozenset(languages)
        self.naturalness = naturalness
        self.rtf = rtf
        self.non_commercial = non_commercial
        self._available = available

    async def is_available(self) -> bool:
        return self._available

    async def voices(self, language: str | None = None) -> tuple[str, ...]:
        return (f"{self.name}-voz",)

    def default_voice(self, language: str) -> str:
        return f"{self.name}-{language}"

    async def synthesize(
        self, utterance: Utterance, *, voice: str, out_dir: Path
    ) -> AudioSegment:  # pragma: no cover - no se sintetiza en estos tests
        raise NotImplementedError

    async def close(self) -> None:
        return None


def _kokoro(**kwargs) -> FakeEngine:
    return FakeEngine("kokoro", {"en", "es", "fr"}, 0.90, 0.05, **kwargs)


def _piper(**kwargs) -> FakeEngine:
    return FakeEngine("piper", {"en", "es", "pl", "cs"}, 0.68, 0.02, **kwargs)


def _xtts(**kwargs) -> FakeEngine:
    return FakeEngine("xtts", {"es", "en"}, 0.95, 1.8, non_commercial=True, **kwargs)


async def test_alta_calidad_elige_el_mas_natural() -> None:
    selection = await select_engine([_piper(), _kokoro()], language="es")
    assert selection.engine.name == "kokoro"


async def test_borrador_elige_el_mas_rapido() -> None:
    selection = await select_engine([_kokoro(), _piper()], language="es", quality="draft")
    assert selection.engine.name == "piper"


async def test_idioma_sin_kokoro_cae_en_piper() -> None:
    selection = await select_engine([_kokoro(), _piper()], language="pl")
    assert selection.engine.name == "piper"


async def test_excluye_licencia_no_comercial_por_defecto() -> None:
    # xtts es el más natural, pero su licencia lo deja fuera sin permiso explícito.
    selection = await select_engine([_xtts(), _kokoro()], language="es")
    assert selection.engine.name == "kokoro"


async def test_permite_no_comercial_si_se_activa() -> None:
    selection = await select_engine([_xtts(), _kokoro()], language="es", allow_non_commercial=True)
    assert selection.engine.name == "xtts"


async def test_motor_solicitado_tiene_prioridad() -> None:
    selection = await select_engine([_kokoro(), _piper()], language="es", preferred="piper")
    assert selection.engine.name == "piper"
    assert "explícitamente" in selection.reason


async def test_motor_solicitado_inexistente_falla_claro() -> None:
    with pytest.raises(NoEngineAvailable, match="no está disponible"):
        await select_engine([_kokoro()], language="es", preferred="inexistente")


async def test_sin_motores_instalados_sugiere_como_instalar() -> None:
    with pytest.raises(NoEngineAvailable, match="tts-kokoro"):
        await select_engine([_kokoro(available=False)], language="es")


async def test_idioma_no_cubierto_no_aborta_la_conversion() -> None:
    # Mejor narrar con un motor aproximado que negarse a producir audio.
    selection = await select_engine([_kokoro(), _piper()], language="eu")
    assert selection.engine.name == "kokoro"
    assert "ningún motor" in selection.reason


async def test_normaliza_etiquetas_bcp47() -> None:
    selection = await select_engine([_kokoro()], language="es-ES")
    assert selection.language == "es"


async def test_asigna_voz_por_defecto_del_motor() -> None:
    selection = await select_engine([_kokoro()], language="es")
    assert selection.voice == "kokoro-es"


async def test_voz_explicita_gana() -> None:
    selection = await select_engine([_kokoro()], language="es", voice="mi_voz")
    assert selection.voice == "mi_voz"


def test_kokoro_carga_el_modelo_una_sola_vez_con_varios_hilos(monkeypatch) -> None:
    """El pool abre N hilos: sin cerrojo, cada uno cargaba su propio modelo.

    Es la carrera de la que ya avisaba el pipeline y contra la que Piper sí se
    protegía. Se comprueba sin descargar nada: basta con contar construcciones.
    """
    import threading

    pytest.importorskip("kokoro")
    import kokoro

    from hearme.infrastructure.tts.kokoro import KokoroEngine

    construidas = 0
    barrera = threading.Barrier(8)

    class FakeKPipeline:
        def __init__(self, **kwargs) -> None:
            nonlocal construidas
            construidas += 1

    monkeypatch.setattr(kokoro, "KPipeline", FakeKPipeline)
    engine = KokoroEngine(language="es")

    def cargar() -> None:
        barrera.wait()  # maximiza la probabilidad de colisión
        engine._pipeline("es")

    hilos = [threading.Thread(target=cargar) for _ in range(8)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()

    assert construidas == 1


def test_kokoro_expone_prepare_para_precargar_fuera_de_la_medicion() -> None:
    """Sin prepare, el RTF del primer fragmento incluía la carga del modelo."""
    from hearme.infrastructure.tts.kokoro import KokoroEngine

    assert callable(getattr(KokoroEngine, "prepare", None))
