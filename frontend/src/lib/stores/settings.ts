import { writable, get } from 'svelte/store';

const STORAGE_KEY = 'songmaker:claude-key';

function loadKey(): string {
	if (typeof window === 'undefined') return '';
	return localStorage.getItem(STORAGE_KEY) ?? '';
}

export const claudeApiKey = writable(loadKey());

claudeApiKey.subscribe((key) => {
	if (typeof window === 'undefined') return;
	if (key) {
		localStorage.setItem(STORAGE_KEY, key);
	} else {
		localStorage.removeItem(STORAGE_KEY);
	}
});

export function getClaudeKey(): string {
	return get(claudeApiKey);
}
