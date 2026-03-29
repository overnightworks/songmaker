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

const VALID_THEMES: ReadonlySet<string> = new Set<Theme>(['dark', 'light']);

function getInitialTheme(): Theme {
	if (typeof window === 'undefined') return 'dark';
	const stored = localStorage.getItem(STORAGE_KEY);
	return stored && VALID_THEMES.has(stored) ? (stored as Theme) : 'dark';
}

export const theme = writable<Theme>(getInitialTheme());

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
