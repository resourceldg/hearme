"""Catálogo de voces con los metadatos que hacen falta para elegir una.

## El problema que resuelve

Hasta ahora una voz era una cadena: `ef_dora`, `es_ES-sharvard-medium`. Para
quien programa es suficiente; para quien tiene que elegir entre veinte es un
muro. «¿Cuál de estas suena a persona de mi país? ¿Cuál es de mujer? ¿Cuál va a
sonar mejor?» son preguntas razonables que un identificador no responde.

## De dónde salen los metadatos

**No se inventan: se derivan de los nombres**, que ya codifican la información
por convención de cada proyecto.

- **Kokoro** usa dos letras iniciales: la primera es el acento (`a` americano,
  `b` británico, `e` español, `j` japonés…) y la segunda el género (`f`, `m`).
  Así `af_heart` es una voz femenina con acento estadounidense.
- **Piper** usa `idioma_REGIÓN-nombre-calidad`, de donde salen la variante
  regional y el nivel del modelo: `es_ES-sharvard-medium`.

Derivarlo tiene una ventaja sobre mantener una tabla a mano: cuando un motor
añada voces nuevas, aparecen solas con sus metadatos correctos. Lo que no se
puede derivar —el género de una voz Piper, que su nombre no indica— se declara
como desconocido en lugar de adivinarse. Etiquetar mal el género de una voz es
peor que no etiquetarlo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Gender(StrEnum):
    """Género de la voz. `UNKNOWN` es una respuesta legítima, no un fallo."""

    FEMALE = "female"
    MALE = "male"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


class Quality(StrEnum):
    """Nivel del modelo. Más calidad es más lento, no siempre «mejor»."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


#: Primera letra de una voz Kokoro -> (idioma, etiqueta del acento).
_KOKORO_ACCENT: dict[str, tuple[str, str]] = {
    "a": ("en", "estadounidense"),
    "b": ("en", "británico"),
    "e": ("es", "español"),
    "f": ("fr", "francés"),
    "h": ("hi", "hindi"),
    "i": ("it", "italiano"),
    "p": ("pt", "portugués"),
    "j": ("ja", "japonés"),
    "z": ("zh", "chino"),
}

_KOKORO_GENDER: dict[str, Gender] = {"f": Gender.FEMALE, "m": Gender.MALE}

#: Región declarada por Piper -> etiqueta legible. Solo las del índice actual.
_REGIONS: dict[str, str] = {
    "ES": "España",
    "US": "Estados Unidos",
    "GB": "Reino Unido",
    "BR": "Brasil",
    "FR": "Francia",
    "DE": "Alemania",
    "IT": "Italia",
    "NL": "Países Bajos",
    "PL": "Polonia",
    "RU": "Rusia",
    "UA": "Ucrania",
    "TR": "Turquía",
    "SE": "Suecia",
    "DK": "Dinamarca",
    "NO": "Noruega",
    "FI": "Finlandia",
    "GR": "Grecia",
    "CZ": "Chequia",
    "RO": "Rumanía",
    "HU": "Hungría",
    "JO": "Jordania",
    "CN": "China",
    "VN": "Vietnam",
    "IR": "Irán",
    "IN": "India",
}

#: Género del hablante en modelos multi-hablante. La clave viene del propio
#: `speaker_id_map` del índice oficial de Piper, así que aquí no se adivina nada.
_SPEAKER_GENDER: dict[str, Gender] = {
    "M": Gender.MALE,
    "F": Gender.FEMALE,
    # Hablantes ucranianos, nombrados en el índice oficial.
    "lada": Gender.FEMALE,
    "tetiana": Gender.FEMALE,
    "mykyta": Gender.MALE,
}

