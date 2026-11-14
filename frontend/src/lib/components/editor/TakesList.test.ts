import { failed } from '#lib/test-utils/generate-states.ts';
import { makeGeneration as generation, makeSong as song } from '#lib/test-utils/factories.ts';
import { tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { HITBOX_FREQUENT_PX } from '#lib/constants/hitbox.ts';
import {
	clearHitboxStyles,
	clearPointer,
	injectHitboxStyles,
	minSquarePx,
	setPointer
} from '#lib/test-utils/hitbox.ts';
import { selectedSongId } from '#lib/stores/player.ts';
import { get } from 'svelte/store';
import { clearSelection, selectedIds, toggleSelection } from '#lib/stores/selection.ts';

function enterSelectionMode(id = 'g1'): void {
	toggleSelection(id);
}

function stubCoarsePointer(isCoarse: boolean): void {
	vi.stubGlobal(
		'matchMedia',
		vi.fn((query: string) => ({
			matches: isCoarse ? query.includes('coarse') : false,
			media: query,
			onchange: null,
			addEventListener: vi.fn(),
			removeEventListener: vi.fn(),
			addListener: vi.fn(),
			removeListener: vi.fn(),
			dispatchEvent: vi.fn()
		}))
	);
}

vi.mock('#lib/api/client.ts', async (importOriginal) => {
	const actual = await importOriginal<typeof import('#lib/api/client.ts')>();
	return {
		...actual,
		bulkDeleteGenerations: vi.fn(),
		cancelJob: vi.fn(),
		fetchSong: vi.fn(),
		deleteVersion: vi.fn(),
		fetchVersions: vi.fn().mockResolvedValue([])
	};
});
vi.mock('#lib/stores/toast.ts', () => ({ addToast: vi.fn() }));
const generateState = await vi.hoisted(async () => {
	const { writable } = await import('svelte/store');
	return writable<GenerateState>({ kind: 'idle' });
});
vi.mock('#lib/stores/generateAction.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/stores/generateAction.ts')>()),
	generateAction: generateState
}));
vi.mock('#lib/stores/navigation.ts', async (importOriginal) => {
	const actual = await importOriginal<typeof import('#lib/stores/navigation.ts')>();
	return { ...actual, persistLibraryHistory: vi.fn() };
});
vi.mock('#lib/stores/player.ts', async (importOriginal) => {
	const actual = await importOriginal<typeof import('#lib/stores/player.ts')>();
	return {
		...actual,
		playTake: vi.fn(async () => undefined),
		playTakeAndShowNowPlaying: vi.fn(async () => undefined)
	};
});

import { addToast } from '#lib/stores/toast.ts';
import { bulkDeleteGenerations } from '#lib/api/client.ts';
import { ApiError, NetworkError } from '#lib/api/fetch.ts';
import type { GenerateState } from '#lib/stores/generateAction.ts';
import { activeJobs, generationFailures } from '#lib/stores/jobs.ts';
import { playTake, playTakeAndShowNowPlaying } from '#lib/stores/player.ts';
import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
import { playlistList, playlistLoad } from '#lib/stores/playlists.ts';
import { shownTransportFace } from '#lib/test-utils/transport-face.ts';
import {
	IDLE,
	addToPlaylist,
	clickMenuItem,
	clickVersion,
	keep,
	measuredTakeDefaults,
	mounted,
	openTakeMenu,
	pick,
	playlist,
	render,
	useSeed,
	versionedSongDefaults
} from '#lib/test-utils/takes-list.ts';
import { words } from '#lib/words/en.ts';

const emptyText = words['takesList.empty']({ generate: words['generate.button'] });
const takeOne = words['takeRow.takeVersioned']({ version: '1', take: '1' });
const repaintFromOne = words['takeRow.provenanceRepaint']({ take: takeOne });
const takeTwo = words['takeRow.takeVersioned']({ version: '3', take: '2' });
const takeThree = words['takeRow.takeVersioned']({ version: '3', take: '3' });
const noVocals = `⚠ ${words['takeRow.flagNoVocals']}`;
const playTakeLabel = (action: string) => words['takeRow.playTake']({ action, take: takeThree });
// defect:#1568 — these fixtures retain determinate progress and no elapsed phase.
const RUNNING: GenerateState = {
	kind: 'generating',
	indeterminate: false,
	elapsedLabel: null,
	jobId: 'j1',
	phase: 'Rendering',
	takeCounter: null,
	progress: 40,
	readout: '40%',
	ended: false,
	reconnecting: false,
	offline: false
};
const SUBMITTING: GenerateState = {
	kind: 'generating',
	indeterminate: false,
	elapsedLabel: null,
	jobId: null,
	phase: 'Generating...',
	takeCounter: null,
	progress: 0,
	readout: '0%',
	ended: false,
	reconnecting: false,
	offline: false
};
const QUEUED: Extract<GenerateState, { kind: 'queued' }> = {
	kind: 'queued',
	jobId: 'j1',
	label: 'Queued #2',
	reason: null,
	reconnecting: false,
	offline: false
};

