<!--
  Progressive Disclosure: el mecanismo, no el adorno.

  La filosofía es sencilla de enunciar y difícil de sostener: **quien llega por
  primera vez ve lo mínimo para conseguir lo que vino a hacer; quien sabe lo que
  quiere, lo tiene todo a un clic.** Ni un asistente que trate a nadie como
  novato para siempre, ni un panel de veinte controles que ahuyente en el primer
  minuto.

  Detalles que suelen faltar en implementaciones de esto:

  - `aria-expanded` y `aria-controls` de verdad, para que un lector de pantalla
    anuncie el estado y sepa qué región gobierna el botón.
  - El contenido se **desmonta** al cerrar, no se oculta con CSS. Escondido con
    `display:none` seguiría en el árbol de accesibilidad de algunos navegadores y
    en el orden de tabulación de otros.
  - La animación de apertura respeta `--motion`, que a su vez respeta
    `prefers-reduced-motion`.
-->
<script lang="ts">
	interface Props {
		summary: string;
		hint?: string;
		open?: boolean;
		/** Cuenta de elementos activos dentro; se anuncia junto al título. */
		badge?: string;
		children: import('svelte').Snippet;
	}

	let { summary, hint = '', open = $bindable(false), badge = '', children }: Props = $props();

	const id = $props.id();
	const panelId = `disclosure-panel-${id}`;
	const buttonId = `disclosure-button-${id}`;
</script>

<div class="disclosure">
	<!--
		`aria-controls` solo cuando el panel existe de verdad. Cerrado se desmonta,
		y una referencia colgante es peor que no ponerla: no degrada, deja el
		atributo sin efecto y engaña a quien lea el código creyendo que hace algo.
		La norma lo da por opcional en este patrón, así que se omite en vez de mentir.
	-->
	<button
		type="button"
		id={buttonId}
		class="trigger"
		aria-expanded={open}
		aria-controls={open ? panelId : undefined}
		onclick={() => (open = !open)}
	>
		<svg class="chevron" class:open viewBox="0 0 16 16" aria-hidden="true" focusable="false">
			<path
				d="M6 4l4 4-4 4"
				fill="none"
				stroke="currentColor"
				stroke-width="1.75"
				stroke-linecap="round"
				stroke-linejoin="round"
			/>
		</svg>
		<span class="label">
			{summary}
			{#if badge}<span class="badge">{badge}</span>{/if}
		</span>
		{#if hint && !open}
			<span class="hint">{hint}</span>
		{/if}
	</button>

	{#if open}
		<!-- El id tiene que ser `panelId`, el mismo al que apunta aria-controls.
		     Aquí ponía `id` a secas y la referencia quedaba rota: la interfaz se
		     veía perfecta y solo lo habría notado quien navega con lector. -->
		<div class="panel" id={panelId} role="region" aria-labelledby={buttonId}>
			{@render children()}
		</div>
	{/if}
</div>

<style>
	.disclosure {
		border: 1px solid var(--border);
		border-radius: var(--radius);
		background: var(--bg-elevated);
		overflow: hidden;
	}

	.trigger {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		width: 100%;
		min-height: var(--target-min);
		padding: var(--space-3) var(--space-4);
		background: none;
		border: none;
		color: var(--text);
		font: inherit;
		font-size: var(--font-sm);
		font-weight: 600;
		text-align: left;
		cursor: pointer;
		transition: background var(--duration-fast) var(--ease);
	}

	.trigger:hover {
		background: var(--surface-hover);
	}

	.chevron {
		width: 1em;
		height: 1em;
		flex-shrink: 0;
		color: var(--text-muted);
		transition: transform var(--duration) var(--ease);
	}
	.chevron.open {
		transform: rotate(90deg);
	}

	.label {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}

	.badge {
		padding: 0.1em 0.5em;
		border-radius: var(--radius-full);
		background: var(--accent-subtle);
		color: var(--accent);
		font-size: var(--font-xs);
		font-weight: 600;
	}

	/* La pista solo aparece cerrado: es la promesa de lo que hay dentro, y una
	   vez abierto el contenido habla por sí mismo. */
	.hint {
		margin-left: auto;
		color: var(--text-muted);
		font-weight: 400;
		font-size: var(--font-xs);
		text-align: right;
	}

	.panel {
		padding: 0 var(--space-4) var(--space-4);
		animation: reveal var(--duration) var(--ease);
	}

	@keyframes reveal {
		from {
			opacity: 0;
			transform: translateY(-4px);
		}
	}

	/* Con --motion a 0 la duración es 0 y la animación no llega a verse. */
</style>