#: Género de los modelos de **un solo hablante**.
#:
#: Aquí no hay nada que derivar: el nombre del archivo no lo indica y el índice
#: oficial de Piper tampoco lo publica. Es una tabla **declarada** a partir de la
#: documentación de cada conjunto de datos y del nombre propio de la persona que
#: prestó la voz.
#:
#: Se distingue de lo derivado a propósito. Una tabla escrita a mano puede tener
#: errores, y corregir uno es cambiar una línea aquí; las voces sobre las que no
#: hay señal fiable se quedan fuera y salen como desconocidas, que es preferible
#: a etiquetar mal a alguien.
_PIPER_SINGLE_GENDER: dict[str, Gender] = {
    "en_US-lessac-medium": Gender.FEMALE,
    "fr_FR-siwis-medium": Gender.FEMALE,
    "de_DE-thorsten-medium": Gender.MALE,
    "it_IT-riccardo-x_low": Gender.MALE,
    "pt_BR-faber-medium": Gender.MALE,
    "pl_PL-darkman-medium": Gender.MALE,
    "ru_RU-dmitri-medium": Gender.MALE,
    "fi_FI-harri-medium": Gender.MALE,
    "el_GR-rapunzelina-low": Gender.FEMALE,
    "cs_CZ-jirka-medium": Gender.MALE,
    "ro_RO-mihai-medium": Gender.MALE,
    "hu_HU-anna-medium": Gender.FEMALE,
    "ca_ES-upc_ona-medium": Gender.FEMALE,
    "ar_JO-kareem-medium": Gender.MALE,
    "zh_CN-huayan-medium": Gender.FEMALE,
    "fa_IR-amir-medium": Gender.MALE,
    "hi_IN-pratham-medium": Gender.MALE,
    # Sin entrada, y a conciencia: nl_NL-mls (52 hablantes de LibriVox),
    # sv_SE-nst, da_DK/no_NO-talesyntese, tr_TR-dfki y vi_VN-vais1000 no
    # identifican a nadie en su nombre ni en su documentación.
}

_PIPER_NAME = re.compile(
    r"^(?P<lang>[a-z]{2})_(?P<region>[A-Z]{2})-(?P<name>[^-]+)-(?P<quality>.+)$"
)

_PIPER_QUALITY: dict[str, Quality] = {
    "x_low": Quality.LOW,
    "low": Quality.LOW,
    "medium": Quality.MEDIUM,
    "high": Quality.HIGH,
}


@dataclass(frozen=True, slots=True)
class VoiceProfile:
    """Una voz con todo lo que hace falta para decidir si es la que quieres."""

    id: str
    engine: str
    language: str
    #: Cómo se llama la voz para una persona: «Dora», no «ef_dora».
    display_name: str
    gender: Gender = Gender.UNKNOWN
    #: «español», «británico»… Vacío si el nombre no lo indica.
    accent: str = ""
    #: «España», «Brasil»… Vacío si no consta.
    region: str = ""
    quality: Quality = Quality.MEDIUM
    #: 0..1 declarado por el motor. Orienta, no es una medida perceptual.
    naturalness: float = 0.5
    #: Real-Time Factor. Menor es más rápido.
    rtf: float = 0.1
    non_commercial: bool = False

    @property
    def is_fast(self) -> bool:
        """Suficientemente rápida para convertir un libro largo sin esperar horas."""
        return self.rtf <= 0.05

    def describe(self) -> str:
        """Una línea legible. Es lo que se enseña bajo el nombre en la interfaz."""
        partes: list[str] = []
        if self.gender is not Gender.FEMALE and self.gender is not Gender.MALE:
            pass
        else:
            partes.append("voz femenina" if self.gender is Gender.FEMALE else "voz masculina")
        if self.accent:
            partes.append(f"acento {self.accent}")
        elif self.region:
            partes.append(f"de {self.region}")
        if self.quality is Quality.HIGH:
            partes.append("calidad alta")
        elif self.quality is Quality.LOW:
            partes.append("calidad básica, muy rápida")
        return " · ".join(partes) or "sin datos adicionales"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "engine": self.engine,
            "language": self.language,
            "display_name": self.display_name,
            "gender": self.gender.value,
            "accent": self.accent,
            "region": self.region,
            "quality": self.quality.value,
            "naturalness": round(self.naturalness, 2),
            "rtf": self.rtf,
            "non_commercial": self.non_commercial,
            "description": self.describe(),
            "is_fast": self.is_fast,
        }


