import { writable } from 'svelte/store';

export type SortMode = 'vocal' | 'latest' | 'dynamics' | 'name';

export const scoreFilter = writable(0);
export const sortMode = writable<SortMode>('vocal');
