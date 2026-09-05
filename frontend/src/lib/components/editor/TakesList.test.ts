import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { GenerationItem, SongItem } from '$lib/api/types';
import { GENERATION_ACTIONS_KEY, type GenerationActions } from '$lib/contexts/generation-actions';
import {
	HITBOX_COMPACT_PX,
	HITBOX_FREQUENT_PX,
	TAKE_ARCHIVED_SOURCE_TITLE,
	TAKE_ARCHIVED_TITLE,
	TAKE_PLAYLIST_LABEL,
	TAKE_RESCORE_LABEL,
	TAKE_RESCORING_LABEL,
	TAKES_MOBILE_HINT
} from '$lib/constants';
import {
	clearHitboxStyles,
	clearPointer,
	injectHitboxStyles,
	minSquarePx,
	setPointer
} from '$lib/test-utils/hitbox';
import { get } from 'svelte/store';
import { clearSelection, selectedIds, toggleSelection } from '$lib/stores/selection';

function enterSelectionMode(): void {
	toggleSelection('selection-mode-seed');
}

vi.mock('$lib/api/client', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/api/client')>();
	return {
		...actual,
		bulkDeleteGenerations: vi.fn(),
		cancelJob: vi.fn(),
		remasterGeneration: vi.fn(),
		unarchiveGeneration: vi.fn(),
		scoreGeneration: vi.fn(),
		fetchSong: vi.fn(),
		deleteVersion: vi.fn(),
		fetchVersions: vi.fn().mockResolvedValue([])
	};
});
vi.mock('$lib/stores/toast', () => ({ addToast: vi.fn() }));
vi.mock('$lib/stores/navigation', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/stores/navigation')>();
	return { ...actual, persistLibraryHistory: vi.fn() };
});
vi.mock('$lib/stores/player', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/stores/player')>();
	return {
		...actual,
		playTakeAndShowNowPlaying: vi.fn(async () => undefined)
	};
});

import { scoreGeneration } from '$lib/api/client';
import { addToast } from '$lib/stores/toast';
import { activeJobs, generationFailures } from '$lib/stores/jobs';
import { playTakeAndShowNowPlaying } from '$lib/stores/player';
import { playlistList, playlistLoad } from '$lib/stores/playlists';
import TakesList from './TakesList.svelte';

const playlist = {
	id: 'p1',
	title: 'Night Drive',
	slug: 'night-drive',
	entry_count: 0,
	is_shared: false,
	share_slug: null,
	album_covers: [],
	created_at: '2026-01-01T00:00:00+00:00'
};

function openTakeMenu(row: HTMLElement): void {
	row.querySelector<HTMLButtonElement>('.overflow-btn')?.click();
}

function clickMenuItem(root: ParentNode, label: string): void {
	const item = Array.from(root.querySelectorAll<HTMLButtonElement>('.overflow-item')).find(
		(el) => el.textContent?.trim() === label
	);
	if (!item) throw new Error(`No take menu item named "${label}"`);
	item.click();
}

vi.mock('$lib/stores/playlists', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/stores/playlists')>();
	return { ...actual, ensurePlaylistsLoaded: vi.fn(async () => undefined) };
});

const VRAM_CAUSE =
	'Music generation failed: Insufficient free VRAM: need ~2.0 GB, only 1.3 GB available';

const mounted: Array<ReturnType<typeof mount>> = [];
const pick = vi.fn();
const keep = vi.fn();
const pinSeed = vi.fn();

const addToPlaylist = vi.fn(async () => undefined);

function mockActions(): GenerationActions {
	return {
		pick,
		keep,
		del: vi.fn(),
		rate: vi.fn(async () => undefined),
		share: vi.fn(async () => ({
			status: 'ok',
			share_url: '',
			share_slug: '',
			songs_without_playable_take: []
		})),
		unshare: vi.fn(async () => undefined),
		addToPlaylist,
		pinSeed,
		clickVersion: vi.fn()
	};
}

