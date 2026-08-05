# Community Narration Training

> Cómo la comunidad mejora, de forma continua y acumulativa, la calidad de la
> narración de HearMe — y por qué lo que se entrena no es la voz.

Este documento describe la arquitectura del módulo comunitario: qué se aporta,
cómo se valida, cómo se impide el abuso y cómo llegan las mejoras a lo que la
gente escucha. Es un documento de diseño: las decisiones están razonadas y las
alternativas descartadas también, para que quien discrepe sepa exactamente
contra qué argumenta.

---

## 1. El problema

Una voz sintética suena mal por dos motivos distintos, y conviene no
confundirlos:

**Timbre.** Que la voz suene a persona y no a robot. Aquí el progreso es rápido,
caro y ajeno: lo empujan laboratorios con presupuestos que ninguna comunidad va
a igualar. Cada dieciocho meses aparece un motor claramente mejor.

**Interpretación.** Dónde respirar, qué palabra lleva el peso, cuándo bajar el
ritmo porque el párrafo lo pide, cómo se lee un diálogo frente a una nota al
pie. Aquí el progreso es lento, barato y **profundamente humano**: depende de
criterio, no de cómputo. Un motor de 2026 con la interpretación de un lector de
teleprónter suena peor que un motor de 2021 bien dirigido.

La segunda es la que arruina la escucha de un libro entero, y es justo donde una
comunidad puede aportar algo que ningún laboratorio va a producir: miles de
juicios humanos sobre cómo debe leerse un texto concreto.

## 2. La decisión: se entrena al director, no al motor

**No entrenamos el motor de voz. Entrenamos un _director de narración_: un
modelo que lee un texto y produce anotaciones de pausa, énfasis, ritmo y tono.**

El motor recibe esas anotaciones y pone la voz. Son piezas separadas unidas por
un formato estable —la *partitura*, `hearme.narration.score`— y esa separación
es la tesis central del proyecto.

Las consecuencias son grandes:

- **El aporte comunitario sobrevive al motor.** Cuando en 2028 aparezca algo
  mejor que Kokoro, se escribe un adaptador de cincuenta líneas y el criterio
  acumulado durante años se aplica igual. Sin esta separación, cada cambio de
  motor tiraría el trabajo de la comunidad a la basura.
- **Entrenar cuesta poco.** Un modelo texto→anotaciones es órdenes de magnitud
  más barato que un modelo texto→audio. Se puede reentrenar semanalmente con
  recursos donados, y una universidad o una biblioteca pueden reproducirlo.
- **La barrera de entrada baja.** Aportar es decir «aquí falta una pausa» o
  «esta versión suena mejor». No hace falta saber de fonética, ni tener un
  micrófono, ni ceder la voz.
- **Es auditable.** Una anotación es texto legible: se puede revisar, discutir,
  versionar y corregir. Los pesos de un modelo de voz, no.

