"""Community Knowledge Network: se comparte conocimiento, nunca datos.

La red comunitaria y el módulo de privacidad no son dos cosas en tensión que haya
que equilibrar. Son la misma decisión mirada desde dos lados:

  **privacy/**    lo que es de una persona: cifrado, local, suyo.
  **knowledge/**  lo que no es de nadie: reglas generalizadas, públicas, de todos.

La frontera entre ambos es explícita y estrecha. Solo se cruza en un sentido, con
consentimiento expreso, y solo la atraviesan afirmaciones lingüísticas que ya no
contienen ni obras ni identidades.

| Módulo | Responsabilidad |
|---|---|
| `knowledge` | Reglas generalizadas, umbral de k contribuyentes, ruido diferencial |
| `review` | Historial, justificación obligatoria y reversión en una operación |
| `lab` | Laboratorio y benchmark: solo textos públicos o sintéticos |

## Lo que nunca sale de una instalación

No es una lista de buenas intenciones: cada punto está impedido por código y
cubierto por un test.

- El texto de un documento, o cualquier fragmento suyo.
- Un identificador de un texto —ni siquiera su hash: es reversible.
- El léxico personal: el vocabulario delata oficio, salud y procedencia.
- Los seudónimos de quien apoya cada regla.
- Cualquier regla que no respalden al menos `K_ANONYMITY` personas distintas.
"""

from hearme.knowledge.knowledge import (
    K_ANONYMITY,
    Effect,
    KnowledgeBase,
    KnowledgeError,
    NarrationRule,
    RuleKind,
    Trigger,
    TriggerType,
    dp_noise,
    extract_shareable,
    merge_effects,
)
from hearme.knowledge.lab import (
    BenchmarkItem,
    LabError,
    NarrationBenchmark,
    NarrationLab,
    Provenance,
    TextSource,
)
from hearme.knowledge.review import (
    ChangeType,
    ReviewedKnowledge,
    ReviewError,
    ReviewLedger,
)

__all__ = [
    "K_ANONYMITY",
    "BenchmarkItem",
    "ChangeType",
    "Effect",
    "KnowledgeBase",
    "KnowledgeError",
    "LabError",
    "NarrationBenchmark",
    "NarrationLab",
    "NarrationRule",
    "Provenance",
    "ReviewError",
    "ReviewLedger",
    "ReviewedKnowledge",
    "RuleKind",
    "TextSource",
    "Trigger",
    "TriggerType",
    "dp_noise",
    "extract_shareable",
    "merge_effects",
]
