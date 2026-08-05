"""Sincronización de conocimiento: deltas pequeños, nunca documentos.

## El principio

> **El servidor orquesta, no almacena.**

Lo que viaja entre un cliente y el servidor es *conocimiento narrativo*: reglas
generalizadas, sus versiones y su historial. Nunca documentos, nunca audio,
nunca texto de nadie.

Medido sobre un libro real, la diferencia no es de matiz:

| Qué | Tamaño |
|---|---|
| Un libro conservado en el servidor (PDF + texto en BD + audio) | ~134 MB |
| Toda la base de conocimiento de un idioma (1000 reglas) | ~200 KB |
| Un delta de sincronización típico | unos pocos KB |

Una biblioteca con 5000 títulos serían **672 GB** si el servidor guardase los
archivos. Guardando solo conocimiento, cabe en un disquete de los de antes.

## Por qué direccionado por contenido

Cada instantánea se identifica por el hash de su contenido, no por un número que
alguien incrementa. Tres consecuencias:

1. **Comparar es gratis.** Si tu hash coincide con el del servidor, no hay nada
   que sincronizar y se corta la conversación en un byte.
2. **Verificable.** Al recibir un delta puedes comprobar que llegas al hash
   anunciado. Si no coincide, algo se corrompió o te lo cambiaron por el camino.
3. **Sin coordinación.** Dos servidores distintos que tengan las mismas reglas
   tienen el mismo hash. No hace falta una autoridad que reparta números.

## Offline primero, de verdad

Un cliente funciona **indefinidamente** sin servidor: tiene su instantánea, narra
con ella y acumula sus contribuciones en una cola local. Cuando haya red, envía
lo acumulado y recibe lo que le falte.

La sincronización es una mejora, no un requisito. Una biblioteca sin conexión
estable —o sin conexión alguna— sigue narrando igual de bien; simplemente su
conocimiento avanza cuando alguien lleve una copia en una memoria USB, que es un
caso de uso real y no una hipótesis.

## Qué NO viaja

Se enumera porque un protocolo de sincronización es justo el sitio por donde se
escapan los datos sin que nadie se dé cuenta:

- Documentos, fragmentos de documentos o sus identificadores.
- Audio, ni generado ni de referencia.
- El ADN de narración personal, ni entero ni resumido.
- El léxico personal de pronunciaciones.
- Qué ha convertido alguien, cuándo o cuánto.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from hearme.knowledge.knowledge import (
    Effect,
    KnowledgeBase,
    NarrationRule,
    RuleKind,
    Trigger,
    TriggerType,
)

PROTOCOL_VERSION = "1.0"

#: Tope de una carga de sincronización. Existe para que el protocolo no pueda
#: convertirse en un canal de transferencia de archivos por acumulación: si un
#: delta no cabe aquí, algo se está intentando colar que no son reglas.
MAX_DELTA_BYTES = 256 * 1024


class SyncError(Exception):
    pass


def content_hash(rules: list[dict[str, Any]]) -> str:
    """Hash de un conjunto de reglas, independiente del orden.

    Se ordena por identificador antes de serializar: dos servidores con las
    mismas reglas deben llegar al mismo hash aunque las tengan guardadas en
    distinto orden, o la comparación daría falsos negativos eternamente.
    """
    canonico = json.dumps(
        sorted(rules, key=lambda r: str(r.get("id", ""))),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Estado publicado del conocimiento de un idioma, en un momento dado."""

    language: str
    #: Hash del contenido. Es el identificador real de esta instantánea.
    digest: str
    rules: tuple[dict[str, Any], ...] = ()
    published_at: str = ""
    protocol: str = PROTOCOL_VERSION

    @classmethod
    def of(cls, base: KnowledgeBase, *, epsilon: float | None = None) -> Snapshot:
        publicables = base.publishable(epsilon=epsilon)
        return cls(
            language=base.language,
            digest=content_hash(publicables),
            rules=tuple(publicables),
            published_at=datetime.now(UTC).isoformat(),
        )

    @property
    def size_bytes(self) -> int:
        return len(json.dumps(self.to_dict(), ensure_ascii=False).encode("utf-8"))

    def verify(self) -> bool:
        """¿El contenido corresponde al hash anunciado?"""
        return content_hash(list(self.rules)) == self.digest

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "language": self.language,
            "digest": self.digest,
            "published_at": self.published_at,
            "rules": list(self.rules),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Snapshot:
        protocolo = str(data.get("protocol", ""))
        if protocolo.split(".")[0] != PROTOCOL_VERSION.split(".")[0]:
            raise SyncError(f"protocolo de sincronización incompatible: {protocolo!r}")
        return cls(
            language=str(data["language"]),
            digest=str(data["digest"]),
            rules=tuple(data.get("rules", ())),
            published_at=str(data.get("published_at", "")),
            protocol=protocolo,
        )


