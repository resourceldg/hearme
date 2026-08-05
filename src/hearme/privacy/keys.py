"""Jerarquía y ciclo de vida de las claves.

## Por qué una jerarquía y no una sola clave

Con una única clave derivada de la contraseña, cambiar la contraseña obliga a
redescifrar y recifrar todo el almacén. Con dos niveles —una clave maestra
aleatoria que cifra los datos, envuelta a su vez por la clave de la contraseña—
cambiar la contraseña es reenvolver 32 bytes.

Eso no es solo comodidad: una operación de horas es una operación que **nadie
hace**. Que rotar la contraseña sea instantáneo es lo que hace que se rote de
verdad, y una clave rotada vale más que una jerarquía elegante sin usar.

La jerarquía también permite el borrado criptográfico: destruir la clave maestra
inutiliza todo lo cifrado con ella al instante, sin tocar un solo byte de datos.
En almacenamiento moderno eso es la **única** forma fiable de borrar (ver
`shredder`).

```
  contraseña ──scrypt──► clave de envoltura ──cifra──► clave maestra
                                                             │
                                        ┌────────────────────┼────────────┐
                                        ▼                    ▼            ▼
                                  contenido            perfil       índice local
                                 (por registro)     (ADN lectura)   (huella con clave)
```

## Dónde vive la clave maestra envuelta

En el propio almacén, junto a los datos. Puede sonar mal, pero es correcto: está
cifrada con una clave que solo existe mientras alguien escribe la contraseña. La
alternativa —el llavero del sistema operativo— se soporta como opción, no como
requisito, porque en un servidor sin sesión de escritorio no hay llavero, y una
dependencia que falla en el despliegue típico no es una mejora de seguridad.
"""

from __future__ import annotations

import json
import logging
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hearme.privacy.crypto import (
    SALT_BYTES,
    SCRYPT_N,
    SCRYPT_P,
    SCRYPT_R,
    CryptoError,
    Envelope,
    derive_key_from_passphrase,
    generate_key,
    seal,
    unseal,
    wipe,
)

logger = logging.getLogger(__name__)

KEYRING_VERSION = 1

#: Contexto del sobre que guarda la clave maestra. Fijo y distinto de cualquier
#: otro para que un sobre de datos no pueda hacerse pasar por el de la clave.
_MASTER_CONTEXT = "hearme:keyring:master:v1"


class Locked(Exception):
    """Se pidió una clave con el llavero bloqueado."""


@dataclass(slots=True)
class KeyringFile:
    """Metadatos públicos del llavero. No contiene ningún secreto."""

    version: int
    salt: str
    scrypt_n: int
    scrypt_r: int
    scrypt_p: int
    wrapped_master: dict[str, Any]
    #: Clave para las huellas locales, cifrada bajo la maestra. Ver `keyed_digest`.
    wrapped_index_key: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "salt": self.salt,
            "kdf": {"name": "scrypt", "n": self.scrypt_n, "r": self.scrypt_r, "p": self.scrypt_p},
            "wrapped_master": self.wrapped_master,
            "wrapped_index_key": self.wrapped_index_key,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KeyringFile:
        kdf = data.get("kdf", {})
        return cls(
            version=int(data["version"]),
            salt=str(data["salt"]),
            scrypt_n=int(kdf.get("n", SCRYPT_N)),
            scrypt_r=int(kdf.get("r", SCRYPT_R)),
            scrypt_p=int(kdf.get("p", SCRYPT_P)),
            wrapped_master=data["wrapped_master"],
            wrapped_index_key=data["wrapped_index_key"],
        )


