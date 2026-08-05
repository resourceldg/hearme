"""Derechos de la persona interesada, implementados y no solo declarados.

Casi toda la conformidad con el RGPD que se ve por ahí es una política de
privacidad. Aquí los derechos son funciones que se ejecutan, porque un derecho
que exige escribir un correo y esperar treinta días no se ejerce nunca.

| Artículo | Derecho | Función |
|---|---|---|
| 15 | Acceso | `access_report()` |
| 16 | Rectificación | Se ejerce corrigiendo el perfil; queda en auditoría |
| 17 | Supresión | `erase()` — borrado criptográfico |
| 20 | Portabilidad | `export_portable()` — JSON abierto y documentado |
| 21 | Oposición | `withdraw_consent()` |
| 22 | Decisiones automatizadas | `explain_decisions()` |
| 30 | Registro de actividades | `processing_record()` |

## La postura del proyecto sobre la base jurídica

HearMe procesa en local y por instrucción de quien lo usa. En un despliegue
doméstico ni siquiera hay tratamiento en el sentido del reglamento. En una
biblioteca sí lo hay, y ahí la institución es la responsable del tratamiento y
HearMe la herramienta.

Este módulo existe para que **esa institución pueda cumplir sin desarrollar
nada**. La única base jurídica que el proyecto asume para sí es el
consentimiento explícito, y solo para lo que es opcional: contribuir a la red de
conocimiento.

## Por qué el consentimiento es granular

Un único «acepto» que cubra analítica, contribución y perfilado no es
consentimiento informado: es una casilla. Aquí cada finalidad se concede y se
retira por separado, y todas empiezan apagadas.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from hearme.privacy.audit import AuditLog, EventKind


class ConsentPurpose(StrEnum):
    """Finalidades separables. Todas desactivadas de origen."""

    #: Aportar reglas generalizadas a la red de conocimiento comunitaria.
    CONTRIBUTE_KNOWLEDGE = "contribute_knowledge"
    #: Aprender de las correcciones para construir el perfil personal.
    PERSONAL_PROFILE = "personal_profile"
    #: Estadísticas agregadas de uso del despliegue.
    USAGE_METRICS = "usage_metrics"
    #: Ceder el audio de una lectura de referencia (no solo su prosodia).
    VOICE_DONATION = "voice_donation"


@dataclass(frozen=True, slots=True)
class ConsentGrant:
    purpose: ConsentPurpose
    granted: bool
    at: datetime
    #: Texto exacto que se aceptó. Sin esto no se puede demostrar qué se informó,
    #: y un consentimiento que no se puede acreditar no vale.
    notice_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose.value,
            "granted": self.granted,
            "at": self.at.isoformat(),
            "notice_version": self.notice_version,
        }


@dataclass(slots=True)
class ConsentLedger:
    """Historial completo de consentimientos. Solo se añade, nunca se reescribe.

    Guardar el estado actual no basta: hay que poder demostrar *qué se consintió
    y cuándo*, y también cuándo se retiró. Un dato tratado antes de la retirada
    fue lícito; después, no. Sin historial no se puede distinguir.
    """

    subject: str = "local"
    history: list[ConsentGrant] = field(default_factory=list)

    def grant(self, purpose: ConsentPurpose, *, notice_version: str) -> ConsentGrant:
        entrada = ConsentGrant(purpose, True, datetime.now(UTC), notice_version)
        self.history.append(entrada)
        return entrada

    def withdraw(self, purpose: ConsentPurpose) -> ConsentGrant:
        """Retirar debe ser tan fácil como conceder. Sin fricción y sin preguntas."""
        entrada = ConsentGrant(purpose, False, datetime.now(UTC))
        self.history.append(entrada)
        return entrada

    def has(self, purpose: ConsentPurpose) -> bool:
        """Estado actual. Ausencia de constancia = no concedido."""
        for entrada in reversed(self.history):
            if entrada.purpose is purpose:
                return entrada.granted
        return False

    def granted_at(self, purpose: ConsentPurpose) -> datetime | None:
        for entrada in reversed(self.history):
            if entrada.purpose is purpose and entrada.granted:
                return entrada.at
        return None

    def to_dict(self) -> dict[str, Any]:
        return {"subject": self.subject, "history": [g.to_dict() for g in self.history]}


class ConsentRequired(Exception):
    """Se intentó una operación opcional sin el consentimiento correspondiente."""


def require_consent(ledger: ConsentLedger, purpose: ConsentPurpose) -> None:
    """Puerta única para toda operación opcional.

    Todo lo que no sea estrictamente necesario para narrar un documento pasa por
    aquí. Centralizarlo es lo que permite auditar que no hay atajos.
    """
    if not ledger.has(purpose):
        raise ConsentRequired(
            f"'{purpose.value}' requiere consentimiento explícito y no consta concedido"
        )


@dataclass(frozen=True, slots=True)
class ErasureReceipt:
    """Comprobante de supresión. Se entrega a quien la solicitó.

    Incluye qué se destruyó y **qué no se pudo destruir**, con su motivo. Un
    comprobante que solo diga «hecho» no permite verificar nada.
    """

    subject: str
    at: datetime
    keys_destroyed: int
    records_removed: int
    retained: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "at": self.at.isoformat(),
            "keys_destroyed": self.keys_destroyed,
            "records_removed": self.records_removed,
            "retained": self.retained,
        }


class DataSubjectRights:
    """Ejercicio de los derechos sobre un almacén, un perfil y una auditoría."""

    def __init__(
        self,
        *,
        vault: Any = None,
        profile: Any = None,
        consent: ConsentLedger | None = None,
        audit: AuditLog | None = None,
    ) -> None:
        self.vault = vault
        self.profile = profile
        self.consent = consent or ConsentLedger()
        self.audit = audit

    def access_report(self, subject: str = "local") -> dict[str, Any]:
        """Art. 15: qué se trata, con qué fin y desde cuándo."""
        informe: dict[str, Any] = {
            "subject": subject,
            "generated_at": datetime.now(UTC).isoformat(),
            "categories": {},
            "consents": self.consent.to_dict(),
            "automated_decisions": self.explain_decisions(),
        }
        if self.vault is not None:
            informe["categories"]["stored_records"] = {
                "count": len(self.vault),
                "content": "cifrado; solo se puede abrir con la clave de la persona",
                "metadata": "degradado a propósito (tamaño en cubos, tiempos redondeados)",
            }
        if self.profile is not None:
            informe["categories"]["reading_profile"] = self.profile.shareable_summary()
        if self.audit is not None:
            informe["categories"]["audit_entries"] = len(self.audit.for_actor(subject))
        if self.audit is not None:
            self.audit.append(EventKind.DATA_EXPORTED, actor=subject, detail={"article": "15"})
        return informe

    def export_portable(self, subject: str = "local") -> str:
        """Art. 20: formato estructurado, de uso común y legible por máquina.

        JSON con esquema documentado y versionado. No un volcado de base de datos
        que solo sepa leer este proyecto: eso incumple el espíritu del artículo,
        que es poder llevarse los datos *a otro sitio*.
        """
        datos: dict[str, Any] = {
            "format": "hearme.portable.v1",
            "exported_at": datetime.now(UTC).isoformat(),
            "subject": subject,
            "consents": self.consent.to_dict(),
        }
        if self.profile is not None:
            datos["reading_dna"] = self.profile.to_dict()
        if self.audit is not None:
            datos["audit"] = [e.to_dict() for e in self.audit.for_actor(subject)]
            self.audit.append(EventKind.DATA_EXPORTED, actor=subject, detail={"article": "20"})
        return json.dumps(datos, ensure_ascii=False, indent=2, default=str)

    def erase(self, subject: str = "local", *, keyring: Any = None) -> ErasureReceipt:
        """Art. 17: supresión por destrucción de la clave.

        Se destruye la clave antes de tocar los registros. Si el proceso muriera
        a mitad, lo que quede en disco ya es indescifrable: el borrado es
        efectivo desde el primer paso, no desde el último.
        """
        claves = 0
        registros = 0
        retenido: dict[str, str] = {}

        if keyring is not None:
            keyring.destroy()
            claves = 1

        if self.vault is not None:
            for registro in list(self.vault.records()):
                if self.vault.forget(registro.id):
                    registros += 1

        if self.audit is not None:
            # La cadena de auditoría no se borra: es el propio comprobante de que
            # la supresión ocurrió, y su integridad depende de no tener huecos.
            # No contiene datos personales porque `validate_metadata` lo impide.
            retenido["audit_log"] = (
                "se conserva la cadena de auditoría: acredita la supresión y no "
                "contiene contenido ni identificadores directos"
            )
            self.audit.append(
                EventKind.ERASURE_REQUESTED,
                actor=subject,
                detail={"records_removed": registros, "keys_destroyed": claves},
            )

        return ErasureReceipt(
            subject=subject,
            at=datetime.now(UTC),
            keys_destroyed=claves,
            records_removed=registros,
            retained=retenido,
        )

    def withdraw_consent(self, purpose: ConsentPurpose, subject: str = "local") -> ConsentGrant:
        """Art. 21. Efecto inmediato y sin pedir explicaciones."""
        entrada = self.consent.withdraw(purpose)
        if self.audit is not None:
            self.audit.append(
                EventKind.CONSENT_CHANGED,
                actor=subject,
                detail={"purpose": purpose.value, "granted": False},
            )
        return entrada

    def explain_decisions(self, subject_filter: str | None = None) -> list[dict[str, str]]:
        """Art. 22: explicación significativa de las decisiones automatizadas."""
        if self.audit is None:
            return []
        return [
            {"subject": d.subject, "outcome": d.outcome, "explanation": d.explain()}
            for d in self.audit.decisions(subject_filter)
        ]

    def processing_record(self) -> dict[str, Any]:
        """Art. 30: registro de actividades de tratamiento, para la institución."""
        return {
            "controller": "el despliegue que ejecuta HearMe",
            "processor": "ninguno: no hay terceros ni transferencias",
            "purposes": {
                "narrar_documentos": {
                    "basis": "ejecución por instrucción de la persona usuaria",
                    "data": "documento aportado y audio derivado",
                    "retention": "hasta que se borre; inmediato en sesión privada",
                    "recipients": "ninguno",
                },
                "perfil_de_lectura": {
                    "basis": "consentimiento explícito",
                    "data": "preferencias prosódicas, sin textos",
                    "retention": "hasta retirada del consentimiento",
                    "recipients": "ninguno",
                },
                "conocimiento_comunitario": {
                    "basis": "consentimiento explícito",
                    "data": "reglas generalizadas, sin textos ni identidades",
                    "retention": "indefinida (publicado en CC0 y no reversible)",
                    "recipients": "público",
                },
            },
            "transfers": "ninguna: el tratamiento es local por diseño",
            "security": (
                "ChaCha20-Poly1305 con subclave por registro, jerarquía de claves con "
                "scrypt, separación contenido/metadatos, auditoría encadenada"
            ),
        }
