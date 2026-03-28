import { get, writable, derived } from 'svelte/store';
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
export const chatOpen = writable(false);

let suppressPush = false;

interface NavState {
	songId: string | null;
	genId: string | null;
	tab: DetailTab;
	chat: boolean;
}

function stateToUrl(state: NavState): string {
	const params = new URLSearchParams();
	if (state.songId) params.set('song', state.songId);
	if (state.genId) params.set('gen', state.genId);
	if (state.songId && !state.genId && state.tab === 'edit') params.set('tab', 'edit');
	if (state.chat) params.set('chat', '1');
	const qs = params.toString();
	return qs ? `/?${qs}` : '/';
}

function pushNav(state: NavState): void {
	if (suppressPush) return;
	history.pushState(state, '', stateToUrl(state));
}

function currentChat(): boolean {
	return get(chatOpen);
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
	chatOpen.set(state.chat);
}

export function selectSong(songId: string): void {
	playerSelectSong(songId);
	const expanded = get(expandedSongIds);
	if (!expanded.has(songId)) toggleSongExpanded(songId);
	ensureGenerationsLoaded(songId);
	detailTab.set('generations');
	chatOpen.set(false);
	closeSidebar();
	pushNav({ songId, genId: null, tab: 'generations', chat: false });
}

export function deselectSong(): void {
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	detailTab.set('generations');
	chatOpen.set(false);
	pushNav({ songId: null, genId: null, tab: 'generations', chat: false });
}

export function selectGeneration(gen: GenerationItem, song: SongItem): void {
	playerSelectGeneration(gen, song);
	chatOpen.set(false);
	pushNav({ songId: song.id, genId: gen.id, tab: get(detailTab), chat: false });
}

export function clearGenerationSelection(): void {
	playerClearGeneration();
	pushNav({ songId: get(selectedSongId), genId: null, tab: get(detailTab), chat: currentChat() });
}

export function navigateToSongTab(tab: DetailTab): void {
	playerClearGeneration();
	detailTab.set(tab);
	pushNav({ songId: get(selectedSongId), genId: null, tab, chat: currentChat() });
}

export function switchTab(tab: DetailTab): void {
	detailTab.set(tab);
	chatOpen.set(false);
	pushNav({ songId: get(selectedSongId), genId: null, tab, chat: false });
}

export function toggleChat(): void {
	const next = !get(chatOpen);
	chatOpen.set(next);
	pushNav({ songId: get(selectedSongId), genId: null, tab: get(detailTab), chat: next });
}

export function initNavigation(): () => void {
	const params = new URLSearchParams(window.location.search);
	const songId = params.get('song');
	const genId = params.get('gen');
	const tab: DetailTab = params.get('tab') === 'edit' ? 'edit' : 'generations';
	const chat = params.get('chat') === '1';

	const initialState: NavState = { songId: songId ?? null, genId: genId ?? null, tab, chat };
	history.replaceState(initialState, '', window.location.href);

	if (songId) {
		suppressPush = true;
		applyState(initialState);
		suppressPush = false;
	}

	function onPopstate(e: PopStateEvent): void {
		suppressPush = true;
		const state = (e.state as NavState) ?? {
			songId: null,
			genId: null,
			tab: 'generations' as DetailTab,
			chat: false
		};
		applyState(state);
		suppressPush = false;
	}

	window.addEventListener('popstate', onPopstate);
	return () => window.removeEventListener('popstate', onPopstate);
}

export const canGoBack = derived(
	[selectedSongId, chatOpen],
	([$songId, $chat]) => $songId !== null || $chat
);
