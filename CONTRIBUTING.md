# Contribuir a HearMe

Gracias por estar aquí.

Este proyecto no lo sostiene quien programa. Lo sostiene quien escucha un
capítulo y dice «esta pausa está mal», quien prueba la interfaz con un lector de
pantalla, quien traduce la interfaz a su lengua, quien conoce a las personas para
las que esto existe. **El código es la parte fácil.**

## Cómo aportar sin escribir código

### Mejorar cómo suena (la aportación más valiosa)

| Vía | Qué implica | Tiempo |
| --- | --- | --- |
| **Preferencia** | Escuchas dos versiones del mismo pasaje y eliges la mejor | 10 segundos |
| **Corrección** | Señalas una pausa que falta, un énfasis mal puesto, un nombre mal pronunciado | 1 minuto |
| **Lectura de referencia** | Narras un pasaje y se extrae su prosodia, no tu voz. *Aún no disponible: faltan los términos de cesión* | 10 minutos |

No hace falta saber fonética. La vía de preferencia está diseñada justo para eso:
si aportar exigiera conocimientos previos, solo aportaría quien ya los tiene y el
corpus acabaría reflejando sus sesgos.

Cómo se validan y qué pasa después: [Community Narration
Training](docs/COMMUNITY-NARRATION-TRAINING.md).

### Probar con tecnología de asistencia

Lo que más nos falta, con diferencia. Si usas lector de pantalla (NVDA, JAWS,
Narrator, VoiceOver, TalkBack, Orca), magnificador, navegación por conmutador o
control por voz: cuéntanos qué falla con lo tuyo. Ninguna combinación está
validada todavía, y así consta en la matriz de
[docs/ASSISTIVE-TECHNOLOGY.md](docs/ASSISTIVE-TECHNOLOGY.md).

**Elige tú qué recibes** —crédito, voz en las decisiones, prioridad, o nada— en
[docs/ASSISTIVE-TECHNOLOGY.md](docs/ASSISTIVE-TECHNOLOGY.md).

También sirve —y mucho— contar simplemente qué falló, sin comprometerse a nada
más.

Abre una incidencia con la etiqueta `accesibilidad` y describe la situación
concreta: qué se intentaba hacer, con qué apoyo técnico, qué pasó.

### Añadir un idioma

Necesitamos hablantes, no lingüistas. Hace falta:

1. Comprobar si hay un motor de voz libre para esa lengua.
2. Revisar cómo se trocean las frases (las abreviaturas y la puntuación cambian
   mucho entre lenguas).
3. Escuchar y corregir las primeras narraciones.

Abre una incidencia con la etiqueta `idioma` y lo vemos juntos.

### Documentación y traducción

La documentación está en español. Traducirla —empezando por este archivo y el
README— abre el proyecto a comunidades enteras. También vale corregir una
explicación que no se entiende: si te costó, le costará a quien venga detrás.

## Cómo aportar código

### Montar el entorno

```bash
git clone https://github.com/resourceldg/hearme
cd hearme
uv sync --extra documents --extra tts-piper --extra dev
```

### Antes de abrir una propuesta de cambio

```bash
uv run pytest              # todo debe pasar
uv run ruff check src tests
uv run mypy src
cd web && npm run check    # si tocaste la interfaz
```

### Qué esperamos de un cambio

- **Que explique el porqué, no el qué.** El código ya dice lo que hace. Los
  comentarios de este proyecto explican por qué se eligió así y qué alternativa
  se descartó. Mantén ese tono.
- **Una prueba que falle sin tu arreglo.** Si corriges un error, la prueba debe
  fallar en la versión anterior. Si no falla, no está probando el arreglo.
- **Accesibilidad desde el principio.** Contraste, navegación por teclado,
  etiquetas para lectores de pantalla, `prefers-reduced-motion`. No es una fase
  posterior.
- **Sin ataduras nuevas.** Antes de añadir una dependencia, mira
  [ANALISIS-COMPARATIVO.md](docs/ANALISIS-COMPARATIVO.md): cada una está ahí por
  un motivo medido y con su licencia revisada.

### Licencias

Tu aportación queda bajo **Apache-2.0** —lo dice la propia licencia, sin CLA que
firmar— y las del corpus bajo **CC0**. Conservas tu copyright.

El núcleo solo admite dependencias con licencia permisiva: nada de GPL ni AGPL
en el camino de ejecución. No es purismo, es que una biblioteca pública tiene
que poder desplegar esto sin pasar por su departamento jurídico.

El mapa completo, incluidas las preguntas incómodas, está en
[docs/LICENSING.md](docs/LICENSING.md).

### El idioma del código

Comentarios y documentación en español; identificadores y API en inglés. Es lo
que hay hoy en el repositorio y la coherencia importa más que la preferencia
personal. Si algún día la comunidad decide cambiarlo, se cambia entero.

## Cómo se decide

Las discusiones de diseño van en incidencias públicas antes que en el código.
Los cambios que afectan al formato de la partitura o a las reglas de validación
del corpus necesitan una ADR en `docs/adr/` — son las decisiones caras de
revertir.

Quién decide qué y cómo se resuelven los desacuerdos: [GOVERNANCE.md](GOVERNANCE.md).

## Convivencia

Se aplica el [código de conducta](CODE_OF_CONDUCT.md) en todos los espacios del
proyecto. Léelo: es corto y va en serio.

## Primeras contribuciones

Las incidencias con la etiqueta `primera-contribución` están descritas con el
contexto suficiente para empezar sin conocer el proyecto entero. Si te atascas,
pregunta en la incidencia — preguntar pronto no molesta a nadie.
