<!--
  Asistente de configuración inicial.

  ## Los dos caminos, y por qué no son un asistente por pasos

  Un asistente de cinco pantallas trata a todo el mundo como principiante para
  siempre. Aquí hay **una sola pantalla con dos profundidades**:

  - **Camino rápido:** el sistema ya ha analizado el documento y propone un plan
    completo. Se lee en una frase y se pulsa «Empezar». Un clic.
  - **Camino avanzado:** el mismo plan, con cada decisión abierta y editable.

  No es un modo que haya que elegir al principio: es el mismo panel, revelado.
  Quien va rápido no ve nada de más; quien quiere control lo tiene a un clic, sin
  volver a empezar ni perder lo ya decidido.

  ## Las recomendaciones se ven, se explican y se deshacen

  Cada sugerencia lleva su motivo al lado, y cambiarla es tocar el control. Si el
  sistema no está seguro —confianza baja en la detección de idioma— **no
  preselecciona**: lo dice y pregunta. Es la diferencia entre asistir y decidir
  por alguien.

  ## Lo que este panel no hace

  No inventa una decisión que el sistema no pueda cumplir. Si falta el traductor
  o no hay voces para un idioma, el problema aparece **antes** de convertir, con
  la acción concreta que lo resuelve, no como un fallo diez minutos después.
-->
<script lang="ts">
	import VoicePicker from '$lib/components/VoicePicker.svelte';
	import Segmented from '$lib/components/Segmented.svelte';
	import {
		getVoicesFor,
		validatePlan,
		type AnalysisResult,
		type PlanProblem,
		type Voice
	} from '$lib/api';

	interface Props {
		file: File;
		analysis: AnalysisResult;
		favorites: string[];
		defaultVoices: Record<string, string>;
		onstart: (plan: {
			document_language: string;
			playback_language: string;
			voice: string | null;
			style: string;
			keep_original: boolean;
		}) => void;
		oncancel: () => void;
		ontogglefavorite: (voiceId: string) => void;
	}

	let {
		file,
		analysis,
		favorites,
		defaultVoices,
		onstart,
		oncancel,
		ontogglefavorite
	}: Props = $props();

	const rec = $derived(analysis.recommendations);
	const info = $derived(analysis.analysis);

	// Capturar el valor inicial es intencionado: el asistente se monta de nuevo
	// por cada documento (la página lo aplica con `key`), así que estos son los
	// puntos de partida editables, no un espejo del análisis. Si siguieran a la
	// prop, corregir el idioma a mano se desharía solo.
	// svelte-ignore state_referenced_locally
	let documentLanguage = $state(analysis.analysis.detected_language);
	// svelte-ignore state_referenced_locally
	let playbackLanguage = $state(
		analysis.recommendations.playback_language?.value ?? analysis.analysis.detected_language
	);
	// svelte-ignore state_referenced_locally
	let voice = $state<string | null>(analysis.recommendations.voice?.value ?? null);
	// svelte-ignore state_referenced_locally
	let style = $state(analysis.recommendations.style?.value ?? 'neutral');
	let keepOriginal = $state(false);
	let advanced = $state(false);

	let voices = $state<Voice[]>([]);
	let problems = $state<PlanProblem[]>([]);
	let loadingVoices = $state(false);

	const needsTranslation = $derived(
		Boolean(documentLanguage && playbackLanguage && documentLanguage !== playbackLanguage)
	);
	/** Confianza baja: se pregunta en vez de dar por bueno lo detectado. */
	const uncertainLanguage = $derived(info.confidence < 0.6);

	const chosenVoice = $derived(voices.find((v) => v.id === voice) ?? null);

	const summary = $derived(
		needsTranslation
			? `Se traducirá de ${documentLanguage} a ${playbackLanguage} y se narrará con ${chosenVoice?.display_name ?? 'la voz elegida'}.`
			: `Se narrará en ${playbackLanguage} con ${chosenVoice?.display_name ?? 'la voz elegida'}.`
	);

	/** Al cambiar el idioma de reproducción, la voz anterior deja de valer. */
	$effect(() => {
		const idioma = playbackLanguage;
		if (!idioma) return;
		loadingVoices = true;
		getVoicesFor(idioma)
			.then(({ voices: lista }) => {
				voices = lista;
				const sigueValiendo = lista.some((v) => v.id === voice);
				if (!sigueValiendo) {
					// Preferencia guardada primero; si no, la más natural.
					voice = defaultVoices[idioma] ?? lista[0]?.id ?? null;
				}
			})
			.catch(() => (voices = []))
			.finally(() => (loadingVoices = false));
	});

	$effect(() => {
		const plan = {
			document_language: documentLanguage,
			playback_language: playbackLanguage,
			voice,
			style,
			keep_original: keepOriginal
		};
		validatePlan(plan)
			.then((r) => (problems = r.problems))
			.catch(() => (problems = []));
	});

	const LANGUAGE_NAMES: Record<string, string> = {
		es: 'español', en: 'inglés', fr: 'francés', de: 'alemán', it: 'italiano',
		pt: 'portugués', ca: 'catalán', ja: 'japonés', zh: 'chino', hi: 'hindi'
	};
	const langName = (code: string) => LANGUAGE_NAMES[code] ?? code;

	const STYLES = [
		{ value: 'neutral', label: 'Neutro', hint: 'Equilibrado, sirve para casi todo' },
		{ value: 'novel', label: 'Novela', hint: 'Pausas de respiración entre párrafos' },
		{ value: 'poetry', label: 'Poesía', hint: 'Silencios largos, ritmo lento' },
		{ value: 'technical', label: 'Técnico', hint: 'Cadencia sostenida, pausas breves' },
		{ value: 'academic', label: 'Académico', hint: 'Pausado, con aire en las citas' },
		{ value: 'children', label: 'Infantil', hint: 'Más lento y más expresivo' },
		{ value: 'lecture', label: 'Conferencia', hint: 'Cadencia de exposición oral' }
	];
