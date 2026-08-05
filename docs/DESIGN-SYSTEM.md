# Sistema de diseño y experiencia adaptativa

> Cómo se ve HearMe, por qué se ve así, y por qué la accesibilidad no está en un
> menú aparte.

---

## La tesis

**No existe el «modo accesible».** Existe una interfaz con controles, y todo el
mundo tiene los mismos.

Un modo de accesibilidad separado hace tres daños a la vez:

1. Obliga a la persona a **clasificarse** para usar el producto.
2. Convierte lo básico —poder leer— en una **concesión**.
3. Garantiza que el modo principal se diseñe **sin pensar en nadie**, porque «ya
   está el otro».

Aquí los perfiles son presets sobre los mismos mandos que ve cualquiera. Quien
nunca abra el panel debe recibir ya una experiencia excelente; quien lo abra
encontrará los mismos ajustes tanto si tiene baja visión como si simplemente le
gusta el texto más grande.

Por eso el panel se llama **«Apariencia y lectura»**, no «Accesibilidad». Y por
eso los perfiles se llaman **«Texto amplio»**, no «Baja visión»: quien lo
necesita lo encuentra igual, y quien solo lee de lejos no tiene que identificarse
con un diagnóstico para ajustar su pantalla.

## La estética: VS Code Dark+, corregido

El punto de partida es VS Code Dark+. Superficies (`#1e1e1e`, `#252526`,
`#2d2d30`), la tipografía sobria, la densidad de un editor.

**Pero su azul característico no cumple WCAG AA como texto, y está medido:**

| Color | Uso en VS Code | Sobre `#1e1e1e` | AA exige |
|---|---|---|---|
| `#007acc` | barra de estado | **3,70:1** | 4,5:1 |
| `#0e639c` | fondo de botón | **2,61:1** | 4,5:1 |

La solución no fue cambiar de color, sino de luminosidad: se conserva el tono
exacto (H=204°, S=100%) y se sube hasta el mínimo que cumple.

| Token | Valor | Ratio | Para qué |
|---|---|---|---|
| `--accent` | `#0089e6` | 4,54:1 sobre `--bg` | texto, enlaces, bordes |
| `--accent-solid` | `#0077c7` | 4,69:1 con blanco encima | relleno de botones |

Que sean dos tokens y no uno viene de un error que cometí y que **el test
detectó**: verifiqué el acento contra el fondo de la página y lo di por bueno,
cuando el texto del botón principal va sobre el acento, no sobre el fondo. Blanco
sobre `#0089e6` son 3,67:1. Ahora hay un token para cada situación, y una prueba
para cada uno.

Detalle bonito: `#0077c7` acabó siendo casi exactamente el `#007acc` original.

## El contraste está probado, no prometido

[`tests/test_design_tokens.py`](../tests/test_design_tokens.py) lee los colores
del CSS real, resuelve la herencia entre temas como haría el navegador y
comprueba 18 propiedades. **Un ajuste estético que baje un ratio rompe la CI.**

Se cubren los cuatro temas —oscuro, claro, y sus variantes de contraste alto— y
tres criterios: 1.4.3 (texto), 1.4.11 (controles) y 1.4.6 (AAA, exigido al perfil
de contraste alto, porque quien lo activa suele necesitarlo de verdad).

Hay un test que existe solo para documentar: `test_el_azul_de_vs_code_original_no_habria_cumplido`.
Si alguien «corrige» el color al original por fidelidad estética, ahí está la
razón de por qué no.

## El Adaptive Experience Engine

Once ajustes, un único mecanismo: cada preferencia se escribe como atributo
`data-*` en `<html>` y el CSS reacciona solo.

```
  preferencia  →  data-* en <html>  →  token recalculado  →  toda la interfaz
```

Ningún componente conoce el motor. Se puede sustituir entero sin tocar una sola
vista.

| Ajuste | Valores | Qué mueve |
|---|---|---|
| Tema | sistema · oscuro · claro | paleta completa |
| Contraste | estándar · alto | paleta a ratios AAA |
| Tamaño de texto | 87,5% – 200% | `--font-scale`, y con él toda la escala tipográfica |
| Densidad | compacta · normal · amplia | `--density`, y con él todo el ritmo vertical |
| Animaciones | sistema · completas · suaves · ninguna | `--motion`, multiplicador de toda duración |
| Botones | normales · grandes | `--target-min` (28 px → 44 px) |
| Texto | normal · espaciado · cómodo | interlínea, espaciado de letras y palabras |
| Foco | 2 – 6 px | grosor del anillo |
| Nivel de detalle | lo esencial · todo | cuánta interfaz se despliega |

### Las escalas son multiplicativas, y eso importa

Subir el tamaño de fuente no reescribe cien reglas: cambia un factor y el sistema
entero se reacomoda manteniendo las proporciones.

```css
--font-scale: 1;                              /* lo mueve la persona */
--font-base: calc(1rem * var(--font-scale));  /* todo lo demás se deriva */
--font-lg: calc(var(--font-base) * 1.2);
```

Es la diferencia entre una interfaz que **escala** y una que se rompe al
ampliarla. Lo mismo con `--density` para el espaciado y `--motion` para las
duraciones: poner `--motion: 0` desactiva toda la animación del producto sin que
ningún componente sepa que existen las preferencias.

### Los perfiles son atajos, no compartimentos

