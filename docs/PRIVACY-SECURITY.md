# Privacidad, seguridad y confianza

> Modelo de amenazas, decisiones de diseño con su justificación, y —con el mismo
> detalle— lo que este sistema **no** puede garantizar.

Un documento de seguridad que solo enumere garantías es propaganda. Este enumera
las tres cosas: qué se protege, cómo, y dónde está el límite.

---

## 1. Por qué esto importa aquí más que en otros proyectos

Lo que alguien lee es de los datos más reveladores que existen. Un historial de
lectura dice si te acaban de diagnosticar algo, si estás pensando en divorciarte,
qué crees, a quién votas, si estás saliendo del armario.

Y quien más usa HearMe es quien más expuesto está: personas con discapacidad
—categoría especial del RGPD—, personas mayores, menores en entornos educativos.
Además, el perfil de lectura **revela la discapacidad por sí solo**: alguien que
necesita ritmo muy lento y pausas muy largas está declarando algo sobre sí mismo
sin haberlo dicho nunca.

De ahí el principio que ordena el módulo:

> **El sistema no debería poder traicionar a quien lo usa aunque quisiera.**
> No promete no mirar: se organiza de forma que mirar exija una clave que solo
> tiene la persona.

## 2. Modelo de amenazas

| # | Adversario | Qué busca | ¿Se defiende? |
|---|---|---|---|
| A1 | Quien roba el disco o un backup | Reconstruir qué se ha leído | **Sí.** Contenido cifrado; metadatos degradados |
| A2 | Quien accede al almacén con permisos | Mover o sustituir registros | **Sí.** Datos asociados atan cada sobre a su registro |
| A3 | Quien recibe lo que se comparte con la comunidad | Reidentificar a quien aportó | **Sí.** Reglas generalizadas, umbral k, sin seudónimos |
| A4 | Un plugin malicioso o descuidado | Exfiltrar documentos o el perfil | **Parcial.** Se declara y se audita; no se contiene |
| A5 | Quien administra la máquina, en directo | Leer mientras se procesa | **No.** Imposible en un sistema ajeno |
| A6 | Análisis forense del soporte | Recuperar temporales borrados | **Sí, criptográficamente.** No por sobrescritura |
| A7 | Quien observa el uso del servicio | Saber que se usó y cuándo | **No.** Tiempos y recursos son observables |

Las cuatro filas con «Sí» están cubiertas por tests en
[`tests/test_privacy.py`](../tests/test_privacy.py). Las que no, están explicadas
abajo con el motivo.

## 3. Decisiones criptográficas y su justificación

### ChaCha20-Poly1305, no AES-GCM

AES-GCM es más rápido **cuando hay AES-NI**. Sin aceleración por hardware, una
implementación de AES en software o es lenta o filtra por temporización.

HearMe aspira a correr en el servidor viejo de una biblioteca tanto como en un
contenedor moderno. ChaCha20 es de tiempo constante en software puro. *La
privacidad no puede depender de que a la institución le haya alcanzado el
presupuesto.*

### Subclave por registro, no nonce aleatorio global

La catástrofe clásica de AEAD es repetir un nonce bajo la misma clave. Con 96
bits y claves de larga vida, la colisión deja de ser despreciable antes de lo que
parece.

Cada registro deriva su propia clave con HKDF desde una sal aleatoria de 256
bits. El nonce vuelve a ser irrelevante porque nunca se repite bajo la misma
clave. Cuesta una derivación por registro y **elimina una familia entera de
fallos** en vez de gestionarla.

### Datos asociados obligatorios

`seal()` exige el contexto y lo autentica. Sin esto, quien acceda al almacén
puede mover un ciphertext válido de un registro a otro: no descifra nada, pero
puede hacer que el perfil de A aparezca como el de B. Se previene gratis.

### scrypt, no Argon2id

