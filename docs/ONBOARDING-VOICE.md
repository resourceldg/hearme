# Adaptive Onboarding & Voice Experience

> Cómo se decide qué vas a escuchar, y por qué antes era confuso.

---

## El problema real: seis conceptos disfrazados de tres

La interfaz anterior tenía un campo «Idioma de origen», otro «Traducir a» y un
modo llamado «Traducción». Tres controles para dos ideas, y ninguno respondía a
lo único que de verdad importa: **¿en qué idioma voy a escuchar esto?**

Producía estados absurdos que el sistema aceptaba sin protestar:

- Elegir el modo «Traducción» sin poner idioma de destino → no traducía nada, y
  nada lo indicaba.
- Poner un idioma de destino en modo «Audiolibro» → sí traducía.
- Elegir una voz española para escuchar un texto en alemán → se aceptaba.

El sistema hacía lo correcto en cada caso. Lo que estaba roto era el **modelo
mental** que la interfaz proponía.

## Los seis conceptos, separados

| Concepto | Pregunta que responde | Quién decide |
| --- | --- | --- |
| **Idioma del documento** | ¿En qué está escrito? | Se detecta; se puede corregir |
| **Idioma de reproducción** | ¿En qué lo voy a escuchar? | La persona |
| **Traducción** | ¿Hay que traducir? | **Se deriva**, no se elige |
| **Voz** | ¿Quién lo lee? | La persona, dentro del idioma de reproducción |
| **Estilo narrativo** | ¿Cómo lo lee? | La persona |
| **Motor** | ¿Qué tecnología lo sintetiza? | La voz lo determina |

### La decisión que lo ordena todo

**La traducción no es una opción: es una consecuencia.**

Si el documento está en inglés y quieres escucharlo en español, hay que
traducir. No hace falta que nadie marque una casilla. Eliminar esa casilla
elimina de golpe **todos** los estados incoherentes que producía.

En el código no existe el campo. `needs_translation` es una propiedad derivada, y
un test comprueba que sigue sin ser un campo — porque el día que alguien lo
añada «para tenerlo a mano», la confusión vuelve entera.

### La segunda: la voz se elige después del idioma

Y **solo entre las de ese idioma**. Una voz española leyendo alemán es un error
que la interfaz no debería permitir cometer. Al cambiar el idioma de
reproducción, la voz se reevalúa sola.

## Dos caminos, una sola pantalla

Un asistente de cinco pasos trata a todo el mundo como principiante para
siempre. Aquí hay **una pantalla con dos profundidades**:

**Camino rápido.** El documento ya se analizó al soltarlo. El asistente propone
un plan completo, lo resume en una frase y ofrece un botón:

> «Se narrará en español con Dora.»
> *El documento está en español y hay voces para ese idioma.*

Un clic y empieza.

**Camino avanzado.** El mismo plan con las cuatro decisiones abiertas y
numeradas, cada una con su explicación en lenguaje llano. No es otro modo: es el
mismo panel revelado, sin volver a empezar ni perder lo decidido.

## Analizar antes de convertir

Al soltar un documento se llama a `POST /api/analyze`, que lo parsea y lo
**descarta**: no encola nada, no guarda nada. Cuesta segundos y devuelve idioma
detectado, número de capítulos, duración estimada y un plan sugerido.

Eso permite dos cosas que antes no se podían:

1. **Recomendar con fundamento** en vez de preguntar a ciegas.
2. **Detectar los problemas antes**, no diez minutos después. Que falte el
   traductor o que la voz sea de otro idioma se ve *antes* de empezar.

En la prueba con un libro real: idioma detectado, 254 capítulos, ~274 min
estimados, plan propuesto con motivo. Segundos, no minutos.

## Las recomendaciones se ven, se explican y se deshacen

Cada sugerencia lleva su motivo al lado. Un test comprueba que **ninguna
recomendación puede existir sin explicación**: una sugerencia sin motivo visible
es una decisión que el sistema tomó por alguien.

Y cuando el sistema no está seguro, lo dice en vez de disimularlo:

> El documento es corto y la detección del idioma no es fiable. Compruébalo
> antes de empezar.

Con confianza por debajo de 0,6 no se preselecciona: se pregunta.

### El orden de preferencia, y por qué

1. **El idioma del documento**, si hay voz. Escuchar el original es lo que la
   mayoría espera, y no traducir evita meter errores de traducción en una obra
   que ya se entiende.
2. **El idioma de la interfaz**, si el original no tiene voz. Es la mejor pista
   disponible sobre qué entiende esta persona.
3. **Cualquiera con voz**, avisando de que es una suposición floja.

## Elegir voz escuchando, no leyendo

`ef_dora` y `es_ES-sharvard-medium` no responden a «¿cuál quiero para las
próximas catorce horas?». Dos cambios:

**Metadatos derivados de los nombres.** No inventados: los convenios de cada
proyecto ya los codifican. Kokoro usa dos letras iniciales —acento y género—, y
Piper usa `idioma_REGIÓN-nombre-calidad`. Así `af_heart` es «Heart · voz femenina
· acento estadounidense · calidad alta».

Cuando un motor añada voces nuevas, aparecen solas con sus metadatos correctos.

### El género, y un modelo que estaba a medias

El nombre de una voz Piper no indica el género. Pero al buscar la fuente real
apareció algo mejor que adivinarlo: el índice oficial de `piper-voices` publica
un `speaker_id_map`, y **el modelo español trae dos hablantes**:

```
es_ES-sharvard-medium →  speaker_id_map: {"M": 0, "F": 1}
```