def _titleize(raw: str) -> str:
    """`af_heart` -> `Heart`; `upc_ona` -> `Upc Ona`. Sin inventar nada."""
    limpio = raw.replace("_", " ").strip()
    return " ".join(p.capitalize() for p in limpio.split()) or raw


def parse_kokoro(voice_id: str) -> tuple[str, Gender, str, str]:
    """Deriva (idioma, género, acento, nombre) del convenio de Kokoro."""
    prefijo, _, resto = voice_id.partition("_")
    idioma, acento = _KOKORO_ACCENT.get(prefijo[:1], ("", ""))
    genero = _KOKORO_GENDER.get(prefijo[1:2], Gender.UNKNOWN)
    return idioma, genero, acento, _titleize(resto or voice_id)


def parse_piper(voice_id: str) -> tuple[str, str, Quality, str, Gender]:
    """Deriva (idioma, región, calidad, nombre, género) de una voz Piper.

    El identificador puede llevar hablante: `es_ES-sharvard-medium#F`. En ese
    caso el género sale del `speaker_id_map` oficial, que es un dato, no una
    suposición. Sin hablante, se consulta la tabla declarada.
    """
    modelo, _, hablante = voice_id.partition("#")

    coincidencia = _PIPER_NAME.match(modelo)
    if coincidencia is None:
        return "", "", Quality.MEDIUM, _titleize(voice_id), Gender.UNKNOWN

    datos = coincidencia.groupdict()
    nombre = _titleize(datos["name"])

    if hablante:
        genero = _SPEAKER_GENDER.get(hablante, Gender.UNKNOWN)
        # El hablante distingue la voz: sin esto, dos voces del mismo modelo se
        # llamarían igual en la lista y no habría forma de saber cuál es cuál.
        etiqueta = {"M": "voz masculina", "F": "voz femenina"}.get(hablante)
        nombre = f"{nombre} {hablante}" if etiqueta is None else nombre
    else:
        genero = _PIPER_SINGLE_GENDER.get(modelo, Gender.UNKNOWN)

    return (
        datos["lang"],
        _REGIONS.get(datos["region"], datos["region"]),
        _PIPER_QUALITY.get(datos["quality"], Quality.MEDIUM),
        nombre,
        genero,
    )


def profile_for(voice_id: str, *, engine: Any, language: str) -> VoiceProfile:
    """Construye el perfil de una voz a partir de su motor y su identificador.

    Los campos comunes se pasan explícitos y no con `**dict`: desempaquetar un
    diccionario aquí borra los tipos y mypy deja de comprobar precisamente la
    parte que más fácil es equivocar.
    """
    nombre_motor = str(getattr(engine, "name", "desconocido"))
    naturalidad = float(getattr(engine, "naturalness", 0.5))
    rtf = float(getattr(engine, "rtf", 0.1))
    no_comercial = bool(getattr(engine, "non_commercial", False))

    if nombre_motor == "kokoro":
        idioma, genero, acento, nombre = parse_kokoro(voice_id)
        return VoiceProfile(
            id=voice_id,
            engine=nombre_motor,
            language=idioma or language,
            display_name=nombre,
            gender=genero,
            accent=acento,
            quality=Quality.HIGH,
            naturalness=naturalidad,
            rtf=rtf,
            non_commercial=no_comercial,
        )

    if nombre_motor == "piper":
        idioma, region, calidad, nombre, genero = parse_piper(voice_id)
        return VoiceProfile(
            id=voice_id,
            engine=nombre_motor,
            language=idioma or language,
            display_name=nombre,
            gender=genero,
            region=region,
            quality=calidad,
            naturalness=naturalidad,
            rtf=rtf,
            non_commercial=no_comercial,
        )

    # Motor de un plugin: se toma lo que se sabe y no se inventa el resto.
    return VoiceProfile(
        id=voice_id,
        engine=nombre_motor,
        language=language,
        display_name=_titleize(voice_id),
        naturalness=naturalidad,
        rtf=rtf,
        non_commercial=no_comercial,
    )


