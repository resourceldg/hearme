"""Privacidad, seguridad y confianza. Por diseño y por defecto.

El principio que ordena todo el módulo: **el sistema no debería poder traicionar
a quien lo usa aunque quisiera.** No «promete no mirar»: se organiza de forma que
mirar exija una clave que solo tiene la persona.

## Las piezas

| Módulo | Responsabilidad |
|---|---|
| `crypto` | AEAD con subclave por registro, KDF memoria-dura, huella con clave |
| `keys` | Jerarquía de claves: rotar la contraseña sin recifrar nada |
| `vault` | Almacén cifrado con separación estricta contenido/metadatos |
| `session` | Sesión privada: clave solo en memoria, sin rastro al cerrar |
| `shredder` | Borrado de temporales, con honestidad sobre sus límites |
| `audit` | Cadena de hashes a prueba de manipulación y explicación de decisiones |
| `profile` | ADN de narración: personal, cifrado, portable entre motores |
| `sandbox` | Confianza cero para plugins: capacidades declaradas y concedidas |
| `gdpr` | Derechos ejercitables, no una política de privacidad |

## Lo que este módulo NO promete

Se enumera aquí porque un inventario de garantías sin sus límites es propaganda:

- **No protege frente a quien controla la máquina** mientras la sesión está
  abierta. Nada que se ejecute en un sistema ajeno puede prometerlo.
- **No aísla plugins de verdad.** En el mismo proceso de Python es imposible; ver
  el encabezado de `sandbox`.
- **No garantiza el borrado físico** en SSD ni en sistemas copy-on-write. Por eso
  la garantía real es criptográfica: destruir la clave, no sobrescribir bytes.
- **No oculta que el servicio se está usando.** Los tiempos y el consumo de
  recursos son observables para quien administre el sistema.
"""

from hearme.privacy.audit import AuditLog, Decision, EventKind
from hearme.privacy.crypto import CryptoError, Envelope, keyed_digest, seal, unseal
from hearme.privacy.gdpr import (
    ConsentLedger,
    ConsentPurpose,
    ConsentRequired,
    DataSubjectRights,
    require_consent,
)
from hearme.privacy.keys import Keyring, Locked
from hearme.privacy.profile import ReadingDNA, RoleAdjustment
from hearme.privacy.sandbox import (
    Capability,
    CapabilityDenied,
    PluginGuard,
    PluginManifest,
    TrustPolicy,
    minimal_policy,
)
from hearme.privacy.session import PrivateSession, SessionTrace
from hearme.privacy.shredder import shred, shred_tree
from hearme.privacy.vault import Sensitivity, Vault, coarsen_time, size_bucket

__all__ = [
    "AuditLog",
    "Capability",
    "CapabilityDenied",
    "ConsentLedger",
    "ConsentPurpose",
    "ConsentRequired",
    "CryptoError",
    "DataSubjectRights",
    "Decision",
    "Envelope",
    "EventKind",
    "Keyring",
    "Locked",
    "PluginGuard",
    "PluginManifest",
    "PrivateSession",
    "ReadingDNA",
    "RoleAdjustment",
    "Sensitivity",
    "SessionTrace",
    "TrustPolicy",
    "Vault",
    "coarsen_time",
    "keyed_digest",
    "minimal_policy",
    "require_consent",
    "seal",
    "shred",
    "shred_tree",
    "size_bucket",
    "unseal",
]
