import { writable, derived, get } from 'svelte/store';
import {
	fetchVersions,
	updateSong,
	deleteVersion as apiDeleteVersion,
	fetchSong
} from '$lib/api/client';
import { replaceSongInList } from '$lib/stores/player';
import type { SongItem, VersionGenerationParams, VersionItem } from '$lib/api/types';
import type { ApplyData } from '$lib/utils/chat-context';

export interface SongData {
	lyrics: string;
	prompt: string;
	bpm: number;
	duration: number;
	key: string;
	genParams: VersionGenerationParams | null;
}

const EMPTY_SONG_DATA: SongData = {
	lyrics: '',
	prompt: '',
	bpm: 0,
	duration: 180,
	key: '',
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
		draft.duration !== saved.duration ||
		draft.key !== saved.key ||
		!genParamsEqual(draft.genParams, saved.genParams)
	);
});

export const editLyrics = derived(editorState, (s) => s.draft.lyrics);
export const editPrompt = derived(editorState, (s) => s.draft.prompt);
export const editBpm = derived(editorState, (s) => s.draft.bpm);
export const editDuration = derived(editorState, (s) => s.draft.duration);
export const editKey = derived(editorState, (s) => s.draft.key);
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

export function setDraftDuration(duration: number): void {
	editorState.update((s) => ({ ...s, draft: { ...s.draft, duration } }));
}

export function setDraftKey(key: string): void {
	editorState.update((s) => ({ ...s, draft: { ...s.draft, key } }));
}

export function setDraftGenParams(genParams: VersionGenerationParams | null): void {
	editorState.update((s) => ({ ...s, draft: { ...s.draft, genParams } }));
}

// --- Versions ---
export const versions = writable<VersionItem[]>([]);
export const currentVersionIndex = writable(0);

// --- Status ---
export const saving = writable(false);
export const status = writable('');

let statusTimeout: ReturnType<typeof setTimeout> | null = null;

function showStatus(msg: string): void {
	status.set(msg);
	if (statusTimeout) clearTimeout(statusTimeout);
	statusTimeout = setTimeout(() => status.set(''), 3000);
}

// --- Diff state ---
export const diffBase = writable<VersionItem | null>(null);
export const diffTarget = writable<VersionItem | null>(null);
export const appliedDiffBase = writable<VersionItem | null>(null);
export const appliedDiffTarget = writable<VersionItem | null>(null);

export const diffMode = derived([diffBase, diffTarget], ([$b, $t]) => $b !== null && $t !== null);
export const appliedDiffMode = derived(
	[appliedDiffBase, appliedDiffTarget],
	([$b, $t]) => $b !== null && $t !== null
);

export const activeDiff = derived(
	[diffBase, diffTarget, appliedDiffBase, appliedDiffTarget],
	([$db, $dt, $ab, $at]): { old: VersionItem; new: VersionItem } | null => {
		if ($db && $dt) return { old: $db, new: $dt };
		if ($ab && $at) return { old: $ab, new: $at };
		return null;
	}
);

function songDataFromSong(s: SongItem): SongData {
	return {
		lyrics: s.lyrics,
		prompt: s.prompt,
		bpm: s.bpm ?? 0,
		duration: s.duration ?? 180,
		key: s.key,
		genParams: s.generation_params ?? null
	};
}

function songDataFromVersion(v: VersionItem): SongData {
	return {
		lyrics: v.lyrics,
		prompt: v.prompt,
		bpm: v.bpm,
		duration: v.duration,
		key: v.key,
		genParams: v.generation_params
	};
}

export function loadSongData(s: SongItem): void {
	const data = songDataFromSong(s);
	editorState.set({ saved: data, draft: { ...data } });
	dismissAppliedDiff();
	loadVersions(s.id);
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

export async function handleSave(songId: string): Promise<void> {
	saving.set(true);
	try {
		const { draft } = get(editorState);
		const updated = await updateSong(songId, {
			lyrics: draft.lyrics,
			prompt: draft.prompt,
			bpm: draft.bpm,
			duration: draft.duration,
			key: draft.key,
			generation_params: draft.genParams
		});
		editorState.update((s) => ({ ...s, saved: { ...s.draft } }));
		replaceSongInList(updated);
		await loadVersions(songId);
		dismissAppliedDiff();
		showStatus(`Saved version ${updated.version_count}`);
	} catch (e) {
		showStatus(e instanceof Error ? e.message : 'Save failed');
	} finally {
		saving.set(false);
	}
}

export async function handleDeleteVersion(
	songId: string,
	versionId: string,
	deleteGenerations: boolean
): Promise<void> {
	try {
		await apiDeleteVersion(versionId, deleteGenerations);
		const updated = await fetchSong(songId);
		replaceSongInList(updated);
		await loadVersions(songId);
	} catch {
		showStatus('Delete failed');
	}
}

export function handleDiffChange(pair: [VersionItem, VersionItem] | null): void {
	if (pair) {
		diffBase.set(pair[0]);
		diffTarget.set(pair[1]);
	} else {
		diffBase.set(null);
		diffTarget.set(null);
	}
}

export function handleApply(data: ApplyData): void {
	const { draft } = get(editorState);
	const before: VersionItem = {
		id: 'before',
		version_number: 0,
		lyrics: draft.lyrics,
		prompt: draft.prompt,
		bpm: draft.bpm,
		duration: draft.duration,
		key: draft.key,
		generation_params: draft.genParams,
		created_at: null
	};
	editorState.update((s) => ({
		...s,
		draft: {
			...s.draft,
			...(data.lyrics !== undefined && { lyrics: data.lyrics }),
			...(data.prompt !== undefined && { prompt: data.prompt }),
			...(data.bpm !== undefined && { bpm: data.bpm }),
			...(data.duration !== undefined && { duration: data.duration }),
			...(data.key !== undefined && { key: data.key })
		}
	}));
	const afterDraft = get(editorState).draft;
	const after: VersionItem = {
		id: 'after',
		version_number: 0,
		lyrics: afterDraft.lyrics,
		prompt: afterDraft.prompt,
		bpm: afterDraft.bpm,
		duration: afterDraft.duration,
		key: afterDraft.key,
		generation_params: afterDraft.genParams,
		created_at: null
	};
	appliedDiffBase.set(before);
	appliedDiffTarget.set(after);
}

export function dismissAppliedDiff(): void {
	appliedDiffBase.set(null);
	appliedDiffTarget.set(null);
}