function generation(overrides: Partial<GenerationItem> = {}): GenerationItem {
	return {
		id: 'g1',
		song_id: 's1',
		version_id: 'v1',
		version_number: 1,
		generation_number: 1,
		mp3_path: 'g1.mp3',
		wav_path: null,
		seed: 7,
		status: 'completed',
		is_archived: false,
		is_picked: false,
		is_kept: false,
		is_shared: false,
		model_mode: 'turbo',
		whisper_text: null,
		whisper_cues: null,
		version_lyrics: null,
		scores: null,
		generation_params: { audio_duration: 195 },
		audio_duration_sec: 195,
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
}

function song(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 's1',
		slug: 'local-only',
		title: 'Local Only',
		album_id: 'a-local',
		album_title: 'Local Album',
		artist: 'Artist',
		track_number: 1,
		vocal_language: 'en',
		lyrics: '',
		prompt: '',
		bpm: 120,
		audio_duration: 180,
		key_scale: 'Am',
		generation_params: null,
		version_count: 3,
		generation_count: 5,
		best_scores: null,
		best_rating: null,
		generations: [
			generation({ id: 'g1', version_number: 3, generation_number: 3, is_picked: true }),
			generation({ id: 'g2', version_number: 3, generation_number: 2 }),
			generation({ id: 'g3', version_number: 2, generation_number: 1 })
		],
		created_at: '2026-01-01T00:00:00+00:00',
		is_shared: false,
		share_slug: null,
		...overrides
	};
}

beforeEach(() => {
	pick.mockReset();
	keep.mockReset();
	pinSeed.mockReset();
	addToPlaylist.mockClear();
	playlistList.set([{ ...playlist }]);
	playlistLoad.set({ status: 'ready', error: null });
	vi.mocked(addToast).mockClear();
	vi.mocked(playTakeAndShowNowPlaying).mockClear();
	activeJobs.set([]);
	generationFailures.set({});
	// The scoring job streams its progress over server-sent events jsdom does
	// not implement.
	vi.stubGlobal(
		'EventSource',
		class {
			close(): void {}
		}
	);
	clearSelection();
	injectHitboxStyles();
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	clearHitboxStyles();
	clearPointer();
	activeJobs.set([]);
	generationFailures.set({});
	vi.unstubAllGlobals();
	clearSelection();
});

async function render(overrides: Partial<Record<string, unknown>> = {}) {
	const target = document.createElement('div');
	document.body.append(target);
	const props = {
		song: song(),
		dirty: false,
		draftVersionNumber: 4,
		latestVersionNumber: 3,
		onagain: vi.fn(),
		onsource: vi.fn(),
		...overrides
	};
	mounted.push(
		mount(TakesList, {
			target,
			props,
			context: new Map([[GENERATION_ACTIONS_KEY, mockActions()]])
		})
	);
	await tick();
	return { target, props };
}