Argon2id sería marginalmente preferible, pero exige una dependencia con extensión
en C. scrypt está en la biblioteca estándar y, con parámetros correctos
(n=2¹⁷, r=8 → ~134 MB, ~0,25 s medidos), es defensa de sobra frente a fuerza
bruta con GPU.

**Menos código en el camino crítico de seguridad es, en sí mismo, una propiedad
de seguridad.** `cryptography` es la única dependencia criptográfica del proyecto.

### Jerarquía de claves de dos niveles

Con una sola clave derivada de la contraseña, rotarla obliga a recifrar todo el
almacén. Con jerarquía, rotar es reenvolver 32 bytes.

No es comodidad: **una operación de horas es una operación que nadie hace**. Que
rotar sea instantáneo es lo que hace que se rote de verdad.

## 4. Separación de contenido y metadatos

Cifrar el contenido y dejar los metadatos en claro parece razonable. No lo es:
**los metadatos identifican el contenido sin abrirlo.**

Un documento tiene un tamaño exacto en bytes. Con un catálogo público —y
existen— se busca la coincidencia. Con la marca de tiempo exacta se sabe además
cuándo se leyó.

| Dato | Cómo se guarda | Por qué |
|---|---|---|
| Contenido, título, nombre de archivo | Cifrado | Es la obra y qué lee la persona |
| Tamaño | Cubos logarítmicos («2-4 MB») | El tamaño exacto es una huella dactilar |
| Marcas de tiempo | Redondeadas a la hora | El segundo exacto correlaciona registros |
| Estado, tipo, versión | En claro | Necesario para operar, no distingue documentos |

La separación es **estructural**: `validate_metadata()` se ejecuta siempre y
rechaza `title`, `filename`, `size_bytes` y compañía. Una comprobación de
privacidad que se pueda desactivar acaba desactivada.

## 5. El fallo que encontramos en nuestro propio diseño

El diseño anterior del corpus comunitario compartía anotaciones indexadas por
`sha256` del párrafo, con el argumento de que así no se redistribuían las obras.

**Era insuficiente, y lo medimos:**

```
corpus público del atacante: 1257 párrafos
coste de construir el diccionario: 0,01 s
párrafos reidentificados: 2/2  (100%)
```

Un hash sin clave de un texto público se invierte por diccionario en centésimas
de segundo. Publicar esas huellas equivale a publicar la lista de lo que cada
cual lee.

**La corrección no fue cifrar el hash. Fue dejar de compartir cualquier cosa
ligada a un texto:**

- En local, `keyed_digest()` con una clave que nunca sale de la instalación. Sigue
  sirviendo para deduplicar; fuera no vale nada, y dos instalaciones no se pueden
  correlacionar.
- Hacia la comunidad, **nada indexado por texto**. Solo reglas generalizadas.

El ataque está capturado como test (`test_una_huella_sin_clave_no_protege_lo_que_alguien_lee`)
para que nadie reintroduzca la idea sin toparse con la razón.

## 6. Borrado: por qué sobrescribir no basta

La receta clásica de sobrescribir antes de borrar viene de los discos
magnéticos. En almacenamiento actual casi nunca funciona:

- **SSD y flash** reparten la escritura entre celdas. Sobrescribir escribe en
  celdas *distintas*; las originales siguen ahí hasta que el controlador decida.
  El sistema operativo no puede forzarlo.
- **Copy-on-write** (Btrfs, ZFS, APFS) escribe siempre en bloques nuevos por
  diseño. Cualquier instantánea conserva la versión anterior.
- **Journaling, caché de página y swap** pueden haber copiado el dato fuera del
  alcance de cualquier aplicación.

Quien prometa «borrado seguro garantizado» aquí, o no lo sabe o está vendiendo
algo. `ShredReport.is_cryptographically_final` devuelve **siempre `False`**, para
que ningún módulo se confunda leyendo un `True` optimista.