vi.mock('#lib/stores/playlists.ts', async (importOriginal) => {
	const actual = await importOriginal<typeof import('#lib/stores/playlists.ts')>();
	return { ...actual, ensurePlaylistsLoaded: vi.fn(async () => undefined) };
});

const VRAM_CAUSE =
	'Music generation failed: Insufficient free VRAM: need ~2.0 GB, only 1.3 GB available';

let songSequence = 0;

function voice(overrides: Record<string, unknown> = {}) {
	return {
		id: 'l1',
		user_id: 'u1',
		name: 'Folk Alto',
		slug: 'folk-alto',
		status: 'ready',
		model_mode: 'sft',
		created_at: '2026-01-01T00:00:00+00:00',
		deleted_at: '2026-01-02T00:00:00+00:00',
		samples: [],
		...overrides
	};
}

beforeEach(() => {
	pick.mockReset();
	keep.mockReset();
	useSeed.mockReset();
	clickVersion.mockClear();
	addToPlaylist.mockClear();
	playlistList.set([{ ...playlist }]);
	playlistLoad.set({ status: 'ready', error: null });
	vi.mocked(addToast).mockClear();
	vi.mocked(playTake).mockClear();
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
	selectedSongId.set(`song-${(songSequence += 1)}`);
	clearSelection();
	audioPlayer.current = null;
	audioPlayer.status = 'idle';
	injectHitboxStyles();
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	audioPlayer.current = null;
	audioPlayer.status = 'idle';
	clearHitboxStyles();
	clearPointer();
	activeJobs.set([]);
	generationFailures.set({});
	generateState.set(IDLE);
	vi.unstubAllGlobals();
	clearSelection();
});