describe('TakesList', () => {
	it('groups takes by version, newest first', async () => {
		const { target } = await render();
		const headers = Array.from(target.querySelectorAll('.version-header')).map(
			(el) => el.textContent
		);
		expect(headers[0]).toBe('v3 · 2 takes');
		expect(headers[1]).toBe('v2 · 1 take');
	});

	it('shows the draft banner with the next version number only when dirty', async () => {
		const { target: clean } = await render({ dirty: false });
		expect(clean.querySelector('.draft-banner')).toBeNull();

		const { target: dirty } = await render({ dirty: true, draftVersionNumber: 4 });
		expect(dirty.querySelector('.draft-banner')?.textContent).toContain('v4');
	});

	it('shows why the last generation failed, with the full cause in the title', async () => {
		generationFailures.set({ s1: VRAM_CAUSE });
		const { target } = await render();
		const cause = target.querySelector<HTMLElement>('.failed-cause');
		expect(cause?.textContent).toBe(VRAM_CAUSE);
		expect(cause?.title).toBe(VRAM_CAUSE);
	});

	it('shows the failure even when the song has no takes yet', async () => {
		generationFailures.set({ s1: VRAM_CAUSE });
		const { target } = await render({ song: song({ generations: [] }) });
		expect(target.querySelector('.failed-cause')?.textContent).toBe(VRAM_CAUSE);
	});

	it('hides the failure once the user dismisses it', async () => {
		generationFailures.set({ s1: VRAM_CAUSE });
		const { target } = await render();
		target.querySelector<HTMLButtonElement>('.failed-dismiss')?.click();
		await tick();
		expect(target.querySelector('.failed-row')).toBeNull();
	});

	it('shows no failure row for another song', async () => {
		generationFailures.set({ s2: VRAM_CAUSE });
		const { target } = await render();
		expect(target.querySelector('.failed-row')).toBeNull();
	});

	it('shows a generating row while a generate job runs for this song', async () => {
		const { target } = await render({
			generateJob: { id: 'j1', type: 'generate', status: 'running', progress: 0.4 }
		});
		expect(target.querySelector('.generating-row')?.textContent).toContain('generating');
	});

	it('shows a queued generation reason and position without treating it as a failure', async () => {
		const { target } = await render({
			generateJob: {
				id: 'j1',
				type: 'generate',
				status: 'queued',
				progress: 0,
				queue_position: 2,
				queue_reason: 'Waiting for LoRA training on this GPU.'
			}
		});

		expect(target.querySelector('.generating-label')?.textContent).toContain('queued #2');
		expect(target.querySelector('.generating-label')?.textContent).toContain(
			'Waiting for LoRA training on this GPU.'
		);
		expect(target.querySelector('.failed-row')).toBeNull();
	});

	it('labels the generating row with the version actually being generated, not the next draft version', async () => {
		// draftVersionNumber (the number Generate would create *next*) is 4
		// here — the two must not be conflated, since a running job always
		// targets an already-saved version (latestVersionNumber).
		const { target } = await render({
			generateJob: { id: 'j1', type: 'generate', status: 'running', progress: 0.4 },
			draftVersionNumber: 4,
			latestVersionNumber: 3
		});
		expect(target.querySelector('.generating-label')?.textContent).toContain('v3');
		expect(target.querySelector('.generating-label')?.textContent).not.toContain('v4');
	});

	it('labels the generating row from the actual highest version number, not the stale version_count after a mid-run deletion', async () => {
		// A middle version (v2) was deleted after this job started: song.version_count
		// dropped to 2, but the job still targets the highest surviving version, v3.
		const { target } = await render({
			song: song({ version_count: 2 }),
			generateJob: { id: 'j1', type: 'generate', status: 'running', progress: 0.4 },
			latestVersionNumber: 3
		});
		expect(target.querySelector('.generating-label')?.textContent).toContain('v3');
		expect(target.querySelector('.generating-label')?.textContent).not.toContain('v2');
	});

	it('deletes a version and its takes from the group header, with confirmation', async () => {
		const { deleteVersion, fetchSong, fetchVersions } = await import('$lib/api/client');
		vi.mocked(deleteVersion).mockResolvedValueOnce(undefined);
		vi.mocked(fetchSong).mockResolvedValueOnce(song({ version_count: 2 }));
		vi.mocked(fetchVersions).mockResolvedValueOnce([]);

		const { target } = await render();
		const deleteBtn = target.querySelector<HTMLButtonElement>('.version-delete-btn');
		if (!deleteBtn) throw new Error('Expected a delete-version button on the newest group');
		deleteBtn.click();
		await tick();
		expect(document.querySelector('.dialog h3')?.textContent).toBe('Delete v3?');

		document.querySelector<HTMLButtonElement>('.confirm-btn')?.click();
		await tick();
		await Promise.resolve();

		expect(deleteVersion).toHaveBeenCalledWith('v1', true);
	});

	it("shows the take's model as a terse badge after the duration", async () => {
		const { target } = await render({
			song: song({ generations: [generation({ id: 'g1', model_mode: 'xl-sft' })] })
		});
		const badge = target.querySelector<HTMLElement>('.model-badge');
		expect(badge?.textContent?.trim()).toBe('xl-sft');
		expect(badge?.previousElementSibling?.classList.contains('take-duration')).toBe(true);
	});

	it('shows its own measured length, not the "auto" (0) duration it was requested with', async () => {
		const { target } = await render({
			song: song({
				generations: [
					generation({
						id: 'g1',
						generation_params: { audio_duration: 0 },
						audio_duration_sec: 188
					})
				]
			})
		});
		expect(target.querySelector('.take-duration')?.textContent).toBe('3:08');
	});

	it('shows no duration at all for a take whose length has not been measured', async () => {
		const { target } = await render({
			song: song({
				generations: [generation({ id: 'g1', audio_duration_sec: null })]
			})
		});
		expect(target.querySelector('.take-duration')).toBeNull();
	});

	it('shows no model badge for a take that carries no model info', async () => {
		const { target } = await render({
			song: song({ generations: [generation({ id: 'g1', model_mode: '' })] })
		});
		expect(target.querySelector('.model-badge')).toBeNull();
	});

	it('shows a batch-reduction badge when the worker delivered fewer takes than asked', async () => {
		const { target } = await render({
			song: song({
				generations: [
					generation({
						id: 'g1',
						generation_params: { batch_size: 2, delivered_batch_size: 1 }
					})
				]
			})
		});
		const badge = target.querySelector<HTMLElement>('.batch-badge');
		expect(badge?.textContent?.trim()).toBe('⚠ 1 of 2');
	});

	it('shows no batch-reduction badge when the worker delivered exactly what was asked', async () => {
		const { target } = await render({
			song: song({
				generations: [
					generation({
						id: 'g1',
						generation_params: { batch_size: 2, delivered_batch_size: 2 }
					})
				]
			})
		});
		expect(target.querySelector('.batch-badge')).toBeNull();
	});

	it('shows no batch-reduction badge for a take with no batch-size info at all', async () => {
		const { target } = await render();
		expect(target.querySelector('.batch-badge')).toBeNull();
	});

	it('flags a take with no vocals detected', async () => {
		const { target } = await render({
			song: song({
				generations: [
					generation({
						id: 'g1',
						scores: { lyrical_coherence: 0, lyrical_summary: 'Whisper found no vocals' }
					})
				]
			})
		});
		const badge = target.querySelector<HTMLElement>('.quality-flag-badge');
		expect(badge?.textContent?.trim()).toBe('⚠ No vocals');
		expect(badge?.title).toBe('Whisper found no vocals');
	});

	it('flags a take with a long silent gap', async () => {
		const { target } = await render({
			song: song({
				generations: [generation({ id: 'g1', scores: { silence_gaps: 1, silence_longest: 20 } })]
			})
		});
		const badge = target.querySelector<HTMLElement>('.quality-flag-badge');
		expect(badge?.textContent?.trim()).toBe('⚠ Long silence');
		expect(badge?.title).toBe('20s of silence detected');
	});

	it('shows no quality flag for a short, ordinary silence gap', async () => {
		const { target } = await render({
			song: song({
				generations: [generation({ id: 'g1', scores: { silence_gaps: 1, silence_longest: 3 } })]
			})
		});
		expect(target.querySelector('.quality-flag-badge')).toBeNull();
	});

	it('shows no quality flag for a take with no scores yet', async () => {
		const { target } = await render();
		expect(target.querySelector('.quality-flag-badge')).toBeNull();
	});

	it('shows no quality flag for a take with a merely low, non-zero coherence score', async () => {
		const { target } = await render({
			song: song({
				generations: [generation({ id: 'g1', scores: { lyrical_coherence: 2 } })]
			})
		});
		expect(target.querySelector('.quality-flag-badge')).toBeNull();
	});

	it('calls pick and keep from the take actions', async () => {
		const { target } = await render();
		const row = target.querySelectorAll('.take-row')[1];
		if (!(row instanceof HTMLElement)) throw new Error('Expected the second take row (g2)');
		row.querySelector<HTMLButtonElement>('.pick-btn')?.click();
		expect(pick).toHaveBeenCalledWith('g2', true);
		row.querySelector<HTMLButtonElement>('.keep-btn')?.click();
		expect(keep).toHaveBeenCalledWith('g2', true);
	});

	it.each([
		['Repaint', 'repaint'],
		['Cover', 'cover']
	] as const)('%s sets the take as the %s source without playing it', async (label, mode) => {
		const { target, props } = await render();
		const row = target.querySelector<HTMLElement>('.take-row');
		if (!row) throw new Error('Expected a take row');
		Array.from(row.querySelectorAll<HTMLButtonElement>('.take-action-btn'))
			.find((button) => button.textContent?.trim() === label)
			?.click();
		await tick();

		expect(props.onsource).toHaveBeenCalledWith(expect.objectContaining({ id: 'g1' }), mode);
		expect(playTakeAndShowNowPlaying).not.toHaveBeenCalled();
	});

	it.each([
		['repaint', 'Repaint from v1 · take 1'],
		['cover', 'Cover from v1 · take 1']
	] as const)(
		'shows %s provenance with a link to its existing source',
		async (task_type, label) => {
			const source = generation({ id: 'source', version_number: 1, generation_number: 1 });
			const result = generation({
				id: 'result',
				version_number: 2,
				generation_number: 1,
				src_generation_id: source.id,
				src_generation_number: source.generation_number,
				src_generation_version_number: source.version_number,
				generation_params: { task_type }
			});
			const { target } = await render({ song: song({ generations: [source, result] }) });
			const provenance = target.querySelector<HTMLElement>('#take-result .take-origin');

			expect(provenance?.textContent?.trim()).toBe(label);
			expect(provenance?.parentElement?.classList.contains('take-main')).toBe(true);
			expect(provenance?.closest('.take-actions')).toBeNull();
			expect(provenance?.querySelector('a')?.getAttribute('href')).toBe('#take-source');
		}
	);

	it('keeps provenance as text when its source metadata has no loaded target', async () => {
		const result = generation({
			id: 'result',
			src_generation_id: 'deleted-source',
			src_generation_number: 1,
			src_generation_version_number: 1,
			generation_params: { task_type: 'repaint' }
		});
		const { target } = await render({ song: song({ generations: [result] }) });
		const provenance = target.querySelector<HTMLElement>('#take-result .take-origin');

		expect(provenance?.textContent?.trim()).toBe('Repaint from v1 · take 1');
		expect(provenance?.querySelector('a')).toBeNull();
	});

	it('keeps source provenance non-navigating while selection mode selects the take', async () => {
		const source = generation({ id: 'source', version_number: 1, generation_number: 1 });
		const result = generation({
			id: 'result',
			src_generation_id: source.id,
			src_generation_number: source.generation_number,
			src_generation_version_number: source.version_number,
			generation_params: { task_type: 'repaint' }
		});
		const { target } = await render({ song: song({ generations: [source, result] }) });
		enterSelectionMode();
		await tick();
		const row = target.querySelector<HTMLElement>('#take-result');

		const provenance = row?.querySelector<HTMLElement>('.take-origin');
		expect(provenance?.querySelector('a')).toBeNull();
		provenance?.click();
		await tick();
		expect(get(selectedIds).has('result')).toBe(true);
	});

	it('plays the take and opens Now Playing on its play target click', async () => {
		const { target } = await render();
		const row = target.querySelector<HTMLElement>('.take-row');
		row?.querySelector<HTMLElement>('.take-summary')?.click();
		expect(playTakeAndShowNowPlaying).toHaveBeenCalledWith(
			expect.objectContaining({ id: 'g1' }),
			expect.objectContaining({ id: 's1' })
		);
	});

	it("names the take on the row's menu, without also playing it", async () => {
		const { target } = await render();
		const row = target.querySelector<HTMLElement>('.take-row');
		row?.querySelector<HTMLButtonElement>('.overflow-btn')?.click();
		await tick();
		expect(target.querySelector('.menu-heading')?.textContent).toBe('Take · v3 · 3');
		expect(playTakeAndShowNowPlaying).not.toHaveBeenCalled();
	});

	it('adds the take to a playlist from its own row, without also playing it', async () => {
		// #141/3: the picker is absolutely positioned, so it must sit inside a
		// positioned anchor in the row — otherwise it escapes the row entirely
		// and the menu entry looks like it does nothing.
		const { target } = await render();
		const row = target.querySelector<HTMLElement>('.take-row');
		if (!row) throw new Error('Expected a take row');
		openTakeMenu(row);
		await tick();
		clickMenuItem(row, TAKE_PLAYLIST_LABEL);
		await tick();

		const picker = row.querySelector('.picker');
		expect(picker, 'the playlist picker renders inside the take row').not.toBeNull();
		expect(picker?.parentElement?.classList.contains('take-picker-anchor')).toBe(true);

		row.querySelector<HTMLButtonElement>('.picker-item')?.click();
		await tick();
		await Promise.resolve();

		expect(addToPlaylist).toHaveBeenCalledWith('p1', 'g1');
		expect(playTakeAndShowNowPlaying).not.toHaveBeenCalled();
	});

	it('re-scores the take from its own menu and marks the row until the job ends', async () => {
		vi.mocked(scoreGeneration).mockResolvedValue({
			id: 'j1',
			type: 'score',
			status: 'queued',
			progress: 0,
			error: null,
			error_type: null,
			started_at: null,
			completed_at: null
		});
		const { target } = await render();
		const row = target.querySelector<HTMLElement>('.take-row');
		if (!row) throw new Error('Expected a take row');
		expect(row.querySelector('.rescoring-badge')).toBeNull();

		openTakeMenu(row);
		await tick();
		clickMenuItem(row, TAKE_RESCORE_LABEL);
		await tick();
		await Promise.resolve();
		await tick();

		expect(scoreGeneration).toHaveBeenCalledTimes(1);
		expect(scoreGeneration).toHaveBeenCalledWith('g1');
		expect(row.querySelector('.rescoring-badge')?.textContent).toBe(TAKE_RESCORING_LABEL);
		expect(playTakeAndShowNowPlaying).not.toHaveBeenCalled();

		activeJobs.set([]);
		await tick();
		expect(row.querySelector('.rescoring-badge')).toBeNull();
	});

	it('keeps every action out of the row body, so a tap on the row plays it', async () => {
		// #163/2: on a 320px screen the three 44px touch targets used to sit
		// across the row's centre, and a tap meant for the row toggled Pick or
		// Keep. The body is one element the actions are never inside of, which
		// is also what lets the actions wrap onto their own line when the row
		// runs out of width.
		const { target } = await render();
		const row = target.querySelector<HTMLElement>('.take-row');
		if (!row) throw new Error('Expected a take row');
		const main = row.querySelector<HTMLElement>('.take-main');
		if (!main) throw new Error('Expected the take row main column');

		expect(main.querySelector('.take-label')).not.toBeNull();
		expect(main.querySelector('.take-duration')).not.toBeNull();
		expect(main.querySelector('button')).toBeNull();
		expect(row.querySelector('.take-actions')?.parentElement).toBe(row);

		// The model badge is another descriptive fact about the take, so it
		// belongs in the body with the rest — never in take-actions, where a
		// row too narrow to hold both wraps actions onto their own line
		// instead of crowding a touch target (#163/2).
		expect(main.querySelector('.model-badge')).not.toBeNull();
		expect(row.querySelector('.take-actions')?.querySelector('.model-badge')).toBeNull();

		main.querySelector<HTMLElement>('.take-summary')?.click();
		await tick();
		expect(pick).not.toHaveBeenCalled();
		expect(keep).not.toHaveBeenCalled();
		expect(playTakeAndShowNowPlaying).toHaveBeenCalledWith(
			expect.objectContaining({ id: 'g1' }),
			expect.objectContaining({ id: 's1' })
		);
	});

	it('sizes pick and keep to the frequent hitbox on a coarse pointer', async () => {
		const { target } = await render();
		const pickBtn = target.querySelector<HTMLButtonElement>('.pick-btn');
		if (!pickBtn) throw new Error('Expected pick button');
		setPointer('coarse');
		expect(minSquarePx(pickBtn, 'pick').width).toBe(HITBOX_FREQUENT_PX);
		expect(minSquarePx(pickBtn, 'pick').height).toBe(HITBOX_FREQUENT_PX);
		setPointer('fine');
		expect(minSquarePx(pickBtn, 'pick').width).toBeGreaterThanOrEqual(HITBOX_COMPACT_PX);
	});
});

