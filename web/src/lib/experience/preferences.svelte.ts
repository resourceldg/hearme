/**
 * Adaptive Experience Engine.
 *
 * ## La idea que ordena todo esto
 *
 * No hay «modo accesible». Hay una interfaz con controles, y todo el mundo tiene
 * los mismos. Quien nunca abra este panel debe recibir ya una experiencia
 * excelente; quien lo abra encontrará los mismos ajustes tanto si tiene baja
 * visión como si simplemente le gusta el texto más grande.
 *
 * Un «modo accesibilidad» separado hace tres daños a la vez: obliga a la persona
 * a clasificarse para usar el producto, convierte lo básico en concesión, y
 * garantiza que el modo principal se diseñe sin pensar en nadie. Aquí los
 * perfiles son **presets sobre los mismos mandos**, no un carril aparte.
 *
 * ## Por qué se guarda en local y nunca se envía
 *
 * Estas preferencias son datos personales, y de los delicados: alguien con
 * contraste alto, fuente grande, movimiento desactivado y perfil de dislexia
 * está declarando una discapacidad sin haberlo dicho. Es categoría especial del
 * RGPD.
 *
 * Por eso viven en `localStorage` y no salen de ahí. Ni telemetría, ni
 * sincronización, ni «mejoramos el producto con datos de uso». Coherente con
 * `hearme.privacy`: si el ADN de narración va cifrado por revelar cómo lee
 * alguien, sería incoherente enviar sus ajustes visuales en claro.
 *
 * ## Cómo se aplica
 *
 * Cada preferencia se escribe como atributo `data-*` en `<html>`. El CSS
 * reacciona por sí solo (ver `tokens.css`). Ningún componente conoce este
 * módulo: se puede cambiar el motor entero sin tocar la interfaz.
 */

import { browser } from '$app/environment';

export type Theme = 'system' | 'dark' | 'light';
export type Contrast = 'standard' | 'high';
export type Density = 'compact' | 'normal' | 'comfortable';
export type Motion = 'system' | 'full' | 'reduced' | 'none';
export type Targets = 'normal' | 'large';
export type Reading = 'default' | 'dyslexia' | 'focus';
export type Expertise = 'guided' | 'full';

export interface Preferences {
	theme: Theme;
	contrast: Contrast;
	/** Multiplicador del tamaño base. 1 = 16 px. */
	fontScale: number;
	density: Density;
	motion: Motion;
	targets: Targets;
	reading: Reading;
	/** Grosor del anillo de foco en px. WCAG 2.2 · 2.4.13. */
	focusWidth: number;
	/** Cuánta interfaz se muestra de partida. Ver Progressive Disclosure. */
	expertise: Expertise;
	/** Velocidad de reproducción por defecto del audio generado. */
	playbackRate: number;
	/** Perfil aplicado por última vez, solo para poder mostrarlo como activo. */
	profile: string | null;
	/**
	 * Voces marcadas como favoritas. Se guardan aquí, en local, por lo mismo que
	 * el resto: qué voz elige alguien puede revelar su procedencia o su lengua
	 * materna, y eso no tiene por qué salir de su navegador.
	 */
	favoriteVoices: string[];
	/** Voz por defecto para cada idioma. El asistente la respeta sin preguntar. */
	defaultVoices: Record<string, string>;
	/** Estilo narrativo preferido. Punto de partida, no imposición. */
	defaultStyle: string;
}

export const DEFAULTS: Preferences = {
	theme: 'system',
	contrast: 'standard',
	fontScale: 1,
	density: 'normal',
	motion: 'system',
	targets: 'normal',
	reading: 'default',
	focusWidth: 2,
	// Arranca guiado a propósito. Quien sabe lo que hace tarda dos segundos en
	// cambiarlo; quien no, se habría ido antes de encontrar el botón entre veinte.
	expertise: 'guided',
	playbackRate: 1,
	profile: null,
	favoriteVoices: [],
	defaultVoices: {},
	defaultStyle: 'neutral'
};

/** Límites. Fuera de ellos la interfaz deja de ser usable, y eso no ayuda a nadie. */
export const LIMITS = {
	fontScale: { min: 0.875, max: 2, step: 0.125 },
	focusWidth: { min: 2, max: 6, step: 1 },
	playbackRate: { min: 0.5, max: 2, step: 0.05 }
} as const;

const STORAGE_KEY = 'hearme.preferences.v1';

function clamp(value: number, { min, max }: { min: number; max: number }): number {
	return Math.min(max, Math.max(min, value));
}

