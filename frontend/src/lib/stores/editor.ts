import { writable, derived, get } from 'svelte/store';
import {
	fetchVersions,
	updateSong,
	deleteVersion as apiDeleteVersion,
	fetchSong
} from '$lib/api/client';
import { songList } from '$lib/stores/player';
import type { SongItem, VersionGenerationParams, VersionItem } from '$lib/api/types';
import type { ApplyData } from '$lib/components/ClaudeChat.svelte';

// --- Editable fields ---
export const editLyrics = writable('');
export const editPrompt = writable('');
export const editBpm = writable(0);
export const editDuration = writable(180);
export const editKey = writable('');
export const editGenParams = writable<VersionGenerationParams | null>(null);

// --- Saved state (for dirty tracking) ---
const savedLyrics = writable('');
const savedPrompt = writable('');
const savedBpm = writable(0);
const savedDuration = writable(180);
const savedKey = writable('');
const savedGenParams = writable<VersionGenerationParams | null>(null);

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

export const isDirty = derived(
	[
		editLyrics,
		editPrompt,
		editBpm,
		editDuration,
		editKey,
		editGenParams,
		savedLyrics,
		savedPrompt,
		savedBpm,
		savedDuration,
		savedKey,
		savedGenParams
	],
	([$el, $ep, $eb, $ed, $ek, $egp, $sl, $sp, $sb, $sd, $sk, $sgp]) =>
		$el !== $sl ||
		$ep !== $sp ||
		$eb !== $sb ||
		$ed !== $sd ||
		$ek !== $sk ||
		!genParamsEqual($egp, $sgp)
);

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

function setSavedState(
	lyrics: string,
	prompt: string,
	bpm: number,
	dur: number,
	key: string,
	genParams: VersionGenerationParams | null
): void {
	savedLyrics.set(lyrics);
	savedPrompt.set(prompt);
	savedBpm.set(bpm);
	savedDuration.set(dur);
	savedKey.set(key);
	savedGenParams.set(genParams);
}

export function loadSongData(s: SongItem): void {
	editLyrics.set(s.lyrics);
	editPrompt.set(s.prompt);
	editBpm.set(s.bpm);
	editDuration.set(s.duration);
	editKey.set(s.key);
	editGenParams.set(s.generation_params);
	setSavedState(s.lyrics, s.prompt, s.bpm, s.duration, s.key, s.generation_params);
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
	editLyrics.set(v.lyrics);
	editPrompt.set(v.prompt);
	editBpm.set(v.bpm);
	editDuration.set(v.duration);
	editKey.set(v.key);
	editGenParams.set(v.generation_params);
	setSavedState(v.lyrics, v.prompt, v.bpm, v.duration, v.key, v.generation_params);
}

export async function handleSave(songId: string): Promise<void> {
	saving.set(true);
	try {
		const updated = await updateSong(songId, {
			lyrics: get(editLyrics),
			prompt: get(editPrompt),
			bpm: get(editBpm),
			duration: get(editDuration),
			key: get(editKey),
			generation_params: get(editGenParams)
		});
		setSavedState(
			get(editLyrics),
			get(editPrompt),
			get(editBpm),
			get(editDuration),
			get(editKey),
			get(editGenParams)
		);
		songList.update((songs) => songs.map((s) => (s.id === updated.id ? updated : s)));
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
		songList.update((songs) => songs.map((s) => (s.id === updated.id ? updated : s)));
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
	const before: VersionItem = {
		id: 'before',
		version_number: 0,
		lyrics: get(editLyrics),
		prompt: get(editPrompt),
		bpm: get(editBpm),
		duration: get(editDuration),
		key: get(editKey),
		generation_params: get(editGenParams),
		created_at: null
	};
	if (data.lyrics !== undefined) editLyrics.set(data.lyrics);
	if (data.prompt !== undefined) editPrompt.set(data.prompt);
	if (data.bpm !== undefined) editBpm.set(data.bpm);
	if (data.duration !== undefined) editDuration.set(data.duration);
	if (data.key !== undefined) editKey.set(data.key);
	const after: VersionItem = {
		id: 'after',
		version_number: 0,
		lyrics: get(editLyrics),
		prompt: get(editPrompt),
		bpm: get(editBpm),
		duration: get(editDuration),
		key: get(editKey),
		generation_params: get(editGenParams),
		created_at: null
	};
	appliedDiffBase.set(before);
	appliedDiffTarget.set(after);
}

export function dismissAppliedDiff(): void {
	appliedDiffBase.set(null);
	appliedDiffTarget.set(null);
}