describe('TakesList', () => {
	it('names a deleted voice without changing the take playback target', async () => {
		const deletedVoiceTake = generation({
			...measuredTakeDefaults(),
			generation_params: { user_lora_id: 'l1' }
		});
		const songWithDeletedVoice = song({
			...versionedSongDefaults(),
			generations: [deletedVoiceTake]
		});
		const { target } = await render({ song: songWithDeletedVoice, voices: [voice()] });

		expect(target.querySelector('.take-voice')?.textContent?.trim()).toBe(
			words['takeRow.voiceDeleted']({ name: 'Folk Alto' })
		);
		target.querySelector<HTMLElement>('.play-btn')?.click();
		expect(playTake).toHaveBeenCalledWith(deletedVoiceTake, songWithDeletedVoice);
	});

	it('shows the current version open and each earlier one folded, newest first', async () => {
		const { target } = await render();
		const headers = Array.from(target.querySelectorAll('.version-header')).map((el) =>
			el.textContent?.trim()
		);
		expect(headers).toEqual([
			words['takesList.currentHead'](2, { number: '3' }),
			words['takesList.foldedVersion'](1, { number: '2' })
		]);
	});

	it('names each row Take n without repeating the version', async () => {
		const { target } = await render({
			song: song({
				generations: [1, 2, 3, 4].map((generation_number) =>
					generation({ id: `g${generation_number}`, version_number: 7, generation_number })
				)
			})
		});
		expect(
			Array.from(target.querySelectorAll('.take-label'), (label) => label.textContent?.trim())
		).toEqual(['1', '2', '3', '4'].map((number) => words['takeRow.takeLabel']({ number })));
	});

	it('opens the version the current head names, through the one version load', async () => {
		const { target } = await render({
			song: song({
				generations: [generation({ id: 'g7', version_id: 'ver-7', version_number: 7 })]
			})
		});

		const open = Array.from(target.querySelectorAll<HTMLButtonElement>('.version-link')).find(
			(button) => button.textContent?.includes(words['takesList.openVersion']({ number: '7' }))
		);
		open?.click();
		await tick();

		expect(clickVersion).toHaveBeenCalledExactlyOnceWith('ver-7');
	});

	it.each([
		{ origin: 'no version at all', version_number: null },
		{ origin: 'a version number but no version', version_number: 3 }
	])('groups imported takes with $origin with no Open link', async ({ version_number }) => {
		const { target } = await render({
			latestVersionNumber: 1,
			song: song({
				generations: [1, 2].map((generation_number) =>
					generation({
						id: `imported-${generation_number}`,
						version_id: null,
						version_number,
						generation_number
					})
				)
			})
		});

		expect(target.querySelector('.version-toggle')?.textContent?.trim()).toBe(
			words['takesList.foldedImported'](2)
		);
		expect(target.querySelector('.version-link')).toBeNull();
		expect(target.textContent).not.toContain('Open v');
	});

	it('shows the draft banner, naming the version it differs from and the one Generate creates, only when dirty', async () => {
		const { target: clean } = await render({ dirty: false });
		expect(clean.querySelector('.draft-banner')).toBeNull();

		const { target: dirty } = await render({
			dirty: true,
			latestVersionNumber: 3,
			draftVersionNumber: 4
		});
		expect(dirty.querySelector('.draft-banner')?.textContent?.trim()).toBe(
			words['takesList.draftDiffers']({ latest: '3', next: '4' })
		);
	});

	it('names no version to differ from once the last version of the song is deleted', async () => {
		const { target } = await render({
			song: song({ ...versionedSongDefaults(), version_count: 0, generations: [] }),
			dirty: true,
			latestVersionNumber: 0,
			draftVersionNumber: 1
		});
		expect(target.querySelector('.draft-banner')?.textContent?.trim()).toBe(
			words['takesList.draftUnsaved']({ next: '1' })
		);
	});

	it.each([true, false])(
		'keeps failures off Takes when existing takes are %s',
		async (hasTakes) => {
			generationFailures.set({ s1: { message: VRAM_CAUSE, unavailable: false } });
			const { target } = await render({
				song: song({
					...versionedSongDefaults(),
					generations: hasTakes ? [generation()] : []
				})
			});
			expect(target.textContent).not.toContain(VRAM_CAUSE);
			expect(target.querySelector('[role="alert"]')).toBeNull();
			if (hasTakes) expect(target.querySelectorAll('.take-row')).toHaveLength(1);
			else expect(target.textContent).toContain(emptyText);
		}
	);

	it('shows the running status slot with its phase while a generate job runs for this song', async () => {
		generateState.set(RUNNING);
		const { target } = await render();
		expect(target.querySelector('.status-slot')?.textContent).toContain('Rendering');
	});

	it('shows a queued generation reason and position without treating it as a failure', async () => {
		generateState.set({ ...QUEUED, reason: 'Waiting for LoRA training on this GPU.' });
		const { target } = await render();

		expect(target.querySelector('.status-title')?.textContent).toContain('Queued #2');
		expect(target.querySelector('.status-line.reason')?.textContent).toContain(
			'Waiting for LoRA training on this GPU.'
		);
	});

	it('labels the status slot with the version actually being generated, not the next draft version', async () => {
		// draftVersionNumber (the number Generate would create *next*) is 4
		// here — the two must not be conflated, since a running job always
		// targets an already-saved version (latestVersionNumber).
		generateState.set(RUNNING);
		const { target } = await render({
			draftVersionNumber: 4,
			latestVersionNumber: 3
		});
		expect(target.querySelector('.status-title')?.textContent).toContain('v3');
		expect(target.querySelector('.status-title')?.textContent).not.toContain('v4');
	});

	it('labels the status slot from the actual highest version number, not the stale version_count after a mid-run deletion', async () => {
		// A middle version (v2) was deleted after this job started: song.version_count
		// dropped to 2, but the job still targets the highest surviving version, v3.
		generateState.set(RUNNING);
		const { target } = await render({
			song: song({ ...versionedSongDefaults(), version_count: 2 }),
			latestVersionNumber: 3
		});
		expect(target.querySelector('.status-title')?.textContent).toContain('v3');
		expect(target.querySelector('.status-title')?.textContent).not.toContain('v2');
	});

	it.each([
		{ name: 'a running job', state: RUNNING, expectSlot: true, expectEmpty: false },
		{ name: 'a queued job', state: QUEUED, expectSlot: true, expectEmpty: false },
		{ name: 'no job', state: IDLE, expectSlot: false, expectEmpty: true },
		{
			name: 'a submission without a job yet',
			state: SUBMITTING,
			expectSlot: false,
			expectEmpty: true
		},
		{
			name: 'a failed job',
			state: { ...failed, cause: 'boom' } satisfies GenerateState,
			expectSlot: false,
			expectEmpty: true
		}
	])(
		'shows the slot and hides "No takes yet" for a song with zero takes and $name',
		async ({ state, expectSlot, expectEmpty }) => {
			generateState.set(state);
			const { target } = await render({
				song: song({ ...versionedSongDefaults(), generations: [] })
			});
			expect(target.querySelector('.status-slot') !== null).toBe(expectSlot);
			expect(target.textContent?.includes(emptyText)).toBe(expectEmpty);
			if (state.kind === 'queued') {
				expect(target.querySelector('.status-title')?.textContent).toContain('Queued #2');
			}
		}
	);

	it('offers no delete on a take-group header; the Versions sheet row carries it', async () => {
		const { target } = await render();
		const names = Array.from(
			target.querySelectorAll<HTMLButtonElement>('.version-header-row button')
		).map((button) => button.getAttribute('aria-label') ?? button.textContent ?? '');
		expect(names.length).toBeGreaterThan(0);
		expect(names.some((name) => /delete/i.test(name))).toBe(false);
	});

	it('leaves the model in the recipe instead of repeating it on the row', async () => {
		const { target } = await render({
			song: song({
				...versionedSongDefaults(),
				generations: [generation({ ...measuredTakeDefaults(), model_mode: 'xl-sft' })]
			})
		});
		expect(target.querySelector('.model-badge')).toBeNull();
	});

	it('shows its own measured length, not the "auto" (0) duration it was requested with', async () => {
		const { target } = await render({
			song: song({
				...versionedSongDefaults(),
				generations: [
					generation({
						...measuredTakeDefaults(),
						generation_params: { audio_duration: 0 },
						audio_duration_sec: 188
					})
				]
			})
		});
		expect(target.querySelector('.take-duration')?.textContent).toBe('3:08');
	});

	it('floors the measured length like every other duration', async () => {
		const { target } = await render({
			song: song({
				...versionedSongDefaults(),
				generations: [generation({ ...measuredTakeDefaults(), audio_duration_sec: 179.6 })]
			})
		});
		expect(target.querySelector('.take-duration')?.textContent).toBe('2:59');
	});

	it('shows no duration at all for a take whose length has not been measured', async () => {
		const { target } = await render({
			song: song({
				...versionedSongDefaults(),
				generations: [generation({ ...measuredTakeDefaults(), audio_duration_sec: null })]
			})
		});
		expect(target.querySelector('.take-duration')).toBeNull();
	});

	it('shows no model badge for a take that carries no model info', async () => {
		const { target } = await render({
			song: song({
				...versionedSongDefaults(),
				generations: [generation({ ...measuredTakeDefaults(), model_mode: '' })]
			})
		});
		expect(target.querySelector('.model-badge')).toBeNull();
	});

	it.each([
		{
			name: 'fewer takes than asked',
			params: { batch_size: 2, delivered_batch_size: 1 },
			badge: '⚠ 1 of 2'
		},
		{
			name: 'exactly what was asked',
			params: { batch_size: 2, delivered_batch_size: 2 },
			badge: null
		},
		{ name: 'no batch-size info at all', params: {}, badge: null },
		{ name: 'no generation params at all', params: null, badge: null }
	])(
		'shows $badge as the batch-reduction badge when the worker delivered $name',
		async ({ params, badge }) => {
			const { target } = await render({
				song: song({
					...versionedSongDefaults(),
					generations: [generation({ ...measuredTakeDefaults(), generation_params: params })]
				})
			});
			expect(target.querySelector('.batch-badge')?.textContent?.trim() ?? null).toBe(badge);
		}
	);

	const LYRICS = 'Night current';
	it.each([
		['lyrics and an empty transcript', LYRICS, '', undefined, noVocals],
		['a stored coherence of 7', LYRICS, '', { lyrical_coherence: 7 }, noVocals],
		['a transcript not yet made', LYRICS, null, undefined, null],
		['no lyrics (an instrumental)', '  ', '', undefined, null],
		['a transcript, stored coherence 0', LYRICS, 'night', { lyrical_coherence: 0 }, null]
	])('shows the flag for %s as %s', async (_name, version_lyrics, whisper_text, scores, label) => {
		const take = { ...measuredTakeDefaults(), version_lyrics, whisper_text, scores };
		const { target } = await render({
			song: song({ ...versionedSongDefaults(), generations: [generation(take)] })
		});
		const badge = target.querySelector<HTMLElement>('.quality-flag-badge');
		expect(badge?.textContent?.trim() ?? null).toBe(label);
		if (label) expect(badge?.title).toBe(words['takeRow.flagNoVocalsTitle']);
	});

	it('flags a take with a long silent gap', async () => {
		const { target } = await render({
			song: song({
				...versionedSongDefaults(),
				generations: [
					generation({
						...measuredTakeDefaults(),
						scores: { silence_gaps: 1, silence_longest: 20 }
					})
				]
			})
		});
		const badge = target.querySelector<HTMLElement>('.quality-flag-badge');
		expect(badge?.textContent?.trim()).toBe(`⚠ ${words['takeRow.flagLongSilence']}`);
		expect(badge?.title).toBe(words['takeRow.flagLongSilenceTitle']({ count: 20 }));
	});

	it('shows no quality flag for a short, ordinary silence gap', async () => {
		const { target } = await render({
			song: song({
				...versionedSongDefaults(),
				generations: [
					generation({
						...measuredTakeDefaults(),
						scores: { silence_gaps: 1, silence_longest: 3 }
					})
				]
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
				...versionedSongDefaults(),
				generations: [generation({ ...measuredTakeDefaults(), scores: { lyrical_coherence: 2 } })]
			})
		});
		expect(target.querySelector('.quality-flag-badge')).toBeNull();
	});

	it.each([
		['pick', '.pick-btn', 'is_picked', false],
		['pick', '.pick-btn', 'is_picked', true],
		['keep', '.keep-btn', 'is_kept', false],
		['keep', '.keep-btn', 'is_kept', true]
	] as const)(
		'toggles the %s in one tap on the row without playing the take (on: %s)',
		async (action, selector, flag, on) => {
			const { target } = await render({
				song: song({ generations: [generation({ [flag]: on })] })
			});
			const button = target.querySelector<HTMLButtonElement>(selector);
			expect(button?.getAttribute('aria-pressed')).toBe(String(on));
			button?.click();
			expect({ pick, keep }[action]).toHaveBeenCalledWith('g1', !on);
			expect(playTake).not.toHaveBeenCalled();
		}
	);

	it.each([
		['.pick-btn', 'picked', 'is_picked', false, words['takeRow.pickTake']({ take: takeTwo })],
		['.pick-btn', 'picked', 'is_picked', true, words['takeRow.unpickTake']({ take: takeTwo })],
		['.keep-btn', 'kept', 'is_kept', false, words['takeRow.keepTake']({ take: takeTwo })],
		['.keep-btn', 'kept', 'is_kept', true, words['takeRow.unkeepTake']({ take: takeTwo })]
	] as const)(
		'marks %s %s when %s is %s and names its tap after its own take: %s',
		async (selector, filledClass, flag, on, label) => {
			const { target } = await render({
				song: song({
					generations: [generation({ version_number: 3, generation_number: 2, [flag]: on })]
				})
			});
			const toggle = target.querySelector<HTMLButtonElement>(selector);
			expect(toggle?.getAttribute('aria-label')).toBe(label);
			expect(toggle?.classList.contains(filledClass)).toBe(on);
		}
	);

	it.each(['fine', 'coarse'] as const)(
		'has four symbol actions (▶ ★ ♥ ⋯) and one labelled row body on a %s pointer',
		async (pointer) => {
			setPointer(pointer);
			const { target } = await render();
			const row = target.querySelector('.take-row');
			if (!row) throw new Error('Expected a take row');
			const buttons = Array.from(row.querySelectorAll('button'));
			expect(buttons).toHaveLength(4);
			for (const button of buttons) {
				expect(button.textContent?.trim()).toBe('');
				expect(button.getAttribute('aria-label')).toBeTruthy();
			}

			const body = row.querySelector<HTMLElement>('[role="button"].take-summary');
			if (!body) throw new Error('Expected the row body target');
			expect(body.textContent?.trim()).not.toBe('');
			expect(body.getAttribute('aria-label')).toBeNull();
			expect(body.getAttribute('tabindex')).toBe('0');
			expect(row?.textContent).not.toMatch(/Repaint|Cover/);
		}
	);

	it('opens Now Playing on This take when the row body is tapped', async () => {
		const { target, props } = await render();
		const row = target.querySelector<HTMLElement>('.take-row');
		row?.querySelector<HTMLElement>('.take-summary')?.click();
		expect(playTakeAndShowNowPlaying).toHaveBeenCalledWith(
			expect.objectContaining({ id: 'g1' }),
			props.song
		);
		expect(playTake).not.toHaveBeenCalled();
	});

	it('opens Now Playing on This take when the row body is activated by keyboard', async () => {
		const { target, props } = await render();
		const row = target.querySelector<HTMLElement>('.take-row');
		const body = row?.querySelector<HTMLElement>('.take-summary');
		body?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
		expect(playTakeAndShowNowPlaying).toHaveBeenCalledWith(
			expect.objectContaining({ id: 'g1' }),
			props.song
		);
	});

	it('names the row body by its visible content, not an overriding label', async () => {
		const { target } = await render();
		const body = target.querySelector<HTMLElement>('.take-summary');
		const duration = target.querySelector('.take-duration')?.textContent?.trim();
		expect(body?.getAttribute('aria-label')).toBeNull();
		expect(body?.textContent?.replace(/\s+/g, ' ').trim()).toBe(
			`Take 3 ${duration}`.replace(/\s+/g, ' ').trim()
		);
	});

	it("still only toggles play on the row's play target, never opening Now Playing itself", async () => {
		const { target } = await render();
		const row = target.querySelector<HTMLElement>('.take-row');
		row?.querySelector<HTMLElement>('.play-btn')?.click();
		expect(playTake).toHaveBeenCalledWith(
			expect.objectContaining({ id: 'g1' }),
			expect.objectContaining({ id: 's1' })
		);
		expect(playTakeAndShowNowPlaying).not.toHaveBeenCalled();
	});

	it.each([
		['repaint', repaintFromOne],
		['cover', words['takeRow.provenanceCover']({ take: takeOne })]
	] as const)(
		'shows %s provenance with a link to its existing source',
		async (task_type, label) => {
			const source = generation({ ...measuredTakeDefaults(), id: 'source' });
			const result = generation({
				...measuredTakeDefaults(),
				id: 'result',
				version_number: 2,
				src_generation_id: source.id,
				src_generation_number: source.generation_number,
				src_generation_version_number: source.version_number,
				generation_params: { task_type }
			});
			const { target } = await render({
				song: song({ ...versionedSongDefaults(), generations: [source, result] })
			});
			const provenance = target.querySelector<HTMLElement>('#take-result .take-origin');

			expect(provenance?.textContent?.trim()).toBe(label);
			expect(provenance?.parentElement?.classList.contains('take-main')).toBe(true);
			expect(provenance?.closest('.take-actions')).toBeNull();
			expect(provenance?.querySelector('a')?.getAttribute('href')).toBe('#take-source');
		}
	);

	it('keeps provenance as text when its source metadata has no loaded target', async () => {
		const result = generation({
			...measuredTakeDefaults(),
			id: 'result',
			src_generation_id: 'deleted-source',
			src_generation_number: 1,
			src_generation_version_number: 1,
			generation_params: { task_type: 'repaint' }
		});
		const { target } = await render({
			song: song({ ...versionedSongDefaults(), generations: [result] })
		});
		const provenance = target.querySelector<HTMLElement>('#take-result .take-origin');

		expect(provenance?.textContent?.trim()).toBe(repaintFromOne);
		expect(provenance?.querySelector('a')).toBeNull();
	});

	it('keeps source provenance non-navigating while selection mode selects the take', async () => {
		const source = generation({ ...measuredTakeDefaults(), id: 'source' });
		const result = generation({
			...measuredTakeDefaults(),
			id: 'result',
			src_generation_id: source.id,
			src_generation_number: source.generation_number,
			src_generation_version_number: source.version_number,
			generation_params: { task_type: 'repaint' }
		});
		const { target } = await render({
			song: song({ ...versionedSongDefaults(), generations: [source, result] })
		});
		enterSelectionMode('source');
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
		row?.querySelector<HTMLElement>('.play-btn')?.click();
		expect(playTake).toHaveBeenCalledWith(
			expect.objectContaining({ id: 'g1' }),
			expect.objectContaining({ id: 's1' })
		);
	});

	const failingActions = [
		{
			action: 'deleting the selected takes',
			fallback: 'Bulk delete failed',
			fail: (error: Error) => vi.mocked(bulkDeleteGenerations).mockRejectedValueOnce(error),
			run: async (target: HTMLElement) => {
				enterSelectionMode();
				await tick();
				target.querySelector<HTMLButtonElement>('.selection-toolbar .destructive')?.click();
				await tick();
				document.querySelector<HTMLButtonElement>('[role="dialog"] .confirm-btn')?.click();
			}
		},
		{
			action: 'adding a take to a playlist',
			fallback: 'Failed to add',
			fail: (error: Error) => addToPlaylist.mockRejectedValueOnce(error),
			run: async (target: HTMLElement) => {
				const row = target.querySelector<HTMLElement>('.take-row');
				if (!row) throw new Error('Expected a take row');
				openTakeMenu(row);
				await tick();
				clickMenuItem(row, words['takeMenu.addToPlaylist']);
				await tick();
				row.querySelector<HTMLButtonElement>('.picker-item')?.click();
			}
		}
	];

	it.each(
		failingActions.flatMap((entry) => [
			{
				...entry,
				failure: 'with no network answer',
				error: new NetworkError('/api/generations', new TypeError('Failed to fetch')),
				shown: entry.fallback
			},
			{
				...entry,
				failure: 'refused by the server',
				error: new ApiError(409, 'A picked take stays', '/api/generations'),
				shown: 'A picked take stays'
			}
		])
	)('says $shown once when $action fails $failure', async ({ fail, run, error, shown }) => {
		fail(error);
		const { target } = await render();
		await run(target);
		await vi.waitFor(() => expect(vi.mocked(addToast).mock.calls).toEqual([[shown, 'error']]));
	});

	it('marks a take while its scoring job runs elsewhere', async () => {
		const { target } = await render();
		const row = target.querySelector<HTMLElement>('.take-row');
		expect(row?.querySelector('.rescoring-badge')).toBeNull();
		activeJobs.set([
			{
				job: {
					id: 'score-g1',
					type: 'score',
					status: 'running',
					progress: 0,
					error: null,
					error_type: null,
					started_at: null,
					completed_at: null
				},
				songId: 's1',
				genId: 'g1'
			}
		]);
		await tick();
		expect(row?.querySelector('.rescoring-badge')?.textContent).toBe(words['takeRow.rescoring']);
		activeJobs.set([]);
		await tick();
		expect(row?.querySelector('.rescoring-badge')).toBeNull();
	});

	it('plays only from its named play control, independently of the pick and menu', async () => {
		const { target } = await render();
		const row = target.querySelector<HTMLElement>('.take-row');
		const play = row?.querySelector<HTMLButtonElement>(`[aria-label="${playTakeLabel('Play')}"]`);
		expect(play).not.toBeNull();
		expect(play?.contains(row?.querySelector('.pick-btn') ?? null)).toBe(false);
		expect(play?.contains(row?.querySelector('.keep-btn') ?? null)).toBe(false);
		expect(play?.contains(row?.querySelector('.menu-trigger') ?? null)).toBe(false);
		play?.click();
		await tick();
		expect(pick).not.toHaveBeenCalled();
		expect(keep).not.toHaveBeenCalled();
		expect(playTake).toHaveBeenCalledWith(
			expect.objectContaining({ id: 'g1' }),
			expect.objectContaining({ id: 's1' })
		);
	});

	it.each([
		{ status: 'playing', label: 'Pause', busy: 'false', face: 'pause' },
		{ status: 'paused', label: 'Play', busy: 'false', face: 'play' },
		{ status: 'buffering', label: 'Pause', busy: 'true', face: 'spinner' },
		{ status: 'error', label: 'Retry', busy: 'false', face: 'refresh-cw' }
	] as const)(
		'names the transport action for a $status take and shows the face the bar shows (#1330)',
		async ({ status, label, busy, face }) => {
			const currentSong = song(versionedSongDefaults());
			audioPlayer.current = {
				generation: currentSong.generations[0],
				songId: currentSong.id,
				songTitle: currentSong.title,
				artist: '',
				albumTitle: '',
				lyrics: null
			};
			audioPlayer.status = status;
			const { target } = await render({ song: currentSong });
			const button = target.querySelector<HTMLButtonElement>(
				`[aria-label="${playTakeLabel(label)}"]`
			);
			expect({ busy: button?.getAttribute('aria-busy'), face: shownTransportFace(button) }).toEqual(
				{
					busy,
					face
				}
			);
			button?.click();
			expect(playTake).toHaveBeenCalledWith(currentSong.generations[0], currentSong);
		}
	);

	it.each(['ctrlKey', 'metaKey'])(
		'selects through the play control with %s without playback',
		async (modifier) => {
			const { target } = await render();
			target
				.querySelector('.play-btn')
				?.dispatchEvent(new MouseEvent('click', { bubbles: true, [modifier]: true }));
			await tick();
			expect(get(selectedIds).has('g1')).toBe(true);
			expect(playTake).not.toHaveBeenCalled();
			expect(target.querySelector('.play-btn')?.getAttribute('aria-pressed')).toBe('true');
		}
	);

	it.each(['fine', 'coarse'] as const)(
		'gives play, pick, keep and menu 44 px targets on a %s pointer',
		async (pointer) => {
			setPointer(pointer);
			const { target } = await render();
			for (const selector of ['.play-btn', '.pick-btn', '.keep-btn', '.menu-trigger']) {
				const button = target.querySelector<HTMLButtonElement>(selector);
				if (!button) throw new Error(`Expected ${selector}`);
				expect(minSquarePx(button, selector)).toEqual({
					width: HITBOX_FREQUENT_PX,
					height: HITBOX_FREQUENT_PX
				});
			}
		}
	);
});

