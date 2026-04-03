import { writable } from 'svelte/store';
import type { GenerationItem } from '$lib/api/types';

export const pendingSource = writable<GenerationItem | null>(null);
