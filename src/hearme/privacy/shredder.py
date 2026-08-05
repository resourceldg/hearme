"""Borrado de temporales, y por qué sobrescribir no basta.

## La verdad incómoda sobre el «borrado seguro»

La receta clásica —sobrescribir el archivo con ceros o con ruido antes de
borrarlo— viene de los discos magnéticos, donde el sector físico que se
sobrescribe es el mismo que contenía el dato. En el almacenamiento actual eso
casi nunca es cierto:

- **SSD y memoria flash** reparten la escritura entre celdas para igualar el
  desgaste. Sobrescribir un archivo escribe en celdas *distintas*; las originales
  siguen ahí, marcadas como libres, hasta que el controlador decida limpiarlas.
  El sistema operativo no puede forzarlo.
- **Sistemas de archivos copy-on-write** (Btrfs, ZFS, APFS) escriben siempre en
  bloques nuevos por diseño. La versión anterior sobrevive hasta que se recoge, y
  cualquier instantánea la conserva indefinidamente.
- **Journaling, caché de página y swap** pueden haber copiado el dato a sitios
  que ninguna aplicación controla.

Quien afirme «borrado seguro garantizado» en este contexto, o no lo sabe o está
vendiendo algo.

## Lo que sí funciona: borrado criptográfico

Si el dato **nunca se escribió en claro**, borrarlo es destruir su clave. La
clave son 32 bytes que viven en memoria y, si acaso, en un archivo diminuto que
sí se puede sobrescribir con garantías razonables. Sin ella, los restos en las
celdas del SSD son ruido.

Por eso el orden de este módulo es:

1. **Que no haya nada que borrar.** Los temporales sensibles se escriben ya
   cifrados con la clave de sesión (ver `session`).
2. **Destruir la clave.** Instantáneo y efectivo, con independencia del
   almacenamiento.
3. **Sobrescribir igualmente.** Defensa en profundidad, no la garantía. Cuesta
   poco y ayuda si algo se escapó al paso 1.

`shred()` implementa el paso 3 y **declara con honestidad lo que ha conseguido**,
en vez de devolver un `True` tranquilizador.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from hearme.privacy.crypto import secure_random_bytes

logger = logging.getLogger(__name__)

#: Una sola pasada de ruido. Las «siete pasadas» son folclore heredado de los
#: discos magnéticos: en flash, siete pasadas solo desgastan siete veces más
#: celdas y no aumentan la garantía en absoluto.
OVERWRITE_PASSES = 1

CHUNK = 1 << 20


class ShredResult(StrEnum):
    """Qué se consiguió de verdad. La honestidad es parte de la garantía."""

    #: Sobrescrito y desenlazado. Efectivo en disco magnético; en flash, parcial.
    OVERWRITTEN = "overwritten"
    #: Desenlazado sin sobrescribir (no se pudo abrir para escritura).
    UNLINKED = "unlinked"
    #: No existía.
    ABSENT = "absent"
    #: Falló. Quien llama debe decidir qué hacer.
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ShredReport:
    result: ShredResult
    path: str
    bytes_overwritten: int = 0
    detail: str = ""

    @property
    def is_cryptographically_final(self) -> bool:
        """¿Es este borrado una garantía real?

        Siempre False: sobrescribir nunca lo es en almacenamiento moderno. Existe
        para que ningún módulo pueda confundirse leyendo un `True` optimista.
        La garantía la da destruir la clave, no esta función.
        """
        return False


def shred(path: Path, *, passes: int = OVERWRITE_PASSES) -> ShredReport:
    """Sobrescribe y borra un archivo. Defensa en profundidad, no garantía."""
    if not path.exists():
        return ShredReport(ShredResult.ABSENT, str(path))
    if path.is_dir():
        raise IsADirectoryError(f"{path} es un directorio; usa shred_tree()")

    escritos = 0
    try:
        size = path.stat().st_size
        with path.open("r+b", buffering=0) as handle:
            for _ in range(max(1, passes)):
                handle.seek(0)
                restante = size
                while restante > 0:
                    bloque = min(CHUNK, restante)
                    handle.write(secure_random_bytes(bloque))
                    restante -= bloque
                    escritos += bloque
                handle.flush()
                # Sin fsync, el sobrescrito puede quedarse en la caché de página
                # y no llegar nunca al soporte antes de que se libere el bloque.
                os.fsync(handle.fileno())
    except OSError as exc:
        try:
            path.unlink()
            return ShredReport(
                ShredResult.UNLINKED, str(path), 0, f"no se pudo sobrescribir: {exc}"
            )
        except OSError as unlink_exc:
            return ShredReport(ShredResult.FAILED, str(path), 0, str(unlink_exc))

    try:
        path.unlink()
    except OSError as exc:
        return ShredReport(ShredResult.FAILED, str(path), escritos, str(exc))

    return ShredReport(ShredResult.OVERWRITTEN, str(path), escritos)


def shred_tree(root: Path, *, passes: int = OVERWRITE_PASSES) -> list[ShredReport]:
    """Aplica `shred` a todo un árbol y elimina los directorios vacíos."""
    if not root.exists():
        return [ShredReport(ShredResult.ABSENT, str(root))]

    informes: list[ShredReport] = []
    for hijo in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if hijo.is_file() or hijo.is_symlink():
            informes.append(shred(hijo, passes=passes))
    shutil.rmtree(root, ignore_errors=True)
    return informes


def summarize(reports: list[ShredReport]) -> str:
    """Resumen para el registro de auditoría, sin nombres de archivo.

    Los nombres son contenido: «memorias-de-mi-diagnostico.pdf» dice tanto como
    el propio documento. Un registro de borrados que los guarde deshace el borrado.
    """
    total = len(reports)
    fallos = sum(1 for r in reports if r.result is ShredResult.FAILED)
    bytes_totales = sum(r.bytes_overwritten for r in reports)
    return f"{total} archivo(s), {bytes_totales} bytes sobrescritos, {fallos} fallo(s)"
