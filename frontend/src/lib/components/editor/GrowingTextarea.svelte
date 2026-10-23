<script lang="ts">
	interface Props {
		value: string;
		oninput: (value: string) => void;
		id?: string;
		class?: string;
		monospace?: boolean;
		minimumLines: number;
	}

	let { value, oninput, id, class: className, monospace = false, minimumLines }: Props = $props();

	const SECTION_LABEL = /(\[[^\]\n]*\])/;

	// The odd entries are the `[…]` section labels the split keeps. The closing
	// newline gives a trailing empty line in the textarea its height here too.
	const segments = $derived(`${value}\n`.split(SECTION_LABEL));
</script>

<!-- The mirror and the textarea share one grid cell and the same metrics, so
     the cell is as tall as the mirrored text and the field never scrolls.
     The mirror only paints; the textarea stays the one editable node. -->
<div class="growing" class:monospace>
	<textarea
		{id}
		class={className}
		rows={minimumLines}
		{value}
		oninput={(event) => oninput(event.currentTarget.value)}></textarea>
	<div class="mirror" aria-hidden="true">
		{#each segments as segment, index (index)}
			{#if index % 2 === 1}<span class="section-label">{segment}</span>{:else}{segment}{/if}
		{/each}
	</div>
</div>

<style>
	.growing {
		display: grid;
		width: 100%;
		min-width: 0;
	}

	.growing > textarea,
	.mirror {
		grid-area: 1 / 1;
		box-sizing: border-box;
		min-width: 0;
		padding: var(--input-padding);
		border: 1px solid transparent;
		border-radius: var(--input-radius);
		font-family: inherit;
		font-size: var(--input-font-size);
		line-height: 1.6;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}

	.monospace > textarea,
	.monospace > .mirror {
		font-family: 'Courier New', monospace;
	}

	textarea {
		background: var(--surface);
		border-color: var(--border);
		color: transparent;
		caret-color: var(--text);
		resize: none;
		overflow: hidden;
	}

	textarea:focus {
		border-color: var(--accent);
		outline: none;
		box-shadow: var(--input-focus-glow);
	}

	.mirror {
		color: var(--text);
		pointer-events: none;
	}

	/* Colour only: any other change of font, size or weight changes the
	   advance widths and shifts the caret off the characters it edits. */
	.section-label {
		color: var(--accent);
	}
</style>
