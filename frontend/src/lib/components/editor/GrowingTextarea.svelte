<script lang="ts">
	import { tick } from 'svelte';
	import { typingOnPhone } from '$lib/stores/ui';

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

	let textarea: HTMLTextAreaElement | undefined = $state();
	let mirror: HTMLDivElement | undefined = $state();

	// The mirror holds exactly `${value}\n`, so the caret's offset in the field
	// is the same offset in the mirror's text. A collapsed range has no box on
	// an empty line in some browsers, so the neighbouring character stands in.
	function caretLineRect(mirrorElement: HTMLElement, caretOffset: number): DOMRect | undefined {
		const walker = document.createTreeWalker(mirrorElement, NodeFilter.SHOW_TEXT);
		const range = document.createRange();
		let passed = 0;
		for (let node = walker.nextNode(); node; node = walker.nextNode()) {
			const length = node.textContent?.length ?? 0;
			if (caretOffset > passed + length) {
				passed += length;
				continue;
			}
			const offset = caretOffset - passed;
			range.setStart(node, offset);
			range.collapse(true);
			const rects = [range.getBoundingClientRect()];
			if (offset < length) {
				range.setEnd(node, offset + 1);
				rects.push(range.getBoundingClientRect());
			}
			return rects.find((rect) => rect.height > 0);
		}
		return undefined;
	}

	// The browser reveals a caret only inside the layout viewport, and the page
	// scrolls, not the field. The keyboard shortens the visual viewport alone, so
	// the caret's line is brought into it by scrolling the page.
	async function keepCaretVisible(): Promise<void> {
		await tick();
		const visible = window.visualViewport;
		if (!$typingOnPhone || !visible || !textarea || !mirror) return;
		if (document.activeElement !== textarea) return;
		const line = caretLineRect(mirror, textarea.selectionEnd);
		if (!line) return;
		const visibleBottom = visible.offsetTop + visible.height;
		if (line.bottom > visibleBottom) window.scrollBy(0, line.bottom - visibleBottom);
		else if (line.top < visible.offsetTop) window.scrollBy(0, line.top - visible.offsetTop);
	}

	$effect(() => {
		if (!textarea || !$typingOnPhone) return;
		const field = textarea;
		void keepCaretVisible();
		field.addEventListener('selectionchange', keepCaretVisible);
		return () => field.removeEventListener('selectionchange', keepCaretVisible);
	});
</script>

<!-- The mirror and the textarea share one grid cell and the same metrics, so
     the cell is as tall as the mirrored text and the field never scrolls.
     The mirror only paints; the textarea stays the one editable node. -->
<div class="growing" class:monospace>
	<textarea
		bind:this={textarea}
		{id}
		class={className}
		rows={minimumLines}
		{value}
		oninput={(event) => {
			oninput(event.currentTarget.value);
			void keepCaretVisible();
		}}></textarea>
	<div class="mirror" aria-hidden="true" bind:this={mirror}>
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
