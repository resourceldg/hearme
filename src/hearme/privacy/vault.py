"""Almacén cifrado con separación estricta entre contenido y metadatos.

## El error que este módulo existe para impedir

Cifrar el contenido y guardar los metadatos en claro parece razonable: el
servicio necesita saber que un trabajo existe, en qué estado está y cuándo se
creó. El problema es que **los metadatos identifican el contenido sin abrirlo**.

Un documento tiene un tamaño en bytes exacto. Quien tenga un catálogo público de
libros —y existen— puede calcular el tamaño de cada uno y buscar coincidencias.
Con la marca de tiempo exacta se sabe además cuándo se leyó. Título y nombre de
archivo, si se guardan en claro, sobran ya para todo.

Por eso aquí los metadatos no son «lo que quedó fuera del cifrado», sino una
categoría con sus propias reglas: **solo lo imprescindible para operar, y
degradado a propósito** para que no identifique nada.

| Dato | Cómo se guarda | Por qué |
|---|---|---|
| Contenido, título, nombre | Cifrado | Es la obra y qué lee la persona |
| Tamaño | En cubos logarítmicos | El tamaño exacto es una huella dactilar |
| Marcas de tiempo | Redondeadas a la hora | El segundo exacto correlaciona con otros registros |
| Estado, tipo, versión | En claro | Necesario para operar y no distingue documentos |

La degradación no es gratis: se pierde precisión en las estadísticas de uso. Es
un intercambio consciente, y va a favor de quien lee.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from hearme.privacy.crypto import Envelope, keyed_digest, seal, unseal


class Sensitivity(StrEnum):
    """Clasificación de un campo. Decide dónde puede vivir."""

    #: La obra, el perfil de lectura, la voz. Siempre cifrado.
    CONTENT = "content"
    #: Identifica indirectamente al contenido. Se guarda degradado.
    QUASI_IDENTIFIER = "quasi_identifier"
    #: No distingue a una persona ni a un documento. Puede ir en claro.
    OPERATIONAL = "operational"


class VaultError(Exception):
    pass


def size_bucket(size_bytes: int) -> str:
    """Cubo logarítmico en base 2.

    Un PDF de 2 481 923 bytes es casi único en un catálogo; «2-4 MB» lo comparte
    con miles. Se conserva lo que hace falta para planificar recursos y se pierde
    justo la precisión que servía para identificar.
    """
    if size_bytes <= 0:
        return "0"
    exponente = int(math.log2(size_bytes))
    inferior = 2**exponente
    return f"{_human(inferior)}-{_human(inferior * 2)}"


def _human(value: int) -> str:
    for unidad, umbral in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if value >= umbral:
            return f"{value // umbral}{unidad}"
    return f"{value}B"


def coarsen_time(moment: datetime, *, hours: int = 1) -> datetime:
    """Redondea hacia abajo. El segundo exacto es un identificador de correlación."""
    if hours < 1:
        raise VaultError("la granularidad mínima es una hora")
    momento = moment.astimezone(UTC)
    return momento.replace(hour=(momento.hour // hours) * hours, minute=0, second=0, microsecond=0)


@dataclass(slots=True)
class VaultRecord:
    """Un registro: metadatos operativos en claro, todo lo demás en un sobre.

    La separación es estructural, no una convención. No existe forma de poner
    contenido en `metadata` sin que `put()` lo rechace.
    """

    id: str
    kind: str
    #: Solo campos OPERATIONAL o degradados. Validado al guardar.
    metadata: dict[str, Any] = field(default_factory=dict)
    #: Todo lo sensible, cifrado con contexto ligado a `id` y `kind`.
    sealed: dict[str, Any] | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def context(self) -> str:
        """Ata el sobre a este registro concreto: impide reubicarlo en otro."""
        return f"hearme:vault:{self.kind}:{self.id}"


#: Claves prohibidas en metadatos. No es una lista exhaustiva —no puede serlo—
#: pero atrapa los descuidos habituales, que es de donde vienen las fugas reales.
_FORBIDDEN_METADATA = frozenset(
    {
        "text",
        "content",
        "title",
        "filename",
        "path",
        "source_path",
        "author",
        "authors",
        "body",
        "excerpt",
        "transcript",
        "voice",
        "passphrase",
        "token",
    }
)

#: Campos que solo se admiten degradados. Guardar el valor exacto es la fuga.
_MUST_BE_COARSE = {"size": "usa size_bucket()", "size_bytes": "usa size_bucket()"}


def validate_metadata(metadata: dict[str, Any]) -> None:
    """Rechaza metadatos que identificarían el contenido.

    Se ejecuta siempre, no solo en depuración: una comprobación de privacidad que
    se puede desactivar acaba desactivada.
    """
    for clave in metadata:
        normalizada = clave.lower()
        if normalizada in _FORBIDDEN_METADATA:
            raise VaultError(
                f"'{clave}' es contenido, no metadato: va cifrado o no va. "
                "Guardarlo en claro permitiría identificar qué se ha leído."
            )
        if normalizada in _MUST_BE_COARSE:
            raise VaultError(f"'{clave}' identifica el contenido: {_MUST_BE_COARSE[normalizada]}")


class Vault:
    """Almacén cifrado. Requiere un llavero desbloqueado para leer o escribir."""

    def __init__(self, keyring: Any) -> None:
        self.keyring = keyring
        self._records: dict[str, VaultRecord] = {}

    def put(
        self,
        record_id: str,
        kind: str,
        *,
        content: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> VaultRecord:
        metadata = dict(metadata or {})
        validate_metadata(metadata)

        registro = VaultRecord(id=record_id, kind=kind, metadata=metadata)
        if content is not None:
            payload = json.dumps(content, ensure_ascii=False, default=str).encode("utf-8")
            registro.sealed = seal(
                self.keyring.master_key, payload, context=registro.context
            ).to_dict()
        self._records[record_id] = registro
        return registro

    def get(self, record_id: str) -> Any | None:
        """Descifra el contenido. Devuelve None si el registro no tiene."""
        registro = self._records.get(record_id)
        if registro is None:
            raise VaultError(f"no existe el registro '{record_id}'")
        if registro.sealed is None:
            return None
        crudo = unseal(
            self.keyring.master_key, Envelope.from_dict(registro.sealed), context=registro.context
        )
        return json.loads(crudo)

    def metadata_of(self, record_id: str) -> dict[str, Any]:
        """Metadatos en claro. Se puede consultar sin descifrar nada."""
        registro = self._records.get(record_id)
        if registro is None:
            raise VaultError(f"no existe el registro '{record_id}'")
        return dict(registro.metadata)

    def fingerprint(self, text: str) -> str:
        """Huella local con clave, para deduplicar sin poder reidentificar fuera."""
        return keyed_digest(self.keyring.index_key, text)

    def forget(self, record_id: str) -> bool:
        """Elimina un registro. El sobre desaparece con él."""
        return self._records.pop(record_id, None) is not None

    def records(self) -> list[VaultRecord]:
        return list(self._records.values())

    def __len__(self) -> int:
        return len(self._records)
