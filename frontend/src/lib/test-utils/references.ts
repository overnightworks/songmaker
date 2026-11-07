import { mount, tick, unmount } from 'svelte';
import type {
	ReferenceRecordingResponse,
	ReferenceTakeUseResponse,
	ReferenceUsageResponse,
	ReferenceVersionUseResponse
} from '#lib/api/types.ts';
import ReferencesPage from '../../routes/settings/references/+page.svelte';

export function referenceRecording(
	overrides: Partial<ReferenceRecordingResponse>
): ReferenceRecordingResponse {
	return {
		id: 'reference-1',
		filename: 'voice-memo.mp3',
		size_bytes: 1000,
		duration_sec: 31.4,
		created_at: '2026-10-27T10:00:00Z',
		in_use: false,
		is_kept: false,
		used_by_versions: 0,
		used_by_takes: 0,
		...overrides
	};
}

export function listAnswer(
	references: ReferenceRecordingResponse[],
	usage: Partial<ReferenceUsageResponse> = {}
) {
	return {
		references,
		usage: { files: references.length, bytes: 0, file_limit: 50, byte_limit: 500_000_000, ...usage }
	};
}

let mountedPage: ReturnType<typeof mount> | undefined;

export async function renderReferencesPage(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mountedPage = mount(ReferencesPage, { target });
	await tick();
	return target;
}

export async function unmountReferencesPage(): Promise<void> {
	if (mountedPage) await unmount(mountedPage);
	mountedPage = undefined;
}

export function listedReferences(target: HTMLElement): { name: string; meta: string }[] {
	return Array.from(target.querySelectorAll('.reference-row')).map((row) => ({
		name: row.querySelector('.reference-name')?.textContent ?? '',
		meta: row.querySelector('.reference-meta')?.textContent ?? ''
	}));
}

export async function chooseFile(target: HTMLElement, file: File): Promise<void> {
	const input = target.querySelector<HTMLInputElement>('input[type="file"]') as HTMLInputElement;
	Object.defineProperty(input, 'files', { value: [file], configurable: true });
	input.dispatchEvent(new Event('change', { bubbles: true }));
	await tick();
}

export function takeUse(
	overrides: Partial<ReferenceTakeUseResponse> = {}
): ReferenceTakeUseResponse {
	return {
		song_id: 'song-1',
		song_title: 'Storytime',
		song_slug: 'storytime',
		album_id: 'album-1',
		generation_number: 11,
		version_number: 6,
		is_archived: false,
		is_trashed: false,
		audio_duration_sec: 193,
		...overrides
	};
}

export function versionUse(
	overrides: Partial<ReferenceVersionUseResponse> = {}
): ReferenceVersionUseResponse {
	return {
		song_id: 'song-1',
		song_title: 'Storytime',
		song_slug: 'storytime',
		album_id: 'album-1',
		version_number: 3,
		is_trashed: false,
		...overrides
	};
}