describe('TakesList archived takes', () => {
	async function renderWithArchived() {
		return render({
			song: song({
				generations: [
					generation({ id: 'g1', version_number: 3, generation_number: 3 }),
					generation({ id: 'g-arch', version_number: 3, generation_number: 2, is_archived: true })
				]
			})
		});
	}

	it('offers no play affordance and does not play on click', async () => {
		const { target } = await renderWithArchived();
		const archivedRow = target.querySelectorAll<HTMLElement>('.take-row')[1];
		if (!archivedRow) throw new Error('Expected the archived take row');

		expect(archivedRow.classList.contains('archived')).toBe(true);
		expect(archivedRow.getAttribute('title')).toBe(TAKE_ARCHIVED_TITLE);
		expect(archivedRow.querySelector('.take-label')?.previousElementSibling).toBeNull();
		const sourceActions = Array.from(
			archivedRow.querySelectorAll<HTMLButtonElement>('.take-action-btn')
		);
		expect(sourceActions).toHaveLength(2);
		for (const action of sourceActions) {
			expect(action.disabled).toBe(true);
			expect(action.title).toBe(TAKE_ARCHIVED_SOURCE_TITLE);
		}

		archivedRow.click();
		await tick();
		expect(playTakeAndShowNowPlaying).not.toHaveBeenCalled();
	});

	it('owns and anchors its menu and playlist picker, archived or not', async () => {
		// Vitest runs with CSS off, so the absent stacking context cannot be
		// asserted by computed style here — the browser walkthrough covers that
		// (R1: row opacity 1, picker bottom hit-testable). What jsdom proves is
		// the structure: the row owns its popovers and anchors them itself.
		const { target } = await renderWithArchived();
		const archivedRow = target.querySelectorAll<HTMLElement>('.take-row')[1];
		if (!archivedRow) throw new Error('Expected the archived take row');

		openTakeMenu(archivedRow);
		await tick();
		expect(archivedRow.querySelector('.overflow-menu')).not.toBeNull();
		clickMenuItem(archivedRow, TAKE_PLAYLIST_LABEL);
		await tick();

		const picker = archivedRow.querySelector('.picker');
		expect(picker, 'the playlist picker renders inside the archived row').not.toBeNull();
		expect(picker?.parentElement?.classList.contains('take-picker-anchor')).toBe(true);
		expect(playTakeAndShowNowPlaying).not.toHaveBeenCalled();
	});

	it('stops announcing itself as a button while it cannot act', async () => {
		const { target } = await renderWithArchived();
		const [playable, archived] = Array.from(target.querySelectorAll<HTMLElement>('.take-row'));
		expect(playable.querySelector('.take-summary')?.getAttribute('role')).toBe('button');
		expect(archived.querySelector('.take-summary')?.getAttribute('role')).toBeNull();
		expect(archived.querySelector('.take-summary')?.getAttribute('tabindex')).toBeNull();
	});

	it('is a button again in selection mode, where ticking it still does something', async () => {
		const { target } = await renderWithArchived();
		enterSelectionMode();
		await tick();
		const archived = target.querySelectorAll<HTMLElement>('.take-row')[1];
		expect(archived.querySelector('.take-summary')?.getAttribute('role')).toBe('button');
		expect(archived.querySelector('.take-action-btn')).toBeNull();
		archived.querySelector<HTMLElement>('.take-summary')?.click();
		await tick();
		expect(get(selectedIds).has('g-arch')).toBe(true);
	});

	it('still plays a take that is not archived', async () => {
		const { target } = await renderWithArchived();
		target.querySelector<HTMLElement>('.take-row .take-summary')?.click();
		await tick();
		expect(playTakeAndShowNowPlaying).toHaveBeenCalledWith(
			expect.objectContaining({ id: 'g1' }),
			expect.objectContaining({ id: 's1' })
		);
	});
});