function sanitize(raw: Partial<Preferences>): Preferences {
	// Se valida lo que viene de localStorage: puede estar editado a mano, venir
	// de una versión anterior o estar corrupto, y una preferencia inválida no
	// puede dejar la interfaz inservible.
	const oneOf = <T extends string>(value: unknown, allowed: readonly T[], fallback: T): T =>
		allowed.includes(value as T) ? (value as T) : fallback;

	return {
		theme: oneOf(raw.theme, ['system', 'dark', 'light'] as const, DEFAULTS.theme),
		contrast: oneOf(raw.contrast, ['standard', 'high'] as const, DEFAULTS.contrast),
		fontScale: clamp(Number(raw.fontScale) || DEFAULTS.fontScale, LIMITS.fontScale),
		density: oneOf(raw.density, ['compact', 'normal', 'comfortable'] as const, DEFAULTS.density),
		motion: oneOf(raw.motion, ['system', 'full', 'reduced', 'none'] as const, DEFAULTS.motion),
		targets: oneOf(raw.targets, ['normal', 'large'] as const, DEFAULTS.targets),
		reading: oneOf(raw.reading, ['default', 'dyslexia', 'focus'] as const, DEFAULTS.reading),
		focusWidth: clamp(Number(raw.focusWidth) || DEFAULTS.focusWidth, LIMITS.focusWidth),
		expertise: oneOf(raw.expertise, ['guided', 'full'] as const, DEFAULTS.expertise),
		playbackRate: clamp(Number(raw.playbackRate) || DEFAULTS.playbackRate, LIMITS.playbackRate),
		profile: typeof raw.profile === 'string' ? raw.profile : null,
		favoriteVoices: Array.isArray(raw.favoriteVoices)
			? raw.favoriteVoices.filter((v): v is string => typeof v === 'string')
			: [],
		defaultVoices:
			raw.defaultVoices && typeof raw.defaultVoices === 'object' ? { ...raw.defaultVoices } : {},
		defaultStyle: typeof raw.defaultStyle === 'string' ? raw.defaultStyle : DEFAULTS.defaultStyle
	};
}

/**
 * Perfiles: atajos, no compartimentos.
 *
 * Cada uno es un puñado de ajustes que ya existen. Se puede aplicar uno y luego
 * cambiar cualquier cosa a mano —el perfil solo deja de constar como activo—,
 * porque nadie encaja exactamente en una etiqueta.
 *
 * Los nombres describen **qué hacen**, no a quién van dirigidos: «Texto amplio»
 * antes que «Baja visión». Quien lo necesita lo encuentra igual, y quien
 * simplemente lee de lejos no tiene que identificarse con un diagnóstico para
 * usarlo.
 */
export interface Profile {
	id: string;
	name: string;
	/** Qué cambia, en lenguaje llano. Se muestra antes de aplicarlo. */
	summary: string;
	preferences: Partial<Preferences>;
}

export const PROFILES: Profile[] = [
	{
		id: 'reading',
		name: 'Lectura larga',
		summary: 'Más aire entre líneas, menos elementos a la vista y animaciones suaves.',
		preferences: { density: 'comfortable', reading: 'focus', motion: 'reduced', fontScale: 1.125 }
	},
	{
		id: 'study',
		name: 'Estudio',
		summary: 'Todo a mano y compacto, para ver muchos trabajos a la vez.',
		preferences: { density: 'compact', expertise: 'full', fontScale: 1 }
	},
	{
		id: 'large-text',
		name: 'Texto amplio',
		summary: 'Tipografía y objetivos grandes, contraste alto y foco muy visible.',
		preferences: {
			fontScale: 1.5,
			contrast: 'high',
			targets: 'large',
			focusWidth: 4,
			density: 'comfortable'
		}
	},
	{
		id: 'dyslexia',
		name: 'Lectura cómoda',
		summary: 'Más espacio entre letras y palabras, interlínea amplia y sin movimiento.',
		preferences: {
			reading: 'dyslexia',
			density: 'comfortable',
			motion: 'none',
			fontScale: 1.125
		}
	},
	{
		id: 'calm',
		name: 'Sin distracciones',
		summary: 'Cero animación, interfaz mínima y objetivos grandes.',
		preferences: { motion: 'none', expertise: 'guided', targets: 'large', density: 'comfortable' }
	}
];

/**
 * Estado reactivo de las preferencias.
 *
 * Se expone como una clase con runas de Svelte 5 en vez de un store clásico
 * porque el consumo es siempre `prefs.current.x`: más directo de leer en las
 * plantillas y sin suscripciones que limpiar.
 */
class PreferenceStore {
	current = $state<Preferences>({ ...DEFAULTS });
	/** True hasta que se ha leído lo guardado. Evita el parpadeo inicial. */
	hydrated = $state(false);

	load(): void {
		if (!browser) return;
		try {
			const raw = localStorage.getItem(STORAGE_KEY);
			if (raw) this.current = sanitize(JSON.parse(raw));
		} catch {
			// Un almacenamiento ilegible o bloqueado (modo privado del navegador,
			// política corporativa) no puede impedir usar la aplicación.
		}
		this.hydrated = true;
		this.apply();
	}

