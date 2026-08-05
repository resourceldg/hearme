<!--
  Valorar una narración terminada.

  ## Por qué tres señales y no una

  | Señal | Coste | Quién la usa |
  |---|---|---|
  | Pulgar | Un toque | Casi todo el mundo |
  | Estrellas | Dos segundos | Quien tiene una opinión formada |
  | Comentario | Media frase | Poca gente, pero es la única que dice **qué** falla |

  Pedir solo estrellas da una nota sin diagnóstico. Pedir solo comentarios deja
  fuera al 95%. Las tres están a la vista y **ninguna es obligatoria**: se puede
  pulsar un pulgar y seguir escuchando.

  ## El detalle que hace que valga la pena escribir

  Al enviar un comentario, el sistema **devuelve qué entendió**:

  > Se detectó: «demasiado rapido» → va muy rápido.

  Eso convierte el comentario en una conversación en lugar de un buzón. Si
  entendió mal, se ve al instante; y quien escribe comprueba que su rato sirvió
  para algo, que es la única razón por la que alguien vuelve a escribir.
-->
<script lang="ts">
	import { submitFeedback, type FeedbackResponse } from '$lib/api';

	interface Props {
		engine: string;
		voice: string;
		style: string;
		language: string;
	}

	let { engine, voice, style, language }: Props = $props();

	let stars = $state(0);
	let thumbs = $state<boolean | null>(null);
	let comment = $state('');
	let sending = $state(false);
	let result = $state<FeedbackResponse | null>(null);
	let error = $state('');
	let expanded = $state(false);

	const canSend = $derived(stars > 0 || thumbs !== null || comment.trim().length > 0);

	async function send() {
		if (!canSend) return;
		sending = true;
		error = '';
		try {
			result = await submitFeedback({
				engine,
				voice,
				style,
				language,
				stars: stars || null,
				thumbs_up: thumbs,
				comment: comment.trim()
			});
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			sending = false;
		}
	}

	function reset() {
		result = null;
		stars = 0;
		thumbs = null;
		comment = '';
		expanded = false;
	}
</script>

