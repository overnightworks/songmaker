import type { ComponentProps } from 'svelte';
import type ShareButton from '$lib/components/ShareButton.svelte';
import type SongMenu from '$lib/components/editor/SongMenu.svelte';
import { readonly, writable } from 'svelte/store';
import { isEditableElement } from '$lib/utils/escape-level-up';

interface PhoneAppBarSongState {
	kind: 'song';
	title: string;
	onrename: (title: string) => Promise<void>;
	share: ComponentProps<typeof ShareButton>;
	menu: Omit<ComponentProps<typeof SongMenu>, 'title' | 'onrename'>;
}

interface PhoneAppBarScreenState {
	kind: 'screen';
	title: string;
	onback: () => void;
}

type PhoneAppBarState = PhoneAppBarSongState | PhoneAppBarScreenState;

export const phoneAppBar = writable<PhoneAppBarState | null>(null);

export const sidebarOpen = writable(false);

export function toggleSidebar(): void {
	sidebarOpen.update((v) => !v);
}

export function closeSidebar(): void {
	sidebarOpen.set(false);
}

const KEYBOARD_INPUT_TYPES: ReadonlySet<string> = new Set([
	'text',
	'search',
	'email',
	'url',
	'tel',
	'password',
	'number'
]);

// A checkbox, slider or date picker is editable but takes no typing, so it
// must not send the bars away; every other editable element does.
export function isTextEntryField(target: EventTarget | null): boolean {
	if (!isEditableElement(target)) return false;
	return !(target instanceof HTMLInputElement) || KEYBOARD_INPUT_TYPES.has(target.type);
}

const typingOnPhoneState = writable(false);

// While a text field has focus on the phone layout the keyboard owns the
// bottom of the screen (#999): the mini-player and any action bar step aside.
// It follows the layout, not the keyboard kind, so a Bluetooth keyboard hides
// the bars too. The app shell is the only writer; pages only read it.
export const typingOnPhone = readonly(typingOnPhoneState);

export function watchTypingOnPhone(root: Document, compact: boolean): () => void {
	typingOnPhoneState.set(compact && isTextEntryField(root.activeElement));
	if (!compact) return () => {};
	// During `focusout` the next focus target is only known as
	// `relatedTarget`; reading it there keeps a move from one field to the
	// next from flashing the bars back in between.
	const onFocusIn = (event: FocusEvent) => typingOnPhoneState.set(isTextEntryField(event.target));
	const onFocusOut = (event: FocusEvent) =>
		typingOnPhoneState.set(isTextEntryField(event.relatedTarget));
	root.addEventListener('focusin', onFocusIn);
	root.addEventListener('focusout', onFocusOut);
	return () => {
		root.removeEventListener('focusin', onFocusIn);
		root.removeEventListener('focusout', onFocusOut);
		typingOnPhoneState.set(false);
	};
}

type Theme = 'dark' | 'light';

const STORAGE_KEY = 'theme';
const RAIL_COLLAPSED_STORAGE_KEY = 'songmaker.rail-collapsed';
const RAIL_WIDTH_STORAGE_KEY = 'songmaker.rail-width';
const LIBRARY_CONTINUE_COLLAPSED_STORAGE_KEY = 'songmaker.library-continue-collapsed';
export const RAIL_MIN_WIDTH_PX = 220;
export const RAIL_MAX_WIDTH_PX = 360;
export const RAIL_WIDTH_STEP_PX = 8;
const DEFAULT_RAIL_WIDTH_PX = 264;

const VALID_THEMES: ReadonlySet<string> = new Set<Theme>(['dark', 'light']);

function getInitialTheme(): Theme {
	if (typeof window === 'undefined') return 'dark';
	const stored = localStorage.getItem(STORAGE_KEY);
	return stored && VALID_THEMES.has(stored) ? (stored as Theme) : 'dark';
}

export const theme = writable<Theme>(getInitialTheme());

function getInitialRailCollapsed(): boolean {
	if (typeof window === 'undefined') return false;
	return localStorage.getItem(RAIL_COLLAPSED_STORAGE_KEY) === 'true';
}

export const railCollapsed = writable(getInitialRailCollapsed());

function getInitialLibraryContinueCollapsed(): boolean {
	if (typeof window === 'undefined') return false;
	return localStorage.getItem(LIBRARY_CONTINUE_COLLAPSED_STORAGE_KEY) === 'true';
}

export const libraryContinueCollapsed = writable(getInitialLibraryContinueCollapsed());

export function toggleLibraryContinueCollapsed(): void {
	libraryContinueCollapsed.update((collapsed) => {
		const next = !collapsed;
		localStorage.setItem(LIBRARY_CONTINUE_COLLAPSED_STORAGE_KEY, String(next));
		return next;
	});
}

export function initLibraryContinueCollapsed(): void {
	libraryContinueCollapsed.set(getInitialLibraryContinueCollapsed());
}

function clampRailWidth(width: number): number {
	return Math.min(RAIL_MAX_WIDTH_PX, Math.max(RAIL_MIN_WIDTH_PX, Math.round(width)));
}

function getInitialRailWidth(): number {
	if (typeof window === 'undefined') return DEFAULT_RAIL_WIDTH_PX;
	const storedValue = localStorage.getItem(RAIL_WIDTH_STORAGE_KEY);
	if (storedValue === null) return DEFAULT_RAIL_WIDTH_PX;
	const stored = Number(storedValue);
	return Number.isFinite(stored) ? clampRailWidth(stored) : DEFAULT_RAIL_WIDTH_PX;
}

export const railWidth = writable(getInitialRailWidth());

export function setRailWidth(width: number): void {
	const next = clampRailWidth(width);
	railWidth.set(next);
	localStorage.setItem(RAIL_WIDTH_STORAGE_KEY, String(next));
}

export function adjustRailWidth(delta: number): void {
	railWidth.update((current) => {
		const next = clampRailWidth(current + delta);
		localStorage.setItem(RAIL_WIDTH_STORAGE_KEY, String(next));
		return next;
	});
}

export function initRailWidth(): void {
	railWidth.set(getInitialRailWidth());
}

export function toggleRailCollapsed(): void {
	railCollapsed.update((collapsed) => {
		const next = !collapsed;
		localStorage.setItem(RAIL_COLLAPSED_STORAGE_KEY, String(next));
		return next;
	});
}

export function initRailCollapsed(): void {
	railCollapsed.set(getInitialRailCollapsed());
}

export function toggleTheme(): void {
	theme.update((t) => {
		const next: Theme = t === 'dark' ? 'light' : 'dark';
		localStorage.setItem(STORAGE_KEY, next);
		document.documentElement.dataset.theme = next;
		return next;
	});
}

export function initTheme(): void {
	const t = getInitialTheme();
	document.documentElement.dataset.theme = t;
	theme.set(t);
}
