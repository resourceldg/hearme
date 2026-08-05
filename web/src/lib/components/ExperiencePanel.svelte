<!--
  Panel de apariencia y lectura.

  Este componente es donde se decide si la accesibilidad es de primera o de
  segunda clase, y la decisión se toma en detalles concretos:

  1. **Se llama «Apariencia y lectura», no «Accesibilidad».** Todo el mundo entra
     aquí a poner el tema oscuro. Nadie tiene que declararse nada para ajustar su
     experiencia.
  2. **Los perfiles van arriba, no escondidos al final.** Son la vía rápida.
  3. **Los nombres describen el efecto, no al destinatario.** «Texto amplio»,
     no «Baja visión». Quien lo necesita lo encuentra igual; quien solo lee de
     lejos no tiene que identificarse con un diagnóstico.
  4. **Cada cambio se aplica al instante y se ve en el propio panel**, que usa
     los mismos tokens que gobierna. No hay «guardar» ni previsualización: el
     panel *es* la previsualización.

  Como diálogo modal implementa el contrato completo: `aria-modal`, foco atrapado
  con ciclo, `Escape` para cerrar y devolución del foco al disparador. Un modal a
  medias es peor que ninguno, porque deja el foco perdido detrás del velo.
-->
<script lang="ts">
	import Segmented from '$lib/components/Segmented.svelte';
	import { LIMITS, PROFILES, preferences } from '$lib/experience/preferences.svelte';

	interface Props {
		open: boolean;
		onclose: () => void;
	}

	let { open, onclose }: Props = $props();

	let dialog = $state<HTMLDivElement | null>(null);
	let previouslyFocused: HTMLElement | null = null;

	const prefs = $derived(preferences.current);

	$effect(() => {
		if (!open) return;
		previouslyFocused = document.activeElement as HTMLElement;
		// El foco entra al diálogo tras pintarlo; sin el microtask, el elemento
		// aún no existe y el foco se queda fuera del velo.
		queueMicrotask(() => dialog?.querySelector<HTMLElement>('[data-autofocus]')?.focus());
		return () => previouslyFocused?.focus();
	});

	function onkeydown(event: KeyboardEvent) {
		if (event.key === 'Escape') {
			event.stopPropagation();
			onclose();
			return;
		}
		if (event.key !== 'Tab' || !dialog) return;

		// Ciclo del foco. Sin esto, tabular saca al usuario del diálogo hacia una
		// página que está detrás de un velo: invisible y aun así navegable.
		const focusables = [
			...dialog.querySelectorAll<HTMLElement>(
				'button:not([disabled]), [href], input, select, [tabindex]:not([tabindex="-1"])'
			)
		].filter((el) => el.offsetParent !== null);
		if (!focusables.length) return;

		const primero = focusables[0];
		const ultimo = focusables[focusables.length - 1];
		if (event.shiftKey && document.activeElement === primero) {
			event.preventDefault();
			ultimo.focus();
		} else if (!event.shiftKey && document.activeElement === ultimo) {
			event.preventDefault();
			primero.focus();
		}
	}

	const escala = (v: number) => `${Math.round(v * 100)}%`;
</script>

<svelte:window on:keydown={open ? onkeydown : undefined} />