<div class="feedback">
	{#if result}
		<div class="thanks" role="status">
			<p class="head">Gracias. Esto ayuda a narrar mejor la próxima vez.</p>
			{#if result.understood.length}
				<!-- Devolver lo entendido es lo que convierte el comentario en una
				     conversación. Si entendió mal, se ve aquí y no a los seis meses. -->
				<p class="understood">
					Se entendió:
					{#each result.understood as tag (tag.tag)}
						<span class="tag {tag.sentiment ?? ''}">{tag.label}</span>
					{/each}
				</p>
				<p class="evidence">{result.explanation}</p>
			{:else if comment.trim()}
				<p class="evidence">
					De tu comentario no se extrajo ninguna etiqueta conocida, pero se guarda tal cual: lo
					leerá una persona.
				</p>
			{/if}
			<button type="button" class="link" onclick={reset}>Valorar de nuevo</button>
		</div>
	{:else}
		<div class="row">
			<span class="label" id="fb-label-{engine}">¿Qué tal ha sonado?</span>

			<div class="stars" role="radiogroup" aria-labelledby="fb-label-{engine}">
				{#each [1, 2, 3, 4, 5] as n (n)}
					<button
						type="button"
						role="radio"
						aria-checked={stars === n}
						tabindex={stars === n || (stars === 0 && n === 1) ? 0 : -1}
						class="star"
						class:on={n <= stars}
						onclick={() => (stars = stars === n ? 0 : n)}
						onkeydown={(e) => {
							if (e.key === 'ArrowRight' || e.key === 'ArrowUp') {
								e.preventDefault();
								stars = Math.min(5, stars + 1);
							} else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') {
								e.preventDefault();
								stars = Math.max(0, stars - 1);
							}
						}}
						aria-label="{n} de 5 estrellas"
					>
						★
					</button>
				{/each}
			</div>

			<div class="thumbs">
				<button
					type="button"
					class="thumb"
					class:on={thumbs === true}
					aria-pressed={thumbs === true}
					onclick={() => (thumbs = thumbs === true ? null : true)}
					aria-label="Me gusta"
				>
					👍
				</button>
				<button
					type="button"
					class="thumb"
					class:on={thumbs === false}
					aria-pressed={thumbs === false}
					onclick={() => (thumbs = thumbs === false ? null : false)}
					aria-label="No me gusta"
				>
					👎
				</button>
			</div>

			{#if !expanded}
				<button type="button" class="link" onclick={() => (expanded = true)}>
					Contar qué falla
				</button>
			{/if}
		</div>

		{#if expanded}
			<label class="comment">
				<span>¿Qué mejorarías? Con media frase basta.</span>
				<textarea
					bind:value={comment}
					rows="2"
					maxlength="500"
					placeholder="Por ejemplo: va muy rápido, o las pausas quedan raras"
				></textarea>
			</label>
		{/if}

		{#if error}
			<p class="error" role="alert">No se pudo enviar: {error}. Puedes intentarlo otra vez.</p>
		{/if}

		{#if canSend}
			<button type="button" class="send" onclick={send} disabled={sending}>
				{sending ? 'Enviando…' : 'Enviar valoración'}
			</button>
		{/if}
	{/if}
</div>

<style>
	.feedback {
		margin-top: var(--space-3);
		padding-top: var(--space-3);
		border-top: 1px solid var(--border);
		display: grid;
		gap: var(--space-2);
	}

	.row {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		flex-wrap: wrap;
	}

	.label {
		font-size: var(--font-xs);
		color: var(--text-muted);
	}

	.stars,
	.thumbs {
		display: flex;
		gap: 2px;
	}

	.star,
	.thumb {
		min-width: var(--target-min);
		min-height: var(--target-min);
		background: none;
		border: none;
		border-radius: var(--radius);
		color: var(--text-muted);
		font-size: var(--font-md);
		line-height: 1;
		transition: color var(--duration-fast) var(--ease);
	}
	.star.on {
		color: var(--warn);
	}
	.star:hover,
	.thumb:hover {
		background: var(--surface-hover);
	}
	.thumb.on {
		background: var(--accent-subtle);
	}

	.comment {
		display: grid;
		gap: var(--space-2);
	}
	.comment span {
		font-size: var(--font-xs);
		color: var(--text-muted);
	}

	textarea {
		width: 100%;
		padding: var(--space-2) var(--space-3);
		background: var(--surface);
		color: var(--text);
		border: 1px solid var(--border-strong);
		border-radius: var(--radius);
		font: inherit;
		font-size: var(--font-sm);
		resize: vertical;
	}

	.send {
		justify-self: start;
		min-height: var(--target-min);
		padding: var(--space-2) var(--space-4);
		background: var(--accent-solid);
		color: var(--accent-contrast);
		border: none;
		border-radius: var(--radius);
		font-size: var(--font-sm);
		font-weight: 600;
	}

	.link {
		background: none;
		border: none;
		color: var(--accent);
		font-size: var(--font-xs);
		text-decoration: underline;
		min-height: var(--target-min);
	}

	.thanks {
		display: grid;
		gap: var(--space-2);
		padding: var(--space-3);
		background: var(--accent-subtle);
		border-radius: var(--radius);
	}
	.head {
		margin: 0;
		font-size: var(--font-sm);
		font-weight: 600;
	}

	.understood {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		flex-wrap: wrap;
		margin: 0;
		font-size: var(--font-xs);
		color: var(--text-muted);
	}

	.tag {
		padding: 0.1em 0.6em;
		border-radius: var(--radius-full);
		background: var(--surface);
		color: var(--text);
		font-size: var(--font-xs);
	}
	.tag.negative {
		background: color-mix(in srgb, var(--err) 18%, transparent);
	}
	.tag.positive {
		background: color-mix(in srgb, var(--ok) 18%, transparent);
	}

	.evidence,
	.error {
		margin: 0;
		font-size: var(--font-xs);
		color: var(--text-muted);
		line-height: var(--leading);
	}
	.error {
		color: var(--err);
	}
</style>
