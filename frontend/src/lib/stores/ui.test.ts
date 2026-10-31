import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import {
	PHONE_VIEWPORT_HEIGHT_PX,
	phoneViewport,
	removePhoneViewport
} from '#lib/test-utils/on-screen-keyboard.ts';

const mockFetchTheme = vi.fn();
const mockUpdateTheme = vi.fn();
vi.mock('#lib/api/settings.ts', () => ({
	fetchTheme: (...args: unknown[]) => mockFetchTheme(...args),
	updateTheme: (...args: unknown[]) => mockUpdateTheme(...args)
}));

beforeEach(() => {
	mockFetchTheme.mockReset();
	mockUpdateTheme.mockReset();
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

describe('libraryWallOrder', () => {
	it('opens in A–Z when this browser has no wall order', async () => {
		const { libraryWallOrder } = await import('./ui');

		expect(get(libraryWallOrder)).toBe('title');
	});

	it('restores and persists the order chosen on this device', async () => {
		localStorage.setItem('songmaker.library-wall-order', 'played');
		const { chooseLibraryWallOrder, initLibraryWallOrder, libraryWallOrder } = await import('./ui');

		expect(get(libraryWallOrder)).toBe('played');
		chooseLibraryWallOrder('title');
		expect(get(libraryWallOrder)).toBe('title');
		expect(localStorage.getItem('songmaker.library-wall-order')).toBe('title');

		libraryWallOrder.set('played');
		initLibraryWallOrder();
		expect(get(libraryWallOrder)).toBe('title');
	});

	// 'recent' and 'added' are the orders this switch offered before Last played.
	it.each(['recent', 'added', 'newest'])(
		'opens in A–Z when the stored order is %s, one it does not know',
		async (stored) => {
			localStorage.setItem('songmaker.library-wall-order', stored);
			const { libraryWallOrder } = await import('./ui');

			expect(get(libraryWallOrder)).toBe('title');
		}
	);
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
		const { watchTypingOnPhone } = await import('./ui');
		const { transportBarHidden } = await import('./transportBar');
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

it('imports with the defaults when browser storage throws', async () => {
	vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
		throw new DOMException('blocked', 'SecurityError');
	});
	const { theme, railCollapsed, railWidth, libraryWallOrder } = await import('./ui');
	vi.restoreAllMocks();

	expect(get(theme)).toBe('light');
	expect(get(railCollapsed)).toBe(false);
	expect(get(railWidth)).toBe(264);
	expect(get(libraryWallOrder)).toBe('title');
});

describe('theme', () => {
	const COPY_KEY = 'songmaker.theme';

	function stubDevice(scheme: 'dark' | 'light' | 'unsupported') {
		if (scheme === 'unsupported') {
			vi.stubGlobal('matchMedia', undefined);
			return;
		}
		vi.stubGlobal(
			'matchMedia',
			vi.fn((query: string) => ({
				matches: query === '(prefers-color-scheme: dark)' && scheme === 'dark'
			}))
		);
	}

	afterEach(() => {
		vi.unstubAllGlobals();
		delete document.documentElement.dataset.theme;
	});

	it.each([
		['follows a dark device when there is no copy', 'dark', null, 'dark'],
		['follows a light device when there is no copy', 'light', null, 'light'],
		['is light when the browser cannot tell the device', 'unsupported', null, 'light'],
		['keeps a light copy on a dark device', 'dark', 'light', 'light'],
		['keeps a dark copy on a light device', 'light', 'dark', 'dark'],
		['follows a dark device under a system copy', 'dark', 'system', 'dark'],
		['follows a light device under a system copy', 'light', 'system', 'light'],
		['ignores the legacy key', 'light', null, 'light']
	] as const)('%s', async (_, device, copy, expected) => {
		stubDevice(device);
		if (copy) localStorage.setItem(COPY_KEY, copy);
		localStorage.setItem('theme', 'dark');
		const { theme } = await import('./ui');

		expect(get(theme)).toBe(expected);
	});

	it('is light without a window', async () => {
		vi.stubGlobal('window', undefined);
		const { theme } = await import('./ui');

		expect(get(theme)).toBe('light');
	});

	it('leaves data-theme unset and removes a stale one when there is no copy', async () => {
		stubDevice('dark');
		const { initTheme } = await import('./ui');
		document.documentElement.dataset.theme = 'light';

		initTheme();

		expect(document.documentElement.dataset.theme).toBeUndefined();
	});

	it.each([
		['light', 'light'],
		['dark', 'dark'],
		['system', undefined]
	] as const)('a %s copy sets data-theme to %s', async (copy, expected) => {
		stubDevice('light');
		localStorage.setItem(COPY_KEY, copy);
		const { initTheme } = await import('./ui');
		document.documentElement.dataset.theme = copy === 'system' ? 'dark' : 'light';

		initTheme();

		expect(document.documentElement.dataset.theme).toBe(expected);
	});

	describe("loading the person's choice", () => {
		it("paints the server's answer, writes the copy and wins over a different copy", async () => {
			stubDevice('light');
			localStorage.setItem(COPY_KEY, 'light');
			mockFetchTheme.mockResolvedValue({ theme: 'dark' });
			const { theme, loadThemeChoice } = await import('./ui');

			await loadThemeChoice();

			expect(get(theme)).toBe('dark');
			expect(document.documentElement.dataset.theme).toBe('dark');
			expect(localStorage.getItem(COPY_KEY)).toBe('dark');
		});

		it('mirrors a system answer as a system copy and follows the device again', async () => {
			stubDevice('light');
			localStorage.setItem(COPY_KEY, 'dark');
			mockFetchTheme.mockResolvedValue({ theme: 'system' });
			const { theme, loadThemeChoice } = await import('./ui');

			await loadThemeChoice();

			expect(get(theme)).toBe('light');
			expect(document.documentElement.dataset.theme).toBeUndefined();
			expect(localStorage.getItem(COPY_KEY)).toBe('system');
		});

		it("does not undo a toggle made while the load is pending when the load's answer arrives", async () => {
			stubDevice('light');
			let answerLoad: (answer: { theme: string }) => void = () => {};
			mockFetchTheme.mockReturnValue(new Promise((resolve) => (answerLoad = resolve)));
			mockUpdateTheme.mockResolvedValue({ theme: 'dark' });
			const { theme, loadThemeChoice, toggleTheme } = await import('./ui');

			const loaded = loadThemeChoice();
			await toggleTheme();
			answerLoad({ theme: 'system' });
			await loaded;

			expect(get(theme)).toBe('dark');
			expect(document.documentElement.dataset.theme).toBe('dark');
			expect(localStorage.getItem(COPY_KEY)).toBe('dark');
		});

		it('keeps the copy when the server cannot be asked', async () => {
			stubDevice('light');
			localStorage.setItem(COPY_KEY, 'dark');
			mockFetchTheme.mockRejectedValue(new Error('offline'));
			const { theme, loadThemeChoice } = await import('./ui');

			await loadThemeChoice();

			expect(get(theme)).toBe('dark');
			expect(localStorage.getItem(COPY_KEY)).toBe('dark');
		});
	});

	describe('toggling', () => {
		it('applies and stores the other way at once, then sends it to the server', async () => {
			stubDevice('light');
			mockUpdateTheme.mockResolvedValue({ theme: 'dark' });
			const { theme, toggleTheme } = await import('./ui');

			const saved = toggleTheme();

			expect(get(theme)).toBe('dark');
			expect(localStorage.getItem(COPY_KEY)).toBe('dark');
			expect(document.documentElement.dataset.theme).toBe('dark');
			await saved;
			expect(mockUpdateTheme).toHaveBeenCalledWith('dark');
		});

		it('sends light when the person follows a dark device', async () => {
			stubDevice('dark');
			localStorage.setItem(COPY_KEY, 'system');
			mockUpdateTheme.mockResolvedValue({ theme: 'light' });
			const { toggleTheme } = await import('./ui');

			await toggleTheme();

			expect(mockUpdateTheme).toHaveBeenCalledWith('light');
		});

		it('reverts the theme and the copy and tells the person when the server refuses', async () => {
			stubDevice('light');
			localStorage.setItem(COPY_KEY, 'light');
			mockUpdateTheme.mockRejectedValue(new Error('refused'));
			const { theme, toggleTheme } = await import('./ui');
			const { toasts } = await import('./toast');

			await toggleTheme();

			expect(get(theme)).toBe('light');
			expect(localStorage.getItem(COPY_KEY)).toBe('light');
			expect(document.documentElement.dataset.theme).toBe('light');
			expect(get(toasts).map((toast) => toast.type)).toEqual(['error']);
		});
	});

	it('forgets the copy', async () => {
		localStorage.setItem(COPY_KEY, 'dark');
		const { forgetThemeChoice } = await import('./ui');

		forgetThemeChoice();

		expect(localStorage.getItem(COPY_KEY)).toBeNull();
	});
});
