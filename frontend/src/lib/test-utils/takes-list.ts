import { mount, tick } from 'svelte';
import { vi } from 'vitest';
import { makeGeneration as generation, makeSong as song } from '#lib/test-utils/factories.ts';
import type { GenerationItem, SongItem } from '#lib/api/types.ts';
import type { GenerationActions } from '#lib/contexts/generation-actions.ts';
import type { GenerateState } from '#lib/stores/generateAction.ts';
import { menuRow } from '#lib/test-utils/collection-menu.ts';
import TakesListHarness from '#lib/components/editor/tests/TakesListHarness.svelte';

export function measuredTakeDefaults(): Partial<GenerationItem> {
	return { generation_params: { audio_duration: 195 }, audio_duration_sec: 195 };
}

export function versionedSongDefaults(): Partial<SongItem> {
	return {
		album_id: 'a-local',
		album_title: 'Local Album',
		version_count: 3,
		generation_count: 5,
		generations: [
			generation({
				...measuredTakeDefaults(),
				version_number: 3,
				generation_number: 3,
				is_picked: true
			}),
			generation({
				...measuredTakeDefaults(),
				id: 'g2',
				version_number: 3,
				generation_number: 2
			}),
			generation({ ...measuredTakeDefaults(), id: 'g3', version_number: 2 })
		]
	};
}

export const IDLE: GenerateState = { kind: 'idle' };

export const playlist = {
	id: 'p1',
	title: 'Night Drive',
	slug: 'night-drive',
	entry_count: 0,
	is_shared: false,
	share_slug: null,
	album_covers: [],
	created_at: '2026-01-01T00:00:00+00:00'
};

export function openTakeMenu(row: HTMLElement): void {
	row.querySelector<HTMLButtonElement>('.menu-trigger')?.click();
}

export function clickMenuItem(root: ParentNode, label: string): void {
	menuRow(root, label).click();
}

export const mounted: Array<ReturnType<typeof mount>> = [];

export const pick = vi.fn();

export const keep = vi.fn();

export const useSeed = vi.fn();

export const clickVersion = vi.fn(() => Promise.resolve(true));

export const addToPlaylist = vi.fn(() => Promise.resolve());

export function mockActions(): GenerationActions {
	return {
		pick,
		keep,
		del: vi.fn(),
		rate: vi.fn(() => Promise.resolve()),
		share: vi.fn(() =>
			Promise.resolve({
				status: 'ok',
				share_url: '',
				share_slug: '',
				songs_without_playable_take: []
			})
		),
		unshare: vi.fn(() => Promise.resolve()),
		addToPlaylist,
		useSeed,
		clickVersion
	};
}

export async function render(overrides: Partial<Record<string, unknown>> = {}) {
	const target = document.createElement('div');
	document.body.append(target);
	const takeSong = (overrides.song as SongItem | undefined) ?? song(versionedSongDefaults());
	const props = {
		song: takeSong,
		dirty: false,
		draftVersionNumber: 4,
		latestVersionNumber: Math.max(0, ...takeSong.generations.map((gen) => gen.version_number ?? 0)),
		onsource: vi.fn(),
		...overrides
	};
	mounted.push(
		mount(TakesListHarness, {
			target,
			props: { ...props, actions: mockActions() }
		})
	);
	await tick();
	return { target, props };
}