@dataclass(slots=True)
class VoiceCatalog:
    """Todas las voces disponibles, filtrables por lo que la gente pregunta."""

    voices: list[VoiceProfile] = field(default_factory=list)

    def add(self, profile: VoiceProfile) -> None:
        self.voices.append(profile)

    def languages(self) -> list[str]:
        return sorted({v.language for v in self.voices if v.language})

    def for_language(self, language: str) -> list[VoiceProfile]:
        """Voces de un idioma, mejores primero.

        El orden es naturalidad y luego calidad del modelo. No se ordena por
        velocidad: quien prioriza rapidez lo hace a conciencia, y ponerle delante
        una voz peor «porque es rápida» es decidir por esa persona.
        """
        candidatas = [v for v in self.voices if v.language == language]
        return sorted(
            candidatas,
            key=lambda v: (v.naturalness, v.quality is Quality.HIGH),
            reverse=True,
        )

    def filter(
        self,
        *,
        language: str | None = None,
        gender: Gender | None = None,
        engine: str | None = None,
        allow_non_commercial: bool = False,
    ) -> list[VoiceProfile]:
        salida = self.voices
        if language:
            salida = [v for v in salida if v.language == language]
        if gender is not None:
            salida = [v for v in salida if v.gender is gender]
        if engine:
            salida = [v for v in salida if v.engine == engine]
        if not allow_non_commercial:
            salida = [v for v in salida if not v.non_commercial]
        return sorted(salida, key=lambda v: (-v.naturalness, v.display_name))

    def get(self, voice_id: str) -> VoiceProfile | None:
        return next((v for v in self.voices if v.id == voice_id), None)

    def grouped_by_language(self) -> dict[str, list[dict[str, Any]]]:
        """Forma que consume la interfaz: agrupado y ya ordenado."""
        return {
            idioma: [v.to_dict() for v in self.for_language(idioma)] for idioma in self.languages()
        }

    def __len__(self) -> int:
        return len(self.voices)


async def build_catalog(engines: Any, *, languages: list[str] | None = None) -> VoiceCatalog:
    """Consulta a cada motor disponible y construye el catálogo completo."""
    catalogo = VoiceCatalog()
    vistos: set[tuple[str, str]] = set()

    for engine in engines:
        if not await engine.is_available():
            continue
        idiomas = languages or sorted(getattr(engine, "languages", ()))
        for idioma in idiomas:
            for voice_id in await engine.voices(idioma):
                clave = (engine.name, voice_id)
                if clave in vistos:
                    continue
                vistos.add(clave)
                catalogo.add(profile_for(voice_id, engine=engine, language=idioma))
    return catalogo


#: Frase de muestra por idioma. Se eligen frases con variedad prosódica —una
#: afirmación, una pausa y una entonación distinta— porque una muestra plana no
#: deja oír lo que diferencia a una voz de otra.
SAMPLE_TEXT: dict[str, str] = {
    "es": "Había una vez un jardín donde el tiempo pasaba despacio. ¿Lo recuerdas?",
    "en": "There was once a garden where time moved slowly. Do you remember it?",
    "fr": "Il était une fois un jardin où le temps passait lentement. T'en souviens-tu ?",
    "de": "Es war einmal ein Garten, in dem die Zeit langsam verging. Erinnerst du dich?",
    "it": "C'era una volta un giardino dove il tempo passava lentamente. Te lo ricordi?",
    "pt": "Era uma vez um jardim onde o tempo passava devagar. Você se lembra?",
    "ca": "Hi havia una vegada un jardí on el temps passava a poc a poc. Te'n recordes?",
}

#: Se recorta el texto de muestra: una previsualización larga cansa y, sobre
#: todo, tarda en generarse. Con dos frases se decide de sobra.
MAX_SAMPLE_CHARS = 90


def sample_text_for(language: str) -> str:
    return SAMPLE_TEXT.get(language, SAMPLE_TEXT["en"])[:MAX_SAMPLE_CHARS]