**Lo que sí funciona: borrado criptográfico.** Si el dato nunca se escribió en
claro, borrarlo es destruir su clave: 32 bytes en memoria, o un archivo diminuto
que sí se puede sobrescribir con garantías razonables. Sin ella, los restos son
ruido.

Por eso la sesión privada genera su clave **solo en memoria** y todo lo que
escribe va ya cifrado. Al cerrar, se olvida la clave *antes* de sobrescribir: si
el proceso muriera entre ambos pasos, lo que queda en disco ya es indescifrable.

## 7. Zero Trust y plugins: lo que no se puede prometer

**En Python no se puede aislar un plugin dentro del mismo proceso.** Un plugin
cargado por `importlib` puede importar `os`, recorrer `gc.get_objects()` y
parchear cualquier módulo. Los intentos históricos de restringirlo —incluido
`rexec` en la propia biblioteca estándar— se retiraron por inseguros.

Lo que sí aporta el modelo de capacidades:

1. **Declaración obligatoria** antes de cargar. Un parser que pide red se ve
   *antes* de instalarlo.
2. **Concesión explícita.** Nada por defecto; no existe interruptor de «permitir
   todo», porque acaba encendido a las once de la noche cuando algo falla.
3. **Rastro auditable** de cada concesión y denegación.
4. **Punto único de aplicación** para cuando el aislamiento sea real (subproceso
   con seccomp, contenedor).

> Protege frente a plugins **descuidados** y hace visible al **malicioso**. No
> detiene al malicioso decidido dentro del mismo proceso. El aislamiento real
> está en la hoja de ruta, y hasta entonces el código lo dice en voz alta.

Un test comprueba que **ningún plugin interno tiene red ni acceso al perfil**.

## 8. El ADN de narración

El perfil personal es un objeto pequeño, cifrado, versionado y **portable entre
motores**: contiene modificadores sobre la partitura neutra, nunca parámetros de
Piper ni de Kokoro.

Dos decisiones que lo hacen durar:

**Modificadores relativos, no valores absolutos.** «Pausas de diálogo ×1,3», no
«520 ms». Un valor absoluto fijaría para siempre una corrección hecha contra una
versión concreta del director; una proporción se compone con lo que el director
sepa en cada momento y sigue teniendo sentido dentro de diez versiones.

**No hay exportación en claro.** Ofrecer un botón de «exportar sin cifrar»
garantiza que el perfil acabe en una carpeta de descargas sincronizada con la
nube. Quien quiera el JSON puede llamar a `to_dict()` a conciencia; lo que no
habrá es un camino cómodo hacia el descuido.

El resumen compartible **excluye el léxico**: el vocabulario de alguien delata su
oficio, su salud y su procedencia.

## 9. Comunidad: por qué esto es más privado que el aprendizaje federado

El federado no comparte datos crudos, comparte gradientes. Pero los gradientes
filtran: hay literatura consolidada sobre inversión de gradientes que reconstruye
ejemplos de entrenamiento a partir de las actualizaciones. Por eso el federado
serio necesita privacidad diferencial **y** agregación segura encima.

Una regla generalizada no tiene esa superficie. No es un residuo del
entrenamiento: es una afirmación lingüística legible que se puede leer, discutir
y rechazar *antes* de publicarla.

> Compartir conocimiento explícito es estrictamente más privado que compartir
> gradientes, y además es auditable, que los gradientes no lo son.

### Las defensas, por orden de importancia

1. **Umbral de k contribuyentes** (k=4). Una regla solo se publica si la
   respaldan k personas *distintas*. Una regla que propone alguien en solitario
   podría reflejar su idiolecto —o su obra rara— y es justo la que le señalaría.
   Es la defensa principal: comprensible sin saber estadística y sin coste de
   utilidad.
2. **Sin seudónimos en lo publicado.** Publicar quién apoya cada regla permitiría
   perfilar por el conjunto de reglas apoyadas.
