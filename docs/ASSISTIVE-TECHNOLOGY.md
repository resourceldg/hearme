# Assistive Technology First

> No basta con «ser accesible». Hay que funcionar bien con las tecnologías que
> las personas **ya usan** — y comprobarlo con ellas, no sobre ellas.

---

## El principio

Cumplir WCAG y funcionar con un lector de pantalla no son lo mismo. Una interfaz
puede pasar todas las comprobaciones automáticas y ser insufrible con NVDA:
anuncios que interrumpen cada dos segundos, un orden de lectura que salta, un
botón que dice «Cerrar» sin decir qué cierra, cuarenta pulsaciones para llegar a
lo que importa.

La norma es el **suelo**. La tecnología de asistencia real es la **prueba**.

De ahí el orden de este proyecto:

1. **HTML semántico** primero. Un `<button>` trae rol, foco, teclado y anuncio
   gratis. Un `<div role="button">` obliga a reimplementarlo todo y siempre falta
   algo.
2. **ARIA solo donde el HTML no llega**, y con la regla que suele ignorarse: no
   usar ARIA es mejor que usar ARIA mal. Un `aria-label` equivocado sustituye a
   un nombre correcto; una referencia rota deja el elemento mudo sin avisar.
3. **Verificación automática** de lo mecánico, para no gastar el tiempo de nadie
   en lo que una máquina caza.
4. **Validación con personas** que usan estas tecnologías a diario. Es lo único
   que responde a la pregunta que importa: ¿se puede usar esto?

## Nada sobre nosotros sin nosotros

El lema viene del movimiento por los derechos de las personas con discapacidad y
está recogido en la Convención de la ONU. Aquí significa:

> **Ninguna decisión que afecte a la accesibilidad se toma sin la participación
> vinculante de personas que usan tecnología de asistencia.**

Vinculante quiere decir con poder de veto, no consultiva. Un consejo que solo
opina es un adorno.

### Qué recibe quien aporta

**Este proyecto no tiene dinero y no gestiona el dinero de nadie.** Es un
proyecto comunitario sostenido por tiempo donado, y decirlo claro forma parte
del trato: nadie debería aportar creyendo que hay fondos que no existen.

Aportar tampoco sale gratis para quien aporta. Elige tú:

- **Crédito.** Coautoría en los commits que salgan de tu sesión y tu nombre
  junto a la combinación que validaste en la matriz.
- **Voz.** Asiento en el consejo de accesibilidad, con veto incluido.
- **Prioridad.** Lo que a ti te estorba se arregla antes que lo demás.
- **Nada.** Aportar y seguir con tu vida es una opción completa.

