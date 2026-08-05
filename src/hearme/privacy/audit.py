"""Auditoría encadenada y explicación de las decisiones automáticas.

Dos necesidades distintas que comparten mecanismo:

**Trazabilidad.** Poder responder «¿qué hizo este sistema con mis datos?» con
algo mejor que la palabra de quien lo opera. El registro está encadenado por
hash: alterar o suprimir una entrada rompe la cadena de forma detectable. No
impide la manipulación —quien controle el archivo puede reescribirlo entero—
pero sí que pase inadvertida, que es lo que se puede lograr sin un tercero.

**Explicabilidad.** El RGPD reconoce el derecho a una explicación significativa
de las decisiones automatizadas. Aquí las decisiones automáticas son de verdad:
qué motor de voz se eligió, por qué se aplicó OCR, por qué esa pausa dura 900 ms
y no 400. Registrarlas con sus factores convierte «el sistema lo decidió» en algo
que una persona puede leer, discutir y rebatir.

## Regla que no se salta: el registro no puede filtrar lo que protege

Un registro de auditoría que anote títulos, rutas o fragmentos deshace el
cifrado del almacén: sería la copia en claro de todo lo que alguien ha leído.
`AuditEvent` valida sus campos con las mismas reglas que el almacén.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from hearme.privacy.vault import validate_metadata

logger = logging.getLogger(__name__)

#: Hash anterior de la primera entrada. Fija el origen de la cadena.
GENESIS = "0" * 64


class EventKind(StrEnum):
    # Ciclo de vida de los datos
    RECORD_CREATED = "record_created"
    RECORD_READ = "record_read"
    RECORD_DELETED = "record_deleted"
    # Claves y sesiones
    KEYRING_UNLOCKED = "keyring_unlocked"
    KEYRING_ROTATED = "keyring_rotated"
    KEY_DESTROYED = "key_destroyed"
    PRIVATE_SESSION_CLOSED = "private_session_closed"
    # Decisiones automáticas
    DECISION = "decision"
    # Derechos de la persona interesada
    DATA_EXPORTED = "data_exported"
    ERASURE_REQUESTED = "erasure_requested"
    CONSENT_CHANGED = "consent_changed"
    # Plugins y confianza
    PLUGIN_LOADED = "plugin_loaded"
    CAPABILITY_DENIED = "capability_denied"


@dataclass(frozen=True, slots=True)
class Decision:
    """Una decisión automática, con lo necesario para poder rebatirla.

    `factors` lleva los datos que la determinaron y `alternatives` lo que se
    descartó. Sin las alternativas, una explicación es una justificación a
    posteriori: dice por qué salió A, no por qué no salió B, que es justo lo que
    quiere saber quien discrepa.
    """

    subject: str  # qué se decidió: "motor_tts", "aplicar_ocr", "pausa"
    outcome: str  # qué salió
    rationale: str  # en lenguaje llano
    factors: dict[str, Any] = field(default_factory=dict)
    alternatives: dict[str, str] = field(default_factory=dict)  # opción -> por qué no
    #: Quién decidió: "rules/1.0", "director/2.3", "selector". Permite atribuir
    #: una mala decisión a una versión concreta y revertirla.
    decided_by: str = ""

    def explain(self) -> str:
        """Explicación legible por una persona sin conocimientos técnicos."""
        partes = [f"{self.subject}: se eligió «{self.outcome}» porque {self.rationale}."]
        if self.factors:
            detalle = ", ".join(f"{k}={v}" for k, v in self.factors.items())
            partes.append(f"Se tuvo en cuenta: {detalle}.")
        if self.alternatives:
            descartes = "; ".join(f"«{k}» no, porque {v}" for k, v in self.alternatives.items())
            partes.append(f"Descartado: {descartes}.")
        if self.decided_by:
            partes.append(f"Decidido por: {self.decided_by}.")
        return " ".join(partes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "outcome": self.outcome,
            "rationale": self.rationale,
            "factors": self.factors,
            "alternatives": self.alternatives,
            "decided_by": self.decided_by,
        }


@dataclass(frozen=True, slots=True)
class AuditEvent:
    kind: EventKind
    at: datetime
    #: Seudónimo estable, nunca un nombre ni un correo.
    actor: str = "system"
    #: Identificador del registro afectado. No su contenido.
    record_id: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    decision: Decision | None = None
    previous_hash: str = GENESIS
    entry_hash: str = ""

    def payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "at": self.at.isoformat(),
            "actor": self.actor,
            "record_id": self.record_id,
            "detail": self.detail,
            "decision": self.decision.to_dict() if self.decision else None,
            "previous_hash": self.previous_hash,
        }

    def compute_hash(self) -> str:
        """Hash sobre la carga serializada de forma determinista.

        `sort_keys` no es cosmético: sin él, dos serializaciones del mismo evento
        podrían dar hashes distintos y la verificación fallaría sin motivo.
        """
        crudo = json.dumps(self.payload(), sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(crudo.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {**self.payload(), "entry_hash": self.entry_hash}


class AuditLog:
    """Registro append-only encadenado por hash.

    Deliberadamente **no cifrado**: su función es ser inspeccionable por la
    persona interesada y por quien audite. No contiene datos sensibles porque no
    se le permite contenerlos, no porque estén ocultos.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._events: list[AuditEvent] = []
        if path and path.exists():
            self._load()

    def append(
        self,
        kind: EventKind,
        *,
        actor: str = "system",
        record_id: str = "",
        detail: dict[str, Any] | None = None,
        decision: Decision | None = None,
    ) -> AuditEvent:
        detalle = dict(detail or {})
        # Las mismas reglas que el almacén: el registro no puede ser la puerta
        # trasera por la que se escapa en claro lo que se cifró al guardarlo.
        validate_metadata(detalle)

        anterior = self._events[-1].entry_hash if self._events else GENESIS
        evento = AuditEvent(
            kind=kind,
            at=datetime.now(UTC),
            actor=actor,
            record_id=record_id,
            detail=detalle,
            decision=decision,
            previous_hash=anterior,
        )
        # `replace` y no `__dict__`: con slots=True no existe __dict__, y el hash
        # se calcula sobre la carga sin incluirse a sí mismo.
        evento = replace(evento, entry_hash=evento.compute_hash())
        self._events.append(evento)
        self._persist(evento)
        return evento

    def verify(self) -> tuple[bool, str]:
        """Comprueba la integridad de la cadena. Devuelve (íntegra, explicación)."""
        anterior = GENESIS
        for indice, evento in enumerate(self._events):
            if evento.previous_hash != anterior:
                return False, f"cadena rota en la entrada {indice}: el enlace anterior no coincide"
            if evento.compute_hash() != evento.entry_hash:
                return False, f"entrada {indice} alterada: su hash no corresponde al contenido"
            anterior = evento.entry_hash
        return True, f"cadena íntegra ({len(self._events)} entradas)"

    def decisions(self, subject: str | None = None) -> list[Decision]:
        """Decisiones automáticas registradas, para explicárselas a alguien."""
        return [
            e.decision
            for e in self._events
            if e.decision is not None and (subject is None or e.decision.subject == subject)
        ]

    def for_actor(self, actor: str) -> list[AuditEvent]:
        """Todo lo registrado sobre un sujeto. Base del derecho de acceso."""
        return [e for e in self._events if e.actor == actor]

    def events(self) -> list[AuditEvent]:
        return list(self._events)

    def __len__(self) -> int:
        return len(self._events)

    # --- persistencia -------------------------------------------------------

    def _persist(self, event: AuditEvent) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # JSON por líneas y solo añadir: reescribir el archivo entero daría la
        # ocasión de perder entradas por una escritura a medias.
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False, default=str) + "\n")

    def _load(self) -> None:
        assert self.path is not None
        for linea in self.path.read_text("utf-8").splitlines():
            if not linea.strip():
                continue
            datos = json.loads(linea)
            decision = datos.get("decision")
            self._events.append(
                AuditEvent(
                    kind=EventKind(datos["kind"]),
                    at=datetime.fromisoformat(datos["at"]),
                    actor=datos.get("actor", "system"),
                    record_id=datos.get("record_id", ""),
                    detail=datos.get("detail", {}),
                    decision=Decision(**decision) if decision else None,
                    previous_hash=datos.get("previous_hash", GENESIS),
                    entry_hash=datos.get("entry_hash", ""),
                )
            )
