"""Plan de escucha: los seis conceptos, separados y nombrados.

## El problema

La interfaz anterior tenía un campo «Idioma de origen» y otro «Traducir a», más
un modo llamado «Traducción». Tres controles para dos ideas, y ninguno decía lo
que de verdad importa: **en qué idioma vas a escuchar esto**.

Se podía elegir el modo «Traducción» sin poner idioma de destino y no pasaba
nada. Se podía poner un idioma de destino en modo «Audiolibro» y sí traducía. El
sistema hacía lo correcto en ambos casos; lo que estaba roto era el modelo mental
que la interfaz proponía.

## Los seis conceptos

Se nombran aquí, una vez, y el resto del sistema usa estos nombres:

| Concepto | Pregunta que responde | Quién decide |
|---|---|---|
| **Idioma del documento** | ¿En qué está escrito? | Se detecta; se puede corregir |
| **Idioma de reproducción** | ¿En qué lo voy a escuchar? | La persona |
| **Traducción** | ¿Hay que traducir? | **Se deriva**, no se elige |
| **Voz** | ¿Quién lo lee? | La persona, dentro del idioma de reproducción |
| **Estilo narrativo** | ¿Cómo lo lee? | La persona |
| **Motor** | ¿Qué tecnología lo sintetiza? | Automático; cambiable |

La clave está en la tercera fila: **la traducción no es una opción, es una
consecuencia.** Si el documento está en inglés y quieres escucharlo en español,
hay que traducir; no hace falta que nadie marque una casilla. Eliminar esa
casilla elimina de golpe todos los estados incoherentes que producía.

La segunda idea que ordena esto: **la voz se elige después del idioma de
reproducción, y solo entre las de ese idioma.** Una voz española leyendo un texto
en alemán es un error que la interfaz no debería permitir cometer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hearme.domain.models import NarrationStyle
from hearme.narration.voices import VoiceCatalog


@dataclass(frozen=True, slots=True)
class Recommendation:
    """Una sugerencia con su motivo. Nunca se aplica sin decir por qué.

    `reason` no es documentación: se enseña junto a la sugerencia. Una
    recomendación sin motivo visible es una decisión tomada por el sistema, y el
    proyecto se comprometió a que fueran «transparentes, reversibles y
    opcionales».
    """

    value: str
    reason: str
    #: 0..1. Por debajo de `LOW_CONFIDENCE` la interfaz pide confirmación en vez
    #: de preseleccionar.
    confidence: float = 1.0

    @property
    def is_confident(self) -> bool:
        return self.confidence >= LOW_CONFIDENCE

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "reason": self.reason,
            "confidence": round(self.confidence, 2),
            "confident": self.is_confident,
        }


#: Por debajo de esto no se preselecciona nada: se pregunta.
LOW_CONFIDENCE = 0.6


@dataclass(slots=True)
class ListeningPlan:
    """Qué va a escuchar la persona, con los seis conceptos separados."""

    #: En qué está escrito. Detectado, corregible.
    document_language: str = ""
    #: En qué se va a escuchar. Si difiere del anterior, se traduce.
    playback_language: str = ""
    voice: str | None = None
    style: NarrationStyle = NarrationStyle.NEUTRAL
    #: None = lo elige el selector según idioma y calidad.
    engine: str | None = None
    #: Mantener también el texto original junto al traducido.
    keep_original: bool = False

    @property
    def needs_translation(self) -> bool:
        """Derivado, nunca elegido. Es el punto de todo este módulo."""
        return bool(
            self.document_language
            and self.playback_language
            and self.document_language != self.playback_language
        )

    def describe(self) -> str:
        """Resumen en una frase, para confirmar antes de convertir.

        Sirve de comprobación de comprensión: si al leerlo alguien piensa «no era
        eso lo que quería», la interfaz falló antes de gastar diez minutos de
        conversión.
        """
        if self.needs_translation:
            base = f"Se traducirá de {self.document_language} a {self.playback_language}"
            if self.keep_original:
                base += ", conservando el texto original"
        else:
            base = f"Se narrará en {self.playback_language or self.document_language}"
        return f"{base}, con estilo {self.style.value}."

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_language": self.document_language,
            "playback_language": self.playback_language,
            "needs_translation": self.needs_translation,
            "voice": self.voice,
            "style": self.style.value,
            "engine": self.engine,
            "keep_original": self.keep_original,
            "summary": self.describe(),
        }


@dataclass(frozen=True, slots=True)
class PlanProblem:
    """Un impedimento, con la acción concreta que lo resuelve.

    `action` es obligatorio. Un mensaje de error que solo describe el problema
    deja el trabajo a medias: quien lo lee ya sabía que algo iba mal.
    """

    field: str
    message: str
    action: str

    def to_dict(self) -> dict[str, str]:
        return {"field": self.field, "message": self.message, "action": self.action}


def validate(
    plan: ListeningPlan,
    *,
    catalog: VoiceCatalog,
    translation_available: bool,
) -> list[PlanProblem]:
    """Comprueba el plan **antes** de convertir.

    Detectar aquí que falta el traductor ahorra esperar el parseo entero de un
    libro para descubrirlo al final.
    """
    problemas: list[PlanProblem] = []

    if not plan.playback_language:
        problemas.append(
            PlanProblem(
                field="playback_language",
                message="No se ha elegido en qué idioma escuchar el documento.",
                action="Elige un idioma de reproducción.",
            )
        )
        return problemas  # sin esto, el resto no se puede comprobar

    if plan.needs_translation and not translation_available:
        problemas.append(
            PlanProblem(
                field="playback_language",
                message=(
                    f"El documento está en {plan.document_language} y quieres escucharlo "
                    f"en {plan.playback_language}, pero este servicio no puede traducir."
                ),
                action=(
                    f"Escúchalo en {plan.document_language}, o pide a quien administra "
                    "el servicio que instale el componente de traducción."
                ),
            )
        )

    disponibles = catalog.for_language(plan.playback_language)
    if not disponibles:
        problemas.append(
            PlanProblem(
                field="playback_language",
                message=f"No hay ninguna voz instalada para {plan.playback_language}.",
                action=(
                    "Elige otro idioma de reproducción entre los que sí tienen voz, "
                    "o instala un motor que cubra este."
                ),
            )
        )
    elif plan.voice and not any(v.id == plan.voice for v in disponibles):
        perfil = catalog.get(plan.voice)
        idioma_voz = perfil.language if perfil else "otro idioma"
        problemas.append(
            PlanProblem(
                field="voice",
                message=(
                    f"La voz elegida es de {idioma_voz} y vas a escuchar en "
                    f"{plan.playback_language}."
                ),
                action=f"Elige una voz de {plan.playback_language}.",
            )
        )

    return problemas


def recommend(
    *,
    detected_language: str,
    detection_confidence: float,
    catalog: VoiceCatalog,
    translation_available: bool,
    preferred_voices: dict[str, str] | None = None,
    interface_language: str = "es",
) -> dict[str, Recommendation]:
    """Propone un plan completo, con el motivo de cada sugerencia.

    El orden de preferencia para el idioma de reproducción es deliberado:

    1. **El idioma del documento**, si hay voz. Escuchar el original es lo que la
       mayoría espera, y no traducir evita introducir errores de traducción en
       una obra que ya se entiende.
    2. **El idioma de la interfaz**, si el original no tiene voz. Es la mejor
       pista disponible sobre qué entiende esta persona.
    3. **Cualquiera con voz**, avisando de que es una suposición floja.
    """
    preferred_voices = preferred_voices or {}
    recomendaciones: dict[str, Recommendation] = {}

    idiomas_con_voz = set(catalog.languages())

    if detected_language in idiomas_con_voz:
        idioma = detected_language
        motivo = f"El documento está en {detected_language} y hay voces para ese idioma."
        confianza = detection_confidence
    elif translation_available and interface_language in idiomas_con_voz:
        idioma = interface_language
        motivo = (
            f"No hay voces para {detected_language or 'el idioma del documento'}, "
            f"así que se traduciría a {interface_language}."
        )
        confianza = min(detection_confidence, 0.7)
    elif idiomas_con_voz:
        idioma = sorted(idiomas_con_voz)[0]
        motivo = "Es el único idioma con voz disponible en este servicio."
        confianza = 0.4
    else:
        idioma = ""
        motivo = "No hay ninguna voz instalada."
        confianza = 0.0

    recomendaciones["playback_language"] = Recommendation(idioma, motivo, confianza)

    if idioma:
        voces = catalog.for_language(idioma)
        favorita = preferred_voices.get(idioma)
        if favorita and any(v.id == favorita for v in voces):
            elegida = next(v for v in voces if v.id == favorita)
            recomendaciones["voice"] = Recommendation(
                elegida.id, "Es la voz que sueles usar para este idioma.", 1.0
            )
        elif voces:
            mejor = voces[0]
            recomendaciones["voice"] = Recommendation(
                mejor.id,
                f"Es la voz más natural disponible en {idioma} ({mejor.describe()}).",
                0.8,
            )

    return recomendaciones


def suggest_style(document_hint: str = "") -> Recommendation:
    """Estilo narrativo a partir de una pista del documento.

    Deliberadamente conservador: ante la duda, neutro. Un estilo mal aplicado
    —poesía en un manual técnico— se nota mucho más que uno neutro de más.
    """
    pista = document_hint.lower()
    # El orden importa: de más específico a más general. «Cuento infantil»
    # contiene «cuento», así que la regla infantil se mira antes que la de
    # narrativa; si no, un cuento para niños se narraría como novela de adultos.
    reglas: list[tuple[tuple[str, ...], NarrationStyle, str]] = [
        (
            ("poema", "poesía", "verso", "poetry"),
            NarrationStyle.POETRY,
            "El documento parece poesía: pausas más largas y ritmo más lento.",
        ),
        (
            ("manual", "técnico", "api", "spec", "informe"),
            NarrationStyle.TECHNICAL,
            "Parece un texto técnico: cadencia sostenida y pausas breves.",
        ),
        (
            ("infantil", "niños", "cuento para"),
            NarrationStyle.CHILDREN,
            "Parece un texto infantil: más expresivo y más lento.",
        ),
        (
            ("novela", "cuento", "relato", "capítulo"),
            NarrationStyle.NOVEL,
            "Parece narrativa: pausas de respiración entre párrafos.",
        ),
        (
            ("tesis", "paper", "artículo", "estudio"),
            NarrationStyle.ACADEMIC,
            "Parece un texto académico: ritmo pausado y pausas marcadas en las citas.",
        ),
        (
            ("conferencia", "charla", "ponencia"),
            NarrationStyle.LECTURE,
            "Parece una conferencia: cadencia de exposición oral.",
        ),
    ]
    for claves, estilo, motivo in reglas:
        if any(clave in pista for clave in claves):
            return Recommendation(estilo.value, motivo, 0.7)

    return Recommendation(
        NarrationStyle.NEUTRAL.value,
        "Sin señales claras del tipo de texto, el estilo neutro es el más seguro.",
        1.0,
    )


@dataclass(slots=True)
class DocumentAnalysis:
    """Lo que se sabe de un documento **antes** de convertirlo.

    Existe para que el asistente pueda proponer algo con fundamento sin gastar
    los minutos de una conversión completa.
    """

    detected_language: str = ""
    confidence: float = 0.0
    chapters: int = 0
    characters: int = 0
    title: str = ""
    #: Estimación de duración del audio. Cambia la decisión: nadie elige la voz
    #: más lenta para un libro de catorce horas.
    estimated_minutes: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "detected_language": self.detected_language,
            "confidence": round(self.confidence, 2),
            "chapters": self.chapters,
            "characters": self.characters,
            "title": self.title,
            "estimated_minutes": round(self.estimated_minutes, 1),
        }


#: Caracteres por minuto de audio a ritmo normal. Medido sobre narración real en
#: español; sirve para orientar, no para prometer una duración exacta.
CHARS_PER_MINUTE = 900


def estimate_minutes(characters: int, *, rate: float = 1.0) -> float:
    if characters <= 0 or rate <= 0:
        return 0.0
    return characters / CHARS_PER_MINUTE / rate


def plan_to_request_kwargs(plan: ListeningPlan, catalog: VoiceCatalog) -> dict[str, Any]:
    """Traduce el plan a los parámetros que espera el pipeline.

    El pipeline sigue hablando de `language` y `target_language` —cambiar sus
    nombres tocaría la cola de trabajos, la persistencia y los tests— así que la
    conversión se hace aquí, en un solo sitio y a la vista.
    """
    perfil = catalog.get(plan.voice) if plan.voice else None
    return {
        "language": plan.document_language or None,
        "target_language": plan.playback_language if plan.needs_translation else None,
        "voice": plan.voice,
        "style": plan.style,
        # Si la voz elegida pertenece a un motor concreto, manda ese motor: pedir
        # una voz de Kokoro y dejar que el selector elija Piper daría otra voz
        # distinta sin explicación.
        "engine": plan.engine or (perfil.engine if perfil else None),
    }
