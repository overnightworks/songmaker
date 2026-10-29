<script lang="ts">
	import { tick } from 'svelte';
	import { onScreenKeyboardHeightPx, typingOnPhone } from '#lib/stores/ui.ts';

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
	// an empty line in some browsers, so the neighbouring characters stand in.
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
			if (offset > 0) {
				range.setStart(node, offset - 1);
				range.setEnd(node, offset);
				rects.push(range.getBoundingClientRect());
			}
			return rects.find((rect) => rect.height > 0);
		}
		return undefined;
	}

	function scrollingAncestor(element: HTMLElement): HTMLElement | undefined {
		for (let parent = element.parentElement; parent; parent = parent.parentElement) {
			const { overflowY } = getComputedStyle(parent);
			if (overflowY === 'auto' || overflowY === 'scroll') return parent;
		}
		return undefined;
	}

	// The keyboard covers the bottom of the layout viewport, so the scroller
	// cannot bring a line near the end of the text above it without room under
	// the text. It is added only while the keyboard is open.
	let keyboardRoomPx = $state(0);

	// The browser reveals a caret only inside the layout viewport, and the page
	// does not scroll, its main region does. The keyboard shortens the visual
	// viewport alone, so the caret's line is brought into the part of the
	// scroller the keyboard leaves free by scrolling that region.
	async function keepCaretVisible(): Promise<void> {
		const visible = window.visualViewport;
		if (!$typingOnPhone || !visible || !textarea || !mirror) return;
		const focused = document.activeElement === textarea;
		keyboardRoomPx = focused ? onScreenKeyboardHeightPx(document) : 0;
		if (!focused) return;
		await tick();
		if (document.activeElement !== textarea) return;
		const scroller = scrollingAncestor(textarea);
		const line = caretLineRect(mirror, textarea.selectionEnd);
		if (!scroller || !line) return;
		const scrollerRect = scroller.getBoundingClientRect();
		const bandTop = Math.max(scrollerRect.top, visible.offsetTop);
		const bandBottom = Math.min(scrollerRect.bottom, visible.offsetTop + visible.height);
		if (line.bottom > bandBottom) scroller.scrollBy(0, line.bottom - bandBottom);
		else if (line.top < bandTop) scroller.scrollBy(0, line.top - bandTop);
	}

	$effect(() => {
		if (!$typingOnPhone) {
			keyboardRoomPx = 0;
			return;
		}
		void keepCaretVisible();
		document.addEventListener('selectionchange', keepCaretVisible);
		return () => document.removeEventListener('selectionchange', keepCaretVisible);
	});
</script>

<!-- The mirror and the textarea share one grid cell and the same metrics, so
     the cell is as tall as the mirrored text and the field never scrolls.
     The mirror only paints; the textarea stays the one editable node. -->
<div class="growing" class:monospace style:padding-bottom="{keyboardRoomPx}px">
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
