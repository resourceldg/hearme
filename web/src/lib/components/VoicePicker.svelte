<!--
  Selector de voz con muestra audible.

  ## La decisión que resuelve

  «¿Cuál de estas seis voces quiero para las próximas catorce horas?» no se
  responde leyendo `es_ES-sharvard-medium`. Se responde escuchando.

  Por eso la muestra no está escondida tras un menú: es un botón grande en cada
  tarjeta, y **escuchar no selecciona**. Son dos acciones distintas a propósito;
  probar sin comprometerse es justo lo que hace que la gente pruebe.

  ## Detalles que importan

  - **Una sola muestra suena a la vez.** Dos voces solapadas no se comparan, se
    estorban.
  - **La primera muestra tarda** —el motor descarga el modelo— y se dice antes de
    que ocurra, no después. Una espera anunciada se tolera; una inesperada se
    interpreta como que algo se ha roto.
  - **El fallo de una muestra no bloquea la elección.** Se puede seguir eligiendo
    a ciegas si el audio no carga, que es mejor que un callejón sin salida.
  - Las tarjetas son `radio` dentro de un `radiogroup` con foco móvil: se entra
    una vez y se recorre con flechas.
-->
<script lang="ts">
	import { voiceSampleUrl, type Voice } from '$lib/api';

	interface Props {
		voices: Voice[];
		language: string;
		selected: string | null;
		onselect: (voiceId: string) => void;
		/** Voces marcadas como favoritas, para destacarlas arriba. */
		favorites?: string[];
		ontogglefavorite?: (voiceId: string) => void;
	}

	let { voices, language, selected, onselect, favorites = [], ontogglefavorite }: Props = $props();

	let playing = $state<string | null>(null);
	let loading = $state<string | null>(null);
	let failed = $state<Record<string, string>>({});
	let audio: HTMLAudioElement | null = null;
	let cards = $state<HTMLButtonElement[]>([]);

	/** Favoritas primero; dentro de cada grupo, el orden que ya trae el backend. */
	const ordered = $derived([
		...voices.filter((v) => favorites.includes(v.id)),
		...voices.filter((v) => !favorites.includes(v.id))
	]);

	const index = $derived(Math.max(0, ordered.findIndex((v) => v.id === selected)));

	async function play(voice: Voice) {
		// Una sola muestra a la vez: solapadas no se comparan, se estorban.
		audio?.pause();
		if (playing === voice.id) {
			playing = null;
			return;
		}

		loading = voice.id;
		failed = { ...failed, [voice.id]: '' };
		audio = new Audio(voiceSampleUrl(voice.engine, voice.id, language));
		audio.onended = () => (playing = null);
		audio.onerror = () => {
			loading = null;
			playing = null;
			failed = {
				...failed,
				[voice.id]: 'No se pudo generar la muestra. Puedes elegirla igualmente.'
			};
		};
		try {
			await audio.play();
			playing = voice.id;
		} catch {
			failed = { ...failed, [voice.id]: 'El navegador bloqueó la reproducción.' };
		} finally {
			loading = null;
		}
	}

	function onkeydown(event: KeyboardEvent) {
		const pasos: Record<string, number> = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 };
		let destino: number | null = null;
		if (event.key in pasos) destino = (index + pasos[event.key] + ordered.length) % ordered.length;
		else if (event.key === 'Home') destino = 0;
		else if (event.key === 'End') destino = ordered.length - 1;
		if (destino === null) return;
		event.preventDefault();
		onselect(ordered[destino].id);
		cards[destino]?.focus();
	}

	$effect(() => () => audio?.pause());
</script>

