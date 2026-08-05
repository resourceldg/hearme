"""Modo estudio: explicaciones, resúmenes, preguntas, flashcards y glosario.

Regla de diseño que atraviesa todos los prompts: **no alterar el contenido
técnico**. El LLM añade capas alrededor del texto (explicación, ejemplo, pregunta),
nunca reescribe el original. Por eso cada salida se devuelve como material
*adicional* asociado al capítulo, no como sustitución de sus bloques.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from hearme.domain.models import Chapter
from hearme.domain.ports import LLMProvider

logger = logging.getLogger(__name__)

MAX_CONTEXT_CHARS = 6000

_SYSTEM = (
    "Eres un asistente de estudio riguroso. Trabajas SIEMPRE en el idioma del texto "
    "que recibes. Regla inviolable: no alteras, no corriges y no reinterpretas el "
    "contenido técnico del original. Solo añades explicación alrededor. Si un dato "
    "no aparece en el texto, no lo inventas: dices que no está."
)


@dataclass(slots=True)
class Flashcard:
    front: str
    back: str


@dataclass(slots=True)
class StudyPack:
    chapter_id: str
    chapter_title: str
    summary: str = ""
    explanation: str = ""
    questions: list[str] = field(default_factory=list)
    flashcards: list[Flashcard] = field(default_factory=list)
    glossary: dict[str, str] = field(default_factory=dict)
    available: bool = True
    reason: str = ""


def _excerpt(chapter: Chapter, limit: int = MAX_CONTEXT_CHARS) -> str:
    text = chapter.text
    if len(text) <= limit:
        return text
    # Principio y final: conservan tesis y conclusión, que es donde vive el sentido.
    head, tail = int(limit * 0.7), int(limit * 0.3)
    return f"{text[:head]}\n\n[...]\n\n{text[-tail:]}"


def _extract_json(raw: str) -> object | None:
    """Los modelos pequeños envuelven el JSON en prosa o en vallas de código."""
    fenced = re.search(r"```(?:json)?\s*(.+?)```", raw, re.DOTALL)
    candidate = fenced.group(1) if fenced else raw
    match = re.search(r"[\[{].*[\]}]", candidate, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


class StudyService:
    def __init__(self, llm: LLMProvider) -> None:
        self.llm = llm

    async def build(
        self,
        chapter: Chapter,
        *,
        summary: bool = True,
        explanation: bool = True,
        questions: bool = True,
        flashcards: bool = True,
        glossary: bool = True,
    ) -> StudyPack:
        pack = StudyPack(chapter_id=chapter.id, chapter_title=chapter.title)

        if not await self.llm.is_available():
            pack.available = False
            pack.reason = (
                "No hay backend LLM disponible. Instala Ollama "
                "(https://ollama.com) y descarga un modelo: ollama pull llama3.2:3b"
            )
            return pack

        text = _excerpt(chapter)
        if not text.strip():
            pack.available = False
            pack.reason = "El capítulo no tiene contenido narrable."
            return pack

        if summary:
            pack.summary = await self._summary(text)
        if explanation:
            pack.explanation = await self._explanation(text)
        if questions:
            pack.questions = await self._questions(text)
        if flashcards:
            pack.flashcards = await self._flashcards(text)
        if glossary:
            pack.glossary = await self._glossary(text)

        return pack

    async def _summary(self, text: str) -> str:
        return await self.llm.complete(
            "Resume el siguiente texto en 5 u 8 frases. Conserva cifras, nombres y "
            "términos técnicos exactamente como aparecen. No añadas nada que no esté.\n\n"
            f"---\n{text}\n---",
            system=_SYSTEM,
        )

    async def _explanation(self, text: str) -> str:
        return await self.llm.complete(
            "Explica este texto a alguien competente pero ajeno al tema. "
            "Simplifica el lenguaje y añade un ejemplo concreto por cada idea central. "
            "IMPORTANTE: no cambies definiciones, fórmulas, cifras ni nomenclatura "
            "técnica; repítelas literalmente y explica alrededor.\n\n"
            f"---\n{text}\n---",
            system=_SYSTEM,
        )

    async def _questions(self, text: str) -> list[str]:
        raw = await self.llm.complete(
            "Genera entre 5 y 8 preguntas de comprensión sobre el texto, todas "
            "respondibles solo con el texto. Devuelve EXCLUSIVAMENTE un array JSON "
            'de cadenas. Ejemplo: ["¿...?", "¿...?"]\n\n'
            f"---\n{text}\n---",
            system=_SYSTEM,
        )
        data = _extract_json(raw)
        if isinstance(data, list):
            return [str(item) for item in data if str(item).strip()][:8]
        # Respaldo: si el modelo ignoró el formato, se rescatan las líneas útiles.
        return [line.strip(" -*0123456789.") for line in raw.splitlines() if "?" in line][:8]

    async def _flashcards(self, text: str) -> list[Flashcard]:
        raw = await self.llm.complete(
            "Crea entre 5 y 10 flashcards de repaso. Devuelve EXCLUSIVAMENTE un array "
            'JSON de objetos con las claves "front" y "back". El reverso debe estar '
            "literalmente respaldado por el texto.\n\n"
            f"---\n{text}\n---",
            system=_SYSTEM,
        )
        data = _extract_json(raw)
        if not isinstance(data, list):
            return []
        cards = []
        for item in data:
            if isinstance(item, dict) and item.get("front") and item.get("back"):
                cards.append(Flashcard(front=str(item["front"]), back=str(item["back"])))
        return cards[:10]

    async def _glossary(self, text: str) -> dict[str, str]:
        raw = await self.llm.complete(
            "Extrae los términos técnicos del texto y defínelos en una frase, usando "
            "solo lo que dice el texto. Devuelve EXCLUSIVAMENTE un objeto JSON "
            '{"término": "definición"}. Máximo 15 términos.\n\n'
            f"---\n{text}\n---",
            system=_SYSTEM,
        )
        data = _extract_json(raw)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in list(data.items())[:15]}
        return {}
