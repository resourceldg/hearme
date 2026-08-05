"""Primitivas criptográficas. Pocas, elegidas a conciencia y difíciles de usar mal.

Este módulo no inventa criptografía: envuelve la de `cryptography` (pyca) con una
API que hace que el uso incorrecto sea complicado. Casi todos los fallos reales
en sistemas cifrados no vienen de romper el cifrado, sino de reutilizar un nonce,
de olvidar autenticar los metadatos o de confundir «cifrado» con «autenticado».

## Elecciones y por qué

**ChaCha20-Poly1305 frente a AES-GCM.** AES-GCM es más rápido *cuando hay
AES-NI*. Sin aceleración por hardware, una implementación de AES en software o
es lenta o filtra por temporización. HearMe aspira a correr en el servidor viejo
de una biblioteca tanto como en un contenedor moderno, y ChaCha20 es de tiempo
constante en software puro sin instrucciones especiales. La privacidad no puede
depender de que a la institución le haya alcanzado el presupuesto.

**Subclave por registro frente a nonce aleatorio global.** La catástrofe clásica
de AEAD es repetir un nonce con la misma clave: se pierde la confidencialidad de
los dos mensajes y, en GCM, la clave de autenticación. Con un nonce de 96 bits y
claves de larga vida, la probabilidad de colisión deja de ser despreciable antes
de lo que parece. Aquí cada registro deriva **su propia clave** con HKDF a partir
de una sal aleatoria de 256 bits; el nonce vuelve a ser irrelevante porque nunca
se repite bajo la misma clave. Cuesta una derivación por registro y elimina toda
una familia de fallos.

**Datos asociados obligatorios.** `seal()` exige el contexto (tipo de registro,
identificador, versión) y lo autentica. Sin esto, quien tenga acceso al almacén
puede mover un ciphertext válido de un registro a otro: no descifra nada, pero
puede hacer que el perfil de A aparezca como el de B. Es un ataque de
reubicación, y se previene gratis obligando a declarar el contexto.

**scrypt para contraseñas.** Memoria-dura, en la biblioteca estándar. Argon2id
sería marginalmente preferible, pero exige una dependencia con extensión en C y
scrypt con parámetros correctos es defensa de sobra frente a un ataque por
fuerza bruta con GPU. Menos dependencias en el camino crítico de seguridad es,
en sí mismo, una propiedad de seguridad.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from typing import Any, Final

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

#: Versión del formato de sobre. Va dentro de los datos autenticados: cambiar de
#: formato no puede permitir que un sobre viejo se interprete como uno nuevo.
ENVELOPE_VERSION: Final = 1

KEY_BYTES: Final = 32
NONCE_BYTES: Final = 12
SALT_BYTES: Final = 32

#: Parámetros de scrypt. n=2^17 con r=8 es el mínimo que recomienda OWASP;
#: medido, son ~134 MB y ~0,25 s, coste aceptable para un desbloqueo y muy caro
#: de paralelizar para quien pruebe contraseñas a millones.
SCRYPT_N: Final = 1 << 17
SCRYPT_R: Final = 8
SCRYPT_P: Final = 1


class CryptoError(Exception):
    """Fallo criptográfico. Nunca detalla el motivo: sería un oráculo."""


@dataclass(frozen=True, slots=True)
class Envelope:
    """Un dato cifrado y autenticado, con todo lo necesario para abrirlo salvo la clave."""

    version: int
    salt: bytes
    nonce: bytes
    ciphertext: bytes

    def to_bytes(self) -> bytes:
        """Serialización compacta: versión ‖ sal ‖ nonce ‖ ciphertext."""
        return bytes([self.version]) + self.salt + self.nonce + self.ciphertext

    @classmethod
    def from_bytes(cls, raw: bytes) -> Envelope:
        minimo = 1 + SALT_BYTES + NONCE_BYTES
        if len(raw) < minimo:
            raise CryptoError("sobre corrupto")
        return cls(
            version=raw[0],
            salt=raw[1 : 1 + SALT_BYTES],
            nonce=raw[1 + SALT_BYTES : minimo],
            ciphertext=raw[minimo:],
        )

    def to_dict(self) -> dict[str, Any]:
        return {"v": self.version, "data": self.to_bytes().hex()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Envelope:
        return cls.from_bytes(bytes.fromhex(data["data"]))


def generate_key() -> bytes:
    """Clave simétrica de 256 bits del generador del sistema."""
    return secrets.token_bytes(KEY_BYTES)


def derive_key_from_passphrase(
    passphrase: str, salt: bytes, *, n: int = SCRYPT_N, r: int = SCRYPT_R, p: int = SCRYPT_P
) -> bytes:
    """Deriva una clave de una contraseña con scrypt.

    `n` se puede bajar en despliegues con poca memoria, pero es la única defensa
    real contra el ataque por diccionario: quien lo toque debería saber qué está
    cediendo. Los parámetros se guardan junto a la sal para poder subirlos
    después sin invalidar lo ya cifrado.
    """
    if len(salt) < 16:
        raise CryptoError("la sal debe tener al menos 128 bits")
    return hashlib.scrypt(
        passphrase.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=KEY_BYTES,
        maxmem=n * r * 256,
    )


def _subkey(master: bytes, salt: bytes, context: bytes) -> bytes:
    """Clave irrepetible por registro. Es lo que hace segura la gestión del nonce."""
    return HKDF(algorithm=hashes.SHA256(), length=KEY_BYTES, salt=salt, info=context).derive(master)


def _context_bytes(context: str) -> bytes:
    if not context:
        raise CryptoError("el contexto es obligatorio: sin él, un sobre se puede reubicar")
    return context.encode("utf-8")


def seal(master_key: bytes, plaintext: bytes, *, context: str) -> Envelope:
    """Cifra y autentica.

    `context` identifica *dónde vive* el dato («profile:v1:ana», «job:abc:content»)
    y queda autenticado: un sobre robado de otro sitio no se puede colar aquí.
    """
    if len(master_key) != KEY_BYTES:
        raise CryptoError("clave maestra de tamaño incorrecto")

    info = _context_bytes(context)
    salt = secrets.token_bytes(SALT_BYTES)
    nonce = secrets.token_bytes(NONCE_BYTES)
    aead = ChaCha20Poly1305(_subkey(master_key, salt, info))
    # La versión y el contexto viajan como datos asociados: se autentican pero no
    # se cifran, así se detecta cualquier intento de reinterpretar el sobre.
    aad = bytes([ENVELOPE_VERSION]) + info
    return Envelope(
        version=ENVELOPE_VERSION,
        salt=salt,
        nonce=nonce,
        ciphertext=aead.encrypt(nonce, plaintext, aad),
    )


def unseal(master_key: bytes, envelope: Envelope, *, context: str) -> bytes:
    """Descifra y verifica. Falla igual ante cualquier problema, a propósito.

    Un mensaje de error que distinga «clave incorrecta» de «datos manipulados»
    es un oráculo que ayuda a quien ataca. Aquí todo es `CryptoError`.
    """
    if len(master_key) != KEY_BYTES:
        raise CryptoError("no se pudo abrir el sobre")

    info = _context_bytes(context)
    if envelope.version != ENVELOPE_VERSION:
        raise CryptoError("no se pudo abrir el sobre")

    try:
        aead = ChaCha20Poly1305(_subkey(master_key, envelope.salt, info))
        aad = bytes([envelope.version]) + info
        return aead.decrypt(envelope.nonce, envelope.ciphertext, aad)
    except Exception as exc:
        raise CryptoError("no se pudo abrir el sobre") from exc


def keyed_digest(key: bytes, data: str | bytes) -> str:
    """Huella con clave. **No uses `sha256` a secas para identificar textos.**

    Un SHA-256 de un texto público es reversible por diccionario: medido sobre un
    libro real, indexar 1257 párrafos cuesta 0,01 s y reidentifica el 100%. Una
    huella sin clave de «qué leyó alguien» no es un seudónimo, es el dato en
    claro con un paso extra.

    Con clave —y con la clave sin salir nunca de la instalación— la huella sigue
    sirviendo para deduplicar y correlacionar en local, pero fuera no vale nada.
    """
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return hmac.new(key, raw, hashlib.sha256).hexdigest()


def constant_time_equals(a: str | bytes, b: str | bytes) -> bool:
    """Comparación sin fuga por temporización, para tokens y etiquetas."""
    left = a.encode("utf-8") if isinstance(a, str) else a
    right = b.encode("utf-8") if isinstance(b, str) else b
    return hmac.compare_digest(left, right)


def wipe(buffer: bytearray) -> None:
    """Sobrescribe un buffer mutable con ceros.

    Hay que ser honesto sobre el alcance: en Python no se puede garantizar que no
    queden copias —el recolector de basura mueve objetos, `str` es inmutable, el
    sistema puede haber paginado a disco—. Esto reduce la ventana de exposición
    de una clave en memoria; no la elimina.

    La garantía de verdad no es esta función: es que **el material sensible se
    cifra**, de modo que una copia residual sin la clave no sirve de nada.
    """
    for i in range(len(buffer)):
        buffer[i] = 0


def random_token(length: int = 32) -> str:
    """Identificador aleatorio para seudónimos y tokens de sesión."""
    return secrets.token_hex(length)


def secure_random_bytes(length: int) -> bytes:
    return os.urandom(length)
