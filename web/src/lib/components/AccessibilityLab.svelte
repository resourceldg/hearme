<!--
  Laboratorio de Accesibilidad. Solo en desarrollo.

  ## Para qué existe

  La mayoría de las barreras de accesibilidad no se introducen por descuido, se
  introducen **porque quien programa no las percibe**. Un contraste que funciona
  con vista perfecta, un objetivo de 18 px que se acierta con ratón, un cambio
  de estado que se ve pero no se anuncia: todo eso pasa la revisión visual sin
  despeinarse.

  Este laboratorio hace visible lo invisible *durante* el desarrollo, no en una
  auditoría tres meses después cuando ya cuesta diez veces más arreglarlo.

  ## Lo que NO es

  **Ninguna de estas simulaciones sustituye a una persona.** Un desenfoque no es
  baja visión; una matriz de color no es daltonismo; la previsualización de
  lectura no es NVDA. Simular una condición desde fuera produce, como mucho,
  empatía y una lista de sospechas. La validación de verdad está en
  `docs/ASSISTIVE-TECHNOLOGY.md`, y la hacen personas que usan estas
  tecnologías a diario y cobran por ello.

  Se dice aquí, en el propio panel, porque una herramienta de simulación sin esa
  advertencia produce justo lo contrario de lo que busca: la confianza de creer
  que ya está comprobado.
-->
<script lang="ts">
	import { auditLive, announce, type Finding } from '$lib/a11y/inspect';

	type Vision = 'ninguna' | 'borrosa' | 'protanopia' | 'deuteranopia' | 'tritanopia' | 'acromatopsia';

	let open = $state(false);
	let vision = $state<Vision>('ninguna');
	let keyboardOnly = $state(false);
	let readerPreview = $state(false);
	let findings = $state<Finding[]>([]);
	let focusedAnnouncement = $state('');
	let audited = $state(false);

	const errores = $derived(findings.filter((f) => f.severity === 'error').length);

	function run() {
		findings = auditLive();
		audited = true;
	}

	function clear() {
		vision = 'ninguna';
		keyboardOnly = false;
		readerPreview = false;
		findings = [];
		audited = false;
	}

	// Los filtros se aplican al documento entero salvo a este panel, que debe
	// seguir siendo legible mientras se simula una condición.
	$effect(() => {
		document.documentElement.dataset.a11ySim = vision === 'ninguna' ? '' : vision;
		document.documentElement.dataset.a11yKeyboard = keyboardOnly ? 'on' : '';
	});

	$effect(() => {
		if (!readerPreview) return;
		const onFocus = (e: FocusEvent) => {
			const target = e.target as Element | null;
			focusedAnnouncement = target ? announce(target) : '';
		};
		document.addEventListener('focusin', onFocus);
		return () => document.removeEventListener('focusin', onFocus);
	});

	function highlight(finding: Finding) {
		finding.element.scrollIntoView({ block: 'center', behavior: 'smooth' });
		const el = finding.element as HTMLElement;
		const previo = el.style.outline;
		el.style.outline = '3px solid #ff8a80';
		setTimeout(() => (el.style.outline = previo), 1600);
	}
</script>

<!--
  Matrices de simulación cromática. Son las de uso habitual en la literatura de
  accesibilidad; reproducen la confusión de tonos, no la experiencia de nadie.
-->
<svg class="filters" aria-hidden="true" focusable="false">
	<defs>
		<filter id="sim-protanopia">
			<feColorMatrix
				type="matrix"
				values="0.567 0.433 0 0 0  0.558 0.442 0 0 0  0 0.242 0.758 0 0  0 0 0 1 0"
			/>
		</filter>
		<filter id="sim-deuteranopia">
			<feColorMatrix
				type="matrix"
				values="0.625 0.375 0 0 0  0.7 0.3 0 0 0  0 0.3 0.7 0 0  0 0 0 1 0"
			/>
		</filter>
		<filter id="sim-tritanopia">
			<feColorMatrix
				type="matrix"
				values="0.95 0.05 0 0 0  0 0.433 0.567 0 0  0 0.475 0.525 0 0  0 0 0 1 0"
			/>
		</filter>
		<filter id="sim-acromatopsia">
			<feColorMatrix
				type="matrix"
				values="0.299 0.587 0.114 0 0  0.299 0.587 0.114 0 0  0.299 0.587 0.114 0 0  0 0 0 1 0"
			/>
		</filter>
	</defs>
</svg>

