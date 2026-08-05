<!--
  Control segmentado accesible, al estilo de los conmutadores de Arc o Notion.

  Se implementa como `radiogroup` con navegación por flechas y un solo punto de
  tabulación (patrón «roving tabindex»). Es lo que distingue un control que
  *parece* nativo de uno que se comporta como tal: con cinco opciones, tabular
  cinco veces para atravesar un grupo es exactamente el tipo de fricción que hace
  que la gente abandone la navegación por teclado.

  El indicador deslizante es puramente decorativo (`aria-hidden`) y su transición
  cuelga de `--motion`.
-->
<script lang="ts" generics="T extends string">
	interface Option {
		value: T;
		label: string;
		/** Descripción larga para lectores de pantalla, si el rótulo no basta. */
		description?: string;
	}

	interface Props {
		legend: string;
		options: Option[];
		value: T;
		onchange: (value: T) => void;
		/** Oculta el rótulo visualmente pero lo deja para tecnología asistiva. */
		hideLegend?: boolean;
	}

	let { legend, options, value, onchange, hideLegend = false }: Props = $props();

	let buttons = $state<HTMLButtonElement[]>([]);
	const index = $derived(Math.max(0, options.findIndex((o) => o.value === value)));

	function onkeydown(event: KeyboardEvent) {
		const pasos: Record<string, number> = {
			ArrowRight: 1,
			ArrowDown: 1,
			ArrowLeft: -1,
			ArrowUp: -1
		};
		let destino: number | null = null;

		if (event.key in pasos) destino = (index + pasos[event.key] + options.length) % options.length;
		else if (event.key === 'Home') destino = 0;
		else if (event.key === 'End') destino = options.length - 1;
		if (destino === null) return;

		event.preventDefault();
		onchange(options[destino].value);
		// El foco sigue a la selección: en un radiogroup, mover el foco sin
		// seleccionar deja al lector de pantalla anunciando algo que no ha pasado.
		buttons[destino]?.focus();
	}
</script>

<fieldset class="segmented" role="radiogroup" aria-label={legend}>
	{#if !hideLegend}
		<legend>{legend}</legend>
	{/if}
	<div class="track" style:--count={options.length}>
		<span class="thumb" style:--index={index} aria-hidden="true"></span>
		{#each options as option, i (option.value)}
			<button
				bind:this={buttons[i]}
				type="button"
				role="radio"
				aria-checked={option.value === value}
				tabindex={option.value === value ? 0 : -1}
				class="option"
				class:selected={option.value === value}
				onclick={() => onchange(option.value)}
				{onkeydown}
			>
				{option.label}
				<!-- La descripción va como texto oculto dentro del botón en vez de en
				     `aria-description`, que aún no soportan todos los lectores. Así
				     forma parte del nombre accesible y se anuncia siempre. -->
				{#if option.description}
					<span class="sr-only">. {option.description}</span>
				{/if}
			</button>
		{/each}
	</div>
</fieldset>

<style>
	.segmented {
		border: none;
		margin: 0;
		padding: 0;
		min-width: 0;
	}

	legend {
		padding: 0 0 var(--space-2);
		font-size: var(--font-xs);
		font-weight: 600;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}

	.track {
		position: relative;
		display: grid;
		grid-template-columns: repeat(var(--count), 1fr);
		gap: 2px;
		padding: 3px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
	}

	.thumb {
		position: absolute;
		top: 3px;
		bottom: 3px;
		left: 3px;
		width: calc((100% - 6px - (var(--count) - 1) * 2px) / var(--count));
		transform: translateX(calc(var(--index) * (100% + 2px)));
		background: var(--accent-subtle);
		border: 1px solid var(--accent);
		border-radius: calc(var(--radius) - 3px);
		transition: transform var(--duration) var(--ease-spring);
		pointer-events: none;
	}

	.option {
		position: relative;
		min-height: calc(var(--target-min) - 6px);
		padding: var(--space-2) var(--space-2);
		background: none;
		border: none;
		border-radius: calc(var(--radius) - 3px);
		color: var(--text-muted);
		font: inherit;
		font-size: var(--font-sm);
		cursor: pointer;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		transition: color var(--duration-fast) var(--ease);
	}

	.option:hover {
		color: var(--text);
	}
	.option.selected {
		color: var(--accent);
		font-weight: 600;
	}
</style>
