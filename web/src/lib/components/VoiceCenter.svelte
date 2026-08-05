<!--
  Voice Center: un único sitio donde vive todo lo relativo a la voz.

  ## Por qué existe

  Antes, elegir voz se hacía dentro del formulario de conversión, documento a
  documento. Eso obliga a repetir la misma decisión cada vez y no deja sitio para
  las decisiones duraderas: cuál es *tu* voz en español, cuáles te gustan, con
  qué estilo escuchas normalmente.

  Aquí se separan los dos horizontes:

  - **Por documento** (en el asistente): qué idioma, qué voz para *este* texto.
  - **Duradero** (aquí): tus favoritas, tu voz por defecto en cada idioma, tu
    estilo habitual. El asistente los respeta sin volver a preguntar.

  ## Lo que aprende y lo que no

  El sistema recuerda lo que eliges **explícitamente** aquí. No deduce nada de tu
  comportamiento ni cambia una preferencia por su cuenta: si algún día tu voz por
  defecto cambia, es porque la cambiaste tú. Todo es visible en esta pantalla, y
  quitarlo es un clic.

  Nada de esto sale del navegador. Qué voz elige alguien puede revelar su
  procedencia o su lengua materna.
-->
<script lang="ts">
	import VoicePicker from '$lib/components/VoicePicker.svelte';
	import Segmented from '$lib/components/Segmented.svelte';
	import { getVoices, type Voice } from '$lib/api';
	import { preferences } from '$lib/experience/preferences.svelte';

	interface Props {
		open: boolean;
		onclose: () => void;
	}

	let { open, onclose }: Props = $props();

	let byLanguage = $state<Record<string, Voice[]>>({});
	let languages = $state<string[]>([]);
	let activeLanguage = $state('');
	let loading = $state(false);
	let error = $state('');
	let dialog = $state<HTMLDivElement | null>(null);
	let previouslyFocused: HTMLElement | null = null;

	const prefs = $derived(preferences.current);
	const voices = $derived(byLanguage[activeLanguage] ?? []);
	const defaultVoice = $derived(prefs.defaultVoices[activeLanguage] ?? null);

	const LANGUAGE_NAMES: Record<string, string> = {
		es: 'Español', en: 'Inglés', fr: 'Francés', de: 'Alemán', it: 'Italiano',
		pt: 'Portugués', ca: 'Catalán', ja: 'Japonés', zh: 'Chino', hi: 'Hindi',
		nl: 'Neerlandés', pl: 'Polaco', ru: 'Ruso', tr: 'Turco', sv: 'Sueco',
		da: 'Danés', no: 'Noruego', fi: 'Finés', el: 'Griego', cs: 'Checo',
		ro: 'Rumano', hu: 'Húngaro', ar: 'Árabe', vi: 'Vietnamita', fa: 'Persa',
		uk: 'Ucraniano'
	};
	const langName = (code: string) => LANGUAGE_NAMES[code] ?? code;

	const STYLES = [
		{ value: 'neutral', label: 'Neutro' },
		{ value: 'novel', label: 'Novela' },
		{ value: 'poetry', label: 'Poesía' },
		{ value: 'technical', label: 'Técnico' },
		{ value: 'academic', label: 'Académico' },
		{ value: 'children', label: 'Infantil' },
		{ value: 'lecture', label: 'Conferencia' }
	];

	$effect(() => {
		if (!open || languages.length) return;
		loading = true;
		getVoices()
			.then((c) => {
				byLanguage = c.by_language;
				languages = c.languages;
				// Se abre por un idioma que ya tenga preferencia; si no, el primero.
				activeLanguage =
					c.languages.find((l) => prefs.defaultVoices[l]) ?? c.languages[0] ?? '';
			})
			.catch((e) => (error = e instanceof Error ? e.message : String(e)))
			.finally(() => (loading = false));
	});

	$effect(() => {
		if (!open) return;
		previouslyFocused = document.activeElement as HTMLElement;
		queueMicrotask(() => dialog?.querySelector<HTMLElement>('[data-autofocus]')?.focus());
		return () => previouslyFocused?.focus();
	});

	function onkeydown(event: KeyboardEvent) {
		if (event.key === 'Escape') {
			onclose();
			return;
		}
		if (event.key !== 'Tab' || !dialog) return;
		const focusables = [
			...dialog.querySelectorAll<HTMLElement>(
				'button:not([disabled]), [href], input, select, [tabindex]:not([tabindex="-1"])'
			)
		].filter((el) => el.offsetParent !== null);
		if (!focusables.length) return;
		const [primero] = focusables;
		const ultimo = focusables[focusables.length - 1];
		if (event.shiftKey && document.activeElement === primero) {
			event.preventDefault();
			ultimo.focus();
		} else if (!event.shiftKey && document.activeElement === ultimo) {
			event.preventDefault();
			primero.focus();
		}
	}