Esta arquitectura no es una apuesta a ciegas. La literatura reciente sobre
control prosódico en cascada —un modelo que predice cortes de frase y otro que
regresa objetivos prosódicos, emitiendo SSML consumible por motores
comerciales— reporta **99,2% de F1 en colocación de pausas** y **25–40% menos
error absoluto en tono, ritmo y volumen** frente a las alternativas, y es
portable entre motores por construcción ([Prosody-Control-French-TTS, ICNLSP
2025](https://github.com/hi-paris/Prosody-Control-French-TTS)). El enfoque
funciona; lo que aporta HearMe es el circuito comunitario que lo alimenta.

## 3. Comparativa de las opciones consideradas

| Enfoque | Coste de cómputo | Atadura al motor | Datos necesarios | Barrera para aportar | Durabilidad del aporte |
|---|---|---|---|---|---|
| **A.** Ajuste supervisado del motor TTS | Muy alto | Total | Miles de horas de audio pareado | Muy alta (grabar, ceder voz) | Nula: muere con el motor |
| **B.** Preferencias (DPO/MPO) sobre el motor | Alto | Total | Decenas de miles de pares A/B | Baja | Nula: muere con el motor |
| **C.** Director entrenado (**elegido**) | Bajo | Ninguna | Anotaciones sobre texto | Muy baja | Alta: es un corpus de texto |
| **D.** Entrenamiento federado | Alto + complejidad | Variable | Datos distribuidos | Media | Media |
| **E.** Correcciones humanas revisadas | Nulo (es la capa de datos) | Ninguna | Personas con criterio | Muy baja | Alta |

### A. Ajuste supervisado del motor — descartado

Es el enfoque clásico y el que más gente propone primero. Requiere miles de
horas de audio alineado, cómputo que no tenemos y, sobre todo, **que la gente
ceda su voz**. Eso último no es un detalle logístico: una comunidad que recoge
voces se convierte en un repositorio de material para clonación, con todo lo que
implica en consentimiento y riesgo de suplantación. Y al final del esfuerzo, el
resultado son unos pesos atados a una arquitectura concreta que quedará obsoleta.

Se descarta como vía principal. Reaparece, acotada, en §6.3.

### B. Optimización por preferencias sobre el motor — descartado como vía principal, adoptado como algoritmo

La optimización por preferencias aplicada a TTS es real y activa: DPO sobre
modelos autorregresivos, MPO para alinear varias dimensiones a la vez
(inteligibilidad, similitud de locutor, prosodia), GRPO, variantes a nivel de
token. Funciona. Pero, como reconoce la propia literatura, **RLHF en TTS sigue
en pañales** comparado con su madurez en texto, y todas estas técnicas producen
un motor ajustado: máxima atadura.

La idea que sí adoptamos es el *algoritmo*, no el objetivo. **Aplicar
aprendizaje por preferencias al director** —que es un modelo pequeño de
texto→anotaciones— da lo mejor de ambos: la eficiencia de datos de las
comparaciones A/B, sin la atadura ni el coste de reentrenar un modelo de audio.
Comparar dos lecturas y quedarse con la mejor es la forma más barata y más
limpia de recoger juicio humano, y no exige a nadie saber fonética.

### C. Director de narración entrenado — **elegido**

Es la propuesta descrita en §2. Es también la que mejor encaja con lo que ya
existe: el segmentador de HearMe llevaba desde el principio unas tablas de
pausas por tipo de bloque escritas a mano. Eso **ya era un director por
reglas**, solo que incrustado y sin posibilidad de mejorar. El módulo
`hearme.narration` lo extrae, le pone un contrato (`NarrationDirector`) y deja
el hueco para que un modelo entrenado ocupe su sitio sin tocar nada más.

### D. Entrenamiento federado — descartado, con una excepción reservada

El aprendizaje federado resuelve un problema concreto: entrenar sin que los
datos crudos salgan del dispositivo. Es sólido para reconocimiento de voz en
móviles y hay trabajo serio en clonación federada de voz.

**No es nuestro problema.** Las anotaciones de prosodia son etiquetas sobre
textos de dominio público. No hay nada privado que proteger; al contrario, **el
objetivo declarado es publicarlas**, que es exactamente lo opuesto a la premisa
del federado. Adoptarlo aquí sería pagar heterogeneidad de clientes, cuellos de
botella de comunicación, agregación segura y vulnerabilidad residual a ataques
de inferencia, todo ello para proteger datos que queremos regalar.

Queda reservado para un caso que sí lo justificaría: **personalización en el
dispositivo de quien escucha**. Si alguien con dislexia ajusta durante meses el
ritmo a su medida, esos ajustes sí son personales y sí merecen no salir de su
equipo. Ese día, el federado será la herramienta correcta. Hoy no.

### E. Correcciones humanas con revisión — adoptado como capa de datos

No compite con C: la alimenta. Es el mecanismo de recogida, y su diseño está en
§5 y §6.

### Veredicto

> **Columna vertebral: C.** Un director de narración entrenado, desacoplado del
> motor mediante la partitura.
> **Capa de datos: E.** Correcciones y preferencias de la comunidad, validadas
> por revisión ponderada.
> **Algoritmo de aprendizaje: B aplicado al director**, no al motor.
> **A y D: descartados hoy**, con condiciones explícitas de reapertura.

## 4. Arquitectura

```
  Texto  ──►  Director  ──►  Partitura  ──►  Adaptador  ──►  Motor  ──►  Audio
                  ▲          (neutra)         (por motor)
                  │                                │
                  │                                ▼
                  │                          Lo que el motor
                  │                          NO pudo respetar
                  │                          (RenderPlan.dropped)
                  │
            ┌─────┴──────────────────────────────────┐
            │  Entrenamiento (semanal, reproducible) │
            └─────▲──────────────────────────────────┘
                  │
            Corpus validado  ◄── Revisión ◄── Aportaciones de la comunidad
```

Cuatro piezas, en `src/hearme/narration/`:

| Módulo | Responsabilidad | Por qué está separado |
|---|---|---|
| `score.py` | El formato de la partitura | Es el activo que perdura. Sobrevive a motores y a modelos |
| `director.py` | Texto → partitura | Es lo que se entrena y se sustituye |
| `adapters.py` | Partitura → mandos del motor | Aísla lo específico de cada motor y **declara lo que se pierde** |
| `contributions.py` | Aportar, revisar, admitir | Es donde vive la defensa contra el abuso |

### Por qué la partitura está diseñada así

Tres decisiones que son caras de revertir y conviene entender:

**Unidades neutras.** Milisegundos, semitonos, multiplicadores. Nunca
`length_scale` ni `<prosody rate="x-slow">`, que son mandos de un motor concreto
y caducan con él. Los semitonos, en particular, se eligen sobre los hercios
porque son relativos a la voz y por tanto transferibles entre voces distintas.

**Anclaje al texto, no al troceo.** Las marcas apuntan a desplazamientos de
carácter sobre el texto normalizado, con su huella SHA-256 al lado. Si cambia el
segmentador, o el motor, o el idioma, las anotaciones se pueden volver a aplicar
porque describen *el texto*, no la ejecución de aquel día.

**Procedencia explícita.** Cada marca sabe si viene de una regla, de un modelo,
de una persona o de una lectura humana medida, y esa jerarquía decide quién gana
al fusionar. Un corpus sin procedencia no se puede auditar, ni depurar, ni
retirar cuando se descubra que una fuente estaba envenenada.

### El corpus no contiene las obras

El corpus guarda **anotaciones indexadas por la huella del texto**, no los
textos. Esto no es un detalle de implementación: permite anotar material con
derechos sin redistribuirlo, hace las aportaciones citables y reproducibles, y
mantiene el conjunto publicable sin auditoría legal por obra.

## 5. Cómo se aporta

Tres vías, ordenadas de menor a mayor coste para quien contribuye. **La primera
es la principal**, y es deliberado: si aportar exige conocimientos, solo
aportarán quienes ya los tienen, y el corpus reflejará sus sesgos.

### 5.1 Preferencia — «¿cuál suena mejor?»

Se ofrecen dos versiones del mismo pasaje y se elige. Sin formación previa, sin
micrófono, en diez segundos, desde el móvil mientras se escucha un libro.

Es la vía de mayor volumen y mejor relación señal/ruido, y la que alimenta
directamente el aprendizaje por preferencias del director. Las dos versiones se
generan variando la partitura, **nunca el motor ni la voz**: si cambiara el
timbre, se estaría midiendo qué voz gusta más, no qué interpretación es mejor.

### 5.2 Corrección — «aquí falta una pausa»

Sobre un pasaje concreto: alargar un silencio, mover el énfasis, marcar un
tramo como diálogo, corregir la pronunciación de un nombre propio. Produce
marcas con `MarkSource.HUMAN`, que ganan a cualquier regla o predicción.

Es la vía que mejor recoge conocimiento especializado —una bibliotecaria que
sabe cómo se lee un texto litúrgico, un docente que sabe qué cadencia necesita
un alumno con dislexia— y la que hay que cuidar más contra el desgaste: quien
corrige merece ver su corrección aplicada y saber por qué, si no se marcha.

### 5.3 Lectura de referencia — la voz humana como patrón

Alguien narra un pasaje. No se publica el audio como voz: se **alinea con el
texto y se extraen las pausas, la entonación y la energía**, que se convierten
en una partitura con `MarkSource.REFERENCE`. Es la única evidencia que no es una
opinión sobre cómo debería sonar algo, sino la medida de cómo sonó de verdad, y
por eso pesa más que todo lo demás.

Es también la vía más delicada, y por eso **todavía no está abierta**: los
términos de cesión no están redactados y no se recoge ninguna grabación hasta
que lo estén. Cuando se abra, será con estas condiciones:

- **Consentimiento explícito, informado y revocable**, separado del alta.
- **Se publica la prosodia extraída, no el audio**, salvo cesión expresa
  adicional. Quien narra aporta criterio, no su timbre.
- **Retirada efectiva**: revocar elimina las marcas derivadas de la siguiente
  publicación del corpus, y el rastro queda en el registro de cambios.

Este último punto es lo que separa una donación de voz de una cesión de
identidad biométrica, y no es negociable.

## 6. Cómo se valida

Implementado y probado en `contributions.py`. El diseño parte de un hecho
incómodo: **el voto por mayoría simple se rompe en cuanto hay revisores
maliciosos coordinados**, y envenenar el 10% de un conjunto basta para inducir
errores masivos en un objetivo elegido.

### Cuórum ponderado por reputación

Cada revisor pesa según su fiabilidad *medida*, no declarada. La fiabilidad sale
de **ítems de control**: aportaciones de resultado ya conocido, mezcladas de
forma indistinguible con el trabajo real (10% de las colas).

El cálculo usa suavizado de Laplace en vez del acierto crudo, para que nadie
llegue a peso máximo con tres aciertos afortunados. La confianza tiene que
costar tiempo, o fabricar revisores fiables vuelve a ser barato.

### Reglas de admisión

| Regla | Valor | Por qué |
|---|---|---|
| Peso a favor para aceptar | 1.0 | Con fiabilidad inicial 0.25, exige 4 revisores nuevos o 2 contrastados |
| Peso en contra para rechazar | 0.75 | Más bajo que el de aceptar: ante la duda, no entra |
| Revisores distintos mínimos | 2 | Ni el más veterano valida solo: una cuenta comprometida no puede ser llave maestra |
| Rechazo | exige además `en_contra ≥ a_favor` | Sin esto, una minoría vetaba a una mayoría clara |
| Desacuerdo que escala | minoría ≥ 35% del peso | Un texto que divide a revisores fiables suele ser una duda legítima, no un fraude |

El desacuerdo genuino **no se resuelve con un umbral**: se eleva a decisión
editorial. Cómo debe leerse un pasaje ambiguo es una pregunta legítima, y
tratarla como si fuera spam es la forma más rápida de perder a la gente que más
sabe.

## 7. Cómo se evita el abuso

| Vector | Defensa | Estado |
|---|---|---|
| Identidades fabricadas (Sybil) | Peso por fiabilidad medida; cuentas nuevas no alcanzan cuórum ni coordinadas | Implementado |
| Auto-validación | Detección y cuarentena si quien aporta revisa lo suyo | Implementado |
| Voto duplicado | Una persona un voto; cuenta la última revisión | Implementado |
| Cuenta de confianza comprometida | Mínimo de revisores distintos; techo al peso individual | Implementado |
| Envenenamiento por volumen | Límite de aportaciones por hora y persona | Política definida |
| Envenenamiento sutil | Ítems de control y detección de discrepancia con el consenso | Política definida |
| Sesgo por deriva del consenso | Auditoría periódica contra lecturas de referencia humanas | Proceso |
| Suplantación de voz | Se publica prosodia, no timbre; consentimiento revocable | Política definida |
| Material con derechos | El corpus indexa por huella, no almacena obras | Por diseño |

Una honestidad necesaria: **ninguna de estas defensas es suficiente contra un
atacante decidido y con recursos.** Lo que hacen es encarecer el ataque hasta que
deje de compensar frente a un proyecto sin ánimo de lucro, y garantizar que
cuando ocurra quede rastro suficiente para revertirlo. Un corpus abierto se
protege sobre todo con transparencia y capacidad de retirada, no con muros.

## 8. Cómo se integran las mejoras

Nada llega a los oídos de nadie sin pasar por cuatro fases:

1. **Candidata.** La aportación entra como `PENDING`.
2. **Validada.** Supera el cuórum y pasa a `ACCEPTED`. Ya cuenta para el corpus,
   todavía no para la escucha.
3. **Publicación del corpus.** Instantánea versionada e inmutable, con
   periodicidad trimestral —el ritmo que ha demostrado sostenible Common Voice—
   y su registro de cambios. Todo entrenamiento se referencia a una instantánea
   concreta: sin eso, ningún resultado es reproducible.
4. **Promoción del director.** Se entrena una candidata sobre la instantánea y
   se la somete a **evaluación a ciegas** contra la que está en producción:
   pasajes idénticos, mismo motor, misma voz, orden aleatorio, evaluadores que
   no saben cuál es cuál. Solo entra si gana.

El paso 4 es el que evita el fallo clásico de estos proyectos: acumular datos
durante dos años y descubrir que el modelo nuevo suena peor. Se mide antes de
promover, y una regresión detectada revierte al director anterior en una versión.

### Métricas

**De sistema**, automáticas: F1 de colocación de pausas contra lecturas de
referencia; error absoluto en ritmo y énfasis; tasa de `RenderPlan.dropped` por
motor —cuánta partitura se está perdiendo por limitaciones del motor.

**De escucha**, con personas: preferencia por pares frente a la versión anterior;
comprensión y fatiga en sesiones largas, medidas con quienes de verdad usan
esto: personas con dislexia, personas mayores, estudiantes.

**De comunidad**: proporción de aportaciones que terminan aceptadas —si cae, algo
está expulsando a la gente—, tiempo hasta la primera revisión, y diversidad
lingüística y demográfica de quien aporta. Los conjuntos de voz multilingües
tienen un historial bien documentado de problemas de calidad por falta de
conciencia sociolingüística; medirlo desde el principio es más barato que
corregirlo después.

## 9. Licencia del corpus

**CC0** para las anotaciones, siguiendo el precedente de Common Voice. El
objetivo es que el corpus sea usable por cualquiera, incluidos proyectos que
compitan con HearMe: si el corpus solo sirve para HearMe, no es infraestructura
pública, es un foso.

Las lecturas de referencia se rigen por su cesión específica, siempre más
restrictiva y siempre revocable. **Esos términos aún no están escritos, y hasta
que lo estén no se recoge ninguna grabación** — ver
[LICENSING.md](LICENSING.md#lo-que-todavía-no-está-cerrado).

## 10. Estado y lo que no sabemos

**Implementado y probado** (`tests/test_narration.py`, 32 tests): el formato de
la partitura con su serialización y su jerarquía de procedencia; el director por
reglas como línea base sustituible; los adaptadores con declaración de pérdidas;
la validación con cuórum ponderado y las defensas contra abuso.

**Definido pero no construido**: el servicio de aportaciones y su interfaz; la
extracción de prosodia por alineación; el entrenamiento del director; la
evaluación a ciegas; la publicación del corpus.

**Preguntas abiertas y honestas:**

- *¿Cuántas aportaciones hacen falta para superar a las reglas?* No lo sabemos.
  La respuesta razonable es medirlo pronto con un piloto en un solo idioma, no
  estimarlo.
- *¿Transfiere el criterio entre idiomas?* Las pausas sintácticas probablemente
  sí; el énfasis y la cadencia casi seguro que no. Afecta a cuánto esfuerzo
  necesita cada idioma nuevo.
- *¿Se puede recoger preferencia sin sesgar por el orden de presentación?* Hay
  literatura, y hay que aplicarla desde la primera versión, no después.
- *¿Aguanta el ritmo trimestral una comunidad pequeña?* Common Voice lo sostiene
  con el respaldo de una fundación. Habrá que ajustarlo a la realidad.

## Referencias

- [Fine-grained Preference Optimization Improves Zero-shot Text-to-Speech](https://arxiv.org/pdf/2502.02950)
- [MPO: Multidimensional Preference Optimization for LM-based TTS](https://arxiv.org/abs/2509.00685)
- [Group Relative Policy Optimization for TTS with LLMs](https://arxiv.org/pdf/2509.18798)
- [Improving French Synthetic Speech Quality via SSML Prosody Control](https://arxiv.org/pdf/2508.17494) · [código](https://github.com/hi-paris/Prosody-Control-French-TTS)
- [Predicting Prosodic Prominence from Text with Pre-trained Contextualized Word Representations](https://arxiv.org/pdf/1908.02262)
- [ToBI: A standard for labeling English prosody](https://www.researchgate.net/publication/221492301_ToBI_A_standard_for_labeling_English_prosody)
- [Common Voice: A Massively-Multilingual Speech Corpus](https://arxiv.org/pdf/1912.06670) · [Common Voice 20](https://www.mozillafoundation.org/en/blog/common-voice-20-is-now-available/)
- [Data Poisoning Attacks and Defenses to Crowdsourcing Systems](https://dl.acm.org/doi/fullHtml/10.1145/3442381.3450066)
- [Mitigating Sybils in Federated Learning Poisoning](https://www.researchgate.net/publication/327050197_Mitigating_Sybils_in_Federated_Learning_Poisoning)
- [Data Quality Issues in Multilingual Speech Datasets](https://arxiv.org/pdf/2506.17525)
- [Federated Learning: A Survey of Core Challenges, Current Methods, and Opportunities](https://www.mdpi.com/2073-431X/15/3/155)
- [Fed-PISA: Federated Voice Cloning via Personalized Identity-Style Adaptation](https://arxiv.org/pdf/2509.16010)
