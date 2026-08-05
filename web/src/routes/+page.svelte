<!--
  Pantalla principal.

  ## Arquitectura de la información

  Tres zonas, siempre en el mismo orden, porque el orden *es* la explicación de
  cómo funciona esto:

    1. Traer un documento
    2. Decidir cómo se lee   (plegado si no hace falta)
    3. Escuchar lo convertido

  ## Progressive Disclosure aplicado

  De partida solo se ve lo imprescindible: soltar un archivo y pulsar convertir.
  El resto vive tras revelaciones etiquetadas con lo que contienen —«Voz y
  formato», «Idioma y traducción»— nunca tras un «Avanzado» genérico, que no dice
  nada y obliga a abrirlo para saber si te interesa.

  Quien elige «Todo» en el panel de apariencia lo ve desplegado desde el
  principio: el nivel de detalle es una preferencia, no una fase por la que haya
  que pasar cada vez.
-->
<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import Disclosure from '$lib/components/Disclosure.svelte';
	import SetupAssistant from '$lib/components/SetupAssistant.svelte';
	import VoiceCenter from '$lib/components/VoiceCenter.svelte';
	import ExperiencePanel from '$lib/components/ExperiencePanel.svelte';
	import Segmented from '$lib/components/Segmented.svelte';
	import { preferences } from '$lib/experience/preferences.svelte';
	import {
		cancelJob,
		convert,
		downloadUrl,
		formatDuration,
		getSystem,
		listJobs,
		subscribeToJob,
		analyzeDocument,
		type AnalysisResult,
		type ConversionOptions,
		type Job,
		type SystemInfo
	} from '$lib/api';

	let system = $state<SystemInfo | null>(null);
	let jobs = $state<Job[]>([]);
	let error = $state('');
	let dragging = $state(false);
	let uploading = $state(false);
	let uploadingNow = $state('');
	let uploadedCount = $state(0);
	let panelOpen = $state(false);
	let voiceCenterOpen = $state(false);
	let pending = $state<File[]>([]);

	/**
	 * Documento en el asistente.
	 *
	 * El flujo pasa a ser: soltar -> analizar -> confirmar el plan -> convertir.
	 * Analizar cuesta segundos y evita el error caro: descubrir a los diez
	 * minutos que la voz era de otro idioma o que no había traductor.
	 */
	let assistantFile = $state<File | null>(null);
	let assistantAnalysis = $state<AnalysisResult | null>(null);
	let analyzing = $state(false);

	/** Anuncios para lectores de pantalla. WCAG 4.1.3 (Status Messages). */
	let announcement = $state('');

	let live = $state<Record<string, { stage: string; ratio: number; detail: string }>>({});
	const streams = new Map<string, () => void>();
	const MAX_STREAMS = 2;

	let options = $state<ConversionOptions>({
		mode: 'audiobook',
		formats: ['m4b'],
		style: 'neutral',
		quality: 'high',
		engine: null,
		language: null,
		target_language: null
	});

	const AUDIO_FORMATS = ['m4b', 'mp3'];
	const TEXT_FORMATS = ['markdown', 'txt', 'json', 'epub'];

	const availableEngines = $derived(system?.tts_engines.filter((e) => e.available) ?? []);
	const activeJobs = $derived(jobs.filter((j) => j.status === 'pending' || j.status === 'running'));
	const doneJobs = $derived(jobs.filter((j) => j.status === 'completed'));
	/** Con «Todo», las opciones nacen abiertas en vez de esconderse cada vez. */
	const showAll = $derived(preferences.current.expertise === 'full');
	/** Un campo que no puede funcionar debe verse deshabilitado, no fallar al usarlo. */
	const translationAvailable = $derived((system?.translators?.length ?? 0) > 0);

	/**
	 * ¿Responde la API una forma que esta interfaz entiende?
	 *
	 * Frontend y API se despliegan por separado —son dos contenedores— así que
	 * pueden quedar desparejados. Antes eso reventaba el render entero y dejaba
	 * la página en blanco, que es el peor diagnóstico posible: parece que la
	 * aplicación está rota cuando solo falta reconstruir una imagen.
	 */
	const apiMismatch = $derived(Boolean(system) && system?.runtime === undefined);

	// --- datos -----------------------------------------------------------------

	async function refresh() {
		try {
			jobs = await listJobs(30);
			for (const job of jobs) {
				if (job.status !== 'running') {
					streams.get(job.id)?.();
					streams.delete(job.id);
					delete live[job.id];
				} else if (!streams.has(job.id) && streams.size < MAX_STREAMS) {
					watch(job.id);
				}
			}
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	function watch(jobId: string) {
		if (streams.has(jobId) || streams.size >= MAX_STREAMS) return;
		const close = subscribeToJob(jobId, (event) => {
			if (event.type === 'JobProgress') {
				live[jobId] = {
					stage: event.stage ?? '',
					ratio: event.total ? (event.current ?? 0) / event.total : 0,
					detail: event.detail ?? ''
				};
			}
			if (event.type === 'JobCompleted' || event.type === 'JobFailed') {
				delete live[jobId];
				announcement =
					event.type === 'JobCompleted' ? 'Conversión terminada.' : 'Una conversión ha fallado.';
				refresh();
			}
		});
		streams.set(jobId, close);
	}

	function queue(files: FileList | null) {
		if (!files?.length) return;
		error = '';
		const nuevos = Array.from(files);
		const yaEsta = (f: File) => pending.some((p) => p.name === f.name && p.size === f.size);
		const añadidos = nuevos.filter((f) => !yaEsta(f));
		pending = [...pending, ...añadidos];
		announcement = `${añadidos.length} documento(s) en la lista. ${pending.length} en total.`;

		// Con un solo documento se abre el asistente: es donde se decide bien.
		// Con varios no, porque un plan por documento sería una entrevista.
		if (pending.length === 1 && añadidos.length === 1) openAssistant(añadidos[0]);
	}

	async function openAssistant(file: File) {
		analyzing = true;
		assistantFile = file;
		assistantAnalysis = null;
		announcement = 'Analizando el documento para proponer una configuración.';
		try {
			assistantAnalysis = await analyzeDocument(file);
		} catch (e) {
			// Que falle el análisis no puede impedir convertir: se sigue con las
			// opciones manuales, que es exactamente lo que había antes.
			assistantFile = null;
			error = `No se pudo analizar el documento: ${e instanceof Error ? e.message : e}. Puedes configurarlo a mano abajo.`;
		} finally {
			analyzing = false;
		}
	}

	async function startFromAssistant(plan: {
		document_language: string;
		playback_language: string;
		voice: string | null;
		style: string;
		keep_original: boolean;
	}) {
		const file = assistantFile;
		if (!file) return;
		// El plan usa los seis conceptos; el pipeline sigue hablando de
		// language/target_language. La conversión se hace aquí, a la vista.
		options = {
			...options,
			language: plan.document_language || null,
			target_language:
				plan.playback_language !== plan.document_language ? plan.playback_language : null,
			voice: plan.voice,
			style: plan.style
		};
		assistantFile = null;
		assistantAnalysis = null;
		await convertPending();
	}

	function unqueue(file: File) {
		pending = pending.filter((f) => f !== file);
		announcement = `Quitado ${file.name}. Quedan ${pending.length}.`;
	}

	async function convertPending() {
		if (!pending.length) return;
		error = '';
		uploading = true;
		uploadedCount = 0;
		const total = pending.length;
		try {
			while (pending.length) {
				const file = pending[0];
				uploadingNow = total > 1 ? `${file.name} (${uploadedCount + 1}/${total})` : file.name;
				try {
					await convert(file, options);
				} catch (e) {
					error = `${file.name}: ${e instanceof Error ? e.message : String(e)}`;
					break;
				}
				pending = pending.slice(1);
				uploadedCount += 1;
			}
			announcement = `${uploadedCount} documento(s) en cola de conversión.`;
			await refresh();
		} finally {
			uploading = false;
			uploadingNow = '';
		}
	}

	function toggleFormat(format: string) {
		const current = options.formats ?? [];
		options.formats = current.includes(format)
			? current.filter((f) => f !== format)
			: [...current, format];
	}

	async function onCancel(id: string) {
		await cancelJob(id);
		announcement = 'Conversión cancelada.';
		await refresh();
	}

	function onDrop(event: DragEvent) {
		event.preventDefault();
		dragging = false;
		queue(event.dataTransfer?.files ?? null);
	}

	// --- presentación ----------------------------------------------------------

	const audioOutput = (job: Job) => job.outputs.findIndex((p) => /\.(m4b|mp3)$/i.test(p));
	const filename = (path: string) => path.split('/').pop() ?? path;

	function formatSize(bytes: number): string {
		if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
		return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
	}

	const STAGE_LABELS: Record<string, string> = {
		inicio: 'Preparando',
		ocr: 'Reconociendo texto',
		parseo: 'Leyendo el documento',
		traduccion: 'Traduciendo',
		sintesis: 'Generando voz',
		completado: 'Listo',
		error: 'Error'
	};
	const stageLabel = (stage?: string) => (stage ? (STAGE_LABELS[stage] ?? stage) : 'En cola');

	let poller: ReturnType<typeof setInterval>;

	onMount(async () => {
		try {
			system = await getSystem();
		} catch (e) {
			error = `No se pudo contactar con el servicio: ${e instanceof Error ? e.message : e}`;
		}
		await refresh();
		poller = setInterval(refresh, 5000);
	});

	onDestroy(() => {
		clearInterval(poller);
		for (const close of streams.values()) close();
		streams.clear();
	});
</script>

<div class="shell">
	<header class="topbar">
		<div class="brand">
			<span class="mark" aria-hidden="true">
				<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor">
					<path d="M4 10v4M8 6v12M12 3v18M16 7v10M20 11v2" stroke-width="2" stroke-linecap="round" />
				</svg>
			</span>
			<div>
				<h1>HearMe</h1>
				<p class="tagline">Lecturas en voz de alta calidad, abiertas para todo el mundo</p>
			</div>
		</div>

		<div class="topbar-actions">
			{#if system}
				<span class="chip-static">{system.runtime?.languages?.length ?? 0} idiomas</span>
			{/if}
			<button
				type="button"
				class="btn ghost"
				onclick={() => (voiceCenterOpen = true)}
				aria-haspopup="dialog"
				aria-expanded={voiceCenterOpen}
			>
				<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true" fill="none">
					<path
						d="M8 2v12M4.5 5v6M11.5 5v6M1.5 7v2M14.5 7v2"
						stroke="currentColor"
						stroke-width="1.5"
						stroke-linecap="round"
					/>
				</svg>
				Voces
			</button>
			<button
				type="button"
				class="btn ghost"
				onclick={() => (panelOpen = true)}
				aria-haspopup="dialog"
				aria-expanded={panelOpen}
			>
				<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true" fill="none">
					<path
						d="M2 4h12M2 8h12M2 12h12"
						stroke="currentColor"
						stroke-width="1.5"
						stroke-linecap="round"
					/>
					<circle cx="6" cy="4" r="2" fill="var(--bg)" stroke="currentColor" stroke-width="1.5" />
					<circle cx="10" cy="12" r="2" fill="var(--bg)" stroke="currentColor" stroke-width="1.5" />
				</svg>
				Apariencia
			</button>
		</div>
	</header>

	<main id="contenido">
		<!-- Región viva: los cambios de estado también se anuncian a quien no los ve. -->
		<div aria-live="polite" class="sr-only">{announcement}</div>

		{#if apiMismatch}
			<div class="alert err" role="alert">
				<strong>El servicio y esta interfaz no están sincronizados</strong>
				<span>
					La API responde en un formato anterior a esta versión de la interfaz. Suele
					significar que se reconstruyó el contenedor <code>web</code> pero no el de la API.
				</span>
				<span>Ejecuta: <code>docker compose build api &amp;&amp; docker compose up -d</code></span>
			</div>
		{/if}

		{#if error}
			<div class="alert err" role="alert">
				<strong>No se pudo completar</strong>
				<span>{error}</span>
			</div>
		{/if}

		{#each system?.warnings ?? [] as warning (warning)}
			<div class="alert warn" role="status">{warning}</div>
		{/each}

		<!-- 1 · Traer un documento -->
		<section
			class="dropzone"
			class:dragging
			class:busy={uploading}
			ondragover={(e) => {
				e.preventDefault();
				dragging = true;
			}}
			ondragleave={() => (dragging = false)}
			ondrop={onDrop}
			aria-label="Añadir documentos"
		>
			<p class="drop-title">
				{uploading ? `Subiendo ${uploadingNow}…` : 'Arrastra tus documentos aquí'}
			</p>
			<p class="muted small">
				{#if uploading}
					Un documento largo tarda en subir; no cierres la pestaña.
				{:else}
					{(system?.parsers ?? []).join(' · ') || 'pdf · epub · docx · md · txt · html'}
				{/if}
			</p>

			<!-- WCAG 2.2 · 2.5.7 (Dragging Movements): arrastrar nunca es la única
			     vía. Este botón hace exactamente lo mismo y es igual de visible. -->
			<label class="btn primary file">
				Elegir archivos
				<input
					type="file"
					multiple
					disabled={uploading}
					onchange={(e) => queue((e.currentTarget as HTMLInputElement).files)}
				/>
			</label>

			{#if pending.length}
				<ul class="pending" aria-label="Documentos por convertir">
					{#each pending as file (file.name + file.size)}
						<li>
							<span class="pending-name">{file.name}</span>
							<span class="muted small tabular">{formatSize(file.size)}</span>
							<button
								class="icon-btn"
								type="button"
								disabled={uploading}
								onclick={() => unqueue(file)}
								aria-label="Quitar {file.name}"
							>
								<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" fill="none">
									<path
										d="M4 4l8 8M12 4l-8 8"
										stroke="currentColor"
										stroke-width="1.75"
										stroke-linecap="round"
									/>
								</svg>
							</button>
						</li>
					{/each}
				</ul>
			{/if}
		</section>

		{#if analyzing}
			<p class="analyzing" role="status">
				<span class="spinner" aria-hidden="true"></span>
				Analizando el documento para proponerte una configuración…
			</p>
		{/if}

		<!-- 2 · Confirmar el plan. El asistente se remonta por documento: sus
		     valores son puntos de partida editables, no un espejo del análisis. -->
		{#if assistantFile && assistantAnalysis}
			{#key assistantFile.name}
				<SetupAssistant
					file={assistantFile}
					analysis={assistantAnalysis}
					favorites={preferences.current.favoriteVoices}
					defaultVoices={preferences.current.defaultVoices}
					onstart={startFromAssistant}
					oncancel={() => {
						assistantFile = null;
						assistantAnalysis = null;
					}}
					ontogglefavorite={(v) => preferences.toggleFavorite(v)}
				/>
			{/key}
		{/if}

		<!-- 3 · Opciones manuales. Quedan para varios documentos a la vez y para
		     quien prefiera no pasar por el asistente. -->
		<section class="options" aria-label="Opciones de conversión">
			<Segmented
				legend="Qué quieres obtener"
				value={options.mode ?? 'audiobook'}
				options={[
					{ value: 'audiobook', label: 'Audiolibro', description: 'Audio con índice de capítulos' },
					{ value: 'read', label: 'Solo texto', description: 'Sin generar voz' },
					{ value: 'study', label: 'Estudio', description: 'Resumen y material de repaso' },
					{ value: 'translate', label: 'Traducir', description: 'Traduce y luego narra' }
				]}
				onchange={(v) => (options.mode = v)}
			/>

			<Disclosure
				summary="Voz y formato"
				hint="{options.style} · {(options.formats ?? []).join(', ') || 'sin formato'}"
				open={showAll}
			>
				<div class="grid">
					<Segmented
						legend="Estilo de narración"
						value={options.style ?? 'neutral'}
						options={[
							{ value: 'neutral', label: 'Neutro' },
							{ value: 'novel', label: 'Novela' },
							{ value: 'poetry', label: 'Poesía' },
							{ value: 'technical', label: 'Técnico' }
						]}
						onchange={(v) => (options.style = v)}
					/>
					<Segmented
						legend="Calidad"
						value={options.quality ?? 'high'}
						options={[
							{ value: 'high', label: 'Máxima', description: 'Más natural, más lenta' },
							{ value: 'draft', label: 'Borrador', description: 'Más rápida' }
						]}
						onchange={(v) => (options.quality = v)}
					/>
				</div>

				<fieldset class="formats">
					<legend>Archivos de salida</legend>
					<div class="chips">
						{#each [...AUDIO_FORMATS, ...TEXT_FORMATS] as format (format)}
							{@const on = options.formats?.includes(format)}
							<button
								type="button"
								class="chip"
								class:on
								aria-pressed={on}
								disabled={!system?.exporters?.includes(format)}
								onclick={() => toggleFormat(format)}
							>
								{format}
							</button>
						{/each}
					</div>
				</fieldset>
			</Disclosure>

			<Disclosure
				summary="Idioma y motor de voz"
				hint={options.target_language
					? `traduce a ${options.target_language}`
					: options.language || 'detección automática'}
				open={showAll || options.mode === 'translate'}
			>
				{#if options.mode === 'translate' && !options.target_language}
					<p class="inline-warn" role="status">
						Has elegido traducir: indica abajo el idioma de destino, o no se traducirá nada.
					</p>
				{/if}
				<div class="grid">
					<label class="field">
						<span>Motor de voz</span>
						<select bind:value={options.engine}>
							<option value={null}>Automático por idioma</option>
							{#each availableEngines as engine (engine.name)}
								<option value={engine.name}>
									{engine.name} · naturalidad {engine.naturalness.toFixed(2)}
								</option>
							{/each}
						</select>
					</label>

					<label class="field">
						<span>Idioma del documento</span>
						<input
							type="text"
							placeholder="se detecta solo"
							value={options.language ?? ''}
							oninput={(e) => (options.language = e.currentTarget.value || null)}
						/>
					</label>

					<label class="field">
						<span>Traducir a</span>
						<input
							type="text"
							placeholder={translationAvailable ? 'es, en, fr…' : 'no disponible'}
							disabled={!translationAvailable}
							value={options.target_language ?? ''}
							oninput={(e) => (options.target_language = e.currentTarget.value || null)}
						/>
						{#if !translationAvailable}
							<span class="field-note">
								Este despliegue no incluye traducción. Ver el aviso de arriba.
							</span>
						{/if}
					</label>
				</div>
			</Disclosure>

			<div class="actions">
				<button
					type="button"
					class="btn primary large"
					disabled={!pending.length || uploading || !options.formats?.length}
					onclick={convertPending}
				>
					{uploading
						? 'Convirtiendo…'
						: pending.length > 1
							? `Convertir ${pending.length} documentos`
							: 'Convertir'}
				</button>
				{#if !pending.length}
					<span class="muted small">Elige o arrastra un documento para empezar.</span>
				{:else if !options.formats?.length}
					<span class="muted small">Marca al menos un archivo de salida.</span>
				{/if}
			</div>
		</section>

		<!-- 3 · Escuchar -->
		<section class="jobs-section" aria-labelledby="jobs-title">
			<h2 id="jobs-title">
				Tus conversiones
				{#if activeJobs.length}
					<span class="chip-static live">{activeJobs.length} en curso</span>
				{/if}
			</h2>

			{#if !jobs.length}
				<p class="empty">
					Todavía no hay nada. Sube un documento y aparecerá aquí en cuanto empiece.
				</p>
			{/if}

			<ul class="jobs">
				{#each jobs as job (job.id)}
					{@const progress = live[job.id]}
					{@const ratio = progress?.ratio ?? job.progress}
					{@const audio = audioOutput(job)}
					{@const running = job.status === 'running'}
					<li class="job" class:running>
						<div class="job-head">
							<div class="job-title">
								<strong>{job.title || filename(job.source_path)}</strong>
								<span class="status {job.status}">
									{stageLabel(job.status === 'completed' ? 'completado' : undefined) &&
										(job.status === 'completed'
											? 'Listo'
											: job.status === 'failed'
												? 'Error'
												: job.status === 'cancelled'
													? 'Cancelada'
													: stageLabel(progress?.stage ?? job.stage))}
								</span>
							</div>
							{#if job.status === 'pending'}
								<button class="btn ghost small" onclick={() => onCancel(job.id)}>Cancelar</button>
							{/if}
						</div>

						{#if running || job.status === 'pending'}
							{@const indeterminate = running && ratio <= 0}
							<div
								class="bar"
								class:indeterminate
								role="progressbar"
								aria-valuenow={indeterminate ? undefined : Math.round(ratio * 100)}
								aria-valuemin="0"
								aria-valuemax="100"
								aria-label="Progreso de {job.title}"
							>
								<div class="fill" style:width={indeterminate ? undefined : `${ratio * 100}%`}></div>
							</div>
							<p class="muted small">
								{stageLabel(progress?.stage ?? job.stage)}
								{#if progress?.detail}· {progress.detail}{/if}
								{#if !indeterminate}· <span class="tabular">{Math.round(ratio * 100)}%</span>{/if}
							</p>
						{/if}

						{#if job.status === 'failed'}
							<p class="small err-text">{job.error}</p>
						{/if}

						{#if job.status === 'completed'}
							<p class="muted small meta">
								{#if job.engine}<span>{job.engine}/{job.voice}</span>{/if}
								{#if job.language}<span>{job.language}</span>{/if}
								{#if job.duration_s}<span class="tabular">{formatDuration(job.duration_s)}</span>{/if}
							</p>

							{#if audio >= 0}
								<!-- svelte-ignore a11y_media_has_caption -->
								<audio controls preload="none" src={downloadUrl(job.id, audio)}></audio>
							{/if}

							<div class="downloads">
								{#each job.outputs as output, index (output)}
									{@const ext = (filename(output).split('.').pop() ?? '').toLowerCase()}
									<a
										class="download"
										href={downloadUrl(job.id, index)}
										download
										aria-label="Descargar {filename(output)}"
									>
										<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" fill="none">
											<path
												d="M8 2v8m0 0L5 7m3 3l3-3M3 13h10"
												stroke="currentColor"
												stroke-width="1.6"
												stroke-linecap="round"
												stroke-linejoin="round"
											/>
										</svg>
										Descargar {ext}
									</a>
								{/each}
							</div>
						{/if}
					</li>
				{/each}
			</ul>
		</section>
	</main>

	<footer class="foot">
		<p>Todo se procesa aquí. Ningún documento sale de este servicio.</p>
	</footer>
</div>

<ExperiencePanel open={panelOpen} onclose={() => (panelOpen = false)} />
<VoiceCenter open={voiceCenterOpen} onclose={() => (voiceCenterOpen = false)} />

<style>
	.shell {
		min-height: 100dvh;
		display: flex;
		flex-direction: column;
	}

	/* --- Barra superior ---------------------------------------------------- */

	.topbar {
		position: sticky;
		top: 0;
		z-index: 20;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-4);
		flex-wrap: wrap;
		padding: var(--space-3) var(--space-5);
		background: color-mix(in srgb, var(--bg-elevated) 88%, transparent);
		backdrop-filter: blur(12px);
		border-bottom: 1px solid var(--border);
	}

	.brand {
		display: flex;
		align-items: center;
		gap: var(--space-3);
	}

	.mark {
		display: grid;
		place-items: center;
		width: 2.25rem;
		height: 2.25rem;
		border-radius: var(--radius);
		background: var(--accent-subtle);
		color: var(--accent);
		flex-shrink: 0;
	}

	h1 {
		margin: 0;
		font-size: var(--font-lg);
	}

	.tagline {
		margin: 0;
		font-size: var(--font-xs);
		color: var(--text-muted);
	}

	.topbar-actions {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}

	/* --- Contenido ---------------------------------------------------------- */

	main {
		flex: 1;
		width: 100%;
		max-width: var(--content-width);
		margin: 0 auto;
		padding: var(--space-6) var(--space-5) var(--space-7);
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
	}

	h2 {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		margin: 0 0 var(--space-4);
		font-size: var(--font-md);
	}

	.muted {
		color: var(--text-muted);
	}
	.small {
		font-size: var(--font-sm);
	}
	/* Cifras alineadas: sin esto, un progreso que va del 9% al 10% da un salto
	   lateral que el ojo lee como parpadeo. */
	.tabular {
		font-variant-numeric: tabular-nums;
	}

	.alert {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: var(--space-3) var(--space-4);
		border-radius: var(--radius);
		border-inline-start: 3px solid;
		font-size: var(--font-sm);
		line-height: var(--leading);
	}
	.alert.err {
		border-color: var(--err);
		background: color-mix(in srgb, var(--err) 12%, transparent);
		color: var(--text);
	}
	.alert.warn {
		border-color: var(--warn);
		background: color-mix(in srgb, var(--warn) 12%, transparent);
		color: var(--text);
	}

	/* --- Zona de subida ----------------------------------------------------- */

	.dropzone {
		padding: var(--space-7) var(--space-5);
		text-align: center;
		background: var(--bg-elevated);
		border: 1.5px dashed var(--border-strong);
		border-radius: var(--radius-lg);
		transition:
			border-color var(--duration) var(--ease),
			background var(--duration) var(--ease);
	}
	.dropzone.dragging {
		border-color: var(--accent);
		border-style: solid;
		background: var(--accent-subtle);
	}
	.dropzone.busy {
		opacity: 0.75;
	}

	.drop-title {
		margin: 0 0 var(--space-2);
		font-size: var(--font-lg);
		font-weight: 600;
	}

	.pending {
		list-style: none;
		margin: var(--space-5) auto 0;
		padding: 0;
		max-width: 34rem;
		display: grid;
		gap: var(--space-2);
		text-align: left;
	}

	.pending li {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-2) var(--space-3);
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		animation: slide-up var(--duration) var(--ease);
	}

	.pending-name {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: var(--font-sm);
	}

	/* --- Opciones ----------------------------------------------------------- */

	.analyzing {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		margin: 0;
		padding: var(--space-4);
		background: var(--accent-subtle);
		border-radius: var(--radius);
		font-size: var(--font-sm);
	}
	.spinner {
		width: 14px;
		height: 14px;
		border: 2px solid var(--border-strong);
		border-top-color: var(--accent);
		border-radius: 50%;
		animation: spin 0.7s linear infinite;
		flex-shrink: 0;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	.options {
		display: grid;
		gap: var(--space-4);
	}

	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
		gap: var(--space-4);
		padding-top: var(--space-3);
	}

	.field {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.inline-warn {
		margin: var(--space-3) 0 0;
		padding: var(--space-2) var(--space-3);
		background: color-mix(in srgb, var(--warn) 14%, transparent);
		border-inline-start: 3px solid var(--warn);
		border-radius: var(--radius);
		font-size: var(--font-sm);
		line-height: var(--leading);
	}

	.field-note {
		font-size: var(--font-xs);
		color: var(--text-muted);
		text-transform: none;
		letter-spacing: 0;
		font-weight: 400;
		line-height: var(--leading);
	}

	.field span {
		font-size: var(--font-xs);
		font-weight: 600;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}

	select,
	input[type='text'] {
		min-height: var(--target-min);
		padding: var(--space-2) var(--space-3);
		background: var(--surface);
		color: var(--text);
		border: 1px solid var(--border-strong);
		border-radius: var(--radius);
		font-size: var(--font-sm);
	}
	select:hover,
	input[type='text']:hover {
		border-color: var(--accent);
	}

	.formats {
		border: none;
		margin: var(--space-4) 0 0;
		padding: 0;
	}
	.formats legend {
		padding: 0 0 var(--space-2);
		font-size: var(--font-xs);
		font-weight: 600;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}

	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}

	.chip {
		min-height: var(--target-min);
		padding: var(--space-1) var(--space-3);
		background: var(--surface);
		border: 1px solid var(--border-strong);
		border-radius: var(--radius-full);
		color: var(--text-muted);
		font-size: var(--font-sm);
		text-decoration: none;
		transition:
			background var(--duration-fast) var(--ease),
			color var(--duration-fast) var(--ease),
			border-color var(--duration-fast) var(--ease);
	}
	.chip:hover:not(:disabled) {
		color: var(--text);
		border-color: var(--accent);
	}
	.chip.on {
		background: var(--accent-solid);
		border-color: var(--accent-solid);
		color: var(--accent-contrast);
		font-weight: 600;
	}
	.chip.link {
		display: inline-flex;
		align-items: center;
		color: var(--accent);
	}

	.chip-static {
		padding: 0.15em 0.7em;
		border-radius: var(--radius-full);
		background: var(--accent-subtle);
		color: var(--accent);
		font-size: var(--font-xs);
		font-weight: 600;
		white-space: nowrap;
	}
	.chip-static.live::before {
		content: '';
		display: inline-block;
		width: 0.45em;
		height: 0.45em;
		margin-inline-end: 0.45em;
		border-radius: 50%;
		background: currentColor;
		animation: pulse 2s var(--ease) infinite;
	}

	.actions {
		display: flex;
		align-items: center;
		gap: var(--space-4);
		flex-wrap: wrap;
		padding-top: var(--space-2);
	}

	/* --- Botones ------------------------------------------------------------ */

	.btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: var(--space-2);
		min-height: var(--target-min);
		padding: var(--space-2) var(--space-4);
		border-radius: var(--radius);
		border: 1px solid transparent;
		font-size: var(--font-sm);
		font-weight: 600;
		text-decoration: none;
		transition:
			background var(--duration-fast) var(--ease),
			border-color var(--duration-fast) var(--ease),
			transform var(--duration-fast) var(--ease);
	}
	.btn:active:not(:disabled) {
		transform: translateY(1px);
	}

	.btn.primary {
		background: var(--accent-solid);
		color: var(--accent-contrast);
	}
	.btn.primary:hover:not(:disabled) {
		background: var(--accent-hover);
	}
	.btn.large {
		font-size: var(--font-md);
		padding: var(--space-3) var(--space-6);
	}

	.btn.ghost {
		background: var(--surface);
		border-color: var(--border-strong);
		color: var(--text);
	}
	.btn.ghost:hover {
		background: var(--surface-hover);
	}
	.btn.small {
		font-size: var(--font-xs);
		padding: var(--space-1) var(--space-3);
	}

	.btn.file {
		margin-top: var(--space-4);
		cursor: pointer;
	}
	/* El input real se oculta sin salir del árbol de accesibilidad: sigue siendo
	   enfocable y el <label> lo etiqueta. `display:none` lo habría dejado
	   inalcanzable por teclado. */
	.btn.file input {
		position: absolute;
		width: 1px;
		height: 1px;
		opacity: 0;
		pointer-events: none;
	}
	/* El foco del input invisible se pinta sobre su etiqueta, que sí se ve. */
	.btn.file:has(input:focus-visible) {
		outline: var(--focus-width) solid var(--focus-color);
		outline-offset: var(--focus-offset);
	}

	.icon-btn {
		display: grid;
		place-items: center;
		min-width: var(--target-min);
		min-height: var(--target-min);
		background: none;
		border: 1px solid transparent;
		border-radius: var(--radius);
		color: var(--text-muted);
		transition:
			color var(--duration-fast) var(--ease),
			background var(--duration-fast) var(--ease);
	}
	.icon-btn:hover:not(:disabled) {
		color: var(--err);
		background: var(--surface-hover);
	}

	/* --- Conversiones -------------------------------------------------------- */

	.jobs-section {
		padding: var(--space-5);
		background: var(--bg-elevated);
		border: 1px solid var(--border);
		border-radius: var(--radius-lg);
	}

	.empty {
		margin: 0;
		color: var(--text-muted);
		font-size: var(--font-sm);
		line-height: var(--leading);
	}

	.jobs {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: var(--space-3);
	}

	.job {
		padding: var(--space-4);
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		transition: border-color var(--duration) var(--ease);
	}
	.job.running {
		border-color: var(--accent);
	}

	.job-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-3);
	}

	.job-title {
		display: flex;
		align-items: baseline;
		gap: var(--space-3);
		flex-wrap: wrap;
		min-width: 0;
	}
	.job-title strong {
		font-size: var(--font-sm);
	}

	.status {
		font-size: var(--font-xs);
		color: var(--text-muted);
	}
	.status.completed {
		color: var(--ok);
	}
	.status.failed {
		color: var(--err);
	}
	.status.running {
		color: var(--accent);
	}

	.meta {
		display: flex;
		gap: var(--space-3);
		flex-wrap: wrap;
		margin: var(--space-2) 0 0;
	}

	.bar {
		height: 4px;
		margin: var(--space-3) 0 var(--space-2);
		background: var(--border);
		border-radius: var(--radius-full);
		overflow: hidden;
	}
	.fill {
		height: 100%;
		background: var(--accent);
		border-radius: inherit;
		transition: width var(--duration-slow) var(--ease);
	}
	.bar.indeterminate .fill {
		width: 35%;
		animation: slide 1.6s var(--ease) infinite;
	}

	.err-text {
		margin: var(--space-2) 0 0;
		color: var(--err);
	}

	audio {
		width: 100%;
		margin-top: var(--space-3);
		border-radius: var(--radius);
	}

	/* Un chip con la extensión suelta («md») no se lee como algo pulsable. Con
	   icono, verbo y borde de acento sí. Es el elemento que más se busca al
	   terminar una conversión: merece parecer un botón. */
	.download {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		min-height: var(--target-min);
		padding: var(--space-2) var(--space-3);
		background: var(--surface-hover);
		border: 1px solid var(--accent);
		border-radius: var(--radius);
		color: var(--accent);
		font-size: var(--font-sm);
		font-weight: 600;
		text-decoration: none;
		transition:
			background var(--duration-fast) var(--ease),
			color var(--duration-fast) var(--ease);
	}
	.download:hover {
		background: var(--accent-solid);
		color: var(--accent-contrast);
	}
	.download:active {
		transform: translateY(1px);
	}

	.downloads {
		display: flex;
		gap: var(--space-2);
		flex-wrap: wrap;
		margin-top: var(--space-3);
	}

	.foot {
		padding: var(--space-5);
		border-top: 1px solid var(--border);
		text-align: center;
	}
	.foot p {
		margin: 0;
		font-size: var(--font-xs);
		color: var(--text-muted);
	}

	/* --- Micro-interacciones -------------------------------------------------
	 * Todas cuelgan de --motion. Con animaciones desactivadas, las duraciones son
	 * 0 y estos fotogramas no llegan a verse: no hace falta condicionar el marcado.
	 */

	@keyframes slide-up {
		from {
			opacity: 0;
			transform: translateY(4px);
		}
	}
	@keyframes slide {
		from {
			transform: translateX(-120%);
		}
		to {
			transform: translateX(400%);
		}
	}
	@keyframes pulse {
		50% {
			opacity: 0.35;
		}
	}

	/* --- Adaptación al ancho -------------------------------------------------
	 * WCAG 1.4.10 (Reflow): usable a 320 px sin desplazamiento horizontal.
	 */
	@media (max-width: 34rem) {
		.topbar {
			padding: var(--space-3);
		}
		.tagline {
			display: none;
		}
		main {
			padding: var(--space-4) var(--space-3) var(--space-6);
		}
		.dropzone {
			padding: var(--space-5) var(--space-3);
		}
	}
</style>
