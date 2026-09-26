import { beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

beforeEach(() => {
	localStorage.clear();
	vi.resetModules();
});

describe('railCollapsed', () => {
	it('starts expanded when this browser has no rail preference', async () => {
		const { railCollapsed } = await import('./ui');

		expect(get(railCollapsed)).toBe(false);
	});

	it('restores the browser preference after a reload', async () => {
		localStorage.setItem('songmaker.rail-collapsed', 'true');
		const { initRailCollapsed, railCollapsed } = await import('./ui');

		expect(get(railCollapsed)).toBe(true);
		railCollapsed.set(false);
		initRailCollapsed();
		expect(get(railCollapsed)).toBe(true);
	});

	it('persists each edge-control toggle', async () => {
		const { railCollapsed, toggleRailCollapsed } = await import('./ui');

		toggleRailCollapsed();
		expect(get(railCollapsed)).toBe(true);
		expect(localStorage.getItem('songmaker.rail-collapsed')).toBe('true');

		toggleRailCollapsed();
		expect(get(railCollapsed)).toBe(false);
		expect(localStorage.getItem('songmaker.rail-collapsed')).toBe('false');
	});
});

describe('libraryContinueCollapsed', () => {
	it('starts open when this browser has no Continue preference', async () => {
		const { libraryContinueCollapsed } = await import('./ui');

		expect(get(libraryContinueCollapsed)).toBe(false);
	});

	it('restores and persists the browser preference', async () => {
		localStorage.setItem('songmaker.library-continue-collapsed', 'true');
		const {
			initLibraryContinueCollapsed,
			libraryContinueCollapsed,
			toggleLibraryContinueCollapsed
		} = await import('./ui');

		expect(get(libraryContinueCollapsed)).toBe(true);
		toggleLibraryContinueCollapsed();
		expect(get(libraryContinueCollapsed)).toBe(false);
		expect(localStorage.getItem('songmaker.library-continue-collapsed')).toBe('false');

		libraryContinueCollapsed.set(true);
		initLibraryContinueCollapsed();
		expect(get(libraryContinueCollapsed)).toBe(false);
	});
});

describe('railWidth', () => {
	it('starts at the default width when this browser has no rail preference', async () => {
		const { railWidth } = await import('./ui');

		expect(get(railWidth)).toBe(264);
	});

	it('clamps and persists width changes at the store boundary', async () => {
		const { railWidth, setRailWidth, RAIL_MAX_WIDTH_PX, RAIL_MIN_WIDTH_PX } = await import('./ui');

		setRailWidth(RAIL_MAX_WIDTH_PX + 20);
		expect(get(railWidth)).toBe(RAIL_MAX_WIDTH_PX);
		expect(localStorage.getItem('songmaker.rail-width')).toBe(String(RAIL_MAX_WIDTH_PX));

		setRailWidth(RAIL_MIN_WIDTH_PX - 20);
		expect(get(railWidth)).toBe(RAIL_MIN_WIDTH_PX);
		expect(localStorage.getItem('songmaker.rail-width')).toBe(String(RAIL_MIN_WIDTH_PX));
	});

	it('restores a clamped browser preference after a reload', async () => {
		localStorage.setItem('songmaker.rail-width', '480');
		const { initRailWidth, railWidth } = await import('./ui');

		expect(get(railWidth)).toBe(360);
		railWidth.set(264);
		initRailWidth();
		expect(get(railWidth)).toBe(360);
	});
});

describe('phoneAppBar', () => {
	it('starts with the library brand rather than a persisted song context', async () => {
		const { phoneAppBar } = await import('./ui');
		expect(get(phoneAppBar)).toBeNull();
	});
});

describe('typingOnPhone', () => {
	function field(html: string): HTMLElement {
		const holder = document.createElement('div');
		holder.innerHTML = html;
		document.body.replaceChildren(holder);
		const element = holder.firstElementChild;
		if (!(element instanceof HTMLElement)) throw new Error(`Expected an element from ${html}`);
		return element;
	}

	it.each([
		['the lyrics', '<textarea></textarea>'],
		['a rename field', '<input />'],
		['a search field', '<input type="search" />'],
		['a recipe number', '<input type="number" />']
	])(
		'hides the bars while %s has focus on the phone, and brings them back on leaving it',
		async (_, html) => {
			const { typingOnPhone, watchTypingOnPhone } = await import('./ui');
			const stop = watchTypingOnPhone(document, true);
			const input = field(html);

			input.focus();
			expect(get(typingOnPhone)).toBe(true);
			input.blur();
			expect(get(typingOnPhone)).toBe(false);
			stop();
		}
	);

	it.each([
		['a checkbox', '<input type="checkbox" />'],
		['a slider', '<input type="range" />'],
		['a button', '<button type="button">Generate</button>']
	])('keeps the bars while %s has focus, since it takes no typing', async (_, html) => {
		const { typingOnPhone, watchTypingOnPhone } = await import('./ui');
		const stop = watchTypingOnPhone(document, true);

		field(html).focus();
		expect(get(typingOnPhone)).toBe(false);
		stop();
	});

	it('keeps the bars away while focus moves from one field to the next', async () => {
		const { typingOnPhone, watchTypingOnPhone } = await import('./ui');
		const stop = watchTypingOnPhone(document, true);
		const [style, lyrics] = Array.from(
			field('<div><textarea></textarea><textarea></textarea></div>').children
		) as HTMLTextAreaElement[];
		style.focus();
		const seen: boolean[] = [];
		const unsubscribe = typingOnPhone.subscribe((typing) => seen.push(typing));

		lyrics.focus();
		expect(seen).toEqual([true]);
		unsubscribe();
		stop();
	});

	it('picks up a field that already has focus when the phone layout begins', async () => {
		const { typingOnPhone, watchTypingOnPhone } = await import('./ui');
		field('<textarea></textarea>').focus();

		const stop = watchTypingOnPhone(document, true);
		expect(get(typingOnPhone)).toBe(true);
		stop();
		expect(get(typingOnPhone)).toBe(false);
	});

	it('never hides the bars on the desktop layout', async () => {
		const { typingOnPhone, watchTypingOnPhone } = await import('./ui');
		const stop = watchTypingOnPhone(document, false);

		field('<textarea></textarea>').focus();
		expect(get(typingOnPhone)).toBe(false);
		stop();
	});
});
