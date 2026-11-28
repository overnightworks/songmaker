import { makeGeneration as generation, makeSong as song } from '#lib/test-utils/factories.ts';
import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { GenerationItem, SongItem } from '#lib/api/types.ts';

vi.mock('#lib/stores/navigation.ts', async (importOriginal) => ({
	appPageAddress: (await importOriginal<typeof import('#lib/stores/navigation.ts')>())
		.appPageAddress,
	followAppPageLink: vi.fn()
}));

import { words } from '#lib/words/en.ts';
import { followAppPageLink } from '#lib/stores/navigation.ts';
import NowPlayingTake from './NowPlayingTake.svelte';

const generationDefaults = {
	version_number: 3,
	generation_number: 3,
	mp3_path: 'a.mp3',
	seed: 48113,
	model_mode: 'sft',
	version_lyrics: 'la la',
	created_at: ''
} satisfies Partial<GenerationItem>;

let mounted: ReturnType<typeof mount> | undefined;
let target: HTMLDivElement;

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	vi.clearAllMocks();
});

async function render(overrides: Partial<{ generation: GenerationItem; song: SongItem }> = {}) {
	target = document.createElement('div');
	document.body.append(target);
	mounted = mount(NowPlayingTake, {
		target,
		props: {
			generation: overrides.generation ?? generation(generationDefaults),
			song:
				overrides.song ??
				song({
					slug: 'tide',
					title: 'Tide',
					album_title: 'Nachtstrom',
					lyrics: 'la la',
					prompt: 'dreamy',
					created_at: ''
				})
		}
	});
	await tick();
}

describe('NowPlayingTake', () => {
	it("names the take's version, number, duration and model in the heading", async () => {
		await render({
			generation: generation({
				...generationDefaults,
				model_mode: 'xl-sft',
				audio_duration_sec: 195
			})
		});
		expect(target.querySelector('.take-heading')?.textContent).toBe(
			`${words['nowPlaying.takeVersioned']({ version: '3', take: '3' })} · 3:15 · xl-sft`
		);
	});

	it('shows its own measured length, not the "auto" (0) duration it was requested with', async () => {
		await render({
			generation: generation({
				...generationDefaults,
				version_number: 4,
				generation_number: 4,
				model_mode: 'xl-turbo',
				generation_params: { audio_duration: 0 },
				audio_duration_sec: 188
			})
		});
		expect(target.querySelector('.take-heading')?.textContent).toBe(
			`${words['nowPlaying.takeVersioned']({ version: '4', take: '4' })} · 3:08 · xl-turbo`
		);
	});

	it('names no duration at all for a take whose length has not been measured', async () => {
		await render({
			generation: generation({ ...generationDefaults, version_number: 1, generation_number: 1 })
		});
		const heading = target.querySelector('.take-heading')?.textContent ?? '';
		expect(heading).toBe(`${words['nowPlaying.takeVersioned']({ version: '1', take: '1' })} · sft`);
		expect(heading).not.toContain('0:00');
	});
});

describe('NowPlayingTake imported heading', () => {
	it.each([
		{ origin: 'no version at all', version_number: null },
		{ origin: 'a version number but no version', version_number: 3 }
	])(
		'names an imported take with $origin "Imported take", with no model',
		async ({ version_number }) => {
			await render({
				generation: generation({
					...generationDefaults,
					version_id: null,
					version_number,
					model_mode: 'sft'
				})
			});

			expect(target.querySelector('.take-heading')?.textContent).toBe(
				words['nowPlayingTake.importedHeading']
			);
		}
	);
});

describe('NowPlayingTake recipe section', () => {
	function recipeRows(root: ParentNode): Array<[string, string]> {
		return Array.from(root.querySelectorAll('.recipe-row')).map((row) => [
			row.querySelector('dt')?.textContent ?? '',
			row.querySelector('dd')?.textContent ?? ''
		]);
	}

	it('groups everything the take carries under its own labelled section', async () => {
		await render({
			generation: generation({
				...generationDefaults,
				model_mode: 'xl-sft',
				generation_params: {
					inference_steps: 50,
					guidance_scale: 7.5,
					bpm: 128,
					audio_duration: 195,
					key_scale: 'Am'
				}
			}),
			song: song({
				slug: 'tide',
				title: 'Tide',
				album_title: 'Nachtstrom',
				lyrics: 'la la',
				prompt: 'dreamy',
				created_at: ''
			})
		});

		const groupLabels = Array.from(target.querySelectorAll('.recipe-group-label')).map(
			(el) => el.textContent
		);
		expect(groupLabels).toEqual([
			words['takeRecipe.groupModel'],
			words['takeRecipe.groupReproducibility'],
			words['takeRecipe.groupVersion']
		]);
		expect(recipeRows(target)).toEqual([
			[words['takeRecipe.model'], 'xl-sft'],
			[words['paramField.inferenceSteps'], '50'],
			[words['paramField.guidanceScale'], '7.5'],
			[words['takeRecipe.seed'], '48113'],
			[words['takeRecipe.bpm'], '128'],
			[words['takeRecipe.duration'], '3:15'],
			[words['takeRecipe.key'], 'Am'],
			[words['takeRecipe.language'], 'en']
		]);
	});

	it('names a param the registry does not know under Other', async () => {
		await render({
			generation: generation({
				...generationDefaults,
				model_mode: '',
				seed: null,
				generation_params: { repaint_wav_crossfade_sec: 0.25 }
			}),
			song: song({
				slug: 'tide',
				title: 'Tide',
				album_title: 'Nachtstrom',
				lyrics: 'la la',
				prompt: 'dreamy',
				created_at: '',
				vocal_language: ''
			})
		});
		expect(
			Array.from(target.querySelectorAll('.recipe-group-label')).map((el) => el.textContent)
		).toEqual([words['takeRecipe.groupOther']]);
		expect(recipeRows(target)).toEqual([['Repaint Wav Crossfade Sec', '0.25']]);
	});

	it('shows no recipe section for a take that carries nothing to show', async () => {
		await render({
			generation: generation({ ...generationDefaults, model_mode: '', seed: null }),
			song: song({
				slug: 'tide',
				title: 'Tide',
				album_title: 'Nachtstrom',
				lyrics: 'la la',
				prompt: 'dreamy',
				created_at: '',
				vocal_language: ''
			})
		});
		expect(target.querySelector('.recipe-section')).toBeNull();
	});

	it('shows the reference as a link to its row, and every other entry as text', async () => {
		await render({
			generation: generation({
				...generationDefaults,
				model_mode: 'xl-sft',
				reference: { id: 'r 1', filename: 'demo take.wav' }
			})
		});

		const link = target.querySelector<HTMLAnchorElement>('.recipe-row dd a');
		expect(link?.textContent).toContain('demo take.wav');
		expect(link?.getAttribute('href')).toBe('/settings/references?reference=r+1');
		expect(target.querySelectorAll('.recipe-row dd a')).toHaveLength(1);

		link?.click();
		expect(followAppPageLink).toHaveBeenCalledWith(expect.any(MouseEvent), '/settings/references', {
			reference: 'r 1'
		});
	});

	it('starts collapsed — the listener opens it, it does not open on them', async () => {
		await render({ generation: generation({ ...generationDefaults, model_mode: 'xl-sft' }) });
		const details = target.querySelector<HTMLDetailsElement>('.recipe-section');
		expect(details?.open).toBe(false);
	});
});