3. **Disparadores acotados.** El único campo que admite palabras concretas está
   limitado a 40 caracteres y 4 palabras: cabe un lema, no una cita.
4. **Ruido diferencial**, secundario. Con ε=1 la desviación es ~1,4: despreciable
   en una regla con 500 apoyos, la mitad del valor en una con 5. **Justo donde
   más falta hace, más destroza la utilidad.** Por eso se ofrece encima del
   umbral k, nunca en su lugar.

### El laboratorio nunca toca material privado

Un texto que alguien subió para escucharlo no es material de experimentación.
`TextSource` **rechaza en el constructor** cualquier procedencia privada, y exige
atribución: «es de dominio público» sin fuente citada es una promesa, no una
verificación.

## 10. RGPD: derechos ejecutables

| Artículo | Derecho | Implementación |
|---|---|---|
| 15 | Acceso | `access_report()` |
| 17 | Supresión | `erase()` — destruye la clave, con comprobante |
| 20 | Portabilidad | `export_portable()` — JSON documentado y versionado |
| 21 | Oposición | `withdraw_consent()`, efecto inmediato |
| 22 | Decisiones automatizadas | `explain_decisions()` |
| 30 | Registro de tratamientos | `processing_record()` |

**El consentimiento es granular y todo empieza apagado.** Un único «acepto» que
cubra analítica, contribución y perfilado no es consentimiento informado: es una
casilla. El historial no se reescribe nunca, porque hay que poder demostrar qué
era lícito y cuándo.

**El comprobante de supresión declara lo que NO se pudo borrar.** La cadena de
auditoría se conserva: es el propio comprobante de que la supresión ocurrió, y su
integridad depende de no tener huecos. No contiene datos personales porque
`validate_metadata()` lo impide.

### Explicabilidad con alternativas

Una explicación que solo diga por qué salió A es una justificación a posteriori.
`Decision` incluye `alternatives`: por qué **no** salió B, que es lo que quiere
saber quien discrepa.

> `motor_tts`: se eligió «piper» porque es el único motor instalado que cubre el
> idioma del documento. Se tuvo en cuenta: idioma=ca. Descartado: «kokoro» no,
> porque no cubre el catalán. Decidido por: selector/1.0.

## 11. Lo que este sistema NO garantiza

Se repite al final porque es la parte que se olvida:

- **No protege frente a quien controla la máquina** mientras la sesión está
  abierta. Nada que se ejecute en un sistema ajeno puede prometerlo.
- **No aísla plugins de verdad** dentro del mismo proceso de Python.
- **No garantiza el borrado físico** en SSD ni en copy-on-write. La garantía es
  criptográfica.
- **No oculta que el servicio se usa.** Tiempos y consumo son observables.
- **No protege una contraseña débil.** scrypt encarece el ataque; no lo impide.
- **`wipe()` no garantiza borrar memoria.** Python mueve objetos, `str` es
  inmutable y el sistema puede paginar. Reduce la ventana; la garantía real es
  que lo sensible está cifrado.

## 12. Estado

**Implementado y probado** (110 tests entre `test_privacy.py` y
`test_knowledge.py`): cifrado con subclave por registro, jerarquía de claves,
almacén con separación de metadatos, sesión privada, borrado, auditoría
encadenada, ADN portable, capacidades de plugins, derechos RGPD, reglas
generalizadas con umbral k, revisión con reversión, laboratorio y benchmark.

**Diseñado, no construido:** integración del almacén con la base de datos actual,
aislamiento real de plugins en subproceso, servicio de aportaciones y su
interfaz, extracción de prosodia por alineación.

**Pendiente de revisión externa.** Nada de esto ha pasado una auditoría de
seguridad independiente. Hasta que ocurra, trátese como lo que es: un diseño
cuidadoso y probado por quien lo escribió, que es exactamente el tipo de revisión
que menos vale.
