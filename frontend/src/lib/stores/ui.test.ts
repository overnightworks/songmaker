import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import {
	PHONE_VIEWPORT_HEIGHT_PX,
	phoneViewport,
	removePhoneViewport
} from '$lib/test-utils/on-screen-keyboard';

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

afterEach(removePhoneViewport);

describe('typingOnPhone', () => {
	function field(html: string): HTMLElement {
		const holder = document.createElement('div');
		holder.innerHTML = html;
		document.body.replaceChildren(holder);
		const element = holder.firstElementChild;
		if (!(element instanceof HTMLElement)) throw new Error(`Expected an element from ${html}`);
		return element;
	}

	// The watcher reads focus and the viewport once each event has settled.
	const settled = () => Promise.resolve();

	it.each([
		['the lyrics', '<textarea></textarea>'],
		['a rename field', '<input />'],
		['a search field', '<input type="search" />'],
		['a recipe number', '<input type="number" />']
	])(
		'hides the bars while %s has focus with the keyboard open, and brings them back on leaving it',
		async (_, html) => {
			const viewport = phoneViewport();
			const { typingOnPhone, watchTypingOnPhone } = await import('./ui');
			const stop = watchTypingOnPhone(document, true);
			const input = field(html);

			input.focus();
			viewport.openKeyboard();
			await settled();
			expect(get(typingOnPhone)).toBe(true);
			input.blur();
			viewport.closeKeyboard();
			await settled();
			expect(get(typingOnPhone)).toBe(false);
			stop();
		}
	);

	it.each([
		['a checkbox', '<input type="checkbox" />'],
		['a slider', '<input type="range" />'],
		['a button', '<button type="button">Generate</button>']
	])('keeps the bars while %s has focus, since it takes no typing', async (_, html) => {
		const viewport = phoneViewport();
		const { typingOnPhone, watchTypingOnPhone } = await import('./ui');
		const stop = watchTypingOnPhone(document, true);

		field(html).focus();
		viewport.openKeyboard();
		await settled();
		expect(get(typingOnPhone)).toBe(false);
		stop();
	});

	// #1017: Android's back gesture closes the keyboard and leaves the field
	// focused; with long lyrics there is no outside left to tap.
	it('brings the bars back when the keyboard closes while the field keeps focus, and sends them away when it reopens', async () => {
		const viewport = phoneViewport();
		const { typingOnPhone, watchTypingOnPhone } = await import('./ui');
		const stop = watchTypingOnPhone(document, true);
		const lyrics = field('<textarea></textarea>');
		lyrics.focus();
		viewport.openKeyboard();
		await settled();

		viewport.closeKeyboard();
		await settled();
		expect(document.activeElement).toBe(lyrics);
		expect(get(typingOnPhone)).toBe(false);

		viewport.openKeyboard();
		await settled();
		expect(get(typingOnPhone)).toBe(true);
		stop();
	});

	it.each([
		['a hardware keyboard, which opens none on screen', PHONE_VIEWPORT_HEIGHT_PX, 1],
		['a pinch zoom, which shrinks the view but opens no keyboard', PHONE_VIEWPORT_HEIGHT_PX / 2, 2]
	])('keeps the bars while a field has focus with %s', async (_, height, scale) => {
		const viewport = phoneViewport();
		const { typingOnPhone, watchTypingOnPhone } = await import('./ui');
		const stop = watchTypingOnPhone(document, true);

		field('<textarea></textarea>').focus();
		viewport.show(height, scale);
		await settled();
		expect(get(typingOnPhone)).toBe(false);
		stop();
	});

	it('brings the bars back when the focused field leaves the page without a blur', async () => {
		const viewport = phoneViewport();
		const { typingOnPhone, watchTypingOnPhone } = await import('./ui');
		const stop = watchTypingOnPhone(document, true);
		const lyrics = field('<textarea></textarea>');
		lyrics.focus();
		viewport.openKeyboard();
		await settled();

		lyrics.remove();
		await settled();
		expect(get(typingOnPhone)).toBe(false);
		stop();
	});

	it('keeps the bars away while focus moves from one field to the next', async () => {
		phoneViewport().openKeyboard();
		const { typingOnPhone, watchTypingOnPhone } = await import('./ui');
		const stop = watchTypingOnPhone(document, true);
		const [style, lyrics] = Array.from(
			field('<div><textarea></textarea><textarea></textarea></div>').children
		) as HTMLTextAreaElement[];
		style.focus();
		await settled();
		const seen: boolean[] = [];
		const unsubscribe = typingOnPhone.subscribe((typing) => seen.push(typing));

		lyrics.focus();
		await settled();
		expect(seen).toEqual([true]);
		unsubscribe();
		stop();
	});

	it('picks up a field that already has focus when the phone layout begins', async () => {
		phoneViewport().openKeyboard();
		const { typingOnPhone, watchTypingOnPhone } = await import('./ui');
		field('<textarea></textarea>').focus();

		const stop = watchTypingOnPhone(document, true);
		expect(get(typingOnPhone)).toBe(true);
		stop();
		expect(get(typingOnPhone)).toBe(false);
	});

	it('never hides the bars on the desktop layout', async () => {
		phoneViewport().openKeyboard();
		const { typingOnPhone, watchTypingOnPhone } = await import('./ui');
		const stop = watchTypingOnPhone(document, false);

		field('<textarea></textarea>').focus();
		await settled();
		expect(get(typingOnPhone)).toBe(false);
		stop();
	});
});

describe('transportBarHidden', () => {
	it.each([
		['hides the bar while the full Now Playing surface is open', 'full', true, true],
		['hides the bar while the keyboard owns the bottom of the phone', 'closed', false, true],
		['keeps the bar while Now Playing is docked beside it', 'docked', true, false],
		['keeps the bar while nothing covers it', 'closed', true, false]
	] as const)('%s', async (_, surface, keyboardClosed, hidden) => {
		const viewport = phoneViewport();
		if (!keyboardClosed) viewport.openKeyboard();
		const { transportBarHidden, watchTypingOnPhone } = await import('./ui');
		const { nowPlayingSurface } = await import('./player');
		const lyrics = document.createElement('textarea');
		document.body.replaceChildren(lyrics);
		lyrics.focus();
		const stop = watchTypingOnPhone(document, true);
		nowPlayingSurface.set(surface);

		expect(get(transportBarHidden)).toBe(hidden);
		stop();
	});
});