describe('TakesList score pill', () => {
	// #163/4: a take is scored by seven scorers that can land one at a time, so
	// "scored" is never all-or-nothing. The row shows the highest-ranked score
	// the take actually carries instead of hiding the pill until a rating
	// exists — and shows every one of them on the same 0-100 scale, since one
	// unlabelled number cannot say which scale it is on.
	const cases = [
		{ name: 'the rating the listener gave', scores: { user_rating: 82 }, text: '82' },
		{
			name: 'the rating even when automatic scores exist too',
			scores: { user_rating: 82, text_accuracy: 41 },
			text: '82'
		},
		{ name: 'lyrics sung when unrated', scores: { text_accuracy: 87 }, text: '87' },
		{
			name: 'dynamics when neither rating nor transcript exist',
			scores: { dynamics: 54, audiobox_quality: 8.15, audiobox_enjoyment: 7.46 },
			text: '54'
		},
		{
			name: 'quality out of ten as a score out of a hundred',
			scores: { audiobox_quality: 8.15 },
			text: '82'
		},
		{
			name: 'enjoyment out of ten as a score out of a hundred',
			scores: { audiobox_enjoyment: 7.46 },
			text: '75'
		},
		{
			name: 'coherence out of ten as a score out of a hundred',
			scores: { lyrical_coherence: 7 },
			text: '70'
		}
	];

	it.each(cases)('shows $name', async ({ scores, text }) => {
		const { target } = await render({
			song: song({ generations: [generation({ id: 'g1', scores })] })
		});
		expect(target.querySelector('.score-badge')?.textContent?.trim()).toBe(text);
	});

	it("colours the pill from the scorer's own scale, not from the shown number", async () => {
		// 4.5 out of 10 is 'ok' (threshold 4), while 45 out of 100 would be too
		// — the thresholds are read on the raw value.
		const { target } = await render({
			song: song({ generations: [generation({ id: 'g1', scores: { audiobox_quality: 4.5 } })] })
		});
		const pill = target.querySelector('.score-badge');
		expect(pill?.textContent?.trim()).toBe('45');
		expect(pill?.classList.contains('ok')).toBe(true);
	});

	it('names the metric behind the number', async () => {
		const { target } = await render({
			song: song({ generations: [generation({ id: 'g1', scores: { dynamics: 54 } })] })
		});
		expect(target.querySelector('.score-badge')?.getAttribute('title')).toBe('Dynamics 54');
	});

	it('shows no pill for a take that carries no score at all', async () => {
		const { target } = await render({
			song: song({ generations: [generation({ id: 'g1', scores: { detected_language: 'en' } })] })
		});
		expect(target.querySelector('.score-badge')).toBeNull();
	});
});