{#if !ordered.length}
	<p class="empty">
		No hay voces instaladas para este idioma. Elige otro idioma de reproducción o pide que se
		instale un motor que lo cubra.
	</p>
{:else}
	<ul class="voices" role="radiogroup" aria-label="Elige una voz">
		{#each ordered as voice, i (voice.id)}
			{@const isSelected = voice.id === selected}
			{@const isFavorite = favorites.includes(voice.id)}
			<li>
				<div class="card" class:selected={isSelected}>
					<button
						bind:this={cards[i]}
						type="button"
						role="radio"
						aria-checked={isSelected}
						tabindex={isSelected || (selected === null && i === 0) ? 0 : -1}
						class="choose"
						onclick={() => onselect(voice.id)}
						{onkeydown}
					>
						<span class="name">
							{voice.display_name}
							{#if isFavorite}<span class="fav-dot" aria-label="Favorita">★</span>{/if}
						</span>
						<span class="desc">{voice.description}</span>
						<span class="tags">
							<span class="tag">{voice.engine}</span>
							{#if voice.is_fast}<span class="tag">rápida</span>{/if}
							{#if voice.non_commercial}<span class="tag warn">no comercial</span>{/if}
						</span>
					</button>

					<div class="actions">
						<button
							type="button"
							class="sample"
							onclick={() => play(voice)}
							disabled={loading === voice.id}
							aria-label="Escuchar muestra de {voice.display_name}"
						>
							{#if loading === voice.id}
								<span class="spinner" aria-hidden="true"></span>
							{:else if playing === voice.id}
								<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
									<rect x="4" y="3" width="3" height="10" fill="currentColor" />
									<rect x="9" y="3" width="3" height="10" fill="currentColor" />
								</svg>
							{:else}
								<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
									<path d="M5 3l8 5-8 5V3z" fill="currentColor" />
								</svg>
							{/if}
							{loading === voice.id ? 'Generando…' : playing === voice.id ? 'Parar' : 'Escuchar'}
						</button>

						{#if ontogglefavorite}
							<button
								type="button"
								class="fav"
								class:on={isFavorite}
								aria-pressed={isFavorite}
								onclick={() => ontogglefavorite?.(voice.id)}
								aria-label="{isFavorite ? 'Quitar de' : 'Añadir a'} favoritas: {voice.display_name}"
							>
								★
							</button>
						{/if}
					</div>
				</div>

				{#if failed[voice.id]}
					<p class="failed" role="status">{failed[voice.id]}</p>
				{/if}
			</li>
		{/each}
	</ul>

	<p class="hint">
		La primera muestra de cada motor tarda unos segundos: se descarga el modelo de voz. Escuchar no
		selecciona nada.
	</p>
{/if}

<style>
	.voices {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: var(--space-2);
	}

	.card {
		display: flex;
		align-items: stretch;
		gap: var(--space-2);
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		transition:
			border-color var(--duration-fast) var(--ease),
			background var(--duration-fast) var(--ease);
	}
	.card:hover {
		border-color: var(--border-strong);
	}
	.card.selected {
		border-color: var(--accent);
		background: var(--accent-subtle);
	}

	.choose {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-height: var(--target-min);
		padding: var(--space-3);
		background: none;
		border: none;
		border-radius: var(--radius);
		color: var(--text);
		font: inherit;
		text-align: left;
		cursor: pointer;
	}

	.name {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--font-sm);
		font-weight: 600;
	}
	.fav-dot {
		color: var(--warn);
	}

	.desc {
		font-size: var(--font-xs);
		color: var(--text-muted);
		line-height: var(--leading);
	}

	.tags {
		display: flex;
		gap: var(--space-2);
		margin-top: var(--space-1);
		flex-wrap: wrap;
	}
	.tag {
		padding: 0 0.5em;
		border-radius: var(--radius-full);
		background: var(--surface-hover);
		color: var(--text-muted);
		font-size: var(--font-xs);
	}
	.tag.warn {
		background: color-mix(in srgb, var(--warn) 20%, transparent);
		color: var(--text);
	}

	.actions {
		display: flex;
		align-items: center;
		gap: var(--space-1);
		padding-inline-end: var(--space-2);
	}

	.sample {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		min-height: var(--target-min);
		padding: var(--space-2) var(--space-3);
		background: var(--surface-hover);
		border: 1px solid var(--border-strong);
		border-radius: var(--radius);
		color: var(--text);
		font-size: var(--font-xs);
		font-weight: 600;
		white-space: nowrap;
	}
	.sample:hover:not(:disabled) {
		border-color: var(--accent);
		color: var(--accent);
	}

	.fav {
		min-width: var(--target-min);
		min-height: var(--target-min);
		background: none;
		border: none;
		border-radius: var(--radius);
		color: var(--text-muted);
		font-size: var(--font-md);
	}
	.fav.on {
		color: var(--warn);
	}
	.fav:hover {
		background: var(--surface-hover);
	}

	.spinner {
		width: 12px;
		height: 12px;
		border: 2px solid var(--border-strong);
		border-top-color: var(--accent);
		border-radius: 50%;
		animation: spin 0.7s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	.failed {
		margin: var(--space-1) 0 0;
		padding-inline-start: var(--space-3);
		font-size: var(--font-xs);
		color: var(--warn);
		line-height: var(--leading);
	}

	.hint,
	.empty {
		margin: var(--space-3) 0 0;
		font-size: var(--font-xs);
		color: var(--text-muted);
		line-height: var(--leading);
	}
</style>
