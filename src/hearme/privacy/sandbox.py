"""Confianza cero para plugins: capacidades declaradas y concedidas.

## Qué garantiza esto y qué no

Hay que empezar por lo incómodo: **en Python no se puede aislar de verdad un
plugin dentro del mismo proceso.** Un plugin cargado por `importlib` puede
importar `os`, recorrer `gc.get_objects()`, parchear cualquier módulo y leer la
memoria del intérprete. Cualquier «sandbox» que se anuncie como barrera de
seguridad dentro del proceso es falso, y ha habido intentos célebres —incluido
el propio `rexec` de la biblioteca estándar— que se retiraron por eso.

Lo que este módulo aporta de verdad:

1. **Declaración obligatoria.** Un plugin dice qué necesita antes de cargarse. Un
   parser que pide red es una señal que se ve *antes* de instalarlo, no después.
2. **Concesión explícita.** Nada por defecto. Sin política que lo permita, no se
   carga. Es la parte «confianza cero»: la pertenencia al registro de plugins no
   otorga ningún permiso.
3. **Rastro auditable.** Cada concesión y cada denegación quedan registradas.
4. **Punto único de aplicación** para cuando el aislamiento sea real: los
   plugins con capacidades peligrosas se ejecutarán en subproceso con seccomp,
   en contenedor o con un intérprete restringido. La arquitectura ya está
   preparada; hoy la aplicación es *advertencia*, no *contención*, y el código lo
   dice en voz alta en vez de fingir lo contrario.

Un modelo de amenaza honesto: esto protege frente a plugins **descuidados** y
hace visible al **malicioso**. No detiene al malicioso decidido dentro del mismo
proceso. Para eso hace falta el paso 4, y está en la hoja de ruta.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum

logger = logging.getLogger(__name__)


class Capability(StrEnum):
    """Lo que un plugin puede pedir. Deliberadamente pocas y gruesas.

    Un catálogo de cincuenta permisos finos no lo lee nadie y se acepta entero.
    Seis categorías que se entienden de un vistazo producen mejores decisiones.
    """

    #: Leer el documento que se está convirtiendo. Lo mínimo de un parser.
    READ_DOCUMENT = "read_document"
    #: Escribir en el directorio de salida del trabajo.
    WRITE_OUTPUT = "write_output"
    #: Salir a la red. **La más peligrosa**: es la que permite exfiltrar.
    NETWORK = "network"
    #: Lanzar procesos externos (ffmpeg, tesseract).
    SUBPROCESS = "subprocess"
    #: Leer o escribir modelos en caché.
    MODEL_CACHE = "model_cache"
    #: Acceder al perfil de lectura. Prácticamente nunca debería concederse.
    READ_PROFILE = "read_profile"


#: Capacidades que exigen una decisión consciente, nunca una política amplia.
DANGEROUS = frozenset({Capability.NETWORK, Capability.READ_PROFILE, Capability.SUBPROCESS})


class CapabilityDenied(Exception):
    """Un plugin pidió algo que no tiene concedido."""


@dataclass(frozen=True, slots=True)
class PluginManifest:
    """Lo que un plugin declara necesitar. Se inspecciona antes de cargarlo."""

    name: str
    version: str
    capabilities: frozenset[Capability] = frozenset()
    #: Por qué necesita cada capacidad. Obligatorio para las peligrosas: quien
    #: no sepa explicar para qué quiere la red, no debería tenerla.
    justification: dict[str, str] = field(default_factory=dict)

    def validate(self) -> None:
        faltan = [
            c.value
            for c in self.capabilities
            if c in DANGEROUS and not self.justification.get(c.value)
        ]
        if faltan:
            raise CapabilityDenied(
                f"el plugin '{self.name}' pide capacidades peligrosas sin justificar: {faltan}"
            )

    @property
    def risk(self) -> str:
        peligrosas = self.capabilities & DANGEROUS
        if not peligrosas:
            return "bajo"
        if Capability.NETWORK in peligrosas or Capability.READ_PROFILE in peligrosas:
            return "alto"
        return "medio"


@dataclass(slots=True)
class TrustPolicy:
    """Qué se concede. Todo denegado salvo mención expresa.

    `default_allow` no existe a propósito: una política con interruptor de
    «permitir todo» acaba encendido en producción el día que algo falla a las
    once de la noche.
    """

    #: plugin -> capacidades concedidas.
    grants: dict[str, frozenset[Capability]] = field(default_factory=dict)
    #: Nunca se conceden, ni aunque `grants` lo diga. Vale como freno duro para
    #: un despliegue que quiera garantizar, por ejemplo, cero red.
    never: frozenset[Capability] = frozenset()

    def grant(self, plugin: str, *capabilities: Capability) -> None:
        actuales = self.grants.get(plugin, frozenset())
        self.grants[plugin] = actuales | frozenset(capabilities)

    def revoke(self, plugin: str, *capabilities: Capability) -> None:
        actuales = self.grants.get(plugin, frozenset())
        self.grants[plugin] = actuales - frozenset(capabilities)

    def allows(self, plugin: str, capability: Capability) -> bool:
        if capability in self.never:
            return False
        return capability in self.grants.get(plugin, frozenset())


@dataclass(frozen=True, slots=True)
class LoadDecision:
    """Resultado de evaluar un plugin, con motivo legible."""

    allowed: bool
    plugin: str
    granted: frozenset[Capability] = frozenset()
    denied: frozenset[Capability] = frozenset()
    reason: str = ""


class PluginGuard:
    """Evalúa manifiestos contra la política y registra cada decisión."""

    def __init__(self, policy: TrustPolicy, audit_log: object | None = None) -> None:
        self.policy = policy
        self.audit = audit_log

    def evaluate(self, manifest: PluginManifest) -> LoadDecision:
        manifest.validate()

        concedidas = frozenset(
            c for c in manifest.capabilities if self.policy.allows(manifest.name, c)
        )
        denegadas = manifest.capabilities - concedidas

        if denegadas:
            decision = LoadDecision(
                allowed=False,
                plugin=manifest.name,
                granted=concedidas,
                denied=denegadas,
                reason=(
                    f"'{manifest.name}' pide {sorted(c.value for c in denegadas)} "
                    "y la política no lo concede"
                ),
            )
        else:
            decision = LoadDecision(
                allowed=True,
                plugin=manifest.name,
                granted=concedidas,
                reason=(
                    f"todas las capacidades solicitadas están concedidas (riesgo {manifest.risk})"
                ),
            )

        self._record(manifest, decision)
        return decision

    def require(self, plugin: str, capability: Capability) -> None:
        """Comprobación en el punto de uso. Advertencia, no contención.

        Es útil porque atrapa el error honesto —un plugin que hace algo que no
        declaró— y deja rastro. No frena a quien quiera saltárselo dentro del
        mismo proceso; ver el encabezado del módulo.
        """
        if not self.policy.allows(plugin, capability):
            self._deny(plugin, capability)
            raise CapabilityDenied(
                f"'{plugin}' intentó usar '{capability.value}' sin tenerlo concedido"
            )

    # --- auditoría ----------------------------------------------------------

    def _record(self, manifest: PluginManifest, decision: LoadDecision) -> None:
        if self.audit is None:
            return
        from hearme.privacy.audit import Decision, EventKind

        self.audit.append(  # type: ignore[attr-defined]
            EventKind.PLUGIN_LOADED if decision.allowed else EventKind.CAPABILITY_DENIED,
            actor=f"plugin:{manifest.name}",
            detail={"version": manifest.version, "risk": manifest.risk},
            decision=Decision(
                subject="carga_de_plugin",
                outcome="permitido" if decision.allowed else "denegado",
                rationale=decision.reason,
                factors={
                    "solicitadas": sorted(c.value for c in manifest.capabilities),
                    "concedidas": sorted(c.value for c in decision.granted),
                },
                decided_by="TrustPolicy",
            ),
        )

    def _deny(self, plugin: str, capability: Capability) -> None:
        logger.warning("capacidad denegada: %s -> %s", plugin, capability.value)
        if self.audit is None:
            return
        from hearme.privacy.audit import EventKind

        self.audit.append(  # type: ignore[attr-defined]
            EventKind.CAPABILITY_DENIED,
            actor=f"plugin:{plugin}",
            detail={"capability": capability.value},
        )


def minimal_policy() -> TrustPolicy:
    """Política de partida: los plugins internos, con lo justo y nada más.

    Ninguno lleva NETWORK. El de OCR lleva SUBPROCESS porque invoca a `ocrmypdf`,
    y esa es exactamente la clase de dato que debería verse al instalar algo.
    """
    policy = TrustPolicy()
    for parser in ("pdf", "epub", "docx", "odt", "markdown", "text", "html", "rtf"):
        policy.grant(parser, Capability.READ_DOCUMENT)
    policy.grant("ocrmypdf", Capability.READ_DOCUMENT, Capability.SUBPROCESS)
    for engine in ("piper", "kokoro"):
        policy.grant(engine, Capability.MODEL_CACHE, Capability.WRITE_OUTPUT)
    for exporter in ("m4b", "mp3"):
        policy.grant(exporter, Capability.WRITE_OUTPUT, Capability.SUBPROCESS)
    return policy