**Donaciones:** puedes publicar tu enlace junto a tu crédito, y quien quiera
apoyarte lo hace directamente contigo. El proyecto no intermedia ni lleva
cuentas. Las reglas y los medios recomendados están en
[GOVERNANCE.md § Dinero](../GOVERNANCE.md#dinero).

### Por qué no se exige pagar

Una versión anterior de este documento decía «la validación se remunera siempre;
si no hay fondos, la función espera». Sonaba firme y estaba mal:

- **Paralizaba el proyecto**, que no tiene dinero. La accesibilidad no se haría
  nunca, y quien pierde cuando no se hace es justo a quien la regla protegía.
- **Era paternalista.** Decirle a alguien que usa lector de pantalla «no acepto
  tu contribución porque no puedo pagarte» le niega decidir por sí mismo. Es una
  decisión sobre esa persona tomada sin ella: contradecía el propio lema.
- **Cerraba la puerta a la comunidad**, que es de lo que vive un proyecto libre.

La línea que importa no es si hay factura. Es que el proyecto **no dependa** de
trabajo que no devuelve nada, y que quien aporte pueda marcharse sin reproche.
Por eso:

- **No dependemos de vosotros.** Se automatiza todo lo automatizable y se
  publica qué queda sin validar, en vez de esperar a que alguien lo regale.
- **No os hacemos perder el tiempo.** Ninguna sesión empieza con fallos que una
  máquina podía cazar. Es la forma más concreta de respeto que existe.
- **Se responde.** Qué se arregló, qué no y por qué.

## Matriz de compatibilidad

Estado honesto a fecha de hoy. **Ninguna combinación ha sido validada por una
persona usuaria.** La tabla existe justamente para que ese hueco se vea, no para
disimularlo.

| Lector | Plataforma | Navegador | Estado |
| --- | --- | --- | --- |
| NVDA | Windows | Firefox, Chrome | ⬜ Sin validar |
| JAWS | Windows | Chrome, Edge | ⬜ Sin validar |
| Narrator | Windows | Edge | ⬜ Sin validar |
| VoiceOver | macOS | Safari | ⬜ Sin validar |
| VoiceOver | iOS | Safari | ⬜ Sin validar |
| TalkBack | Android | Chrome | ⬜ Sin validar |
| Orca | Linux | Firefox | ⬜ Sin validar |

Leyenda: ✅ validado · ⚠️ con incidencias conocidas · ⬜ sin validar

**Orca** merece una nota: es el lector libre de GNOME y el que usaría cualquiera
que despliegue esto en una biblioteca con equipos Linux. Suele quedar el último
en las matrices del sector. Aquí es prioridad igual que NVDA.

### Qué sí está verificado (por máquina)

`tests/test_accessibility.py` audita el HTML **realmente renderizado** por el
build de producción, no el código fuente: un lector de pantalla no lee
componentes, lee el árbol de accesibilidad que el navegador construye.

19 comprobaciones sobre idioma del documento, puntos de referencia, jerarquía de
encabezados sin saltos, nombre accesible en todo control, campos etiquetados,
iconos decorativos silenciados, roles ARIA existentes, referencias que apuntan a
algo real, estados válidos, regiones vivas, y navegación por teclado —incluido
que un grupo de opciones tenga exactamente un punto de tabulación—.

Esa auditoría ya encontró un fallo que la interfaz no delataba: un
`aria-controls` que apuntaba a un `id` inexistente. Se veía perfecta; solo lo
habría notado quien navega con lector.

**Lo que no puede comprobar:** cómo suena. Si el orden de lectura tiene sentido,
si la verbosidad cansa a los diez minutos, si un anuncio llega tarde o
interrumpe, si «Cerrar» se entiende en contexto. Eso solo lo dice una persona.

## Navegación por teclado

Contrato completo, sin ratón en ningún momento:

| Tecla | Efecto |
| --- | --- |
| `Tab` / `Shift+Tab` | Recorrer controles en orden de documento |
| `Flechas` | Moverse dentro de un grupo de opciones |
| `Inicio` / `Fin` | Primera / última opción del grupo |
| `Espacio` / `Enter` | Activar |
| `Escape` | Cerrar el panel de apariencia |

Decisiones que sostienen esto:

- **Foco móvil** en los grupos de opciones: se entra una vez y se recorre con
  flechas. Con cinco opciones tabulables, atravesar un grupo costaría cinco
  pulsaciones — la fricción que hace abandonar el teclado.
- **Ningún `tabindex` positivo.** Rompe el orden natural y se desincroniza del
  orden visual en cuanto alguien reordena algo.
- **Foco atrapado con ciclo** en el diálogo, y devuelto al disparador al cerrar.
  Un modal a medias deja el foco perdido detrás del velo.
- **`:focus-visible`, nunca `:focus`.** El anillo aparece con teclado y no al
  pulsar con ratón.
- **Grosor de foco ajustable** de 2 a 6 px: para quien ve poco, 2 px no bastan.

## El Laboratorio de Accesibilidad

Panel de desarrollo (`web/src/lib/components/AccessibilityLab.svelte`) que hace
visible lo invisible **mientras** se programa, no en una auditoría tres meses
después cuando arreglarlo cuesta diez veces más.

| Simulación | Qué revela |
| --- | --- |
| Agudeza reducida | Jerarquías que solo funcionan con vista perfecta |
| Protanopia / deuteranopia / tritanopia | Información codificada solo por color |
| Acromatopsia | Lo mismo, en el caso extremo |
| Solo teclado | Oculta el puntero: obliga a recorrer la interfaz sin ratón |
| Previsualización de lectura | Qué se anunciaría al enfocar cada elemento |
| Auditoría en vivo | Fallos en el DOM real, incluidos diálogos abiertos |

La auditoría en vivo complementa a la del servidor: ve lo que solo existe tras
interactuar y **mide los objetivos táctiles con el CSS ya aplicado**, que es
donde aparecen los botones de 18 px.

### La advertencia va dentro del propio panel

> Simular una condición no equivale a vivirla.

Un desenfoque no es baja visión. Una matriz de color no es daltonismo. La
previsualización de lectura no es NVDA: aproxima el algoritmo `accname` y el
orden nombre–rol–estado de NVDA y VoiceOver, pero JAWS y Narrator varían y
TalkBack añade pistas táctiles.

Simular desde fuera produce, como mucho, empatía y una lista de sospechas. Una
herramienta de simulación **sin esa advertencia** produce lo contrario de lo que
busca: la confianza de creer que ya está comprobado. Por eso el aviso está en el
panel y no solo en esta página.

El laboratorio se carga con `import()` dinámico bajo `import.meta.env.DEV`; en
producción no viaja ni su CSS. Está verificado tras el build.

## Protocolo de validación

### Antes de convocar a nadie

1. La auditoría automática pasa sin fallos.
2. Se ha recorrido la tarea completa solo con teclado.
3. Se ha revisado con el laboratorio.

Presentarse a una sesión con fallos que una máquina caza es hacer perder el
tiempo a quien viene a ayudar.

### La sesión

- **Tareas, no funciones.** «Convierte este libro y escucha el segundo
  capítulo», no «prueba el botón de convertir». Lo que falla casi nunca es un
  control: es el recorrido entre controles.
- **Su equipo y su configuración.** Nada de máquinas preparadas: la gente tiene
  su velocidad de voz, su nivel de verbosidad y sus atajos.
- **Sin ayudar.** El impulso de explicar destruye el dato. Si hay que explicar
  algo, ahí está el fallo.
- **Se graba lo que se anuncia**, con consentimiento, para poder revisarlo sin
  hacer repetir la sesión.
- **Se acuerda la reciprocidad antes de empezar**, no después. Eliges tú del
  menú de arriba, y se cumple pase lo que pase con el resultado.

### Después

- Cada incidencia entra como issue con la etiqueta `accesibilidad` y **cita
  textual** de lo que ocurrió. Un resumen escrito por quien programa pierde
  exactamente el matiz que importaba.
- La matriz de arriba se actualiza con lo validado y lo que quedó con
  incidencias.
- Se responde a quien participó: qué se arregló, qué no y por qué. Sin eso, la
  siguiente vez no viene nadie — con razón.

## Cómo participar

Si usas lector de pantalla, magnificador, navegación por conmutador, control por
voz o cualquier otra tecnología de asistencia, y quieres que HearMe funcione
bien con lo tuyo: abre una incidencia con la etiqueta `accesibilidad` o escribe
al proyecto.

**Elige del menú de reciprocidad lo que te parezca justo**, o di que no quieres
nada. Ambas respuestas están bien y ninguna condiciona que tu aportación se
tenga en cuenta.

También sirve —y mucho— contar simplemente qué falló, sin comprometerte a nada
más. Un mensaje de dos líneas diciendo «con Orca, el botón de convertir no dice
qué hace» ya es una aportación completa.

## Lo que falta

- **Todo lo de la matriz.** Cero combinaciones validadas por personas.
- **Dinero.** No hay. El orden de reparto está fijado por escrito para cuando lo
  haya —accesibilidad cobra primero—, pero hoy eso es un compromiso, no un
  presupuesto. Decirlo claro es parte del trato: nadie debería aportar creyendo
  que hay fondos que no existen.
- **Consejo de accesibilidad constituido.** Sin él, esto lo decide quien
  programa, que es justo lo que el principio quiere evitar.
- **Navegación por conmutador y control por voz.** El teclado está cubierto; el
  resto de vías de entrada no se han considerado con seriedad.
