import { get, writable } from 'svelte/store';
import {
	selectedSongId,
	selectedGenerationId,
	selectSong as playerSelectSong,
	selectGenerationInSidebar as playerSelectGeneration,
	clearGenerationSelection as playerClearGeneration,
	ensureGenerationsLoaded,
	expandedSongIds,
	toggleSongExpanded
} from '$lib/stores/player';
import { closeSidebar } from '$lib/stores/ui';
import type { GenerationItem, SongItem } from '$lib/api/types';

export type DetailTab = 'generations' | 'edit';
export const detailTab = writable<DetailTab>('generations');

let suppressPush = false;

interface NavState {
	songId: string | null;
	genId: string | null;
	tab: DetailTab;
}

function stateToUrl(state: NavState): string {
	const params = new URLSearchParams();
	if (state.songId) params.set('song', state.songId);
	if (state.genId) params.set('gen', state.genId);
	if (state.songId && !state.genId && state.tab === 'edit') params.set('tab', 'edit');
	const qs = params.toString();
	return qs ? `/?${qs}` : '/';
}

function pushNav(state: NavState): void {
	if (suppressPush) return;
	history.pushState(state, '', stateToUrl(state));
}

function applyState(state: NavState): void {
	if (state.songId) {
		playerSelectSong(state.songId);
		const expanded = get(expandedSongIds);
		if (!expanded.has(state.songId)) toggleSongExpanded(state.songId);
		ensureGenerationsLoaded(state.songId);
		if (state.genId) {
			selectedGenerationId.set(state.genId);
		}
	} else {
		selectedSongId.set(null);
		selectedGenerationId.set(null);
	}
	detailTab.set(state.tab);
}

export function selectSong(songId: string): void {
	playerSelectSong(songId);
	const expanded = get(expandedSongIds);
	if (!expanded.has(songId)) toggleSongExpanded(songId);
	ensureGenerationsLoaded(songId);
	detailTab.set('generations');
	closeSidebar();
	pushNav({ songId, genId: null, tab: 'generations' });
}

export function selectGeneration(gen: GenerationItem, song: SongItem): void {
	playerSelectGeneration(gen, song);
	closeSidebar();
	pushNav({ songId: song.id, genId: gen.id, tab: get(detailTab) });
}

export function clearGenerationSelection(): void {
	playerClearGeneration();
	pushNav({ songId: get(selectedSongId), genId: null, tab: get(detailTab) });
}

export function navigateToSongTab(tab: DetailTab): void {
	playerClearGeneration();
	detailTab.set(tab);
	pushNav({ songId: get(selectedSongId), genId: null, tab });
}

export function switchTab(tab: DetailTab): void {
	detailTab.set(tab);
	pushNav({ songId: get(selectedSongId), genId: null, tab });
}

export function initNavigation(): () => void {
	const params = new URLSearchParams(window.location.search);
	const songId = params.get('song');
	const genId = params.get('gen');
	const tab: DetailTab = params.get('tab') === 'edit' ? 'edit' : 'generations';

	const initialState: NavState = { songId: songId ?? null, genId: genId ?? null, tab };
	history.replaceState(initialState, '', window.location.href);

	if (songId) {
		suppressPush = true;
		applyState(initialState);
		suppressPush = false;
	}

	function onPopstate(e: PopStateEvent): void {
		suppressPush = true;
		const state = (e.state as NavState) ?? { songId: null, genId: null, tab: 'generations' };
		applyState(state);
		suppressPush = false;
	}

	window.addEventListener('popstate', onPopstate);
	return () => window.removeEventListener('popstate', onPopstate);
}
