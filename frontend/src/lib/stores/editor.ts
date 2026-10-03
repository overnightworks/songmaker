import { writable, derived, get, type Readable } from 'svelte/store';
import {
	fetchVersions,
	updateSong,
	deleteVersion as apiDeleteVersion,
	fetchSong
} from '$lib/api/client';
import { replaceSongInList } from '$lib/stores/libraryData';
import { selectedSongId } from '$lib/stores/player';
import type {
	GenerationItem,
	SongItem,
	VersionGenerationParams,
	VersionItem
} from '$lib/api/types';

interface SongData {
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
	/** The version number an older version was loaded from into the draft, until it is saved. */
	loadedFrom: number | null;
}

const editorState = writable<EditorState>({
	saved: { ...EMPTY_SONG_DATA },
	draft: { ...EMPTY_SONG_DATA },
	loadedFrom: null
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

function songDataEqual(a: SongData, b: SongData): boolean {
	return (
		a.lyrics === b.lyrics &&
		a.prompt === b.prompt &&
		a.bpm === b.bpm &&
		a.audio_duration === b.audio_duration &&
		a.key_scale === b.key_scale &&
		genParamsEqual(a.genParams, b.genParams)
	);
}

function draftIsSaved(s: EditorState): boolean {
	return songDataEqual(s.draft, s.saved);
}

/**
 * Whether the draft still awaits a save: it differs from the latest version,
 * or it came from an older version, which a save or Generate makes the next
 * version even when its text matches the latest (#1245 rules 3 and 6). The one
 * rule for the `· draft` chip and the "Loaded from vN" hint together.
 */
function draftAwaitsSave(s: EditorState): boolean {
	return s.loadedFrom !== null || !draftIsSaved(s);
}

export const isDirty = derived(editorState, draftAwaitsSave);

export const savedSongData = derived(editorState, (s) => s.saved);

/** Which older version the draft came from, until it is saved; see {@link draftAwaitsSave}. */
export const draftLoadedFrom = derived(editorState, (s) => s.loadedFrom);

/** A draft loaded from an older version is saved as the next version, never over the latest. */
export const draftSavesAsNewVersion = derived(draftLoadedFrom, (from) => from !== null);

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

/**
 * Whether the draft holds work none of `held` has, so replacing it would lose
 * something. A draft loaded from an older version and left untouched is still
 * a draft of the latest (`isDirty`), yet replacing it loses nothing.
 */
function holdsUnversionedChanges(s: EditorState, held: VersionItem[]): boolean {
	if (draftIsSaved(s)) return false;
	return !held.some((version) => songDataEqual(s.draft, songDataFromVersion(version)));
}

export const draftHasUnversionedChanges = derived([editorState, versions], ([s, all]) =>
	holdsUnversionedChanges(s, all)
);

/** A version to load into a song's draft once that song's page shows it (Open vN in Now Playing). */
interface PendingVersionLoad {
	songId: string;
	versionId: string;
}

export const pendingVersionLoad = writable<PendingVersionLoad | null>(null);

/** What a version delete takes from the editor besides the version and its takes. */
export type VersionDeleteEditorLoss =
	| { kind: 'unsaved-draft'; emptiesEditor: boolean }
	| { kind: 'current-lyrics'; replacedBy: number }
	| { kind: 'all-lyrics' };

/** A version the Versions list asks to delete, with what goes with it. */
interface VersionDeleteRequest {
	songId: string;
	version: VersionItem;
	takeCount: number;
	holdsPick: boolean;
	editorLoss: VersionDeleteEditorLoss | null;
}

// The song page confirms it: a dialog inside the editor would sit in its size
// container and inherit the Lyrics label's type.
export const versionDeleteRequest = writable<VersionDeleteRequest | null>(null);

// --- Pinned seed (forwarded to the next generation request) ---
export const pinnedSeed = writable<number | null>(null);

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
	editorState.set({ saved: data, draft: { ...data }, loadedFrom: null });
	loadVersions(s.id);
}

/** Resets the draft back to the last-saved values, discarding unsaved edits. */
export function discardDraft(): void {
	editorState.update((s) => ({ ...s, draft: { ...s.saved }, loadedFrom: null }));
}

async function loadVersions(songId: string): Promise<void> {
	versions.set(await fetchVersions(songId));
	currentVersionIndex.set(0);
}

function resetToVersion(v: VersionItem): void {
	const data = songDataFromVersion(v);
	editorState.set({ saved: data, draft: { ...data }, loadedFrom: null });
}

/**
 * The way back from a version load, whether it still holds, and the end of
 * its offer once the toast that raised it times out.
 */
interface VersionLoadUndo {
	undo: () => void;
	holds: Readable<boolean>;
	expire: () => void;
}

/**
 * The one version load whose undo is still offered, and whether the opened
 * Versions list has only set it aside; null once the next action has retired it.
 */
interface OfferedVersionLoad {
	load: symbol;
	setAside: boolean;
	undo: VersionLoadUndo;
	/** Whether the editor still shows exactly what the load left: same song, saved version and draft. */
	stands: () => boolean;
}

const offeredVersionLoad = writable<OfferedVersionLoad | null>(null);

/**
 * Loads a version into the draft only: the latest version stays saved, so a
 * save or Generate makes the next version and the loaded one is never
 * touched. Loading the latest version itself is the way back to the saved
 * state. Nothing reaches the server. Answers the undo, which puts back the
 * draft this load replaced, only until the next action: typing in the draft,
 * another load, a save, a move to another song, or anything that calls
 * `retireVersionLoadUndo()` ends it, so an Undo never restores over work done
 * after the load, and so does `expire()` once its toast times out. A load
 * that would change nothing the musician sees, neither the draft nor its
 * "Loaded from" hint, is no action: it answers null, or, when the opened
 * Versions list set the last load's undo aside, that same undo offered again.
 */
export function loadVersionAsDraft(version: VersionItem): VersionLoadUndo | null {
	const songId = get(selectedSongId);
	const { saved, draft: replaced, loadedFrom: replacedLoadedFrom } = get(editorState);
	const isLatest = version.id === get(versions)[0]?.id;
	const draft = isLatest ? { ...saved } : songDataFromVersion(version);
	const loadedFrom = isLatest ? null : version.version_number;
	if (songDataEqual(draft, replaced) && loadedFrom === replacedLoadedFrom) {
		return offerSetAsideLoadAgain();
	}
	const thisLoad = Symbol('version load');
	editorState.update((s) => ({ ...s, draft, loadedFrom }));
	const standsIn = (currentSongId: string | null, s: EditorState) =>
		currentSongId === songId && s.saved === saved && s.draft === draft;
	const holds = derived(
		[offeredVersionLoad, selectedSongId, editorState],
		([$offered, $selectedSongId, $editorState]) =>
			$offered?.load === thisLoad && !$offered.setAside && standsIn($selectedSongId, $editorState)
	);
	const undo: VersionLoadUndo = {
		holds,
		undo: () => {
			if (!get(holds)) return;
			offeredVersionLoad.set(null);
			editorState.update((s) => ({ ...s, draft: replaced, loadedFrom: replacedLoadedFrom }));
		},
		expire: () =>
			offeredVersionLoad.update((offered) => (offered?.load === thisLoad ? null : offered))
	};
	offeredVersionLoad.set({
		load: thisLoad,
		setAside: false,
		undo,
		stands: () => standsIn(get(selectedSongId), get(editorState))
	});
	return undo;
}

function offerSetAsideLoadAgain(): VersionLoadUndo | null {
	const offered = get(offeredVersionLoad);
	if (!offered?.setAside || !offered.stands()) return null;
	offeredVersionLoad.set({ ...offered, setAside: false });
	return offered.undo;
}

/**
 * Takes the offered version-load undo off screen while the Versions list is
 * open; a load from the list that changes nothing offers it again.
 */
export function setAsideVersionLoadUndo(): void {
	offeredVersionLoad.update((offered) => offered && { ...offered, setAside: true });
}

/** The Versions list closed: an undo it set aside and did not offer again is retired. */
export function retireSetAsideVersionLoadUndo(): void {
	offeredVersionLoad.update((offered) => (offered?.setAside ? null : offered));
}

/** Ends the offered version-load undo: the musician has moved on to the next action. */
export function retireVersionLoadUndo(): void {
	offeredVersionLoad.set(null);
}

/**
 * Predicts the version number a save will produce, mirroring the backend's
 * `update_song()`: the highest existing version is overwritten in place
 * (its own number, no increment) when it has no takes yet and the save does
 * not ask for a new version; otherwise a save creates `version_number + 1`. `versions` must be newest-first, matching
 * `fetchVersions()`. Never derive this from `song.version_count` — that is a
 * *count* of surviving versions, not the highest version number, and the two
 * diverge as soon as any version has been deleted.
 */
export function computeDraftVersionNumber(
	versions: VersionItem[],
	generations: GenerationItem[],
	savesAsNewVersion: boolean
): number {
	const latest = versions[0];
	if (!latest) return 1;
	const latestHasTakes = generations.some((g) => g.version_number === latest.version_number);
	return latestHasTakes || savesAsNewVersion ? latest.version_number + 1 : latest.version_number;
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
		generation_params: draft.genParams,
		new_version: get(draftSavesAsNewVersion)
	});
	editorState.update((s) => ({ ...s, saved: { ...s.draft }, loadedFrom: null }));
	replaceSongInList(updated);
	await loadVersions(songId);
	return updated;
}

/**
 * What deleting `version` takes from the editor, which {@link handleDeleteVersion}
 * resets to the latest version left, or empties when none is left: a draft no
 * surviving version holds, or, under a draft of the latest itself, the latest's
 * lyrics when it is the one deleted.
 */
export function versionDeleteEditorLoss(version: VersionItem): VersionDeleteEditorLoss | null {
	const state = get(editorState);
	const all = get(versions);
	const survivors = all.filter((candidate) => candidate.id !== version.id);
	if (holdsUnversionedChanges(state, survivors)) {
		return { kind: 'unsaved-draft', emptiesEditor: survivors.length === 0 };
	}
	if (!draftIsSaved(state) || version.id !== all[0]?.id) return null;
	const nextLatest = survivors[0];
	return nextLatest
		? { kind: 'current-lyrics', replacedBy: nextLatest.version_number }
		: { kind: 'all-lyrics' };
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
	const latest = get(versions)[0];
	if (latest) resetToVersion(latest);
	else loadSongData(updated);
}
