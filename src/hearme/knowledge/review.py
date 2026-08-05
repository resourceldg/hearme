"""Revisión comunitaria de reglas: historial, justificación y reversión.

Una regla mal aceptada no es un fallo cosmético: cambia cómo suenan miles de
libros para miles de personas. Así que el sistema tiene que responder tres
preguntas en cualquier momento:

1. **¿Por qué la narración suena así?** → la regla activa y su justificación.
2. **¿Quién decidió eso y cuándo?** → el historial de propuestas y revisiones.
3. **¿Cómo se deshace?** → reversión a un estado anterior, con constancia.

La tercera es la que suele faltar. Muchos sistemas colaborativos permiten
proponer y aprobar, pero deshacer exige un administrador y un rato. Un cambio
que no se puede revertir con facilidad es un cambio que nadie se atreve a hacer,
y eso paraliza a la comunidad tanto como el caos.

## Reversión frente a rectificación

Se distingue a propósito:

- **Revertir** devuelve el estado anterior tal cual, en una operación. Es para
  cuando algo salió mal y hay prisa.
- **Sustituir** (`supersede` en `knowledge`) crea una versión nueva con su
  justificación. Es para cuando se ha aprendido algo.

Ambas dejan rastro. Ninguna borra nada.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from hearme.knowledge.knowledge import KnowledgeBase, NarrationRule


class ChangeType(StrEnum):
    PROPOSED = "proposed"
    SUPPORTED = "supported"
    DISPUTED = "disputed"
    SUPERSEDED = "superseded"
    REVERTED = "reverted"
    PUBLISHED = "published"


@dataclass(frozen=True, slots=True)
class ChangeEntry:
    """Una entrada del historial. Inmutable por construcción."""

    at: datetime
    change: ChangeType
    rule_id: str
    #: Seudónimo. El historial es público, así que nunca lleva identidad real.
    actor: str
    #: Por qué. Obligatorio para SUPERSEDED y REVERTED: los cambios que alteran
    #: lo que ya sonaba de una forma no pueden ser anónimos en su motivo.
    reason: str = ""
    #: Instantánea del efecto anterior, para poder revertir con exactitud.
    previous: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "at": self.at.isoformat(),
            "change": self.change.value,
            "rule_id": self.rule_id,
            "actor": self.actor,
            "reason": self.reason,
            "previous": self.previous,
        }


class ReviewError(Exception):
    pass


@dataclass(slots=True)
class ReviewLedger:
    """Historial completo de una base de conocimiento. Solo crece.

    Deliberadamente separado de `KnowledgeBase`: el conocimiento es el estado
    actual, el historial es cómo se llegó a él. Mezclarlos hace que purgar el
    estado se lleve por delante la trazabilidad.
    """

    entries: list[ChangeEntry] = field(default_factory=list)

    def record(
        self,
        change: ChangeType,
        rule: NarrationRule,
        *,
        actor: str,
        reason: str = "",
        previous: dict[str, Any] | None = None,
    ) -> ChangeEntry:
        if change in {ChangeType.SUPERSEDED, ChangeType.REVERTED} and not reason.strip():
            raise ReviewError(f"'{change.value}' exige un motivo: cambia lo que la gente ya oía")

        entrada = ChangeEntry(
            at=datetime.now(UTC),
            change=change,
            rule_id=rule.id,
            actor=actor,
            reason=reason,
            previous=previous,
        )
        self.entries.append(entrada)
        return entrada

    def history_of(self, rule_id: str) -> list[ChangeEntry]:
        """Todo lo ocurrido a una regla, en orden. Responde al «¿por qué suena así?»."""
        return [e for e in self.entries if e.rule_id.startswith(rule_id.split("-v")[0])]

    def explain(self, rule: NarrationRule) -> str:
        """Explicación legible del estado de una regla y de cómo llegó ahí."""
        historial = self.history_of(rule.id)
        lineas = [
            f"Regla {rule.id} ({rule.kind.value}) sobre «{rule.trigger.value}» en "
            f"{rule.trigger.language}.",
            f"Efecto: {rule.effect.to_dict()}.",
            f"Motivo: {rule.rationale}",
            f"Apoyo: {rule.support} contribuyente(s), {rule.disputes} disputa(s), "
            f"confianza {rule.confidence}.",
        ]
        if not rule.is_publishable:
            lineas.append(
                "Retenida: aún no la respaldan suficientes personas independientes "
                "como para publicarla sin que señale a ninguna."
            )
        if historial:
            lineas.append(
                f"Historial: {len(historial)} cambio(s), el último "
                f"{historial[-1].change.value} el {historial[-1].at.date()}."
            )
        return " ".join(lineas)

    def to_json(self) -> str:
        return json.dumps(
            {"format": "hearme.review.v1", "entries": [e.to_dict() for e in self.entries]},
            ensure_ascii=False,
            indent=2,
        )


class ReviewedKnowledge:
    """Base de conocimiento con historial. Es la que se usa en producción.

    Envuelve `KnowledgeBase` para que **no exista forma de cambiar una regla sin
    dejar constancia**: si el historial fuera opcional, un camino de código lo
    acabaría saltando y la trazabilidad tendría agujeros justo donde importa.
    """

    def __init__(self, base: KnowledgeBase, ledger: ReviewLedger | None = None) -> None:
        self.base = base
        self.ledger = ledger or ReviewLedger()

    def propose(self, *, contributor: str, **kwargs: Any) -> NarrationRule:
        antes = set(self.base.rules)
        regla = self.base.propose(contributor=contributor, **kwargs)
        cambio = ChangeType.PROPOSED if regla.id not in antes else ChangeType.SUPPORTED
        self.ledger.record(cambio, regla, actor=contributor)
        return regla

    def dispute(self, rule_id: str, *, actor: str, reason: str) -> NarrationRule:
        regla = self.base.dispute(rule_id)
        self.ledger.record(ChangeType.DISPUTED, regla, actor=actor, reason=reason)
        return regla

    def supersede(
        self, rule_id: str, *, effect: Any, rationale: str, contributor: str, reason: str
    ) -> NarrationRule:
        anterior = self.base.rules[rule_id]
        instantanea = anterior.to_public_dict()
        nueva = self.base.supersede(
            rule_id, effect=effect, rationale=rationale, contributor=contributor
        )
        self.ledger.record(
            ChangeType.SUPERSEDED, nueva, actor=contributor, reason=reason, previous=instantanea
        )
        return nueva

    def revert(self, rule_id: str, *, actor: str, reason: str) -> NarrationRule:
        """Devuelve una regla a su versión anterior. Una operación, con constancia.

        No borra la versión revertida: queda en el historial para que se entienda
        qué se probó y por qué no funcionó. Repetir un error ya cometido es la
        forma más cara de aprender.
        """
        regla = self.base.rules.get(rule_id)
        if regla is None:
            raise ReviewError(f"no existe la regla '{rule_id}'")
        if regla.supersedes is None:
            raise ReviewError(f"'{rule_id}' no sustituye a ninguna: no hay a dónde volver")

        previa = self.base.rules.get(regla.supersedes)
        if previa is None:
            raise ReviewError(
                f"la versión anterior '{regla.supersedes}' ya no está: no se puede revertir"
            )

        del self.base.rules[rule_id]
        self.ledger.record(
            ChangeType.REVERTED,
            regla,
            actor=actor,
            reason=reason,
            previous=regla.to_public_dict(),
        )
        return previa

    def publish(self, *, actor: str = "release", epsilon: float | None = None) -> str:
        """Publica las reglas que superan el umbral y anota la publicación."""
        for regla in self.base.rules.values():
            if regla.is_publishable:
                self.ledger.record(ChangeType.PUBLISHED, regla, actor=actor)
        return self.base.to_json(epsilon=epsilon)
