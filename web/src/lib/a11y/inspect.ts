/**
 * Inspección del árbol de accesibilidad en el navegador.
 *
 * Calcula, para un elemento, lo que una tecnología de asistencia percibiría:
 * su rol, su nombre accesible y su estado. Es lo que alimenta tanto la
 * previsualización de lectura como la auditoría en vivo del laboratorio.
 *
 * ## Advertencia que no se puede omitir
 *
 * **Esto no es un lector de pantalla.** Es una aproximación al algoritmo
 * `accname` y al mapeo de roles implícitos, suficiente para cazar el fallo
 * mecánico —un control sin nombre, un rol mal puesto— pero incapaz de decir
 * cómo suena algo en contexto, en qué orden se lee, si un anuncio interrumpe o
 * llega tarde, o si la verbosidad hace la interfaz insoportable a los diez
 * minutos.
 *
 * Existe para que ninguna sesión de validación con personas se gaste en algo
 * que una máquina podía haber cazado antes. Nunca para sustituirla.
 */

/** Roles implícitos por etiqueta. Solo los que aparecen en esta interfaz. */
const IMPLICIT_ROLES: Record<string, string> = {
	a: 'enlace',
	button: 'botón',
	h1: 'encabezado nivel 1',
	h2: 'encabezado nivel 2',
	h3: 'encabezado nivel 3',
	h4: 'encabezado nivel 4',
	header: 'banner',
	footer: 'pie',
	main: 'contenido principal',
	nav: 'navegación',
	section: 'región',
	form: 'formulario',
	ul: 'lista',
	ol: 'lista',
	li: 'elemento de lista',
	select: 'cuadro combinado',
	textarea: 'edición',
	audio: 'reproductor de audio',
	fieldset: 'grupo',
	dialog: 'diálogo',
	output: 'salida'
};

const INPUT_ROLES: Record<string, string> = {
	text: 'edición',
	range: 'deslizador',
	checkbox: 'casilla',
	radio: 'opción',
	file: 'selector de archivo',
	search: 'búsqueda'
};

/** Traducción de roles ARIA explícitos a lo que anunciaría un lector en español. */
const ARIA_ROLE_NAMES: Record<string, string> = {
	button: 'botón',
	link: 'enlace',
	radio: 'opción',
	radiogroup: 'grupo de opciones',
	checkbox: 'casilla',
	dialog: 'diálogo',
	region: 'región',
	progressbar: 'barra de progreso',
	alert: 'alerta',
	status: 'estado',
	list: 'lista',
	listitem: 'elemento de lista',
	group: 'grupo',
	main: 'contenido principal',
	banner: 'banner',
	navigation: 'navegación'
};

export function isHidden(element: Element): boolean {
	if (element.closest('[aria-hidden="true"]')) return true;
	const style = getComputedStyle(element);
	return style.display === 'none' || style.visibility === 'hidden';
}

/** Rol efectivo: el explícito manda sobre el implícito. */
export function computeRole(element: Element): string {
	const explicito = element.getAttribute('role');
	if (explicito) return ARIA_ROLE_NAMES[explicito] ?? explicito;

	const tag = element.tagName.toLowerCase();
	if (tag === 'input') {
		return INPUT_ROLES[(element as HTMLInputElement).type] ?? 'edición';
	}
	if (tag === 'a' && !element.hasAttribute('href')) return '';
	return IMPLICIT_ROLES[tag] ?? '';
}

/**
 * Nombre accesible, siguiendo el orden de precedencia de `accname`.
 *
 * Simplificado a propósito: el algoritmo completo recorre subárboles con
 * reglas de recursión que aquí no aportan nada. Lo que sí respeta es el orden
 * —labelledby, label, label envolvente, contenido, title— porque equivocarlo
 * daría un nombre distinto del que anuncia el lector, y entonces la
 * previsualización mentiría.
 */
export function computeAccessibleName(element: Element): string {
	const labelledby = element.getAttribute('aria-labelledby');
	if (labelledby) {
		const textos = labelledby
			.split(/\s+/)
			.map((id) => document.getElementById(id)?.textContent?.trim())
			.filter(Boolean);
		if (textos.length) return textos.join(' ');
	}

	const label = element.getAttribute('aria-label');
	if (label?.trim()) return label.trim();

	if (element.tagName === 'INPUT' || element.tagName === 'SELECT') {
		const id = element.getAttribute('id');
		if (id) {
			const asociada = document.querySelector(`label[for="${CSS.escape(id)}"]`);
			if (asociada?.textContent?.trim()) return asociada.textContent.trim();
		}
		const envolvente = element.closest('label');
		if (envolvente?.textContent?.trim()) return envolvente.textContent.trim();
	}

	if (element.tagName === 'IMG') return element.getAttribute('alt') ?? '';

	// Contenido propio, descontando lo marcado como decorativo.
	const clon = element.cloneNode(true) as Element;
	clon.querySelectorAll('[aria-hidden="true"]').forEach((n) => n.remove());
	const texto = clon.textContent?.replace(/\s+/g, ' ').trim();
	if (texto) return texto;

	return element.getAttribute('title')?.trim() ?? '';
}