	set<K extends keyof Preferences>(key: K, value: Preferences[K]): void {
		// Tocar un mando a mano desactiva el perfil: seguir mostrándolo como
		// activo mentiría sobre el estado real.
		const clearsProfile = key !== 'profile';
		this.current = {
			...this.current,
			[key]: value,
			...(clearsProfile ? { profile: null } : {})
		};
		this.persist();
		this.apply();
	}

	applyProfile(id: string): void {
		const profile = PROFILES.find((p) => p.id === id);
		if (!profile) return;
		this.current = sanitize({ ...this.current, ...profile.preferences, profile: id });
		this.persist();
		this.apply();
	}

	/** Alterna una voz favorita. No toca el perfil: no es un ajuste de apariencia. */
	toggleFavorite(voiceId: string): void {
		const favoritas = this.current.favoriteVoices;
		this.current = {
			...this.current,
			favoriteVoices: favoritas.includes(voiceId)
				? favoritas.filter((v) => v !== voiceId)
				: [...favoritas, voiceId]
		};
		this.persist();
	}

	/** Fija la voz por defecto de un idioma, o la quita si se pasa null. */
	setDefaultVoice(language: string, voiceId: string | null): void {
		const mapa = { ...this.current.defaultVoices };
		if (voiceId) mapa[language] = voiceId;
		else delete mapa[language];
		this.current = { ...this.current, defaultVoices: mapa };
		this.persist();
	}

	reset(): void {
		this.current = { ...DEFAULTS };
		this.persist();
		this.apply();
	}

	/** Escribe el estado en `<html>`. Único punto de contacto con el DOM. */
	apply(): void {
		if (!browser) return;
		const root = document.documentElement;
		const p = this.current;

		const theme =
			p.theme === 'system'
				? window.matchMedia('(prefers-color-scheme: light)').matches
					? 'light'
					: 'dark'
				: p.theme;

		root.dataset.theme = theme;
		root.dataset.contrast = p.contrast;
		root.dataset.density = p.density;
		root.dataset.motion = p.motion;
		root.dataset.targets = p.targets;
		root.dataset.reading = p.reading;
		root.dataset.expertise = p.expertise;
		root.style.setProperty('--font-scale', String(p.fontScale));
		root.style.setProperty('--focus-width', `${p.focusWidth}px`);
	}

	persist(): void {
		if (!browser) return;
		try {
			localStorage.setItem(STORAGE_KEY, JSON.stringify(this.current));
		} catch {
			// Sin persistencia se pierde al recargar, pero la sesión sigue viva.
		}
	}

	/**
	 * Resumen legible del estado. Se enseña en el panel para que nadie tenga que
	 * deducir qué está activo leyendo cinco controles.
	 */
	get summary(): string {
		const p = this.current;
		const partes: string[] = [];
		if (p.theme !== 'system') partes.push(p.theme === 'dark' ? 'oscuro' : 'claro');
		if (p.contrast === 'high') partes.push('contraste alto');
		if (p.fontScale !== 1) partes.push(`texto al ${Math.round(p.fontScale * 100)}%`);
		if (p.density !== 'normal') partes.push(p.density === 'compact' ? 'compacto' : 'espaciado');
		if (p.motion === 'none') partes.push('sin animación');
		if (p.reading !== 'default') partes.push('lectura adaptada');
		return partes.length ? partes.join(' · ') : 'ajustes por defecto';
	}
}

export const preferences = new PreferenceStore();

/**
 * Script que se inyecta antes de pintar para evitar el destello de tema.
 *
 * Sin esto, la página se pinta en oscuro y salta a claro cuando hidrata: un
 * fogonazo blanco que, a quien tiene fotosensibilidad o migraña, le arruina la
 * sesión. Se ejecuta síncrono en <head>, antes del primer píxel.
 */
export const BOOTSTRAP_SCRIPT = `
(function () {
  try {
    var p = JSON.parse(localStorage.getItem('${STORAGE_KEY}') || '{}');
    var r = document.documentElement;
    var t = p.theme && p.theme !== 'system' ? p.theme
      : (window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
    r.dataset.theme = t;
    if (p.contrast) r.dataset.contrast = p.contrast;
    if (p.density) r.dataset.density = p.density;
    if (p.motion) r.dataset.motion = p.motion;
    if (p.targets) r.dataset.targets = p.targets;
    if (p.reading) r.dataset.reading = p.reading;
    if (p.expertise) r.dataset.expertise = p.expertise;
    if (p.fontScale) r.style.setProperty('--font-scale', String(p.fontScale));
    if (p.focusWidth) r.style.setProperty('--focus-width', p.focusWidth + 'px');
  } catch (e) {}
})();
`;