describe('TakesList archived takes', () => {
	async function renderWithArchived() {
		return render({
			song: song({
				...versionedSongDefaults(),
				generations: [
					generation({
						...measuredTakeDefaults(),
						version_number: 3,
						generation_number: 3
					}),
					generation({
						...measuredTakeDefaults(),
						id: 'g-arch',
						version_number: 3,
						generation_number: 2,
						is_archived: true
					})
				]
			})
		});
	}

	it('offers no play affordance and does not play on click', async () => {
		const { target } = await renderWithArchived();
		const archivedRow = target.querySelectorAll<HTMLElement>('.take-row')[1];
		if (!archivedRow) throw new Error('Expected the archived take row');

		expect(archivedRow.classList.contains('archived')).toBe(true);
		expect(archivedRow.getAttribute('title')).toBe(words['takeRow.archivedTitle']);
		expect(archivedRow.querySelector('.take-label')?.previousElementSibling).toBeNull();
		expect(archivedRow.querySelector('.play-btn')).toBeNull();

		archivedRow.click();
		await tick();
		expect(playTake).not.toHaveBeenCalled();
	});

	it('owns and anchors its menu, and its playlist picker on a live row', async () => {
		// CSS is off in Vitest; the browser walkthrough covers stacking (R1). This proves the structure.
		const { target } = await renderWithArchived();
		const [liveRow, archivedRow] = Array.from(target.querySelectorAll<HTMLElement>('.take-row'));
		if (!liveRow || !archivedRow) throw new Error('Expected a live and an archived take row');

		openTakeMenu(archivedRow);
		await tick();
		expect(archivedRow.querySelector('.menu-panel')).not.toBeNull();
		expect(() => clickMenuItem(archivedRow, words['takeMenu.addToPlaylist'])).toThrow();

		openTakeMenu(liveRow);
		await tick();
		clickMenuItem(liveRow, words['takeMenu.addToPlaylist']);
		await tick();

		const picker = liveRow.querySelector('.picker');
		expect(picker?.parentElement?.classList.contains('take-picker-anchor')).toBe(true);
		expect(playTake).not.toHaveBeenCalled();
	});

	it('stops announcing itself as a button while it cannot act', async () => {
		const { target } = await renderWithArchived();
		const [playable, archived] = Array.from(target.querySelectorAll<HTMLElement>('.take-row'));
		expect(playable.querySelector('button.play-btn')).not.toBeNull();
		expect(archived.querySelector('button.play-btn')).toBeNull();
	});

	it('is a button again in selection mode, where ticking it still does something', async () => {
		const { target } = await renderWithArchived();
		enterSelectionMode();
		await tick();
		const archived = target.querySelectorAll<HTMLElement>('.take-row')[1];
		expect(archived.querySelector('button[aria-label="Select v3 · take 2"]')).not.toBeNull();
		archived.querySelector<HTMLElement>('.play-btn')?.click();
		await tick();
		expect(get(selectedIds).has('g-arch')).toBe(true);
	});

	it('still plays a take that is not archived', async () => {
		const { target } = await renderWithArchived();
		target.querySelector<HTMLElement>('.take-row .play-btn')?.click();
		await tick();
		expect(playTake).toHaveBeenCalledWith(
			expect.objectContaining({ id: 'g1' }),
			expect.objectContaining({ id: 's1' })
		);
	});

	it('does not play an archived take from its unreachable row body outside selection mode', async () => {
		const { target } = await renderWithArchived();
		const archivedRow = target.querySelectorAll<HTMLElement>('.take-row')[1];
		if (!archivedRow) throw new Error('Expected the archived take row');
		const body = archivedRow.querySelector<HTMLElement>('.take-summary');
		expect(body?.getAttribute('aria-disabled')).toBe('true');
		expect(body?.getAttribute('tabindex')).toBe('-1');
		body?.click();
		await tick();
		expect(playTakeAndShowNowPlaying).not.toHaveBeenCalled();
	});

	it('selects an archived take from its row body in selection mode', async () => {
		const { target } = await renderWithArchived();
		enterSelectionMode();
		await tick();
		const archivedRow = target.querySelectorAll<HTMLElement>('.take-row')[1];
		if (!archivedRow) throw new Error('Expected the archived take row');
		const body = archivedRow.querySelector<HTMLElement>('.take-summary');
		expect(body?.getAttribute('aria-disabled')).toBeNull();
		expect(body?.getAttribute('tabindex')).toBe('0');
		body?.click();
		await tick();
		expect(get(selectedIds).has('g-arch')).toBe(true);
		expect(playTakeAndShowNowPlaying).not.toHaveBeenCalled();
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
		{ name: 'a low rating', scores: { user_rating: 20 }, text: '20' },
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
			song: song({
				...versionedSongDefaults(),
				generations: [generation({ ...measuredTakeDefaults(), scores })]
			})
		});
		expect(target.querySelector('.score-badge')?.textContent?.trim()).toBe(text);
		expect(target.querySelector('.score-shape[aria-hidden="true"]')).not.toBeNull();
	});

	it("colours the pill from the scorer's own scale, not from the shown number", async () => {
		// 4.5 out of 10 is 'ok' (threshold 4), while 45 out of 100 would be too
		// — the thresholds are read on the raw value.
		const { target } = await render({
			song: song({
				...versionedSongDefaults(),
				generations: [generation({ ...measuredTakeDefaults(), scores: { audiobox_quality: 4.5 } })]
			})
		});
		const pill = target.querySelector('.score-badge');
		expect(pill?.textContent?.trim()).toBe('45');
		expect(pill?.classList.contains('ok')).toBe(true);
		expect(pill?.querySelector('.score-shape[aria-hidden="true"]')).not.toBeNull();
	});

	it('names the metric behind the number', async () => {
		const { target } = await render({
			song: song({
				...versionedSongDefaults(),
				generations: [generation({ ...measuredTakeDefaults(), scores: { dynamics: 54 } })]
			})
		});
		expect(target.querySelector('.score-badge')?.getAttribute('title')).toBe('Dynamics 54');
	});

	it('shows no pill for a take that carries no score at all', async () => {
		const { target } = await render({
			song: song({
				...versionedSongDefaults(),
				generations: [
					generation({
						...measuredTakeDefaults(),
						scores: { detected_language: 'en' }
					})
				]
			})
		});
		expect(target.querySelector('.score-badge')).toBeNull();
	});
});