<div class="lab" class:open>
	<button
		type="button"
		class="toggle"
		onclick={() => (open = !open)}
		aria-expanded={open}
		aria-controls={open ? 'a11y-lab-panel' : undefined}
	>
		Laboratorio a11y
		{#if audited}
			<span class="count" class:bad={errores > 0}>{findings.length}</span>
		{/if}
	</button>

	{#if open}
		<div class="panel" id="a11y-lab-panel">
			<p class="warn">
				Solo en desarrollo. Simular una condición no equivale a vivirla: esto caza fallos
				mecánicos, no sustituye la validación con personas que usan estas tecnologías.
			</p>

			<fieldset>
				<legend>Visión</legend>
				<select bind:value={vision}>
					<option value="ninguna">Sin simulación</option>
					<option value="borrosa">Agudeza reducida</option>
					<option value="protanopia">Protanopia (rojo)</option>
					<option value="deuteranopia">Deuteranopia (verde)</option>
					<option value="tritanopia">Tritanopia (azul)</option>
					<option value="acromatopsia">Acromatopsia</option>
				</select>
			</fieldset>

			<label class="check">
				<input type="checkbox" bind:checked={keyboardOnly} />
				Solo teclado <span class="hint">oculta el puntero</span>
			</label>

			<label class="check">
				<input type="checkbox" bind:checked={readerPreview} />
				Previsualizar lectura <span class="hint">aproximada, no es un lector real</span>
			</label>

			{#if readerPreview}
				<p class="announcement" aria-live="off">
					{focusedAnnouncement || 'Tabula para oír qué se anunciaría…'}
				</p>
			{/if}

			<div class="row">
				<button type="button" class="run" onclick={run}>Auditar la página</button>
				<button type="button" class="reset" onclick={clear}>Limpiar</button>
			</div>

			{#if audited}
				{#if findings.length === 0}
					<p class="ok">Sin fallos mecánicos. Falta lo importante: probarlo con personas.</p>
				{:else}
					<ul class="findings">
						{#each findings as finding, i (i)}
							<li class={finding.severity}>
								<button type="button" onclick={() => highlight(finding)}>
									<span class="criterion">{finding.criterion}</span>
									{finding.message}
								</button>
							</li>
						{/each}
					</ul>
				{/if}
			{/if}
		</div>
	{/if}
</div>

<style>
	.filters {
		position: absolute;
		width: 0;
		height: 0;
	}

	.lab {
		position: fixed;
		inset-block-end: 1rem;
		inset-inline-start: 1rem;
		z-index: 90;
		font-size: 0.8rem;
		font-family: var(--font-mono, monospace);
	}

	.toggle {
		display: inline-flex;
		align-items: center;
		gap: 0.5rem;
		min-height: 32px;
		padding: 0.35rem 0.7rem;
		background: #1f1f1f;
		color: #d4d4d4;
		border: 1px solid #6e6e73;
		border-radius: 6px;
		font: inherit;
		cursor: pointer;
	}

	.count {
		padding: 0 0.4em;
		border-radius: 999px;
		background: #4ec9b0;
		color: #000;
		font-weight: 700;
	}
	.count.bad {
		background: #f48771;
	}

	.panel {
		width: min(26rem, calc(100vw - 2rem));
		max-height: 70vh;
		overflow-y: auto;
		margin-block-end: 0.5rem;
		padding: 0.9rem;
		background: #1f1f1f;
		color: #d4d4d4;
		border: 1px solid #6e6e73;
		border-radius: 8px;
		display: flex;
		flex-direction: column;
		gap: 0.7rem;
	}

	.warn {
		margin: 0;
		padding: 0.5rem 0.6rem;
		background: rgba(215, 186, 125, 0.14);
		border-inline-start: 3px solid #d7ba7d;
		border-radius: 4px;
		line-height: 1.5;
	}

	fieldset {
		border: none;
		margin: 0;
		padding: 0;
	}
	legend {
		padding: 0 0 0.3rem;
		font-weight: 700;
	}

	select {
		width: 100%;
		min-height: 32px;
		padding: 0.3rem;
		background: #2d2d30;
		color: inherit;
		border: 1px solid #6e6e73;
		border-radius: 4px;
		font: inherit;
	}

	.check {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		min-height: 32px;
		cursor: pointer;
	}
	.hint {
		color: #9d9d9d;
	}

	.announcement {
		margin: 0;
		padding: 0.6rem;
		background: #2d2d30;
		border-radius: 4px;
		border-inline-start: 3px solid #0089e6;
		line-height: 1.5;
	}

	.row {
		display: flex;
		gap: 0.5rem;
	}

	.run,
	.reset {
		flex: 1;
		min-height: 32px;
		background: #0077c7;
		color: #fff;
		border: none;
		border-radius: 4px;
		font: inherit;
		cursor: pointer;
	}
	.reset {
		background: #2d2d30;
		color: #d4d4d4;
		border: 1px solid #6e6e73;
	}

	.ok {
		margin: 0;
		color: #4ec9b0;
		line-height: 1.5;
	}

	.findings {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: 0.3rem;
	}

	.findings button {
		width: 100%;
		padding: 0.45rem 0.6rem;
		text-align: left;
		background: #2d2d30;
		color: inherit;
		border: none;
		border-inline-start: 3px solid #d7ba7d;
		border-radius: 4px;
		font: inherit;
		line-height: 1.5;
		cursor: pointer;
	}
	.findings li.error button {
		border-inline-start-color: #f48771;
	}

	.criterion {
		display: block;
		color: #9d9d9d;
	}

	/* --- Simulaciones ------------------------------------------------------
	 * Se aplican al <body> y no al <html> para que este panel quede fuera: hay
	 * que poder leer los hallazgos mientras se simula una acromatopsia.
	 */
	:global(html[data-a11y-sim='borrosa'] body > *:not(.lab)) {
		filter: blur(1.6px);
	}
	:global(html[data-a11y-sim='protanopia'] body > *:not(.lab)) {
		filter: url(#sim-protanopia);
	}
	:global(html[data-a11y-sim='deuteranopia'] body > *:not(.lab)) {
		filter: url(#sim-deuteranopia);
	}
	:global(html[data-a11y-sim='tritanopia'] body > *:not(.lab)) {
		filter: url(#sim-tritanopia);
	}
	:global(html[data-a11y-sim='acromatopsia'] body > *:not(.lab)) {
		filter: url(#sim-acromatopsia);
	}

	/* Sin puntero: obliga a recorrer la interfaz como quien no usa ratón. Es la
	   simulación más honesta de todas, porque no simula nada: quita una
	   herramienta de verdad. */
	:global(html[data-a11y-keyboard='on'] body *) {
		cursor: none !important;
	}
</style>