</script>

<svelte:window on:keydown={open ? onkeydown : undefined} />

{#if open}
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="scrim" onclick={onclose}></div>

	<div bind:this={dialog} class="dialog" role="dialog" aria-modal="true" aria-labelledby="vc-title">
		<header>
			<div>
				<h2 id="vc-title">Voces</h2>
				<p class="sub">Tus favoritas y la voz que usarás por defecto en cada idioma.</p>
			</div>
			<button type="button" class="icon" onclick={onclose} aria-label="Cerrar" data-autofocus>
				✕
			</button>
		</header>

		<div class="body">
			{#if error}
				<div class="alert" role="alert">
					<strong>No se pudo cargar el catálogo de voces.</strong>
					<span>{error}</span>
					<span>Comprueba que el servicio está en marcha y vuelve a abrir este panel.</span>
				</div>
			{:else if loading}
				<p class="muted">Cargando voces…</p>
			{:else if !languages.length}
				<div class="alert" role="alert">
					<strong>No hay ningún motor de voz instalado.</strong>
					<span>Sin motor no se puede narrar nada.</span>
					<span>Pide a quien administra el servicio que instale Piper o Kokoro.</span>
				</div>
			{:else}
				<section aria-labelledby="vc-style">
					<h3 id="vc-style">Estilo habitual</h3>
					<p class="note">
						Cómo se lee: dónde respira y a qué ritmo. El asistente parte de este y puedes
						cambiarlo en cada documento.
					</p>
					<Segmented
						legend="Estilo por defecto"
						hideLegend
						value={prefs.defaultStyle}
						options={STYLES}
						onchange={(v) => preferences.set('defaultStyle', v)}
					/>
				</section>

				<section aria-labelledby="vc-lang">
					<h3 id="vc-lang">Voz por idioma</h3>
					<p class="note">
						Elige tu voz para cada idioma. El asistente la usará sin volver a preguntar.
					</p>

					<div class="langs" role="tablist" aria-label="Idiomas">
						{#each languages as code (code)}
							<button
								type="button"
								role="tab"
								aria-selected={code === activeLanguage}
								class="lang"
								class:on={code === activeLanguage}
								onclick={() => (activeLanguage = code)}
							>
								{langName(code)}
								{#if prefs.defaultVoices[code]}<span class="dot" aria-label="con voz fijada"
									></span>{/if}
							</button>
						{/each}
					</div>

					{#if defaultVoice}
						<p class="current">
							Voz por defecto en {langName(activeLanguage)}:
							<strong>{voices.find((v) => v.id === defaultVoice)?.display_name ?? defaultVoice}</strong>
							<button
								type="button"
								class="clear"
								onclick={() => preferences.setDefaultVoice(activeLanguage, null)}
							>
								Quitar
							</button>
						</p>
					{:else}
						<p class="note">
							Sin voz fijada: se usará la más natural disponible. Elige una para fijarla.
						</p>
					{/if}

					<VoicePicker
						{voices}
						language={activeLanguage}
						selected={defaultVoice}
						onselect={(v) => preferences.setDefaultVoice(activeLanguage, v)}
						favorites={prefs.favoriteVoices}
						ontogglefavorite={(v) => preferences.toggleFavorite(v)}
					/>
				</section>
			{/if}

			<footer>
				<p class="privacy">
					Tus voces se guardan solo en este navegador. No se envían a ningún sitio.
				</p>
			</footer>
		</div>
	</div>
{/if}

<style>
	.scrim {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.55);
		z-index: 40;
		animation: fade var(--duration) var(--ease);
	}

	.dialog {
		position: fixed;
		z-index: 50;
		inset-block: 0;
		inset-inline-end: 0;
		width: min(40rem, 100vw);
		display: flex;
		flex-direction: column;
		background: var(--bg-elevated);
		border-inline-start: 1px solid var(--border);
		box-shadow: var(--shadow-lg);
		animation: slide-in var(--duration-slow) var(--ease);
	}
	@media (max-width: 40rem) {
		.dialog {
			width: 100vw;
		}
	}

	header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--space-3);
		padding: var(--space-5) var(--space-5) var(--space-4);
		border-bottom: 1px solid var(--border);
	}
	h2 {
		margin: 0;
		font-size: var(--font-lg);
	}
	.sub {
		margin: var(--space-1) 0 0;
		font-size: var(--font-xs);
		color: var(--text-muted);
	}
	h3 {
		margin: 0 0 var(--space-2);
		font-size: var(--font-sm);
		font-weight: 600;
	}

	.body {
		flex: 1;
		overflow-y: auto;
		padding: var(--space-5);
		display: flex;
		flex-direction: column;
		gap: var(--space-6);
	}

	.note,
	.muted {
		margin: 0 0 var(--space-3);
		font-size: var(--font-xs);
		color: var(--text-muted);
		line-height: var(--leading);
	}

	.alert {
		display: grid;
		gap: 2px;
		padding: var(--space-3);
		border-radius: var(--radius);
		border-inline-start: 3px solid var(--err);
		background: color-mix(in srgb, var(--err) 12%, transparent);
		font-size: var(--font-sm);
		line-height: var(--leading);
	}
	.alert span {
		color: var(--text-muted);
	}

	.langs {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		margin-bottom: var(--space-3);
	}
	.lang {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		min-height: var(--target-min);
		padding: var(--space-1) var(--space-3);
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius-full);
		color: var(--text-muted);
		font-size: var(--font-sm);
	}
	.lang:hover {
		border-color: var(--border-strong);
		color: var(--text);
	}
	.lang.on {
		background: var(--accent-subtle);
		border-color: var(--accent);
		color: var(--accent);
		font-weight: 600;
	}
	.dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: currentColor;
	}

	.current {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		flex-wrap: wrap;
		margin: 0 0 var(--space-3);
		padding: var(--space-2) var(--space-3);
		background: var(--accent-subtle);
		border-radius: var(--radius);
		font-size: var(--font-sm);
	}
	.clear {
		min-height: var(--target-min);
		padding: 0 var(--space-2);
		background: none;
		border: none;
		color: var(--text-muted);
		text-decoration: underline;
		font-size: var(--font-xs);
	}
	.clear:hover {
		color: var(--err);
	}

	.icon {
		min-width: var(--target-min);
		min-height: var(--target-min);
		background: var(--surface);
		border: 1px solid var(--border-strong);
		border-radius: var(--radius);
		color: var(--text);
	}
	.icon:hover {
		background: var(--surface-hover);
	}

	footer {
		padding-top: var(--space-4);
		border-top: 1px solid var(--border);
	}
	.privacy {
		margin: 0;
		font-size: var(--font-xs);
		color: var(--text-muted);
		line-height: var(--leading);
	}

	@keyframes fade {
		from {
			opacity: 0;
		}
	}
	@keyframes slide-in {
		from {
			transform: translateX(1.5rem);
			opacity: 0;
		}
	}
</style>