describe('TakesList load states', () => {
	it.each([
		{
			name: 'empty',
			loadStatus: 'ready' as const,
			assert: (target: HTMLElement) => {
				expect(target.textContent).toContain(emptyText);
			}
		},
		{
			name: 'loading',
			loadStatus: 'loading' as const,
			assert: (target: HTMLElement) => {
				expect(target.textContent).toContain(words['takesList.loading']);
				expect(target.querySelectorAll('.skeleton-row')).toHaveLength(3);
			}
		},
		{
			name: 'error',
			loadStatus: 'error' as const,
			assert: (target: HTMLElement) => {
				expect(target.textContent).toContain(words['takesList.error']);
			}
		}
	])('draws the $name state instead of a blank area', async ({ loadStatus, assert }) => {
		const { target } = await render({ song: song({}), loadStatus });
		assert(target);
	});

	it('offers a retry icon named "Try again" that calls onretry when takes failed to load', async () => {
		const onretry = vi.fn();
		const { target } = await render({ song: song({}), loadStatus: 'error', onretry });
		const retry = target.querySelector<HTMLButtonElement>('.retry-btn');
		expect(retry?.getAttribute('aria-label')).toBe(words['takesList.retry']);
		retry?.click();
		expect(onretry).toHaveBeenCalledOnce();
	});

	it('does not offer the tap-play hint on Takes while the first generation has zero takes yet', async () => {
		stubCoarsePointer(true);
		generateState.set(RUNNING);
		const { target } = await render({ song: song({}) });
		expect(target.querySelector('.status-slot')).not.toBeNull();
		expect(target.querySelector('[role="tooltip"]')).toBeNull();
		vi.unstubAllGlobals();
	});
});

describe('TakesList touch hint', () => {
	it('offers the tap hint behind an info tip on a coarse pointer and not on a mouse', async () => {
		stubCoarsePointer(true);
		const tip = (await render()).target.querySelector('.version-head [role="tooltip"]');
		expect(tip?.textContent).toBe(words['takesList.mobileHint']);
		const unsaved = song({ version_count: 0, generations: [generation({})] });
		const imported = (await render({ song: unsaved })).target;
		expect(imported.querySelector('.version-header-row [role="tooltip"]')).not.toBeNull();
		stubCoarsePointer(false);
		expect((await render()).target.querySelector('[role="tooltip"]')).toBeNull();
		vi.unstubAllGlobals();
	});
});
