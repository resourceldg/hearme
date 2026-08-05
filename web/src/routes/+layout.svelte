<!--
  Estilos globales y arranque del Adaptive Experience Engine.

  Aquí vive solo lo que tiene que ser global: el reset, la tipografía base y
  —sobre todo— el tratamiento del foco, que es la pieza de accesibilidad que más
  se rompe al aplicar un diseño «premium». La tentación de quitar el `outline`
  porque «afea» ha dejado sin usar más interfaces que ningún otro detalle.
-->
<script lang="ts">
	import '$lib/design/tokens.css';
	import { preferences } from '$lib/experience/preferences.svelte';
	import { onMount } from 'svelte';

	let { children } = $props();

	/**
	 * Laboratorio de accesibilidad, solo en desarrollo.
	 *
	 * Se carga con `import()` dinámico y no con un import normal: con el estático,
	 * aunque el componente nunca se renderice, su CSS acaba en el bundle de
	 * producción. `import.meta.env.DEV` es una constante que Vite sustituye al
	 * compilar, así que en producción esta rama desaparece entera —y con ella el
	 * chunk— en vez de viajar sin usarse.
	 */
	let Lab = $state<typeof import('$lib/components/AccessibilityLab.svelte').default | null>(null);

	onMount(() => {
		preferences.load();
		if (import.meta.env.DEV) {
			import('$lib/components/AccessibilityLab.svelte').then((m) => (Lab = m.default));
		}
		// Si el tema sigue el sistema, hay que reaccionar a que cambie en caliente
		// (muchos sistemas alternan claro/oscuro por hora del día).
		const media = window.matchMedia('(prefers-color-scheme: light)');
		const alSistemaCambiar = () => {
			if (preferences.current.theme === 'system') preferences.apply();
		};
		media.addEventListener('change', alSistemaCambiar);
		return () => media.removeEventListener('change', alSistemaCambiar);
	});
</script>

<a class="skip-link" href="#contenido">Saltar al contenido</a>

{@render children()}

{#if Lab}
	<Lab />
{/if}

<style>
	/* --- Enlace de salto ---------------------------------------------------
	 * WCAG 2.4.1 (Bypass Blocks). Invisible hasta recibir foco, y entonces
	 * plenamente visible: no basta con que exista, tiene que verse cuando toca.
	 */
	.skip-link {
		position: absolute;
		top: var(--space-2);
		left: var(--space-2);
		z-index: 100;
		padding: var(--space-2) var(--space-4);
		background: var(--accent-solid);
		color: var(--accent-contrast);
		border-radius: var(--radius);
		font-weight: 600;
		text-decoration: none;
		transform: translateY(-200%);
		transition: transform var(--duration) var(--ease);
	}
	.skip-link:focus-visible {
		transform: translateY(0);
	}

	:global(*),
	:global(*::before),
	:global(*::after) {
		box-sizing: border-box;
	}

	:global(html) {
		/* Sin esto, un ancla lleva el foco justo al borde superior y el encabezado
		   fijo lo tapa: WCAG 2.2 · 2.4.11 (Focus Not Obscured). */
		scroll-padding-top: var(--space-6);
		-webkit-text-size-adjust: 100%;
	}

	:global(body) {
		margin: 0;
		background: var(--bg);
		color: var(--text);
		font-family: var(--font-sans);
		font-size: var(--font-md);
		line-height: var(--leading);
		letter-spacing: var(--tracking);
		word-spacing: var(--word-spacing);
		-webkit-font-smoothing: antialiased;
		text-rendering: optimizeLegibility;
		transition:
			background var(--duration) var(--ease),
			color var(--duration) var(--ease);
	}

	/* --- Foco ---------------------------------------------------------------
	 * `:focus-visible` y no `:focus`: el anillo aparece al navegar con teclado y
	 * no al pulsar con el ratón, que es lo que la gente encuentra ruidoso. Se
	 * aplica a todo, incluidos los elementos con tabindex.
	 *
	 * El doble anillo —color de acento más contorno oscuro— garantiza que el
	 * foco se vea sobre cualquier fondo, incluido el propio acento.
	 */
	:global(:focus-visible) {
		outline: var(--focus-width) solid var(--focus-color);
		outline-offset: var(--focus-offset);
		border-radius: var(--radius-sm);
	}

	:global(:focus:not(:focus-visible)) {
		outline: none;
	}

	/* --- Tipografía base ---------------------------------------------------- */

	:global(h1),
	:global(h2),
	:global(h3) {
		line-height: var(--leading-tight);
		letter-spacing: -0.015em;
		font-weight: 650;
		text-wrap: balance;
	}

	:global(p) {
		text-wrap: pretty;
	}

	:global(button),
	:global(input),
	:global(select),
	:global(textarea) {
		font: inherit;
		letter-spacing: inherit;
	}

	:global(button) {
		cursor: pointer;
	}

	:global(button:disabled) {
		cursor: not-allowed;
		opacity: 0.5;
	}

	/* --- Regla de oro del movimiento ---------------------------------------
	 * Última línea de defensa: aunque algún componente olvide usar --motion, si
	 * el sistema pide menos movimiento, aquí se corta. Se usa 0.01ms en vez de 0
	 * para que los eventos `animationend` sigan disparándose y nada se quede a
	 * medias esperando una animación que nunca termina.
	 */
	@media (prefers-reduced-motion: reduce) {
		:global(:root:not([data-motion='full']) *) {
			animation-duration: 0.01ms !important;
			animation-iteration-count: 1 !important;
			transition-duration: 0.01ms !important;
			scroll-behavior: auto !important;
		}
	}

	:global(:root[data-motion='none'] *) {
		animation-duration: 0.01ms !important;
		animation-iteration-count: 1 !important;
		transition-duration: 0.01ms !important;
	}

	/* --- Utilidad ----------------------------------------------------------
	 * Oculta visualmente sin sacar del árbol de accesibilidad. `display:none`
	 * habría eliminado el texto también para quien usa lector de pantalla.
	 */
	:global(.sr-only) {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		margin: -1px;
		overflow: hidden;
		clip-path: inset(50%);
		white-space: nowrap;
		border: 0;
	}
</style>
