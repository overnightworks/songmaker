import { writable, derived, get } from 'svelte/store';
import {
	fetchVersions,
	updateSong,
	deleteVersion as apiDeleteVersion,
	fetchSong
} from '$lib/api/client';
import { replaceSongInList, selectedSongId } from '$lib/stores/player';
import type {
	GenerationItem,
	SongItem,
	VersionGenerationParams,
	VersionItem
} from '$lib/api/types';

export interface SongData {
	lyrics: string;
	prompt: string;
	bpm: number;
	audio_duration: number;
	key_scale: string;
	genParams: VersionGenerationParams | null;
}

const EMPTY_SONG_DATA: SongData = {
	lyrics: '',
	prompt: '',
	bpm: 0,
	audio_duration: 180,
	key_scale: '',
	genParams: null
};

interface EditorState {
	saved: SongData;
	draft: SongData;
}

export const editorState = writable<EditorState>({
	saved: { ...EMPTY_SONG_DATA },
	draft: { ...EMPTY_SONG_DATA }
});

function genParamsEqual(
	a: VersionGenerationParams | null,
	b: VersionGenerationParams | null
): boolean {
	const objA = a ?? {};
	const objB = b ?? {};
	const keys = new Set([...Object.keys(objA), ...Object.keys(objB)]);
	for (const k of keys) {
		if ((objA as Record<string, unknown>)[k] !== (objB as Record<string, unknown>)[k]) {
			return false;
		}
	}
	return true;
}

export const isDirty = derived(editorState, (s) => {
	const { saved, draft } = s;
	return (
		draft.lyrics !== saved.lyrics ||
		draft.prompt !== saved.prompt ||
		draft.bpm !== saved.bpm ||
		draft.audio_duration !== saved.audio_duration ||
		draft.key_scale !== saved.key_scale ||
		!genParamsEqual(draft.genParams, saved.genParams)
	);
});

export const savedSongData = derived(editorState, (s) => s.saved);

export const editLyrics = derived(editorState, (s) => s.draft.lyrics);
export const editPrompt = derived(editorState, (s) => s.draft.prompt);
export const editBpm = derived(editorState, (s) => s.draft.bpm);
export const editAudioDuration = derived(editorState, (s) => s.draft.audio_duration);
export const editKeyScale = derived(editorState, (s) => s.draft.key_scale);
export const editGenParams = derived(editorState, (s) => s.draft.genParams);

export function setDraftLyrics(lyrics: string): void {
	editorState.update((s) => ({ ...s, draft: { ...s.draft, lyrics } }));
}

export function setDraftPrompt(prompt: string): void {
	editorState.update((s) => ({ ...s, draft: { ...s.draft, prompt } }));
}

export function setDraftBpm(bpm: number): void {
	editorState.update((s) => ({ ...s, draft: { ...s.draft, bpm } }));
}

export function setDraftAudioDuration(audio_duration: number): void {
	editorState.update((s) => ({ ...s, draft: { ...s.draft, audio_duration } }));
}

export function setDraftKeyScale(key_scale: string): void {
	editorState.update((s) => ({ ...s, draft: { ...s.draft, key_scale } }));
}

export function setDraftGenParams(genParams: VersionGenerationParams | null): void {
	editorState.update((s) => ({ ...s, draft: { ...s.draft, genParams } }));
}

// --- Versions ---
export const versions = writable<VersionItem[]>([]);
export const currentVersionIndex = writable(0);

// --- Pinned seed (forwarded to the next generation request) ---
export const pinnedSeed = writable<number | null>(null);

// --- Pinned generation settings (loaded via "Use these settings" button) ---
export function applyGenerationSettings(params: VersionGenerationParams): void {
	setDraftGenParams(params);
}

function songDataFromSong(s: SongItem): SongData {
	return {
		lyrics: s.lyrics,
		prompt: s.prompt,
		bpm: s.bpm ?? 0,
		audio_duration: s.audio_duration ?? 180,
		key_scale: s.key_scale ?? '',
		genParams: s.generation_params ?? null
	};
}

function songDataFromVersion(v: VersionItem): SongData {
	return {
		lyrics: v.lyrics,
		prompt: v.prompt,
		bpm: v.bpm,
		audio_duration: v.audio_duration,
		key_scale: v.key_scale,
		genParams: v.generation_params
	};
}

export function loadSongData(s: SongItem): void {
	const data = songDataFromSong(s);
	editorState.set({ saved: data, draft: { ...data } });
	loadVersions(s.id);
}

/** Resets the draft back to the last-saved values, discarding unsaved edits. */
export function discardDraft(): void {
	editorState.update((s) => ({ ...s, draft: { ...s.saved } }));
}

export async function loadVersions(songId: string): Promise<void> {
	versions.set(await fetchVersions(songId));
	currentVersionIndex.set(0);
}

export function loadVersion(index: number): void {
	const vers = get(versions);
	const v = vers[index];
	if (!v) return;
	currentVersionIndex.set(index);
	const data = songDataFromVersion(v);
	editorState.set({ saved: data, draft: { ...data } });
}

/**
 * Predicts the version number a save will produce, mirroring the backend's
 * `update_song()`: the highest existing version is overwritten in place
 * (its own number, no increment) when it has no takes yet; otherwise a save
 * creates `version_number + 1`. `versions` must be newest-first, matching
 * `fetchVersions()`. Never derive this from `song.version_count` — that is a
 * *count* of surviving versions, not the highest version number, and the two
 * diverge as soon as any version has been deleted.
 */
export function computeDraftVersionNumber(
	versions: VersionItem[],
	generations: GenerationItem[]
): number {
	const latest = versions[0];
	if (!latest) return 1;
	const latestHasTakes = generations.some((g) => g.version_number === latest.version_number);
	return latestHasTakes ? latest.version_number + 1 : latest.version_number;
}

/**
 * Persists the draft as a new version. Fails loud: a rejected `updateSong`
 * call propagates to the caller instead of being swallowed, so a caller that
 * depends on the save succeeding (e.g. Generate, which must never run
 * against a stale version) aborts rather than proceeding silently.
 */
export async function handleSave(songId: string): Promise<SongItem> {
	const { draft } = get(editorState);
	const updated = await updateSong(songId, {
		lyrics: draft.lyrics,
		prompt: draft.prompt,
		bpm: draft.bpm,
		audio_duration: draft.audio_duration,
		key_scale: draft.key_scale,
		generation_params: draft.genParams
	});
	editorState.update((s) => ({ ...s, saved: { ...s.draft } }));
	replaceSongInList(updated);
	await loadVersions(songId);
	return updated;
}

/** Deletes a version and its takes. Fails loud — see {@link handleSave}. */
export async function handleDeleteVersion(
	songId: string,
	versionId: string,
	deleteGenerations: boolean
): Promise<void> {
	await apiDeleteVersion(versionId, deleteGenerations);
	const updated = await fetchSong(songId);
	replaceSongInList(updated);
	if (get(selectedSongId) !== songId) return;
	await loadVersions(songId);
	if (get(selectedSongId) !== songId) return;
	if (get(versions)[0]) loadVersion(0);
	else loadSongData(updated);
}