HearMe usaba siempre el hablante 0. **A la voz femenina no se llegaba nunca**, y
nada lo indicaba. Ahora un modelo con dos hablantes son dos voces en el catálogo
—`es_ES-sharvard-medium#F` y `#M`— y el `speaker_id` llega a la síntesis, que es
lo que hace que elegir una u otra cambie de verdad lo que suena.

El género sale entonces de tres sitios, por orden de fiabilidad:

| Fuente | Cuántas | Ejemplo |
| --- | --- | --- |
| Convenio del nombre (Kokoro) | derivado | `af_heart` → femenina |
| `speaker_id_map` oficial (Piper) | dato | `#F` → femenina |
| Tabla declarada a mano | 17 modelos | `de_DE-thorsten` → masculina |
| Sin señal fiable | 5 modelos | `sv_SE-nst` → desconocido |

**45 de 51 voces (88%) llevan género.** Las cinco restantes —MLS, NST, DFKI,
Talesyntese, VAIS1000— son conjuntos anónimos que no identifican a nadie ni en
su nombre ni en su documentación, y se quedan como desconocidas: etiquetar mal a
alguien es peor que no etiquetarlo.

La tabla declarada se distingue de lo derivado a propósito. Puede tener errores,
y corregir uno es cambiar una línea en `_PIPER_SINGLE_GENDER`.

**Muestras audibles.** Un botón «Escuchar» en cada tarjeta. Tres detalles que
deciden si se usa:

- **Escuchar no selecciona.** Son dos acciones distintas: probar sin
  comprometerse es lo que hace que la gente pruebe.
- **Una sola muestra a la vez.** Dos voces solapadas no se comparan, se estorban.
- **La primera tarda** —se descarga el modelo— y se avisa *antes*. Una espera
  anunciada se tolera; una inesperada se lee como que algo se rompió.

Las muestras se cachean en el servidor: comparar seis voces no sintetiza seis
veces cada vez que se abre el selector.

## Voice Center: lo que dura, separado de lo que es de este documento

| Horizonte | Dónde | Qué se decide |
| --- | --- | --- |
| **Este documento** | Asistente | Idioma, voz y estilo para *este* texto |
| **Duradero** | Voice Center | Favoritas, voz por idioma, estilo habitual |

El asistente respeta lo duradero sin volver a preguntar. Si tienes fijada una voz
para español, la propone y lo dice: *«Es la voz que sueles usar para este
idioma.»*

### Lo que aprende y lo que no

El sistema recuerda lo que eliges **explícitamente** en el Voice Center. No
deduce nada de tu comportamiento ni cambia una preferencia por su cuenta. Si tu
voz por defecto cambia, es porque la cambiaste tú.

Todo es visible en una pantalla y quitarlo es un clic. Y nada sale del navegador:
qué voz elige alguien puede revelar su procedencia o su lengua materna.

## Siete estilos narrativos

Neutro, novela, poesía, técnico y tres nuevos: **académico** (pausado, con aire
en las citas), **infantil** (más lento y expresivo) y **conferencia** (cadencia de
exposición oral).

Dos tests los protegen: que todo estilo tenga prosodia definida —añadir uno sin
ella revienta al trocear— y que **cada estilo suene distinto del neutro**. Un
estilo indistinguible de otro no es un estilo, es una etiqueta.

La sugerencia automática es conservadora: ante la duda, neutro. Poesía en un
manual técnico se nota mucho más que un neutro de más.

> Un bug que encontró el test: «Cuento infantil» se clasificaba como novela,
> porque la regla de narrativa contiene «cuento» y se evaluaba antes. Las reglas
> van ahora de más específica a más general.

## Errores con acción, no con diagnóstico

Todo problema trae **qué pasa** y **qué hacer**. Un test comprueba que ninguno
puede existir sin acción: un error que solo describe el problema deja el trabajo
a medias, porque quien lo lee ya sabía que algo iba mal.

| Antes | Ahora |
| --- | --- |
| «No hay traductor disponible para en→es. Si el par existe solo en NLLB, activa `HEARME_ALLOW_NON_COMMERCIAL_MODELS`.» | «El documento está en inglés y quieres escucharlo en español, pero este servicio no puede traducir.» → *«Escúchalo en inglés, o pide a quien administra el servicio que instale el componente de traducción.»* |

El mensaje anterior mandaba a activar modelos no comerciales, **que no arregla
nada** cuando lo que falta es la dependencia entera.

## Reorganización de la interfaz

El flujo pasa de «rellena un formulario y espera» a **soltar → confirmar →
escuchar**:

```
   Soltar documento
        ↓  (segundos)
   Análisis automático
        ↓
   Plan propuesto en una frase  ──►  [Empezar]        camino rápido
        │
        └──►  [Ajustar antes]  ──►  4 decisiones      camino avanzado
                                     numeradas
```

Con **varios documentos** el asistente no se abre: un plan por documento sería
una entrevista. Se usan las opciones manuales, que siguen ahí.

En la barra superior, dos entradas permanentes y bien separadas:

- **Voces** — lo duradero de la voz.
- **Apariencia** — lo duradero de la lectura.

Y si el análisis falla, **no bloquea**: se avisa y quedan las opciones manuales,
que es exactamente lo que había antes.

## Lo que falta

- **Comparar original y traducción a la vez.** El plan ya tiene
  `keep_original`, pero la reproducción sincronizada de ambas versiones no está
  construida.
- **Pronunciaciones personalizadas.** El ADN de narración tiene el campo
  `lexicon` y el Voice Center todavía no lo edita.
- **Filtros del catálogo en la interfaz.** El backend filtra por género, motor e
  idioma; el selector solo agrupa por idioma.
- **Validación con lector de pantalla.** Como todo lo demás:
  [docs/ASSISTIVE-TECHNOLOGY.md](ASSISTIVE-TECHNOLOGY.md).