class Keyring:
    """Custodia las claves en memoria y las entrega solo mientras esté desbloqueado.

    No es un almacén seguro de hardware ni lo pretende. Es la frontera explícita
    entre «hay una contraseña escrita» y «no la hay», para que ningún módulo
    pueda acceder a datos en claro por descuido: sin desbloquear, no hay clave, y
    sin clave no hay lectura.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._master: bytearray | None = None
        self._index_key: bytearray | None = None

    # --- estado -------------------------------------------------------------

    @property
    def exists(self) -> bool:
        return self.path.exists()

    @property
    def is_locked(self) -> bool:
        return self._master is None

    def _require_unlocked(self) -> bytes:
        if self._master is None:
            raise Locked("el llavero está bloqueado")
        return bytes(self._master)

    @property
    def master_key(self) -> bytes:
        """Clave para cifrar contenido. Cada llamada devuelve una copia."""
        return self._require_unlocked()

    @property
    def index_key(self) -> bytes:
        """Clave de las huellas locales. Nunca sale de la instalación."""
        self._require_unlocked()
        assert self._index_key is not None
        return bytes(self._index_key)

    # --- ciclo de vida ------------------------------------------------------

    def initialize(self, passphrase: str, *, scrypt_n: int = SCRYPT_N) -> None:
        """Crea el llavero. Falla si ya existe: sobrescribirlo perdería los datos."""
        if self.exists:
            raise CryptoError("el llavero ya existe; usa change_passphrase() para rotarla")
        _validate_passphrase(passphrase)

        salt = secrets.token_bytes(SALT_BYTES)
        master = generate_key()
        index_key = generate_key()

        wrapping = derive_key_from_passphrase(passphrase, salt, n=scrypt_n)
        try:
            wrapped_master = seal(wrapping, master, context=_MASTER_CONTEXT)
            wrapped_index = seal(master, index_key, context="hearme:keyring:index:v1")
        finally:
            wipe(bytearray(wrapping))

        self._write(
            KeyringFile(
                version=KEYRING_VERSION,
                salt=salt.hex(),
                scrypt_n=scrypt_n,
                scrypt_r=SCRYPT_R,
                scrypt_p=SCRYPT_P,
                wrapped_master=wrapped_master.to_dict(),
                wrapped_index_key=wrapped_index.to_dict(),
            )
        )
        self._master = bytearray(master)
        self._index_key = bytearray(index_key)
        logger.info("llavero creado en %s", self.path)

    def unlock(self, passphrase: str) -> None:
        """Desenvuelve la clave maestra. Error indistinguible ante cualquier fallo."""
        data = self._read()
        wrapping = derive_key_from_passphrase(
            passphrase,
            bytes.fromhex(data.salt),
            n=data.scrypt_n,
            r=data.scrypt_r,
            p=data.scrypt_p,
        )
        try:
            master = unseal(
                wrapping, Envelope.from_dict(data.wrapped_master), context=_MASTER_CONTEXT
            )
        finally:
            wipe(bytearray(wrapping))

        index_key = unseal(
            master, Envelope.from_dict(data.wrapped_index_key), context="hearme:keyring:index:v1"
        )
        self._master = bytearray(master)
        self._index_key = bytearray(index_key)

    def lock(self) -> None:
        """Olvida las claves. Idempotente: bloquear dos veces no es un error."""
        for buffer in (self._master, self._index_key):
            if buffer is not None:
                wipe(buffer)
        self._master = None
        self._index_key = None

    def change_passphrase(self, current: str, new: str) -> None:
        """Rota la contraseña reenvolviendo 32 bytes. No toca los datos cifrados."""
        _validate_passphrase(new)
        self.unlock(current)  # valida la actual
        master = self._require_unlocked()

        data = self._read()
        salt = secrets.token_bytes(SALT_BYTES)
        wrapping = derive_key_from_passphrase(new, salt, n=data.scrypt_n)
        try:
            data.salt = salt.hex()
            data.wrapped_master = seal(wrapping, master, context=_MASTER_CONTEXT).to_dict()
        finally:
            wipe(bytearray(wrapping))
        self._write(data)
        logger.info("contraseña del llavero rotada")

    def destroy(self) -> None:
        """Borrado criptográfico: sin la clave maestra, lo cifrado es ruido.

        Es la operación que hace efectivo el derecho de supresión del RGPD en
        almacenamiento donde sobrescribir no garantiza nada. Ver `shredder`.
        """
        self.lock()
        if self.path.exists():
            # La clave envuelta es pequeña: sobrescribirla sí tiene sentido, a
            # diferencia de un archivo grande en un SSD.
            size = self.path.stat().st_size
            with self.path.open("r+b") as handle:
                handle.write(secrets.token_bytes(size))
                handle.flush()
                import os

                os.fsync(handle.fileno())
            self.path.unlink()
        logger.warning("llavero destruido: los datos cifrados con él son irrecuperables")

    # --- persistencia -------------------------------------------------------

    def _read(self) -> KeyringFile:
        if not self.exists:
            raise CryptoError("no hay llavero; inicialízalo primero")
        try:
            return KeyringFile.from_dict(json.loads(self.path.read_text("utf-8")))
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            raise CryptoError("llavero ilegible o corrupto") from exc

    def _write(self, data: KeyringFile) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporal = self.path.with_suffix(".tmp")
        temporal.write_text(json.dumps(data.to_dict(), indent=2), encoding="utf-8")
        # Solo la persona propietaria. Se aplica antes de publicar el nombre final.
        temporal.chmod(0o600)
        temporal.replace(self.path)

    def __enter__(self) -> Keyring:
        return self

    def __exit__(self, *exc: object) -> None:
        self.lock()


#: Longitud mínima. No se exigen «una mayúscula y un símbolo»: esas reglas
#: producen contraseñas peores y más difíciles de recordar. La longitud es lo que
#: importa, y este umbral admite una frase de cuatro palabras.
MIN_PASSPHRASE_LENGTH = 12


def _validate_passphrase(passphrase: str) -> None:
    if len(passphrase) < MIN_PASSPHRASE_LENGTH:
        raise CryptoError(
            f"la contraseña debe tener al menos {MIN_PASSPHRASE_LENGTH} caracteres; "
            "una frase de varias palabras es mejor que un galimatías corto"
        )