class ChangeKind(StrEnum):
    ADDED = "added"
    UPDATED = "updated"
    REMOVED = "removed"


@dataclass(frozen=True, slots=True)
class Delta:
    """Lo que cambia entre dos instantáneas. Es lo único que viaja hacia abajo."""

    language: str
    #: Instantánea de partida. Vacío = el cliente no tenía nada.
    from_digest: str
    to_digest: str
    added: tuple[dict[str, Any], ...] = ()
    updated: tuple[dict[str, Any], ...] = ()
    removed: tuple[str, ...] = ()
    protocol: str = PROTOCOL_VERSION

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.updated or self.removed)

    @property
    def size_bytes(self) -> int:
        return len(json.dumps(self.to_dict(), ensure_ascii=False).encode("utf-8"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "language": self.language,
            "from": self.from_digest,
            "to": self.to_digest,
            "added": list(self.added),
            "updated": list(self.updated),
            "removed": list(self.removed),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Delta:
        protocolo = str(data.get("protocol", ""))
        if protocolo.split(".")[0] != PROTOCOL_VERSION.split(".")[0]:
            raise SyncError(f"protocolo de sincronización incompatible: {protocolo!r}")
        return cls(
            language=str(data["language"]),
            from_digest=str(data.get("from", "")),
            to_digest=str(data["to"]),
            added=tuple(data.get("added", ())),
            updated=tuple(data.get("updated", ())),
            removed=tuple(data.get("removed", ())),
            protocol=protocolo,
        )


def diff(base: Snapshot | None, target: Snapshot) -> Delta:
    """Calcula qué le falta a `base` para llegar a `target`.

    Sin `base` —cliente nuevo— el delta es la instantánea entera. Es la única
    transferencia grande del protocolo, y sigue siendo de kilobytes.
    """
    anteriores = {str(r["id"]): r for r in (base.rules if base else ())}
    actuales = {str(r["id"]): r for r in target.rules}

    return Delta(
        language=target.language,
        from_digest=base.digest if base else "",
        to_digest=target.digest,
        added=tuple(r for rid, r in actuales.items() if rid not in anteriores),
        updated=tuple(
            r for rid, r in actuales.items() if rid in anteriores and anteriores[rid] != r
        ),
        # Una regla retirada tiene que poder desaparecer del cliente. Sin esto,
        # revertir una regla en el servidor no llegaría nunca a quien la aplica.
        removed=tuple(rid for rid in anteriores if rid not in actuales),
    )


def apply(base: Snapshot | None, delta: Delta) -> Snapshot:
    """Aplica un delta y comprueba que se llega al hash anunciado.

    Idempotente: aplicar dos veces el mismo delta da el mismo resultado, lo que
    permite reintentar una sincronización interrumpida sin llevar la cuenta de
    por dónde iba.
    """
    if base and delta.from_digest and base.digest != delta.from_digest:
        raise SyncError(
            f"el delta parte de {delta.from_digest[:12]}… y esta copia está en "
            f"{base.digest[:12]}…. Pide una sincronización completa."
        )

    reglas = {str(r["id"]): r for r in (base.rules if base else ())}
    for regla in (*delta.added, *delta.updated):
        reglas[str(regla["id"])] = regla
    for rule_id in delta.removed:
        reglas.pop(rule_id, None)

    resultado = Snapshot(
        language=delta.language,
        digest=content_hash(list(reglas.values())),
        rules=tuple(reglas.values()),
        published_at=datetime.now(UTC).isoformat(),
    )

    if resultado.digest != delta.to_digest:
        raise SyncError(
            "tras aplicar el delta el contenido no coincide con el hash anunciado. "
            "La copia recibida está incompleta o alterada; descártala."
        )
    return resultado


@dataclass(frozen=True, slots=True)
class Contribution:
    """Lo que sube un cliente. Una regla propuesta y nada más.

    No lleva documento, ni fragmento, ni identificador de texto, ni marca de
    tiempo de uso. Un servidor que reciba esto no puede deducir qué leyó nadie.
    """

    language: str
    kind: RuleKind
    trigger_type: TriggerType
    trigger_value: str
    effect: dict[str, Any]
    rationale: str
    #: Seudónimo local y estable. No es una cuenta ni se puede correlacionar
    #: entre instalaciones distintas.
    contributor: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": PROTOCOL_VERSION,
            "language": self.language,
            "kind": self.kind.value,
            "trigger": {"type": self.trigger_type.value, "value": self.trigger_value},
            "effect": self.effect,
            "rationale": self.rationale,
            "contributor": self.contributor,
        }

    @property
    def size_bytes(self) -> int:
        return len(json.dumps(self.to_dict(), ensure_ascii=False).encode("utf-8"))

    def to_trigger(self) -> Trigger:
        """Construye el disparador, que valida que no lleve texto de una obra."""
        return Trigger(type=self.trigger_type, value=self.trigger_value, language=self.language)

    def to_effect(self) -> Effect:
        permitidos = {"pause_scale", "emphasis_scale", "rate_scale", "pronunciation", "role"}
        desconocidos = set(self.effect) - permitidos
        if desconocidos:
            raise SyncError(f"campos no permitidos en el efecto: {sorted(desconocidos)}")
        return Effect(**self.effect)


@dataclass(slots=True)
class OutboundQueue:
    """Cola local de contribuciones pendientes de enviar.

    Es lo que hace real el «offline primero»: se aporta sin conexión y se envía
    cuando la haya. Vive en el cliente y **no se sincroniza**: si alguien decide
    no enviar nunca, sus aportaciones se quedan donde están.
    """

    pending: list[Contribution] = field(default_factory=list)

    def add(self, contribution: Contribution) -> None:
        if contribution.size_bytes > MAX_DELTA_BYTES:
            raise SyncError("una contribución no puede ocupar más que un delta entero")
        self.pending.append(contribution)

    def drain(self) -> list[Contribution]:
        """Entrega lo pendiente y vacía la cola. Solo al confirmar el envío."""
        salida = list(self.pending)
        self.pending.clear()
        return salida

    def to_dict(self) -> dict[str, Any]:
        return {"pending": [c.to_dict() for c in self.pending]}

    def __len__(self) -> int:
        return len(self.pending)


def ingest(base: KnowledgeBase, contributions: list[Contribution]) -> tuple[int, list[str]]:
    """Incorpora contribuciones al conocimiento del servidor.

    Devuelve (aceptadas, motivos de rechazo). Una contribución mal formada no
    puede tumbar el lote entero: se descarta con su motivo y las demás siguen.
    """
    aceptadas = 0
    rechazos: list[str] = []

    for contribucion in contributions:
        if contribucion.size_bytes > MAX_DELTA_BYTES:
            rechazos.append("contribución demasiado grande para ser una regla")
            continue
        try:
            base.propose(
                kind=contribucion.kind,
                trigger=contribucion.to_trigger(),
                effect=contribucion.to_effect(),
                rationale=contribucion.rationale,
                contributor=contribucion.contributor,
            )
            aceptadas += 1
        except Exception as exc:
            rechazos.append(str(exc))

    return aceptadas, rechazos


def rule_to_public(rule: NarrationRule) -> dict[str, Any]:
    """Atajo para publicar una regla suelta con la misma forma que el resto."""
    return rule.to_public_dict()