</script>

<section class="assistant" aria-labelledby="assistant-title">
	<header>
		<div>
			<h2 id="assistant-title">Cómo quieres escuchar esto</h2>
			<p class="file">{info.title || file.name}</p>
		</div>
		<button type="button" class="close" onclick={oncancel} aria-label="Cancelar">✕</button>
	</header>

	<!-- Lo que el sistema ha averiguado, en lenguaje llano y siempre corregible -->
	<dl class="facts">
		<div>
			<dt>Está escrito en</dt>
			<dd>
				{langName(documentLanguage)}
				{#if uncertainLanguage}
					<span class="unsure">poco texto para estar seguros</span>
				{/if}
			</dd>
		</div>
		<div>
			<dt>Extensión</dt>
			<dd>{info.chapters} capítulos · unas {Math.round(info.estimated_minutes)} min de audio</dd>
		</div>
	</dl>

	{#if uncertainLanguage}
		<p class="ask" role="status">
			El documento es corto y la detección del idioma no es fiable. Compruébalo antes de empezar.
		</p>
	{/if}

	<!-- Camino rápido: una frase y un botón -->
	<div class="plan">
		<p class="summary">{summary}</p>
		{#if rec.playback_language?.reason && !advanced}
			<p class="why">{rec.playback_language.reason}</p>
		{/if}
	</div>

	{#each problems as problem (problem.field + problem.message)}
		<div class="problem" role="alert">
			<strong>{problem.message}</strong>
			<span>{problem.action}</span>
		</div>
	{/each}

	{#if !advanced}
		<div class="cta">
			<button
				type="button"
				class="btn primary"
				disabled={problems.length > 0 || !voice}
				onclick={() =>
					onstart({
						document_language: documentLanguage,
						playback_language: playbackLanguage,
						voice,
						style,
						keep_original: keepOriginal
					})}
			>
				Empezar a convertir
			</button>
			<button type="button" class="btn ghost" onclick={() => (advanced = true)}>
				Ajustar antes
			</button>
		</div>
	{:else}
		<!-- Camino avanzado: los seis conceptos, cada uno con su nombre -->
		<div class="advanced">
			<fieldset>
				<legend>1 · Idioma del documento</legend>
				<p class="note">En qué está escrito. Corrígelo si la detección falló.</p>
				<select bind:value={documentLanguage}>
					{#each [...new Set([documentLanguage, ...analysis.languages_with_voice])] as code (code)}
						<option value={code}>{langName(code)}</option>
					{/each}
				</select>
			</fieldset>

			<fieldset>
				<legend>2 · Idioma en el que quieres escucharlo</legend>
				<p class="note">
					Si eliges uno distinto al del documento, se traducirá automáticamente. No hay que
					activar nada más.
				</p>
				<select bind:value={playbackLanguage} disabled={!analysis.translation_available && false}>
					{#each analysis.languages_with_voice as code (code)}
						<option value={code}>{langName(code)}</option>
					{/each}
				</select>
				{#if needsTranslation}
					<p class="derived">
						→ Se traducirá de {langName(documentLanguage)} a {langName(playbackLanguage)}.
						<label class="keep">
							<input type="checkbox" bind:checked={keepOriginal} />
							Conservar también el texto original
						</label>
					</p>
				{/if}
			</fieldset>

			<fieldset>
				<legend>3 · Voz</legend>
				<p class="note">Solo voces de {langName(playbackLanguage)}. Escucha antes de elegir.</p>
				{#if loadingVoices}
					<p class="note">Cargando voces…</p>
				{:else}
					<VoicePicker
						{voices}
						language={playbackLanguage}
						selected={voice}
						onselect={(v) => (voice = v)}
						{favorites}
						{ontogglefavorite}
					/>
				{/if}
			</fieldset>

			<fieldset>
				<legend>4 · Estilo narrativo</legend>
				<p class="note">Cómo se lee: dónde respira y a qué ritmo. No cambia la voz.</p>
				<Segmented
					legend="Estilo"
					hideLegend
					value={style}
					options={STYLES.map((s) => ({ value: s.value, label: s.label, description: s.hint }))}
					onchange={(v) => (style = v)}
				/>
				<p class="note">{STYLES.find((s) => s.value === style)?.hint}</p>
			</fieldset>

			{#if chosenVoice}
				<p class="engine-note">
					Motor de síntesis: <strong>{chosenVoice.engine}</strong>. Lo determina la voz elegida.
				</p>
			{/if}

			<div class="cta">
				<button
					type="button"
					class="btn primary"
					disabled={problems.length > 0 || !voice}
					onclick={() =>
						onstart({
							document_language: documentLanguage,
							playback_language: playbackLanguage,
							voice,
							style,
							keep_original: keepOriginal
						})}
				>
					Convertir
				</button>
				<button type="button" class="btn ghost" onclick={() => (advanced = false)}>
					Volver a lo simple
				</button>
			</div>
		</div>
	{/if}
</section>

<style>
	.assistant {
		display: grid;
		gap: var(--space-4);
		padding: var(--space-5);
		background: var(--bg-elevated);
		border: 1px solid var(--accent);
		border-radius: var(--radius-lg);
	}

	header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: var(--space-3);
	}
	h2 {
		margin: 0;
		font-size: var(--font-lg);
	}
	.file {
		margin: var(--space-1) 0 0;
		font-size: var(--font-xs);
		color: var(--text-muted);
	}
	.close {
		min-width: var(--target-min);
		min-height: var(--target-min);
		background: none;
		border: none;
		color: var(--text-muted);
		border-radius: var(--radius);
	}
	.close:hover {
		background: var(--surface-hover);
		color: var(--text);
	}

	.facts {
		display: flex;
		gap: var(--space-6);
		flex-wrap: wrap;
		margin: 0;
		padding: var(--space-3) var(--space-4);
		background: var(--surface);
		border-radius: var(--radius);
	}
	dt {
		font-size: var(--font-xs);
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}
	dd {
		margin: 2px 0 0;
		font-size: var(--font-sm);
		font-weight: 600;
	}
	.unsure {
		margin-inline-start: var(--space-2);
		font-weight: 400;
		font-size: var(--font-xs);
		color: var(--warn);
	}

	.ask,
	.problem {
		padding: var(--space-3);
		border-radius: var(--radius);
		border-inline-start: 3px solid var(--warn);
		background: color-mix(in srgb, var(--warn) 12%, transparent);
		font-size: var(--font-sm);
		line-height: var(--leading);
		margin: 0;
	}
	.problem {
		display: grid;
		gap: 2px;
		border-color: var(--err);
		background: color-mix(in srgb, var(--err) 12%, transparent);
	}
	.problem span {
		color: var(--text-muted);
	}

	.plan {
		padding: var(--space-4);
		background: var(--accent-subtle);
		border-radius: var(--radius);
	}
	.summary {
		margin: 0;
		font-size: var(--font-md);
		font-weight: 600;
		line-height: var(--leading);
	}
	.why {
		margin: var(--space-2) 0 0;
		font-size: var(--font-xs);
		color: var(--text-muted);
		line-height: var(--leading);
	}

	.cta {
		display: flex;
		gap: var(--space-3);
		flex-wrap: wrap;
	}

	.advanced {
		display: grid;
		gap: var(--space-5);
	}

	fieldset {
		border: none;
		border-top: 1px solid var(--border);
		margin: 0;
		padding: var(--space-4) 0 0;
	}
	legend {
		padding: 0;
		font-size: var(--font-sm);
		font-weight: 600;
	}
	.note {
		margin: var(--space-1) 0 var(--space-3);
		font-size: var(--font-xs);
		color: var(--text-muted);
		line-height: var(--leading);
	}

	select {
		width: 100%;
		max-width: 22rem;
		min-height: var(--target-min);
		padding: var(--space-2) var(--space-3);
		background: var(--surface);
		color: var(--text);
		border: 1px solid var(--border-strong);
		border-radius: var(--radius);
		font-size: var(--font-sm);
	}

	/* La consecuencia de una decisión, no otra decisión: por eso se muestra como
	   resultado y no como un control más. */
	.derived {
		margin: var(--space-3) 0 0;
		padding: var(--space-3);
		background: var(--surface);
		border-inline-start: 3px solid var(--accent);
		border-radius: var(--radius);
		font-size: var(--font-sm);
		line-height: var(--leading);
	}
	.keep {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		margin-top: var(--space-2);
		font-size: var(--font-xs);
		color: var(--text-muted);
		cursor: pointer;
	}

	.engine-note {
		margin: 0;
		font-size: var(--font-xs);
		color: var(--text-muted);
	}

	.btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-height: var(--target-min);
		padding: var(--space-3) var(--space-5);
		border-radius: var(--radius);
		border: 1px solid transparent;
		font-size: var(--font-sm);
		font-weight: 600;
	}
	.btn.primary {
		background: var(--accent-solid);
		color: var(--accent-contrast);
	}
	.btn.primary:hover:not(:disabled) {
		background: var(--accent-hover);
	}
	.btn.ghost {
		background: var(--surface);
		border-color: var(--border-strong);
		color: var(--text);
	}
	.btn.ghost:hover {
		background: var(--surface-hover);
	}
	.btn:active:not(:disabled) {
		transform: translateY(1px);
	}
</style>