/** Estados que un lector anuncia junto al nombre. */
export function computeStates(element: Element): string[] {
	const estados: string[] = [];
	const bool = (attr: string, si: string, no?: string) => {
		const v = element.getAttribute(attr);
		if (v === 'true') estados.push(si);
		else if (v === 'false' && no) estados.push(no);
	};

	bool('aria-expanded', 'expandido', 'contraído');
	bool('aria-checked', 'seleccionado', 'no seleccionado');
	bool('aria-pressed', 'activado', 'desactivado');
	if (element.hasAttribute('disabled') || element.getAttribute('aria-disabled') === 'true') {
		estados.push('no disponible');
	}
	if (element.getAttribute('aria-current')) estados.push('actual');

	const rol = element.getAttribute('role');
	if (rol === 'progressbar') {
		const ahora = element.getAttribute('aria-valuenow');
		estados.push(ahora ? `${ahora} por ciento` : 'progreso indeterminado');
	}
	return estados;
}

/**
 * Lo que anunciaría, aproximadamente, un lector de pantalla al enfocar algo.
 *
 * El orden —nombre, rol, estado— es el habitual en NVDA y VoiceOver. JAWS y
 * Narrator varían, y TalkBack añade pistas táctiles. Otra razón por la que esto
 * orienta pero no certifica.
 */
export function announce(element: Element): string {
	const nombre = computeAccessibleName(element);
	const rol = computeRole(element);
	const estados = computeStates(element);

    const partes = [nombre, rol, ...estados].filter(Boolean);
	return partes.length ? partes.join(', ') : '(sin nombre accesible)';
}

// --- auditoría en vivo --------------------------------------------------------

export type Severity = 'error' | 'aviso';

export interface Finding {
	severity: Severity;
	criterion: string;
	message: string;
	element: Element;
}

const FOCUSABLE =
	'a[href], button, input:not([type="hidden"]), select, textarea, [tabindex]:not([tabindex="-1"])';

/**
 * Recorre el DOM real buscando fallos mecánicos.
 *
 * Complementa a `tests/test_accessibility.py`, que audita el HTML renderizado
 * en el servidor: esto ve además lo que solo existe tras interactuar —diálogos
 * abiertos, paneles desplegados— y las medidas reales tras aplicar el CSS, que
 * es donde se detectan los objetivos táctiles pequeños.
 */
export function auditLive(root: ParentNode = document): Finding[] {
	const hallazgos: Finding[] = [];

	for (const el of root.querySelectorAll(FOCUSABLE)) {
		if (isHidden(el)) continue;

		if (!computeAccessibleName(el)) {
			hallazgos.push({
				severity: 'error',
				criterion: 'WCAG 4.1.2',
				message: `<${el.tagName.toLowerCase()}> sin nombre accesible: se anunciará solo como su rol`,
				element: el
			});
		}

		// WCAG 2.2 · 2.5.8. Se mide el rectángulo real, ya con el CSS aplicado.
		const caja = el.getBoundingClientRect();
		if (caja.width > 0 && (caja.width < 24 || caja.height < 24)) {
			hallazgos.push({
				severity: 'aviso',
				criterion: 'WCAG 2.5.8',
				message: `objetivo de ${Math.round(caja.width)}×${Math.round(caja.height)} px; el mínimo es 24×24`,
				element: el
			});
		}
	}

	for (const img of root.querySelectorAll('img')) {
		if (!img.hasAttribute('alt')) {
			hallazgos.push({
				severity: 'error',
				criterion: 'WCAG 1.1.1',
				message: 'imagen sin atributo alt (usa alt="" si es decorativa)',
				element: img
			});
		}
	}

	for (const attr of ['aria-labelledby', 'aria-describedby', 'aria-controls']) {
		for (const el of root.querySelectorAll(`[${attr}]`)) {
			for (const id of el.getAttribute(attr)!.split(/\s+/)) {
				if (!document.getElementById(id)) {
					hallazgos.push({
						severity: 'error',
						criterion: 'WCAG 1.3.1',
						message: `${attr}="${id}" no apunta a ningún elemento: el atributo queda sin efecto`,
						element: el
					});
				}
			}
		}
	}

	const svgRuidosos = [...root.querySelectorAll('svg')].filter(
		(s) => !s.closest('[aria-hidden="true"]') && !s.getAttribute('aria-label') && !s.querySelector('title')
	);
	for (const svg of svgRuidosos) {
		hallazgos.push({
			severity: 'aviso',
			criterion: 'WCAG 1.1.1',
			message: 'SVG que se anunciará sin aportar nada; ponle aria-hidden="true"',
			element: svg
		});
	}

	return hallazgos;
}
