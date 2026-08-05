"""Traducción: MarianMT (por defecto) y NLLB-200 (respaldo).

Decisión razonada en docs/ANALISIS-COMPARATIVO.md §2. Resumen: Marian gana en los
pares de alto recurso con 1/8 del tamaño y licencia Apache-2.0; NLLB solo entra
cuando el par no existe en Marian, y se marca por su licencia CC-BY-NC.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, ClassVar

from hearme.config import settings
from hearme.infrastructure.hardware import detect

logger = logging.getLogger(__name__)

#: Pares con modelo Helsinki-NLP publicado y calidad verificada.
_MARIAN_PAIRS: frozenset[tuple[str, str]] = frozenset(
    {
        ("en", "es"),
        ("es", "en"),
        ("en", "fr"),
        ("fr", "en"),
        ("en", "de"),
        ("de", "en"),
        ("en", "it"),
        ("it", "en"),
        ("en", "pt"),
        ("pt", "en"),
        ("en", "nl"),
        ("nl", "en"),
        ("en", "ru"),
        ("ru", "en"),
        ("en", "zh"),
        ("zh", "en"),
        ("en", "ar"),
        ("ar", "en"),
        ("en", "ja"),
        ("ja", "en"),
        ("es", "fr"),
        ("fr", "es"),
        ("es", "pt"),
        ("pt", "es"),
        ("es", "it"),
        ("it", "es"),
        ("es", "de"),
        ("de", "es"),
        ("fr", "de"),
        ("de", "fr"),
        ("en", "ca"),
        ("ca", "en"),
        ("es", "ca"),
        ("ca", "es"),
        ("en", "pl"),
        ("pl", "en"),
        ("en", "tr"),
        ("tr", "en"),
        ("en", "uk"),
        ("uk", "en"),
    }
)

MAX_BATCH = 16


class MarianTranslator:
    name = "marian"
    non_commercial = False

    def __init__(self) -> None:
        self._models: dict[tuple[str, str], tuple[Any, Any]] = {}

    def supports(self, source: str, target: str) -> bool:
        return (source, target) in _MARIAN_PAIRS

    @staticmethod
    def _model_id(source: str, target: str) -> str:
        return f"Helsinki-NLP/opus-mt-{source}-{target}"

    def _load(self, source: str, target: str) -> tuple[Any, Any]:
        key = (source, target)
        if key not in self._models:
            from transformers import MarianMTModel, MarianTokenizer

            model_id = self._model_id(source, target)
            logger.info("cargando modelo de traducción %s", model_id)
            cache = str(settings.resolved_models_dir / "translate")
            tokenizer = MarianTokenizer.from_pretrained(model_id, cache_dir=cache)
            model = MarianMTModel.from_pretrained(model_id, cache_dir=cache)
            model.eval()

            # 75 M de parámetros: cabe en cualquier GPU. Pero solo se sube si hay
            # margen real, porque el TTS puede estar ocupando VRAM.
            profile = detect()
            if profile.accelerator.value == "cuda" and profile.fits_in_vram(600):
                model = model.to("cuda")  # type: ignore[arg-type]

            self._models[key] = (tokenizer, model)
        return self._models[key]

    async def translate(self, texts: Sequence[str], *, source: str, target: str) -> list[str]:
        import anyio

        if not texts:
            return []
        return await anyio.to_thread.run_sync(self._translate_sync, list(texts), source, target)

    def _translate_sync(self, texts: list[str], source: str, target: str) -> list[str]:
        import torch

        tokenizer, model = self._load(source, target)
        device = next(model.parameters()).device
        output: list[str] = []

        for start in range(0, len(texts), MAX_BATCH):
            batch = texts[start : start + MAX_BATCH]
            encoded = tokenizer(
                batch, return_tensors="pt", padding=True, truncation=True, max_length=512
            ).to(device)
            with torch.inference_mode():
                generated = model.generate(**encoded, max_new_tokens=512, num_beams=4)
            output.extend(tokenizer.batch_decode(generated, skip_special_tokens=True))
        return output

    async def close(self) -> None:
        self._models.clear()


class NLLBTranslator:
    """Respaldo de amplia cobertura. CC-BY-NC: no apto para uso comercial."""

    name = "nllb"
    non_commercial = True

    #: ISO-639-1 -> código FLORES-200 que espera NLLB.
    _CODES: ClassVar[dict[str, str]] = {
        "en": "eng_Latn",
        "es": "spa_Latn",
        "fr": "fra_Latn",
        "de": "deu_Latn",
        "it": "ita_Latn",
        "pt": "por_Latn",
        "nl": "nld_Latn",
        "ru": "rus_Cyrl",
        "zh": "zho_Hans",
        "ja": "jpn_Jpan",
        "ar": "arb_Arab",
        "hi": "hin_Deva",
        "ca": "cat_Latn",
        "eu": "eus_Latn",
        "gl": "glg_Latn",
        "pl": "pol_Latn",
        "tr": "tur_Latn",
        "uk": "ukr_Cyrl",
        "ko": "kor_Hang",
        "sw": "swh_Latn",
        "qu": "quy_Latn",
        "gn": "grn_Latn",
    }

    MODEL_ID = "facebook/nllb-200-distilled-600M"

    def __init__(self) -> None:
        self._pipeline: Any = None

    def supports(self, source: str, target: str) -> bool:
        return source in self._CODES and target in self._CODES

    async def translate(self, texts: Sequence[str], *, source: str, target: str) -> list[str]:
        import anyio

        if not texts:
            return []
        if not settings.allow_non_commercial_models:
            raise RuntimeError(
                "NLLB tiene licencia CC-BY-NC (no comercial). Actívalo con "
                "HEARME_ALLOW_NON_COMMERCIAL_MODELS=true si tu uso lo permite."
            )
        return await anyio.to_thread.run_sync(self._translate_sync, list(texts), source, target)

    def _translate_sync(self, texts: list[str], source: str, target: str) -> list[str]:
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        if self._pipeline is None:
            cache = str(settings.resolved_models_dir / "translate")
            tokenizer = AutoTokenizer.from_pretrained(self.MODEL_ID, cache_dir=cache)
            model = AutoModelForSeq2SeqLM.from_pretrained(self.MODEL_ID, cache_dir=cache)
            model.eval()
            profile = detect()
            # 600M fp32 ≈ 2.4 GB. Con 4 GB de VRAM solo cabe si nada más la ocupa.
            if profile.accelerator.value == "cuda" and profile.fits_in_vram(2400):
                model = model.half().to("cuda")
            self._pipeline = (tokenizer, model)

        tokenizer, model = self._pipeline
        tokenizer.src_lang = self._CODES[source]
        target_id = tokenizer.convert_tokens_to_ids(self._CODES[target])
        device = next(model.parameters()).device
        output: list[str] = []

        for start in range(0, len(texts), MAX_BATCH):
            batch = texts[start : start + MAX_BATCH]
            encoded = tokenizer(
                batch, return_tensors="pt", padding=True, truncation=True, max_length=512
            ).to(device)
            with torch.inference_mode():
                generated = model.generate(
                    **encoded, forced_bos_token_id=target_id, max_new_tokens=512, num_beams=4
                )
            output.extend(tokenizer.batch_decode(generated, skip_special_tokens=True))
        return output

    async def close(self) -> None:
        self._pipeline = None


def select_translator(
    translators: Sequence[Any], source: str, target: str, *, allow_non_commercial: bool
) -> Any:
    """Marian si cubre el par; si no, NLLB. Nunca al revés."""
    commercial_ok = [t for t in translators if not t.non_commercial and t.supports(source, target)]
    if commercial_ok:
        return commercial_ok[0]

    fallback = [t for t in translators if t.supports(source, target)]
    if fallback and allow_non_commercial:
        logger.warning(
            "usando '%s' (licencia no comercial) para %s->%s", fallback[0].name, source, target
        )
        return fallback[0]

    raise LookupError(
        f"No hay traductor disponible para {source}->{target}. "
        "Si el par existe solo en NLLB, activa HEARME_ALLOW_NON_COMMERCIAL_MODELS=true."
    )