describe('TakesList touch hint', () => {
	it('shows the tap hint on a coarse pointer and hides it on a mouse', async () => {
		// #141/11: a narrow desktop window is compact but still has a mouse.
		vi.stubGlobal(
			'matchMedia',
			vi.fn((query: string) => ({
				matches: query.includes('coarse'),
				media: query,
				onchange: null,
				addEventListener: vi.fn(),
				removeEventListener: vi.fn(),
				addListener: vi.fn(),
				removeListener: vi.fn(),
				dispatchEvent: vi.fn()
			}))
		);
		const { target: coarse } = await render();
		expect(coarse.textContent).toContain(TAKES_MOBILE_HINT);

		vi.stubGlobal(
			'matchMedia',
			vi.fn((query: string) => ({
				matches: false,
				media: query,
				onchange: null,
				addEventListener: vi.fn(),
				removeEventListener: vi.fn(),
				addListener: vi.fn(),
				removeListener: vi.fn(),
				dispatchEvent: vi.fn()
			}))
		);
		const { target: fine } = await render();
		expect(fine.textContent).not.toContain(TAKES_MOBILE_HINT);
		vi.unstubAllGlobals();
	});
});

describe('Escape yields to the take overflow menu before any global shortcut', () => {
	it('closes the overflow menu on Escape without leaking to a document listener', async () => {
		const { target } = await render();
		target
			.querySelector<HTMLElement>('.take-row')
			?.querySelector<HTMLButtonElement>('.overflow-btn')
			?.click();
		await tick();
		expect(target.querySelector('.overflow-menu')).not.toBeNull();
		document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
		await tick();
		expect(target.querySelector('.overflow-menu')).toBeNull();
	});
});
