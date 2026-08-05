"""Aportaciones de la comunidad y su validación.

Un corpus abierto no se arruina por falta de datos, sino por falta de criterio
para admitirlos. La literatura de crowdsourcing es contundente: envenenar el 10%
de un conjunto basta para inducir el 99% de errores en un objetivo elegido, y el
voto por mayoría simple —lo primero que se le ocurre a cualquiera— se rompe en
cuanto hay revisores maliciosos coordinados.

Así que las defensas no son un añadido para más adelante; son parte del formato.
Este módulo define qué se puede aportar, cuándo se acepta y qué hace falta para
que una campaña organizada no pueda torcer la narración de un texto.

Tres decisiones que conviene entender antes de tocar nada:

**Cuórum ponderado por reputación, no mayoría.** Cada revisor pesa según su
historial contrastado contra ítems de control. Diez cuentas nuevas que votan
igual no superan a dos revisores con historial: es lo que hace cara la
fabricación de identidades, que es el ataque barato por excelencia.

**Las preferencias valen más que las opiniones.** Comparar dos versiones («¿cuál
suena mejor?») no exige saber fonética y produce una señal mucho más limpia que
pedir a alguien que ponga números. Es la vía principal de aportación, y no por
casualidad: es también la que mejor tolera a quien contribuye de buena fe pero
sin formación.

**Nada entra sin procedencia.** Cada aportación arrastra quién, cuándo y contra
qué versión del director. Cuando dentro de dos años se descubra que una fuente
estaba sesgada, tiene que poder retirarse su rastro sin reconstruir el corpus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from hearme.narration.score import NarrationScore


def _now() -> datetime:
    return datetime.now(UTC)


class ContributionKind(StrEnum):
    """Las tres formas de aportar, de menor a mayor coste para quien contribuye."""

    #: «Esta versión suena mejor que aquella.» Sin conocimientos previos.
    PREFERENCE = "preference"
    #: «Aquí falta una pausa» / «esta palabra no lleva el acento ahí.»
    CORRECTION = "correction"
    #: Una lectura humana real de la que se extrae la prosodia por alineación.
    REFERENCE = "reference"


class ContributionStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    #: Retenida por sospecha: no cuenta para el corpus ni para la reputación.
    QUARANTINED = "quarantined"


class Verdict(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    #: «No sé»: se registra pero no cuenta para el cuórum. Evita el voto forzado,
    #: que es ruido puro y además desmotiva a quien revisa con honestidad.
    ABSTAIN = "abstain"


@dataclass(frozen=True, slots=True)
class Contributor:
    """Quien aporta o revisa.

    `reliability` no se declara: se mide contra ítems de control cuyo resultado
    ya se conoce, mezclados de forma indistinguible con el trabajo real.
    """

    id: str
    #: 0..1, estimada con ítems de control. Los recién llegados empiezan bajo.
    reliability: float = 0.25
    #: Revisiones con veredicto emitidas. Da idea del tamaño de la muestra.
    reviews: int = 0
    #: Marca a quien ha acreditado experiencia (fonetistas, narradores, docentes
    #: de lectura accesible). Sube el techo de peso, nunca lo sustituye.
    accredited: bool = False

    @property
    def weight(self) -> float:
        """Peso en el cuórum.

        Crece con la fiabilidad medida y se topa: ni el revisor más veterano debe
        poder validar en solitario, porque una cuenta de confianza comprometida
        sería entonces una llave maestra.
        """
        base = min(self.reliability, 1.0)
        if self.accredited:
            base = min(base * 1.5, 1.0)
        return round(base, 4)


@dataclass(frozen=True, slots=True)
class Review:
    reviewer: Contributor
    verdict: Verdict
    at: datetime = field(default_factory=_now)
    note: str = ""


@dataclass(slots=True)
class Contribution:
    """Una aportación concreta, con todo lo necesario para auditarla después."""

    id: str
    kind: ContributionKind
    contributor: Contributor
    language: str
    #: Huella del texto al que se refiere. **Dato local: no se publica.**
    #:
    #: La primera versión de este diseño la trataba como un seudónimo del texto y
    #: la daba por publicable. Era un error: un hash sin clave de un texto público
    #: se invierte por diccionario en centésimas de segundo, así que compartirlo
    #: equivale a publicar qué lee cada cual. Se conserva para correlacionar
    #: aportaciones dentro de la instalación y nada más; lo que viaja a la
    #: comunidad son reglas generalizadas sin identificador de texto alguno
    #: (ver `hearme.knowledge`).
    text_sha256: str
    #: Partitura propuesta. En una preferencia, la de la opción elegida.
    score: NarrationScore | None = None
    #: En preferencias: identificadores de las dos versiones comparadas.
    compared: tuple[str, str] | None = None
    #: Versión del director contra la que se aportó. Sin esto no se puede saber
    #: si una corrección sigue siendo pertinente tras cambiar el modelo.
    director_version: str = ""
    status: ContributionStatus = ContributionStatus.PENDING
    reviews: list[Review] = field(default_factory=list)
    at: datetime = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "contributor": self.contributor.id,
            "language": self.language,
            "text_sha256": self.text_sha256,
            "director_version": self.director_version,
            "status": self.status.value,
            "score": self.score.to_dict() if self.score else None,
            "compared": list(self.compared) if self.compared else None,
            "at": self.at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ValidationPolicy:
    """Umbrales de admisión. Explícitos y en un solo sitio, para poder discutirlos.

    Los valores por defecto son deliberadamente conservadores: en un corpus que
    aspira a ser referencia, un falso negativo cuesta una aportación y un falso
    positivo cuesta credibilidad.
    """

    #: Peso acumulado a favor para aceptar. Con la fiabilidad inicial de 0.25,
    #: exige al menos cuatro revisores nuevos o dos ya contrastados.
    approve_weight: float = 1.0
    #: Peso en contra para rechazar. Más bajo que el de aceptar a propósito: ante
    #: la duda, no entra.
    reject_weight: float = 0.75
    #: Revisores distintos como mínimo, por mucho peso que acumulen. Es la
    #: defensa directa contra la cuenta de confianza comprometida.
    min_reviewers: int = 2
    #: Proporción de ítems de control intercalados en las colas de revisión.
    control_rate: float = 0.1
    #: Aportaciones por persona y hora. Frena el volumen automatizado sin
    #: estorbar a nadie que trabaje a mano.
    max_per_hour: int = 60
    #: Desacuerdo tolerado antes de mandar el caso a moderación humana. Un texto
    #: que divide a revisores fiables no es un fraude: suele ser una pregunta
    #: legítima sobre cómo debe leerse, y merece decisión editorial.
    contested_ratio: float = 0.35


@dataclass(frozen=True, slots=True)
class ValidationOutcome:
    status: ContributionStatus
    approve_weight: float
    reject_weight: float
    reviewers: int
    #: Explicación legible. Quien aporta merece saber por qué, y sin esto la
    #: moderación se vuelve una caja negra que quema a la comunidad.
    reason: str
    contested: bool = False


def validate(
    contribution: Contribution, policy: ValidationPolicy | None = None
) -> ValidationOutcome:
    """Decide si una aportación entra en el corpus.

    No muta nada: devuelve el veredicto para que quien llama decida qué hacer con
    él. Así la política se puede reevaluar sobre el histórico cuando cambie, que
    es exactamente lo que hará falta la primera vez que se ajuste un umbral.
    """
    policy = policy or ValidationPolicy()

    # Nadie valida lo suyo. Es la puerta trasera más obvia y la más usada.
    propios = [r for r in contribution.reviews if r.reviewer.id == contribution.contributor.id]
    revisiones = [r for r in contribution.reviews if r.reviewer.id != contribution.contributor.id]

    emitidas = [r for r in revisiones if r.verdict is not Verdict.ABSTAIN]
    # Una persona, un voto: si alguien revisa dos veces, cuenta la última.
    ultima_por_revisor: dict[str, Review] = {r.reviewer.id: r for r in emitidas}
    unicas = list(ultima_por_revisor.values())

    a_favor = sum(r.reviewer.weight for r in unicas if r.verdict is Verdict.APPROVE)
    en_contra = sum(r.reviewer.weight for r in unicas if r.verdict is Verdict.REJECT)
    total = a_favor + en_contra

    if propios:
        return ValidationOutcome(
            status=ContributionStatus.QUARANTINED,
            approve_weight=a_favor,
            reject_weight=en_contra,
            reviewers=len(unicas),
            reason="quien aporta ha intentado revisar su propia aportación",
        )

    # Desacuerdo real entre revisores: lo resuelve una persona, no un umbral.
    contested = bool(total) and min(a_favor, en_contra) / total >= policy.contested_ratio

    # El rechazo exige, además de peso, que no haya una mayoría clara a favor.
    # Sin esa segunda condición, dos revisores fiables aprobando perdían ante uno
    # solo rechazando: un veto de minoría, que es justo lo contrario de un cuórum.
    if en_contra >= policy.reject_weight and en_contra >= a_favor and not contested:
        return ValidationOutcome(
            status=ContributionStatus.REJECTED,
            approve_weight=a_favor,
            reject_weight=en_contra,
            reviewers=len(unicas),
            reason="peso suficiente en contra",
        )

    if contested:
        return ValidationOutcome(
            status=ContributionStatus.PENDING,
            approve_weight=a_favor,
            reject_weight=en_contra,
            reviewers=len(unicas),
            reason="revisores fiables en desacuerdo: se eleva a decisión editorial",
            contested=True,
        )

    if len(unicas) >= policy.min_reviewers and a_favor >= policy.approve_weight:
        return ValidationOutcome(
            status=ContributionStatus.ACCEPTED,
            approve_weight=a_favor,
            reject_weight=en_contra,
            reviewers=len(unicas),
            reason="cuórum alcanzado",
        )

    faltan = max(0, policy.min_reviewers - len(unicas))
    return ValidationOutcome(
        status=ContributionStatus.PENDING,
        approve_weight=a_favor,
        reject_weight=en_contra,
        reviewers=len(unicas),
        reason=(
            f"faltan {faltan} revisor(es)"
            if faltan
            else f"peso a favor insuficiente ({a_favor:.2f} < {policy.approve_weight})"
        ),
    )


def update_reliability(
    contributor: Contributor, *, control_hits: int, control_total: int
) -> Contributor:
    """Recalcula la fiabilidad de un revisor con los ítems de control que ha visto.

    Se usa un suavizado de Laplace en vez del acierto crudo para que nadie
    alcance peso máximo con tres aciertos afortunados: la confianza tiene que
    costar tiempo, o fabricar revisores fiables vuelve a ser barato.
    """
    if control_total < 0 or control_hits < 0 or control_hits > control_total:
        raise ValueError("recuento de ítems de control inconsistente")
    fiabilidad = (control_hits + 1) / (control_total + 4)
    return Contributor(
        id=contributor.id,
        reliability=round(min(fiabilidad, 1.0), 4),
        reviews=contributor.reviews + control_total,
        accredited=contributor.accredited,
    )
