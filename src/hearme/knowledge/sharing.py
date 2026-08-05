"""Compartir narraciones: el trabajo de uno ahorra el de todos.

## Por qué compartir cambia la economía del proyecto

Narrar un libro de 274 minutos cuesta CPU y tiempo. Si una biblioteca convierte
*La Antología de Spoon River* y el resultado se comparte, **ninguna otra
biblioteca del mundo tiene que volver a hacerlo**. El coste pasa de ser por
despliegue a ser por obra, una sola vez.

Es lo que convierte a HearMe en una biblioteca parlante de verdad y no en veinte
conversores aislados repitiendo el mismo trabajo.

## El límite duro: solo dominio público

Compartir el audio de una obra con derechos es distribuir una obra derivada.
Es ilegal en casi cualquier jurisdicción, y no hay matiz que lo salve: el
proyecto no puede ofrecer ese botón.

Así que compartir exige **declarar la procedencia con atribución citable**,
igual que el laboratorio. Y hay que decir lo incómodo: **el proyecto no puede
verificar esa declaración.** Nadie aquí va a comprobar si una edición concreta
entró en dominio público en el país de quien comparte. Por eso:

- Quien comparte **afirma** que puede hacerlo, y su seudónimo queda asociado.
- Existe una vía de retirada que funciona en un clic y sin discusión previa.
- La retirada es inmediata; la discusión, si la hay, viene después.

Un proyecto pequeño no puede permitirse pelear una reclamación de derechos, y
tampoco debería querer hacerlo.

## Qué se comparte y qué no

| Se comparte | No se comparte |
|---|---|
| El audio de una obra de dominio público | Cualquier obra con derechos |
| El plan que lo produjo (voz, estilo, idioma) | Qué más ha convertido esa persona |
| La atribución de la fuente | El documento original |
| Un seudónimo | Identidad, correo, IP |

## Deduplicación: la misma narración se guarda una vez

Dos personas que narren el mismo texto con la misma voz y el mismo estilo
producen el mismo audio. Se identifica por el hash del plan y del texto, así que
la segunda no ocupa espacio: se apunta al que ya está.

Es también la razón de que compartir **reduzca** el gasto total de disco de la
red en vez de aumentarlo.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from hearme.knowledge.lab import Provenance


class ShareError(Exception):
    pass


class ShareState(StrEnum):
    PUBLISHED = "published"
    #: Retirada por quien la compartió o por una reclamación. No se sirve.
    WITHDRAWN = "withdrawn"


#: Atribución mínima aceptable. No es una cifra caprichosa: «dominio público» a
#: secas no permite a nadie comprobar nada, y una atribución que no se puede
#: comprobar es una declaración vacía.
MIN_ATTRIBUTION_CHARS = 20


@dataclass(frozen=True, slots=True)
class NarrationPlanRef:
    """Con qué se narró. Es lo que permite reutilizar y también reproducir.

    No lleva el texto ni su identificador: lleva el hash, que aquí sí es
    admisible porque **la obra es pública por definición**. En una obra de
    dominio público el hash no revela nada que no esté ya en cualquier catálogo.
    """

    text_digest: str
    language: str
    voice: str
    engine: str
    style: str

    @property
    def digest(self) -> str:
        """Identidad de la narración: mismo plan y mismo texto, mismo audio."""
        crudo = json.dumps(
            {
                "text": self.text_digest,
                "language": self.language,
                "voice": self.voice,
                "engine": self.engine,
                "style": self.style,
            },
            sort_keys=True,
        )
        return hashlib.sha256(crudo.encode("utf-8")).hexdigest()[:24]

    def to_dict(self) -> dict[str, str]:
        return {
            "text_digest": self.text_digest,
            "language": self.language,
            "voice": self.voice,
            "engine": self.engine,
            "style": self.style,
            "digest": self.digest,
        }


@dataclass(slots=True)
class SharedNarration:
    """Una narración puesta a disposición de la comunidad."""

    plan: NarrationPlanRef
    title: str
    #: Obra y edición, verificable por terceros. Obligatoria.
    attribution: str
    provenance: Provenance
    duration_s: float
    size_bytes: int
    #: Seudónimo de quien la compartió. Queda asociado a la declaración.
    contributor: str
    state: ShareState = ShareState.PUBLISHED
    downloads: int = 0
    #: Cuántas conversiones se han evitado gracias a esta. Es la métrica que
    #: mide si compartir sirve de algo.
    reuses: int = 0
    shared_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    withdrawn_reason: str = ""

    def __post_init__(self) -> None:
        if self.provenance is not Provenance.PUBLIC_DOMAIN:
            raise ShareError(
                "Solo se pueden compartir narraciones de obras de dominio público. "
                "Compartir el audio de una obra con derechos es distribuir una obra "
                "derivada, y este proyecto no puede ofrecer eso."
            )
        if len(self.attribution.strip()) < MIN_ATTRIBUTION_CHARS:
            raise ShareError(
                "Falta la atribución de la fuente. Indica obra, autoría y edición "
                "—por ejemplo «Edgar Lee Masters, Antología de Spoon River (1915)»— "
                "para que cualquiera pueda comprobar que es de dominio público."
            )

    @property
    def is_available(self) -> bool:
        return self.state is ShareState.PUBLISHED

    @property
    def cpu_minutes_saved(self) -> float:
        """Minutos de síntesis que la comunidad se ha ahorrado con esta.

        Se estima como duración × reutilizaciones: narrar dura aproximadamente
        lo que dura el audio en los motores rápidos. Orienta, no factura.
        """
        return (self.duration_s / 60) * self.reuses

    def withdraw(self, reason: str = "") -> None:
        """Retira la narración. Inmediato y sin discusión previa.

        Si alguien reclama derechos, primero se retira y luego se habla. Un
        proyecto pequeño no puede permitirse el orden contrario.
        """
        self.state = ShareState.WITHDRAWN
        self.withdrawn_reason = reason or "retirada a petición"

    def to_dict(self) -> dict[str, Any]:
        return {
            "digest": self.plan.digest,
            "title": self.title,
            "attribution": self.attribution,
            "plan": self.plan.to_dict(),
            "duration_s": round(self.duration_s, 1),
            "size_bytes": self.size_bytes,
            "state": self.state.value,
            "downloads": self.downloads,
            "reuses": self.reuses,
            "cpu_minutes_saved": round(self.cpu_minutes_saved, 1),
            "contributor": self.contributor,
            "shared_at": self.shared_at.isoformat(),
        }


@dataclass(slots=True)
class SharedCatalog:
    """Catálogo comunitario de narraciones reutilizables."""

    items: dict[str, SharedNarration] = field(default_factory=dict)

    def share(self, narration: SharedNarration) -> tuple[SharedNarration, bool]:
        """Publica una narración. Devuelve (la vigente, si es nueva).

        Si ya existe una con el mismo plan sobre el mismo texto, **no se duplica**:
        se cuenta como reutilización y se devuelve la existente. Dos personas que
        narren lo mismo con la misma voz producen el mismo audio, y guardarlo dos
        veces sería pagar dos veces por el mismo byte.
        """
        clave = narration.plan.digest
        existente = self.items.get(clave)
        if existente is not None and existente.is_available:
            existente.reuses += 1
            return existente, False

        self.items[clave] = narration
        return narration, True

    def find(self, plan: NarrationPlanRef) -> SharedNarration | None:
        """¿Ya existe esta narración? Es la consulta que evita reconvertir."""
        candidata = self.items.get(plan.digest)
        return candidata if candidata and candidata.is_available else None

    def available(self, *, language: str | None = None) -> list[SharedNarration]:
        salida = [n for n in self.items.values() if n.is_available]
        if language:
            salida = [n for n in salida if n.plan.language == language]
        return sorted(salida, key=lambda n: n.reuses, reverse=True)

    def withdraw(self, digest: str, reason: str = "") -> bool:
        narracion = self.items.get(digest)
        if narracion is None:
            return False
        narracion.withdraw(reason)
        return True

    @property
    def total_bytes(self) -> int:
        return sum(n.size_bytes for n in self.items.values() if n.is_available)

    @property
    def total_cpu_minutes_saved(self) -> float:
        return sum(n.cpu_minutes_saved for n in self.items.values())

    def summary(self) -> dict[str, Any]:
        """Lo que se enseña en la interfaz para que compartir tenga sentido."""
        disponibles = self.available()
        return {
            "narrations": len(disponibles),
            "languages": sorted({n.plan.language for n in disponibles}),
            "total_bytes": self.total_bytes,
            "cpu_minutes_saved": round(self.total_cpu_minutes_saved, 1),
            "explanation": (
                f"{len(disponibles)} narración(es) compartidas han evitado "
                f"{self.total_cpu_minutes_saved:.0f} minutos de síntesis a otras personas."
                if disponibles
                else "Todavía no hay narraciones compartidas."
            ),
        }


#: Texto que se muestra antes de compartir. Se declara aquí, y no en la
#: interfaz, para que no pueda haber dos versiones distintas de lo que alguien
#: acepta al pulsar el botón.
SHARING_NOTICE = (
    "Al compartir esta narración afirmas que la obra es de dominio público y "
    "que puedes redistribuirla. El audio quedará disponible para cualquiera y "
    "tu seudónimo constará junto a la declaración. Puedes retirarla en cualquier "
    "momento, y se retirará de inmediato si alguien reclama derechos. No se "
    "comparte el documento original ni nada más de lo que hayas convertido."
)
