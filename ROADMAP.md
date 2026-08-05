# Hoja de ruta

El orden responde a una idea: **primero que se pueda usar de verdad, luego que
mejore sola.** Un circuito comunitario montado sobre algo que una biblioteca no
puede desplegar no recogería nada.

Las fases no llevan fecha. Llevan condición de salida: qué tiene que ser cierto
para dar una por terminada. Un proyecto sostenido por voluntariado no puede
prometer calendarios, pero sí puede prometer en qué orden.

---

## Fase 0 — Que funcione (actual)

**Condición de salida:** una biblioteca puede desplegarlo y convertir su fondo
sin ayuda de quien lo desarrolla.

- [x] Conversión de PDF, EPUB, DOCX, ODT, Markdown, HTML, RTF, web y RSS
- [x] OCR automático de PDF escaneados
- [x] Síntesis con Kokoro y Piper, selección de motor por idioma
- [x] Exportación a `.m4b` con índice de capítulos, `.mp3` y formatos de texto
- [x] API REST, línea de comandos, carpeta vigilada e interfaz web
- [x] Despliegue con contenedores y perfiles opcionales
- [ ] Guía de despliegue verificada por alguien ajeno al proyecto
- [x] Sistema de diseño con contraste verificado por tests en los cuatro temas
- [x] Experiencia adaptativa: contraste, tamaño, densidad, movimiento y perfiles
- [x] Progressive Disclosure y navegación completa por teclado
- [x] Auditoría automática del HTML renderizado (semántica, ARIA, teclado)
- [x] Laboratorio de accesibilidad con simulaciones y auditoría en vivo
- [ ] Consejo de accesibilidad constituido, con mayoría de personas usuarias
- [ ] Validación con NVDA, JAWS, Narrator, VoiceOver, TalkBack y Orca
- [ ] Navegación por conmutador y control por voz
- [ ] Traducción de la interfaz a, como mínimo, inglés

## Fase 1 — Que se oiga bien

**Condición de salida:** en una prueba a ciegas, la narración de HearMe se
prefiere a la lectura plana del mismo motor en la mayoría de los pasajes.

- [x] Separación entre director de narración y motor de voz
- [x] Formato de partitura neutro, versionado y anclado al texto
- [x] Director por reglas como línea base sustituible
- [x] Adaptadores por motor que declaran lo que no pueden respetar
- [ ] Detección de diálogo y de quién habla, más allá de la tipografía
- [ ] Léxico de pronunciación por idioma (nombres propios, extranjerismos, cifras)
- [ ] Protocolo de evaluación a ciegas, con instrumentos y tamaño de muestra
- [ ] Medición de fatiga de escucha en sesiones largas

## Fase 2 — Que la comunidad la mejore

**Condición de salida:** el corpus tiene aportaciones validadas suficientes para
entrenar un director que gane a las reglas en evaluación a ciegas.

- [x] Modelo de aportaciones, revisión y admisión con cuórum ponderado
- [x] Defensas contra identidades fabricadas, auto-validación y voto duplicado
- [ ] Servicio de aportaciones y su interfaz de escucha y corrección
- [ ] Comparación por pares integrada en la escucha normal
- [ ] Ítems de control y cálculo de fiabilidad en producción
- [ ] Publicación trimestral del corpus, versionada y replicada
- [ ] Piloto en un solo idioma para medir cuántas aportaciones hacen falta

## Fase 2b — Que sea de fiar

**Condición de salida:** una biblioteca puede desplegarlo sin pasar por su
departamento jurídico, y una auditoría externa no encuentra nada grave.

- [x] Cifrado del contenido con subclave por registro y datos asociados
- [x] Jerarquía de claves: rotar la contraseña sin recifrar nada
- [x] Separación estricta de contenido y metadatos, con degradación
- [x] Sesión privada: clave solo en memoria, borrado criptográfico al cerrar
- [x] Auditoría encadenada y explicación de las decisiones automáticas
- [x] ADN de narración: personal, cifrado y portable entre motores
- [x] Capacidades declaradas por plugin y política de confianza cero
- [x] Derechos RGPD ejecutables (acceso, portabilidad, supresión, oposición)
- [ ] Integrar el almacén cifrado con la base de datos de trabajos
- [ ] Aislamiento real de plugins en subproceso (seccomp o contenedor)
- [ ] Auditoría de seguridad externa e independiente

## Fase 3 — Que aprenda

**Condición de salida:** el director entrenado está en producción y una
regresión puede revertirse en una versión.

- [x] Reglas generalizadas con umbral de k contribuyentes y ruido diferencial
- [x] Revisión comunitaria con historial, justificación y reversión
- [x] Laboratorio y benchmark abiertos, solo con textos públicos o sintéticos
- [ ] Entrenamiento del director sobre instantáneas del corpus, reproducible
- [ ] Aprendizaje por preferencias aplicado al director
- [ ] Extracción de prosodia por alineación de lecturas de referencia
- [ ] Promoción automatizada solo si gana la evaluación a ciegas
- [ ] Reversión al director anterior ante regresión detectada

## Fase 4 — Que llegue a todo el mundo

**Condición de salida:** una comunidad lingüística puede añadir su lengua sin
intervención del equipo original.

- [ ] Guía de incorporación de un idioma nuevo, de principio a fin
- [ ] ¿Transfiere el criterio narrativo entre idiomas? Medirlo y publicarlo
- [ ] Personalización en el dispositivo de quien escucha, sin enviar datos
- [ ] Sincronización de texto y voz para lectura acompañada
- [ ] Federación entre despliegues de distintas bibliotecas

---

## Lo que no vamos a hacer

Igual de informativo que lo anterior:

- **Clonación de voz.** El riesgo de suplantación supera con mucho el beneficio
  para lo que este proyecto quiere ser.
- **Servicio alojado de pago.** Que otros lo alojen si quieren; el proyecto es
  el software y el corpus.
- **Un corpus exclusivo.** El corpus es CC0 desde el primer día, incluso para
  proyectos rivales.
- **Telemetría sin consentimiento explícito.** Ni siquiera «anónima».
- **Depender de una API en la nube** en el camino de ejecución por defecto.

## Cómo cambia esta hoja de ruta

Se discute en incidencias públicas. Las prioridades las inclina el uso real:
una biblioteca que necesita algo para atender a su comunidad pesa más que una
función que parece elegante. Si algo de aquí te bloquea, dilo en una incidencia
— es la mejor forma de que suba.
