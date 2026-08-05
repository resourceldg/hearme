"""Personal Reading Profile: el ADN de narración de una persona.

## La idea

Alguien lleva un año corrigiendo cómo se le lee: alarga las pausas de los
diálogos, baja el ritmo en los tecnicismos, sube el énfasis de los títulos
porque si no se pierde entre capítulos. Ese conjunto de ajustes **es suyo**, le
ha costado tiempo y describe cómo funciona su forma de leer.

Ese es su ADN de narración: un objeto pequeño, cifrado, exportable y —lo
decisivo— **independiente del motor de voz**. No contiene parámetros de Piper ni
de Kokoro; contiene modificadores sobre la partitura neutra. El día que cambie
el motor, o que la persona se lleve el perfil a otro despliegue, o que aparezca
una tecnología que hoy no existe, su forma de escuchar viaja con ella.

Es la contrapartida personal de `NarrationKnowledge`: uno es privado y describe a
alguien; el otro es público y no describe a nadie.

## Por qué modificadores y no valores absolutos

Un perfil que dijera «pausa de párrafo: 520 ms» quedaría obsoleto en cuanto el
director base mejorase: fijaría para siempre una corrección hecha contra una
versión concreta. Guardando «pausas de párrafo: ×1,3» la preferencia se compone
con lo que el director sepa en cada momento. La persona corrige *una desviación*,
no un valor, y esa desviación sigue teniendo sentido dentro de diez versiones.

## Qué es y qué no es un dato personal aquí

El perfil **es dato personal**: los patrones de lectura pueden revelar una
discapacidad —alguien que necesita ritmo muy lento y pausas largas—, que es una
categoría especial en el RGPD. Por eso va cifrado siempre, nunca se comparte por
defecto, y contribuir cualquier cosa derivada de él exige consentimiento
explícito y separado.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from hearme.narration.score import MarkSource, ProsodyMark, SpanRole
from hearme.privacy.crypto import Envelope, seal, unseal

#: Versión del formato del ADN. Es lo que hace portable el perfil entre
#: despliegues y versiones: quien lo lea sabe qué está leyendo.
DNA_VERSION = "1.0"

_PROFILE_CONTEXT = "hearme:profile:dna:v1"

#: Topes de los modificadores. Un perfil no debe poder volver la narración
#: inservible: ni una pausa de un minuto ni un ritmo indescifrable. También
#: acota el daño si un perfil llegara manipulado desde fuera.
_LIMITS = {"pause_scale": (0.25, 4.0), "rate_scale": (0.5, 2.0), "emphasis_scale": (0.5, 2.0)}


def _clamp(name: str, value: float) -> float:
    minimo, maximo = _LIMITS[name]
    return max(minimo, min(maximo, value))


@dataclass(frozen=True, slots=True)
class RoleAdjustment:
    """Ajustes de una persona para un rol narrativo concreto."""

    pause_scale: float = 1.0
    rate_scale: float = 1.0
    emphasis_scale: float = 1.0
    #: Cuántas correcciones respaldan esto. Con pocas, se aplica atenuado.
    observations: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "pause_scale": round(self.pause_scale, 4),
            "rate_scale": round(self.rate_scale, 4),
            "emphasis_scale": round(self.emphasis_scale, 4),
            "observations": self.observations,
        }


#: Correcciones antes de aplicar un ajuste al completo. Con menos, se interpola
#: desde neutro: dos correcciones puntuales no deben reconfigurar la escucha.
CONFIDENCE_THRESHOLD = 5


@dataclass(slots=True)
class ReadingDNA:
    """El perfil portable. Pequeño, versionado y sin una sola palabra de lo leído.

    Contiene *cómo* le gusta escuchar a alguien, nunca *qué* ha escuchado. Esa
    separación es lo que permite exportarlo, moverlo o incluso —si la persona
    quiere— enseñárselo a otra, sin revelar su biblioteca.
    """

    version: str = DNA_VERSION
    #: Seudónimo local. No es un identificador de cuenta ni viaja al exterior.
    subject: str = "local"
    language: str = "es"
    global_pause_scale: float = 1.0
    global_rate_scale: float = 1.0
    global_emphasis_scale: float = 1.0
    by_role: dict[str, RoleAdjustment] = field(default_factory=dict)
    #: Pronunciaciones personales: nombres propios, extranjerismos, tecnicismos.
    #: Es lo más identificativo del perfil —el vocabulario delata el oficio— y
    #: por eso jamás se contribuye a la comunidad desde aquí.
    lexicon: dict[str, str] = field(default_factory=dict)
    corrections_seen: int = 0
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    # --- aprendizaje --------------------------------------------------------

    def learn_from(self, original: ProsodyMark, corrected: ProsodyMark, *, role: SpanRole) -> None:
        """Incorpora una corrección como desviación relativa.

        Se aprende la *proporción* entre lo que propuso el director y lo que la
        persona prefirió, no el valor final. Así la preferencia sobrevive a que
        el director mejore por debajo.
        """
        actual = self.by_role.get(role.value, RoleAdjustment())
        n = actual.observations

        def mezclar(previo: float, ratio: float) -> float:
            # Media móvil: cada corrección pesa menos según se acumula historia,
            # de modo que un ajuste aislado no borra un año de preferencias.
            return (previo * n + ratio) / (n + 1)

        pausa, ritmo, enfasis = actual.pause_scale, actual.rate_scale, actual.emphasis_scale
        if original.pause_after_ms and corrected.pause_after_ms:
            pausa = mezclar(pausa, corrected.pause_after_ms / original.pause_after_ms)
        if original.rate and corrected.rate:
            ritmo = mezclar(ritmo, corrected.rate / original.rate)
        if original.emphasis and corrected.emphasis:
            enfasis = mezclar(enfasis, corrected.emphasis / original.emphasis)

        self.by_role[role.value] = RoleAdjustment(
            pause_scale=_clamp("pause_scale", pausa),
            rate_scale=_clamp("rate_scale", ritmo),
            emphasis_scale=_clamp("emphasis_scale", enfasis),
            observations=n + 1,
        )
        self.corrections_seen += 1
        self.updated_at = datetime.now(UTC)

    # --- aplicación ---------------------------------------------------------

    def apply(self, mark: ProsodyMark) -> ProsodyMark:
        """Aplica el perfil a una marca. Es el único punto donde el ADN influye.

        Devuelve una marca nueva con procedencia HUMAN: la preferencia de la
        persona pesa más que la regla, y quien inspeccione la partitura ve de
        dónde viene cada valor.
        """
        ajuste = self.by_role.get(mark.role.value, RoleAdjustment())

        # Con pocas observaciones el ajuste se atenúa hacia neutro. Evita que
        # tres correcciones a deshora reconfiguren toda la escucha.
        peso = min(1.0, ajuste.observations / CONFIDENCE_THRESHOLD)

        def escalar(base: float, especifico: float, global_: float) -> float:
            efectivo = 1.0 + (especifico - 1.0) * peso
            return base * efectivo * global_

        cambios: dict[str, Any] = {"source": MarkSource.HUMAN}
        if mark.pause_after_ms is not None:
            cambios["pause_after_ms"] = int(
                escalar(mark.pause_after_ms, ajuste.pause_scale, self.global_pause_scale)
            )
        if mark.rate is not None:
            cambios["rate"] = round(
                escalar(mark.rate, ajuste.rate_scale, self.global_rate_scale), 4
            )
        if mark.emphasis is not None:
            cambios["emphasis"] = round(
                escalar(mark.emphasis, ajuste.emphasis_scale, self.global_emphasis_scale), 4
            )
        return replace(mark, **cambios)

    # --- portabilidad -------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "subject": self.subject,
            "language": self.language,
            "global_pause_scale": round(self.global_pause_scale, 4),
            "global_rate_scale": round(self.global_rate_scale, 4),
            "global_emphasis_scale": round(self.global_emphasis_scale, 4),
            "by_role": {k: v.to_dict() for k, v in self.by_role.items()},
            "lexicon": self.lexicon,
            "corrections_seen": self.corrections_seen,
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReadingDNA:
        version = str(data.get("version", ""))
        if version.split(".")[0] != DNA_VERSION.split(".")[0]:
            raise ValueError(f"ADN de narración incompatible: {version!r}")
        return cls(
            version=version,
            subject=str(data.get("subject", "local")),
            language=str(data.get("language", "es")),
            global_pause_scale=_clamp("pause_scale", float(data.get("global_pause_scale", 1.0))),
            global_rate_scale=_clamp("rate_scale", float(data.get("global_rate_scale", 1.0))),
            global_emphasis_scale=_clamp(
                "emphasis_scale", float(data.get("global_emphasis_scale", 1.0))
            ),
            by_role={
                k: RoleAdjustment(
                    pause_scale=_clamp("pause_scale", float(v.get("pause_scale", 1.0))),
                    rate_scale=_clamp("rate_scale", float(v.get("rate_scale", 1.0))),
                    emphasis_scale=_clamp("emphasis_scale", float(v.get("emphasis_scale", 1.0))),
                    observations=int(v.get("observations", 0)),
                )
                for k, v in data.get("by_role", {}).items()
            },
            lexicon=dict(data.get("lexicon", {})),
            corrections_seen=int(data.get("corrections_seen", 0)),
            updated_at=datetime.fromisoformat(
                data.get("updated_at", datetime.now(UTC).isoformat())
            ),
        )

    def export_encrypted(self, key: bytes) -> bytes:
        """Exporta cifrado. **No hay exportación en claro, y es deliberado.**

        Un perfil de lectura puede revelar una discapacidad. Ofrecer un botón de
        «exportar sin cifrar» garantiza que acabe en una carpeta de descargas
        sincronizada con la nube. Quien de verdad quiera el JSON puede llamar a
        `to_dict()` a conciencia; lo que no habrá es un camino cómodo hacia el
        descuido.
        """
        crudo = json.dumps(self.to_dict(), ensure_ascii=False).encode("utf-8")
        return seal(key, crudo, context=_PROFILE_CONTEXT).to_bytes()

    @classmethod
    def import_encrypted(cls, key: bytes, blob: bytes) -> ReadingDNA:
        crudo = unseal(key, Envelope.from_bytes(blob), context=_PROFILE_CONTEXT)
        return cls.from_dict(json.loads(crudo))

    def shareable_summary(self) -> dict[str, Any]:
        """Lo que se puede enseñar sin revelar a la persona.

        Sin léxico —el vocabulario delata el oficio, la salud y la procedencia—,
        sin seudónimo y sin recuentos exactos. Sirve para «así escucho yo», no
        para reconstruir a nadie.
        """
        return {
            "language": self.language,
            "roles_adjusted": sorted(self.by_role),
            "tends_to": _describe_tendency(self),
        }


def _describe_tendency(dna: ReadingDNA) -> str:
    """Una frase llana. La explicabilidad también aplica a lo que se aprende de ti."""
    if not dna.by_role:
        return "sin preferencias aprendidas todavía"
    pausas = sum(a.pause_scale for a in dna.by_role.values()) / len(dna.by_role)
    ritmos = sum(a.rate_scale for a in dna.by_role.values()) / len(dna.by_role)

    partes = []
    if pausas > 1.1:
        partes.append("pausas más largas de lo habitual")
    elif pausas < 0.9:
        partes.append("pausas más breves")
    if ritmos < 0.95:
        partes.append("ritmo más pausado")
    elif ritmos > 1.05:
        partes.append("ritmo más ágil")
    return ", ".join(partes) if partes else "muy cerca de la narración por defecto"