{#if open}
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="scrim" onclick={onclose}></div>

	<div
		bind:this={dialog}
		class="dialog"
		role="dialog"
		aria-modal="true"
		aria-labelledby="experience-title"
	>
		<header>
			<div>
				<h2 id="experience-title">Apariencia y lectura</h2>
				<p class="summary">{preferences.summary}</p>
			</div>
			<button type="button" class="icon" onclick={onclose} aria-label="Cerrar" data-autofocus>
				<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false" width="16" height="16">
					<path
						d="M4 4l8 8M12 4l-8 8"
						fill="none"
						stroke="currentColor"
						stroke-width="1.75"
						stroke-linecap="round"
					/>
				</svg>
			</button>
		</header>

		<div class="body">
			<section aria-labelledby="perfiles-title">
				<h3 id="perfiles-title">Empezar por un perfil</h3>
				<p class="note">
					Atajos que ajustan varias cosas a la vez. Después puedes cambiar lo que quieras.
				</p>
				<ul class="profiles">
					{#each PROFILES as profile (profile.id)}
						<li>
							<button
								type="button"
								class="profile"
								class:active={prefs.profile === profile.id}
								aria-pressed={prefs.profile === profile.id}
								onclick={() => preferences.applyProfile(profile.id)}
							>
								<span class="profile-name">{profile.name}</span>
								<span class="profile-summary">{profile.summary}</span>
							</button>
						</li>
					{/each}
				</ul>
			</section>

			<section aria-labelledby="ajustes-title">
				<h3 id="ajustes-title">Ajustes</h3>

				<div class="grid">
					<Segmented
						legend="Tema"
						value={prefs.theme}
						options={[
							{ value: 'system', label: 'Sistema' },
							{ value: 'dark', label: 'Oscuro' },
							{ value: 'light', label: 'Claro' }
						]}
						onchange={(v) => preferences.set('theme', v)}
					/>

					<Segmented
						legend="Contraste"
						value={prefs.contrast}
						options={[
							{ value: 'standard', label: 'Estándar' },
							{
								value: 'high',
								label: 'Alto',
								description: 'Fondo negro y colores con contraste reforzado'
							}
						]}
						onchange={(v) => preferences.set('contrast', v)}
					/>

					<Segmented
						legend="Densidad"
						value={prefs.density}
						options={[
							{ value: 'compact', label: 'Compacta' },
							{ value: 'normal', label: 'Normal' },
							{ value: 'comfortable', label: 'Amplia' }
						]}
						onchange={(v) => preferences.set('density', v)}
					/>

					<Segmented
						legend="Animaciones"
						value={prefs.motion}
						options={[
							{ value: 'system', label: 'Sistema' },
							{ value: 'full', label: 'Completas' },
							{ value: 'reduced', label: 'Suaves' },
							{ value: 'none', label: 'Ninguna' }
						]}
						onchange={(v) => preferences.set('motion', v)}
					/>

					<Segmented
						legend="Texto"
						value={prefs.reading}
						options={[
							{ value: 'default', label: 'Normal' },
							{
								value: 'focus',
								label: 'Espaciado',
								description: 'Más interlínea para lectura sostenida'
							},
							{
								value: 'dyslexia',
								label: 'Cómodo',
								description: 'Más espacio entre letras y palabras'
							}
						]}
						onchange={(v) => preferences.set('reading', v)}
					/>

					<Segmented
						legend="Botones"
						value={prefs.targets}
						options={[
							{ value: 'normal', label: 'Normales' },
							{ value: 'large', label: 'Grandes' }
						]}
						onchange={(v) => preferences.set('targets', v)}
					/>
				</div>

				<div class="sliders">
					<div class="slider">
						<label for="font-scale">
							Tamaño del texto
							<output for="font-scale">{escala(prefs.fontScale)}</output>
						</label>
						<input
							id="font-scale"
							type="range"
							min={LIMITS.fontScale.min}
							max={LIMITS.fontScale.max}
							step={LIMITS.fontScale.step}
							value={prefs.fontScale}
							oninput={(e) => preferences.set('fontScale', Number(e.currentTarget.value))}
						/>
					</div>

					<div class="slider">
						<label for="focus-width">
							Grosor del indicador de foco
							<output for="focus-width">{prefs.focusWidth} px</output>
						</label>
						<input
							id="focus-width"
							type="range"
							min={LIMITS.focusWidth.min}
							max={LIMITS.focusWidth.max}
							step={LIMITS.focusWidth.step}
							value={prefs.focusWidth}
							oninput={(e) => preferences.set('focusWidth', Number(e.currentTarget.value))}
						/>
						<p class="note">El recuadro que marca dónde estás al navegar con el teclado.</p>
					</div>
				</div>
			</section>

			<section aria-labelledby="nivel-title">
				<h3 id="nivel-title">Cuánta interfaz quieres ver</h3>
				<Segmented
					legend="Nivel de detalle"
					hideLegend
					value={prefs.expertise}
					options={[
						{
							value: 'guided',
							label: 'Lo esencial',
							description: 'Solo lo necesario para convertir un documento'
						},
						{
							value: 'full',
							label: 'Todo',
							description: 'Motor de voz, idioma, traducción y calidad siempre visibles'
						}
					]}
					onchange={(v) => preferences.set('expertise', v)}
				/>
			</section>

			<footer>
				<p class="privacy">
					Estos ajustes se guardan solo en este navegador. No se envían a ningún sitio.
				</p>
				<button type="button" class="reset" onclick={() => preferences.reset()}>
					Restablecer todo
				</button>
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
		width: min(34rem, 100vw);
		display: flex;
		flex-direction: column;
		background: var(--bg-elevated);
		border-inline-start: 1px solid var(--border);
		box-shadow: var(--shadow-lg);
		animation: slide-in var(--duration-slow) var(--ease);
	}

	/* Por debajo de 640 px ocupa la pantalla: en móvil, un panel lateral estrecho
	   con el texto al 200% es ilegible. Cumple WCAG 1.4.10 (Reflow). */
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
		letter-spacing: -0.01em;
	}

	.summary {
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

	.note {
		margin: 0 0 var(--space-3);
		font-size: var(--font-xs);
		color: var(--text-muted);
		line-height: var(--leading);
	}

	.profiles {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: var(--space-2);
	}

	.profile {
		display: flex;
		flex-direction: column;
		gap: 2px;
		width: 100%;
		min-height: var(--target-min);
		padding: var(--space-3);
		text-align: left;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		color: var(--text);
		font: inherit;
		cursor: pointer;
		transition:
			border-color var(--duration-fast) var(--ease),
			background var(--duration-fast) var(--ease),
			transform var(--duration-fast) var(--ease);
	}

	.profile:hover {
		background: var(--surface-hover);
		border-color: var(--border-strong);
	}
	/* Micro-interacción: un desplazamiento de 1 px al pulsar. Suficiente para
	   que el clic se sienta físico, imperceptible como distracción. */
	.profile:active {
		transform: translateY(1px);
	}
	.profile.active {
		border-color: var(--accent);
		background: var(--accent-subtle);
	}

	.profile-name {
		font-size: var(--font-sm);
		font-weight: 600;
	}
	.profile-summary {
		font-size: var(--font-xs);
		color: var(--text-muted);
		line-height: var(--leading);
	}

	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr));
		gap: var(--space-4);
	}

	.sliders {
		display: grid;
		gap: var(--space-4);
		margin-top: var(--space-5);
	}

	.slider label {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		gap: var(--space-2);
		font-size: var(--font-xs);
		font-weight: 600;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.06em;
		margin-bottom: var(--space-2);
	}

	output {
		font-variant-numeric: tabular-nums;
		color: var(--accent);
		text-transform: none;
		letter-spacing: 0;
	}

	input[type='range'] {
		width: 100%;
		min-height: var(--target-min);
		accent-color: var(--accent);
		cursor: pointer;
	}

	footer {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-3);
		padding-top: var(--space-4);
		border-top: 1px solid var(--border);
		flex-wrap: wrap;
	}

	.privacy {
		margin: 0;
		flex: 1 1 16rem;
		font-size: var(--font-xs);
		color: var(--text-muted);
		line-height: var(--leading);
	}

	.reset,
	.icon {
		min-height: var(--target-min);
		min-width: var(--target-min);
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: var(--space-2);
		padding: var(--space-2) var(--space-3);
		background: var(--surface);
		border: 1px solid var(--border-strong);
		border-radius: var(--radius);
		color: var(--text);
		font: inherit;
		font-size: var(--font-sm);
		cursor: pointer;
		transition: background var(--duration-fast) var(--ease);
	}

	.reset:hover,
	.icon:hover {
		background: var(--surface-hover);
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
