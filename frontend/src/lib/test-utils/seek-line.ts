import { tick } from 'svelte';
import { vi } from 'vitest';

// Where a test lays the seek line out on screen: 200 px wide, 100 px in.
const SEEK_LINE_LEFT = 100;
const SEEK_LINE_WIDTH = 200;

// jsdom has no pointer capture; a no-op lets the line take the pointer as a
// browser would, while the test plays every event the captured pointer sends.
if (typeof HTMLElement.prototype.setPointerCapture !== 'function') {
	HTMLElement.prototype.setPointerCapture = () => {};
}

/** The seek line inside `root`, laid out where a browser would put it. */
export function laidOutSeekLine(root: ParentNode): HTMLElement {
	const line = root.querySelector<HTMLElement>('.seek');
	if (!line) throw new Error('Expected the seek line');
	vi.spyOn(line, 'getBoundingClientRect').mockReturnValue({
		left: SEEK_LINE_LEFT,
		width: SEEK_LINE_WIDTH
	} as DOMRect);
	return line;
}

// The screen x of the point `fraction` of the way along the line; a fraction
// below 0 or above 1 lies off either end.
function alongSeekLine(fraction: number): number {
	return SEEK_LINE_LEFT + fraction * SEEK_LINE_WIDTH;
}

/** One event of the finger or mouse that holds the line. */
export async function pointerOnSeekLine(
	line: HTMLElement,
	type: 'pointerdown' | 'pointermove' | 'pointerup' | 'pointercancel',
	fraction: number
): Promise<void> {
	line.dispatchEvent(
		new PointerEvent(type, {
			bubbles: true,
			button: 0,
			pointerId: 1,
			clientX: alongSeekLine(fraction)
		})
	);
	await tick();
}

/** The time a drag would land on, as shown above the pointer; null when none shows. */
export function shownSeekTime(root: ParentNode): string | null {
	return root.querySelector('.seek-time')?.textContent ?? null;
}
