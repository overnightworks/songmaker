import { writable } from 'svelte/store';

export const sidebarOpen = writable(false);

export function toggleSidebar(): void {
	sidebarOpen.update((v) => !v);
}

export function closeSidebar(): void {
	sidebarOpen.set(false);
}

export type Theme = 'dark' | 'light';

const STORAGE_KEY = 'theme';
export const RAIL_COLLAPSED_STORAGE_KEY = 'songmaker.rail-collapsed';
export const RAIL_WIDTH_STORAGE_KEY = 'songmaker.rail-width';
export const LIBRARY_CONTINUE_COLLAPSED_STORAGE_KEY = 'songmaker.library-continue-collapsed';
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

export function clampRailWidth(width: number): number {
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