| Perfil | Qué hace |
|---|---|
| **Lectura larga** | Más aire, menos elementos, animación suave |
| **Estudio** | Compacto y con todo a la vista |
| **Texto amplio** | 150%, contraste alto, objetivos y foco grandes |
| **Lectura cómoda** | Espaciado de letras y palabras, sin movimiento |
| **Sin distracciones** | Cero animación, interfaz mínima, objetivos grandes |

Se puede aplicar uno y luego cambiar cualquier cosa a mano; el perfil solo deja
de constar como activo. **Nadie encaja exactamente en una etiqueta.**

### Se guarda en local y no sale de ahí

Estas preferencias son datos personales, y de los delicados: alguien con
contraste alto, fuente grande, movimiento desactivado y lectura adaptada está
declarando una discapacidad sin haberlo dicho. Categoría especial del RGPD.

Viven en `localStorage`. Ni telemetría, ni sincronización, ni «mejoramos el
producto con datos de uso». Sería incoherente cifrar el ADN de narración por
revelar cómo lee alguien y enviar sus ajustes visuales en claro.

## Progressive Disclosure

De partida solo se ve lo imprescindible: soltar un archivo y pulsar convertir. El
resto vive tras revelaciones **etiquetadas con lo que contienen** —«Voz y
formato», «Idioma y motor de voz»— nunca tras un «Avanzado» genérico, que no dice
nada y obliga a abrirlo para saber si te interesa.

Tres detalles que suelen faltar:

- El contenido se **desmonta** al cerrar, no se oculta con CSS. Escondido con
  `display:none` seguiría en el orden de tabulación de algunos navegadores.
- La pista del resumen (`hint`) solo aparece cerrado: es la promesa de lo que
  hay dentro; una vez abierto, el contenido habla por sí mismo.
- Quien elige «Todo» lo ve desplegado desde el principio. **El nivel de detalle
  es una preferencia, no una fase por la que haya que pasar cada vez.**

## Detalles de accesibilidad que suelen romperse

| Criterio WCAG 2.2 | Cómo se cumple |
|---|---|
| 2.4.1 Bypass Blocks | Enlace de salto visible al recibir foco |
| 2.4.7 Focus Visible | `:focus-visible`, nunca `:focus` — el anillo no molesta al ratón |
| 2.4.11 Focus Not Obscured | `scroll-padding-top` para que la barra fija no tape el foco |
| 2.4.13 Focus Appearance | Grosor ajustable de 2 a 6 px |
| 2.5.7 Dragging Movements | Arrastrar **nunca** es la única vía: el botón de archivos hace lo mismo |
| 2.5.8 Target Size | 28 px de suelo, 44 px en el perfil de objetivos grandes |
| 1.4.10 Reflow | Usable a 320 px; el panel pasa a pantalla completa bajo 640 px |
| 1.4.12 Text Spacing | El perfil de lectura cómoda cumple los mínimos de la norma |
| 4.1.3 Status Messages | Región `aria-live` que anuncia progreso, errores y finalización |

**El control segmentado** usa `radiogroup` con navegación por flechas y un solo
punto de tabulación. Con cinco opciones, tabular cinco veces para atravesar un
grupo es exactamente la fricción que hace abandonar la navegación por teclado.

**El diálogo modal** implementa el contrato completo: foco atrapado con ciclo,
`Escape`, y devolución del foco al disparador al cerrar. Un modal a medias es
peor que ninguno, porque deja el foco perdido detrás del velo.

**El destello de tema** se evita con un script síncrono en `<head>` que aplica
las preferencias antes del primer píxel. Es la única excepción a «nada de scripts
sueltos» que el proyecto se permite, y está ahí por accesibilidad: un fogonazo
blanco al hidratar le arruina la sesión a quien tiene fotosensibilidad o migraña.

## Micro-interacciones

La regla: **notarse sin verse.**

- Desplazamiento de 1 px al pulsar. Suficiente para que el clic se sienta
  físico, imperceptible como distracción.
- El indicador del control segmentado desliza con una curva ligeramente elástica
  (`--ease-spring`); todo lo demás usa una entrada rápida y salida suave.
- Cifras con `font-variant-numeric: tabular-nums`. Sin esto, un progreso que pasa
  del 9% al 10% da un salto lateral que el ojo lee como parpadeo.
- El punto de «en curso» late a 2 s. Es la única animación en bucle de toda la
  interfaz, y desaparece por completo con el movimiento desactivado.

Todas cuelgan de `--motion`. Con las animaciones apagadas, las duraciones valen
cero y los fotogramas no llegan a verse: no hace falta condicionar el marcado.

Y hay una regla de último recurso en el layout global: aunque un componente
olvide usar `--motion`, si el sistema pide menos movimiento, se corta ahí. Se usa
`0.01ms` en vez de `0` para que los eventos `animationend` sigan disparándose y
nada se quede esperando una animación que nunca termina.

## Lo que falta

- **Auditoría con lector de pantalla real.** Todo lo anterior está construido
  según la norma y probado en lo que se puede probar automáticamente. Nada
  sustituye a una sesión con NVDA, JAWS o VoiceOver y una persona que los use a
  diario.
- **Verificación de contraste en composición.** Los tests comprueban pares
  token/token. Un color semitransparente sobre una superficie inesperada podría
  escaparse.
- **Traducción de la interfaz.** Hoy solo en español.
- **Tipografías empaquetadas.** `Inter` y `Atkinson Hyperlegible` se referencian
  pero no se sirven: si no están en el sistema, se cae a la familia genérica.
