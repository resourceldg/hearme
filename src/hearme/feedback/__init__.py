"""Retroalimentación humana: cada estrella enseña a narrar mejor.

El circuito completo, y por qué cada pieza está donde está:

```
  alguien escucha
        ↓
  ★★★★☆ · 👍 · «va muy rápido pero se entiende bien»
        ↓  signals.extract_tags — léxico, explicable, sin nube
  {too_fast, clear}  + el comentario original, conservado
        ↓  reputation.ReputationIndex — media bayesiana, cota de Wilson
  reputación por (motor, voz, estilo, idioma)
        ↓  reputation.suggest_adjustment
  «el 40% dice que va rápido» → rate_scale 0.9
        ↓
  la partitura del director, que es neutra respecto al motor
```

Es aprendizaje por preferencias aplicado a **la interpretación**, no a la
generación: no se reentrena ninguna voz, se aprende cómo dirigirla. Por eso lo
aprendido sobrevive al cambio de motor, que es la tesis del proyecto entero.

## Las tres reglas que lo hacen fiable

**Nada se aplica solo.** Un ajuste sugerido es una propuesta con su motivo
visible; quien escucha puede ignorarla o cambiarla. La diferencia entre asistir
y decidir por alguien está justo ahí.

**Pocos votos no mandan.** La media bayesiana encoge hacia la media mientras hay
poca evidencia, y hay un tope de valoraciones por persona y sujeto. Sin eso, las
primeras semanas del proyecto serían un sorteo.

**Todo es interrogable.** Cada puntuación dice de qué está hecha y cada etiqueta
guarda el fragmento que la produjo. Una recomendación que no se puede auditar es
una imposición con buenos modales.
"""

from hearme.feedback.reputation import (
    CONFIDENT_SAMPLE,
    MAX_PER_CONTRIBUTOR,
    PRIOR_MEAN,
    PRIOR_WEIGHT,
    Reputation,
    ReputationIndex,
    TagSummary,
    bayesian_average,
    suggest_adjustment,
    wilson_lower_bound,
)
from hearme.feedback.signals import (
    Feedback,
    Sentiment,
    Subject,
    Tag,
    TagMatch,
    extract_tags,
    normalize,
)

__all__ = [
    "CONFIDENT_SAMPLE",
    "MAX_PER_CONTRIBUTOR",
    "PRIOR_MEAN",
    "PRIOR_WEIGHT",
    "Feedback",
    "Reputation",
    "ReputationIndex",
    "Sentiment",
    "Subject",
    "Tag",
    "TagMatch",
    "TagSummary",
    "bayesian_average",
    "extract_tags",
    "normalize",
    "suggest_adjustment",
    "wilson_lower_bound",
]
