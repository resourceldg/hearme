"""Narration Knowledge: lo único que sale de una instalación.

## El cambio respecto al diseño anterior

La primera versión del corpus comunitario compartía anotaciones por texto,
indexadas por `sha256` del párrafo, con el argumento de que así no se
redistribuían las obras. Era cierto pero insuficiente: **un hash sin clave de un
texto público es reversible por diccionario**. Medido sobre un libro real,
indexar 1257 párrafos cuesta 0,01 s y reidentifica el 100%. Compartir esos hashes
equivale a publicar la lista de lo que alguien lee.

La corrección no es cifrar el hash. Es no compartir nada ligado a un texto.

Lo que se comparte aquí son **reglas generalizadas**: «en español, tras un
conector adversativo a mitad de párrafo, la pausa sube un 30%». Esa frase no
contiene ninguna obra, no se puede asociar a ninguna persona y sigue siendo útil
para todo el mundo. Es conocimiento, no datos.

## Por qué esto es más privado que el aprendizaje federado

El federado no comparte datos crudos, comparte gradientes. Pero los gradientes
filtran: hay una literatura consolidada sobre inversión de gradientes que
reconstruye ejemplos de entrenamiento a partir de las actualizaciones, y por eso
hace falta añadirle privacidad diferencial y agregación segura para que sea
defendible.

Una regla generalizada **no tiene esa superficie**. No es un residuo del
entrenamiento del que se pueda extraer nada: es una afirmación lingüística
legible por una persona, que se puede leer, discutir y rechazar antes de
publicarla. Compartir conocimiento explícito es estrictamente más privado que
compartir gradientes, y además es auditable, que los gradientes no lo son.

## Anonimato del conjunto, no del envío

La defensa principal no es criptográfica: es el **umbral de k contribuyentes**.
Una regla solo se publica si la han propuesto o confirmado, de forma
independiente, al menos `K_ANONYMITY` personas distintas. Una regla que solo
propone alguien podría reflejar su idiolecto —o su obra rara— y es justo la que
podría señalarle. Con k personas detrás, la regla ya no es de nadie.

Sobre eso se añade ruido de privacidad diferencial a los recuentos publicados;
ver `dp_noise` y su honesta advertencia sobre comunidades pequeñas.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass, field, fields, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

KNOWLEDGE_VERSION = "1.0"

#: Contribuyentes independientes mínimos para publicar una regla. Cuatro es un
#: compromiso: con dos, dos cuentas coordinadas publican lo que quieran; con
#: diez, ningún idioma pequeño llegaría nunca a tener reglas.
K_ANONYMITY = 4


class RuleKind(StrEnum):
    """Qué tipo de conocimiento captura una regla."""

    PAUSE = "pause"
    EMPHASIS = "emphasis"
    RATE = "rate"
    PRONUNCIATION = "pronunciation"
    ROLE = "role"  # reconocer diálogo, inciso, cita


class TriggerType(StrEnum):
    """Sobre qué se dispara la regla. Todos son categorías lingüísticas.

    Ninguno admite texto libre de una obra: el disparador describe una *clase* de
    contexto, nunca un pasaje. Es lo que hace que la regla no pueda llevar
    contenido dentro.
    """

    #: Categoría gramatical: "conector_adversativo", "vocativo", "subordinada".
    SYNTACTIC = "syntactic"
    #: Signo o patrón tipográfico: "raya_dialogo", "dos_puntos", "parentesis".
    PUNCTUATION = "punctuation"
    #: Posición estructural: "fin_de_parrafo", "inicio_de_capitulo".
    STRUCTURAL = "structural"
    #: Rol narrativo, tal como lo define `narration.score.SpanRole`.
    ROLE_CONTEXT = "role_context"
    #: Un lema aislado y su pronunciación. Ver la validación de `Trigger`.
    LEXICAL = "lexical"


#: Longitud máxima de un disparador léxico. Una palabra o un nombre propio
#: compuesto caben; una frase de una obra, no. Es el cortafuegos que impide
#: colar texto por el único campo que admite palabras concretas.
MAX_LEXICAL_CHARS = 40


class KnowledgeError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Trigger:
    """La condición de una regla. Validada para que no pueda contener una obra."""

    type: TriggerType
    #: Identificador de la categoría, o el lema si es LEXICAL.
    value: str
    language: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise KnowledgeError("el disparador no puede estar vacío")

        if self.type is TriggerType.LEXICAL:
            if len(self.value) > MAX_LEXICAL_CHARS:
                raise KnowledgeError(
                    f"un disparador léxico no puede exceder {MAX_LEXICAL_CHARS} caracteres: "
                    "sería un fragmento de obra, no una palabra"
                )
            if len(self.value.split()) > 4:
                raise KnowledgeError(
                    "un disparador léxico admite como mucho cuatro palabras: "
                    "más de eso deja de ser un lema y pasa a ser una cita"
                )
        elif not self.value.replace("_", "").isalnum():
            raise KnowledgeError(
                f"'{self.value}' no es un identificador de categoría; "
                "los disparadores no léxicos son categorías lingüísticas, no texto"
            )

    @property
    def id(self) -> str:
        return f"{self.language}:{self.type.value}:{self.value}"


@dataclass(frozen=True, slots=True)
class Effect:
    """Qué hace la regla. Multiplicadores relativos, nunca valores absolutos.

    Relativos por la misma razón que en el ADN personal: una regla que fijase
    «pausa de 520 ms» quedaría obsoleta al mejorar el director base. Un ×1,3
    sigue significando lo mismo dentro de diez versiones.
    """

    pause_scale: float | None = None
    emphasis_scale: float | None = None
    rate_scale: float | None = None
    #: Solo para RuleKind.PRONUNCIATION: transcripción fonética o forma hablada.
    pronunciation: str | None = None
    #: Solo para RuleKind.ROLE: el rol que se asigna.
    role: str | None = None

    def to_dict(self) -> dict[str, Any]:
        # `fields()` y no `__dict__`: con slots=True no existe __dict__.
        # Se omiten los nulos para que el corpus no se llene de campos vacíos.
        return {
            f.name: getattr(self, f.name) for f in fields(self) if getattr(self, f.name) is not None
        }


@dataclass(slots=True)
class NarrationRule:
    """Una unidad de conocimiento narrativo. Publicable, discutible, reversible."""

    id: str
    kind: RuleKind
    trigger: Trigger
    effect: Effect
    #: Por qué esta regla es correcta, en lenguaje llano. Obligatorio: una regla
    #: sin justificación no se puede revisar, solo acatar.
    rationale: str
    #: Seudónimos de quien la ha propuesto o confirmado de forma independiente.
    #: Solo el recuento se publica; los seudónimos se quedan en el servicio.
    supporters: set[str] = field(default_factory=set)
    disputes: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1
    #: Regla que esta sustituye. Es lo que permite revertir con exactitud.
    supersedes: str | None = None

    def __post_init__(self) -> None:
        if not self.rationale.strip():
            raise KnowledgeError("una regla sin justificación no es revisable")

    @property
    def support(self) -> int:
        return len(self.supporters)

    @property
    def is_publishable(self) -> bool:
        """¿Hay suficientes personas detrás para que la regla no señale a ninguna?"""
        return self.support >= K_ANONYMITY

    @property
    def confidence(self) -> float:
        """Apoyo frente a disputa, saturando con el número de contribuyentes."""
        total = self.support + self.disputes
        if total == 0:
            return 0.0
        # El factor logarítmico impide que 3-de-3 parezca más sólido que 40-de-45.
        proporcion = self.support / total
        madurez = min(1.0, math.log1p(total) / math.log1p(20))
        return round(proporcion * madurez, 4)

    def add_support(self, contributor: str) -> None:
        self.supporters.add(contributor)

    def to_public_dict(self) -> dict[str, Any]:
        """Forma publicable. **Sin seudónimos**, solo el recuento.

        Publicar quién apoya cada regla permitiría perfilar a las personas por el
        conjunto de reglas que respaldan, que es un identificador tan bueno como
        cualquier otro.
        """
        return {
            "id": self.id,
            "kind": self.kind.value,
            "trigger": {
                "type": self.trigger.type.value,
                "value": self.trigger.value,
                "language": self.trigger.language,
            },
            "effect": self.effect.to_dict(),
            "rationale": self.rationale,
            "support": self.support,
            "disputes": self.disputes,
            "confidence": self.confidence,
            "version": self.version,
            "supersedes": self.supersedes,
            "created_at": self.created_at.isoformat(),
        }


def rule_id(trigger: Trigger, kind: RuleKind) -> str:
    """Identificador determinista: la misma regla propuesta dos veces converge.

    Es lo que permite que las aportaciones independientes se acumulen sobre la
    misma regla en vez de crear duplicados que nunca alcanzarían el umbral k.
    """
    return hashlib.sha256(f"{kind.value}|{trigger.id}".encode()).hexdigest()[:16]


def dp_noise(count: int, *, epsilon: float = 1.0, rng: random.Random | None = None) -> int:
    """Ruido de Laplace sobre un recuento publicado.

    Protege frente a un ataque concreto: observar cómo cambia el recuento de
    apoyos de una regla entre dos publicaciones revela que *alguien* la apoyó en
    ese intervalo. Con pocas personas activas, eso puede bastar para señalarla.

    **Advertencia honesta:** con `epsilon=1.0` el ruido tiene desviación ~1,4. En
    una regla con 500 apoyos es despreciable; en una con 5 es la mitad del valor.
    Justo donde más falta hace la protección, más destroza la utilidad.

    Por eso la privacidad diferencial aquí es **secundaria**. La defensa principal
    es el umbral de k contribuyentes, que es comprensible sin saber estadística y
    no degrada nada. El ruido se añade encima, no en su lugar.
    """
    if epsilon <= 0:
        raise KnowledgeError("epsilon debe ser positivo")
    generador = rng or random.SystemRandom()
    # Laplace por diferencia de dos exponenciales; sensibilidad 1 (una persona
    # cambia el recuento en 1 como mucho).
    escala = 1.0 / epsilon
    u = generador.random() - 0.5
    ruido = -escala * math.copysign(1.0, u) * math.log(1 - 2 * abs(u))
    return max(0, round(count + ruido))


@dataclass(slots=True)
class KnowledgeBase:
    """Conjunto de reglas de una lengua. Es lo que se publica y lo que se instala."""

    language: str
    version: str = KNOWLEDGE_VERSION
    rules: dict[str, NarrationRule] = field(default_factory=dict)

    def propose(
        self,
        *,
        kind: RuleKind,
        trigger: Trigger,
        effect: Effect,
        rationale: str,
        contributor: str,
    ) -> NarrationRule:
        """Propone una regla, o suma apoyo a una equivalente ya existente."""
        if trigger.language != self.language:
            raise KnowledgeError(
                f"la regla es de '{trigger.language}' y esta base es de '{self.language}'"
            )

        identificador = rule_id(trigger, kind)
        existente = self.rules.get(identificador)
        if existente is not None:
            existente.add_support(contributor)
            return existente

        regla = NarrationRule(
            id=identificador, kind=kind, trigger=trigger, effect=effect, rationale=rationale
        )
        regla.add_support(contributor)
        self.rules[identificador] = regla
        return regla

    def dispute(self, rule_id_: str) -> NarrationRule:
        regla = self._get(rule_id_)
        regla.disputes += 1
        return regla

    def supersede(
        self, rule_id_: str, *, effect: Effect, rationale: str, contributor: str
    ) -> NarrationRule:
        """Sustituye una regla dejando rastro. La anterior no se borra.

        Reemplazar sin dejar constancia haría imposible entender por qué la
        narración cambió, y por tanto imposible revertirlo con criterio.
        """
        anterior = self._get(rule_id_)
        nueva = NarrationRule(
            id=f"{anterior.id}-v{anterior.version + 1}",
            kind=anterior.kind,
            trigger=anterior.trigger,
            effect=effect,
            rationale=rationale,
            version=anterior.version + 1,
            supersedes=anterior.id,
        )
        nueva.add_support(contributor)
        self.rules[nueva.id] = nueva
        return nueva

    def publishable(self, *, epsilon: float | None = None) -> list[dict[str, Any]]:
        """Reglas que superan el umbral k, listas para publicar.

        Con `epsilon`, los recuentos salen con ruido diferencial. Sin él, en
        crudo: es la opción por defecto porque el umbral k ya protege y el ruido
        confunde a quien lee la publicación.
        """
        salida = []
        for regla in self.rules.values():
            if not regla.is_publishable:
                continue
            publica = regla.to_public_dict()
            if epsilon is not None:
                publica["support"] = dp_noise(regla.support, epsilon=epsilon)
                publica["disputes"] = dp_noise(regla.disputes, epsilon=epsilon)
                publica["noised"] = True
            salida.append(publica)
        return sorted(salida, key=lambda r: r["confidence"], reverse=True)

    def withheld(self) -> list[str]:
        """Reglas retenidas por no llegar al umbral. Transparencia sobre lo omitido."""
        return [r.id for r in self.rules.values() if not r.is_publishable]

    def _get(self, rule_id_: str) -> NarrationRule:
        regla = self.rules.get(rule_id_)
        if regla is None:
            raise KnowledgeError(f"no existe la regla '{rule_id_}'")
        return regla

    def to_json(self, *, epsilon: float | None = None) -> str:
        return json.dumps(
            {
                "format": "hearme.knowledge.v1",
                "language": self.language,
                "version": self.version,
                "k_anonymity": K_ANONYMITY,
                "published_at": datetime.now(UTC).isoformat(),
                "rules": self.publishable(epsilon=epsilon),
                "withheld_count": len(self.withheld()),
            },
            ensure_ascii=False,
            indent=2,
        )


def extract_shareable(dna: Any, *, contributor: str, language: str) -> list[tuple[Trigger, Effect]]:
    """Deriva reglas candidatas de un ADN personal, descartando lo identificativo.

    **El léxico nunca se extrae.** El vocabulario de alguien —los nombres propios
    que corrige, los tecnicismos de su oficio, los topónimos de su tierra— es de
    lo más identificativo que existe. Un conjunto de pronunciaciones corregidas
    puede señalar la profesión, la salud y la procedencia de una persona.

    Solo salen los ajustes por rol narrativo, que son afirmaciones sobre cómo se
    lee un diálogo o un encabezado, no sobre quién lo lee.
    """
    candidatas: list[tuple[Trigger, Effect]] = []
    for rol, ajuste in dna.by_role.items():
        # Sin observaciones suficientes, el ajuste es ruido de una persona, no
        # una regla: contribuirlo solo aportaría su idiosincrasia.
        if ajuste.observations < 5:
            continue
        # Desviaciones minúsculas no son conocimiento; son deriva.
        if abs(ajuste.pause_scale - 1.0) < 0.1 and abs(ajuste.rate_scale - 1.0) < 0.1:
            continue
        candidatas.append(
            (
                Trigger(type=TriggerType.ROLE_CONTEXT, value=rol, language=language),
                Effect(
                    pause_scale=round(ajuste.pause_scale, 2),
                    rate_scale=round(ajuste.rate_scale, 2),
                ),
            )
        )
    return candidatas


def merge_effects(rules: list[NarrationRule]) -> Effect:
    """Combina reglas aplicables ponderando por confianza."""
    if not rules:
        return Effect()

    def media(campo: str) -> float | None:
        valores = [
            (getattr(r.effect, campo), r.confidence)
            for r in rules
            if getattr(r.effect, campo) is not None
        ]
        if not valores:
            return None
        peso = sum(c for _, c in valores)
        if peso == 0:
            return None
        return round(sum(v * c for v, c in valores) / peso, 4)

    return replace(
        Effect(),
        pause_scale=media("pause_scale"),
        emphasis_scale=media("emphasis_scale"),
        rate_scale=media("rate_scale"),
    )
