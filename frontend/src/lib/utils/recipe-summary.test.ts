import { makeGeneration as generation, makeSong as song } from '#lib/test-utils/factories.ts';
import { describe, expect, it, vi } from 'vitest';
import type { GenerationItem } from '#lib/api/types.ts';
import { words } from '#lib/words/en.ts';
import { sourceLanguage } from '#lib/words/index.ts';

// The registry test resets the module graph, so each import brings its own page words to load.
async function importBuildTakeRecipe() {
	const { loadPageWords } = await import('#lib/utils/page-words.ts');
	await loadPageWords(sourceLanguage);
	return (await import('./recipe-summary')).buildTakeRecipe;
}

describe('buildTakeRecipe', () => {
	it.each([
		{
			name: 'a fully-parameterized take',
			generation: generation({
				model_mode: 'xl-sft',
				seed: 48113,
				generation_params: {
					inference_steps: 50,
					guidance_scale: 7.5,
					infer_method: 'sde',
					sampler_mode: 'heun',
					use_adg: true,
					lm_temperature: 0.85,
					thinking: true,
					lm_negative_prompt: 'noise',
					bpm: 128,
					audio_duration: 195,
					key_scale: 'Am',
					cover_noise_strength: 0.4
				}
			}),
			song: song({ album_id: 'a-local', album_title: 'Local Album', vocal_language: 'en' }),
			groups: [
				{
					label: 'Model & Sampling',
					entries: [
						{ label: 'Model', value: 'xl-sft' },
						{ label: words['paramField.inferenceSteps'], value: '50' },
						{ label: words['paramField.guidanceScale'], value: '7.5' },
						{ label: words['paramField.inferMethod'], value: 'sde' },
						{ label: words['paramField.sampler'], value: 'heun' },
						{ label: words['paramField.adaptiveDualGuidance'], value: 'On' },
						{ label: words['paramField.temperature'], value: '0.85' },
						{ label: words['paramField.thinking'], value: 'On' },
						{ label: words['paramField.negativePrompt'], value: 'noise' }
					]
				},
				{ label: 'Reproducibility', entries: [{ label: 'Seed', value: '48113' }] },
				{
					label: 'Version',
					entries: [
						{ label: 'BPM', value: '128' },
						{ label: 'Duration', value: '3:15' },
						{ label: 'Key', value: 'Am' },
						{ label: 'Language', value: 'en' }
					]
				},
				{
					label: 'Other',
					entries: [{ label: 'Cover Noise Strength', value: '0.4' }]
				}
			]
		},
		{
			name: 'a sparse take that carries only its model',
			generation: generation({ seed: null, model_mode: 'turbo' }),
			song: song({ album_id: 'a-local', album_title: 'Local Album', vocal_language: '' }),
			groups: [{ label: 'Model & Sampling', entries: [{ label: 'Model', value: 'turbo' }] }]
		},
		{
			name: 'a take with nothing set at all',
			generation: generation({ seed: null, model_mode: '' }),
			song: song({ album_id: 'a-local', album_title: 'Local Album', vocal_language: '' }),
			groups: []
		}
	])('groups $name', async ({ generation: gen, song: s, groups }) => {
		const buildTakeRecipe = await importBuildTakeRecipe();
		expect(buildTakeRecipe(gen, s)).toEqual(groups);
	});
});

describe('buildTakeRecipe reading the shared param registry', () => {
	// The registry — not this file — decides which generation_params keys are
	// known and what they're called. Adding a fake entry to the registry and
	// re-importing without touching recipe-summary.ts proves the label came
	// from the registry, not from a second list living here.
	it('shows a param the registry newly knows about, unlabeled by this file', async () => {
		vi.resetModules();
		vi.doMock('#lib/constants/acestep-param-fields.ts', async (importOriginal) => {
			const actual =
				await importOriginal<typeof import('#lib/constants/acestep-param-fields.ts')>();
			return {
				...actual,
				DIT_NUMBER_FIELDS: [
					...actual.DIT_NUMBER_FIELDS,
					{
						key: 'chroma_alignment',
						labelKey: 'paramField.latentRescale',
						min: 0,
						max: 20,
						step: 0.5
					}
				]
			};
		});

		const buildTakeRecipe = await importBuildTakeRecipe();
		const groups = buildTakeRecipe(
			generation({
				seed: null,
				model_mode: '',
				generation_params: {
					chroma_alignment: 4.2
				} as unknown as GenerationItem['generation_params']
			}),
			song({ album_id: 'a-local', album_title: 'Local Album', vocal_language: '' })
		);

		expect(groups).toEqual([
			{
				label: 'Model & Sampling',
				entries: [{ label: words['paramField.latentRescale'], value: '4.2' }]
			}
		]);

		vi.doUnmock('#lib/constants/acestep-param-fields.ts');
		vi.resetModules();
	});

	it('falls back an unknown generation_params key to Other', async () => {
		const buildTakeRecipe = await importBuildTakeRecipe();
		const groups = buildTakeRecipe(
			generation({
				seed: null,
				model_mode: '',
				generation_params: { repaint_wav_crossfade_sec: 0.25 }
			}),
			song({ album_id: 'a-local', album_title: 'Local Album', vocal_language: '' })
		);
		expect(groups).toEqual([
			{ label: 'Other', entries: [{ label: 'Repaint Wav Crossfade Sec', value: '0.25' }] }
		]);
	});

	it('renders textual generation parameters as their stored values', async () => {
		const buildTakeRecipe = await importBuildTakeRecipe();
		const groups = buildTakeRecipe(
			generation({
				seed: null,
				model_mode: '',
				generation_params: {
					timesteps: '1000,500,0',
					task_type: 'repaint'
				}
			}),
			song({ album_id: 'a-local', album_title: 'Local Album', vocal_language: '' })
		);
		expect(groups).toEqual([
			{
				label: 'Other',
				entries: [
					{ label: 'Timesteps', value: '1000,500,0' },
					{ label: 'Task Type', value: 'repaint' }
				]
			}
		]);
	});
});

describe('buildTakeRecipe deduplicating what the take already shows', () => {
	it('does not repeat acestep_model under Other — it is the Model row shown already', async () => {
		const buildTakeRecipe = await importBuildTakeRecipe();
		const groups = buildTakeRecipe(
			generation({
				seed: null,
				model_mode: 'xl-sft',
				generation_params: { acestep_model: 'xl-sft' }
			}),
			song({ album_id: 'a-local', album_title: 'Local Album', vocal_language: '' })
		);
		expect(groups).toEqual([
			{ label: 'Model & Sampling', entries: [{ label: 'Model', value: 'xl-sft' }] }
		]);
	});

	it.each([
		{
			name: 'matches the stored seed_value',
			seed: 48113,
			requestedSeed: 48113,
			reproducibilityEntries: [{ label: 'Seed', value: '48113' }]
		},
		{
			name: 'diverges from the stored seed_value',
			seed: 48113,
			requestedSeed: -1,
			reproducibilityEntries: [
				{ label: 'Seed', value: '48113' },
				{ label: 'Requested Seed', value: '-1' }
			]
		}
	])(
		'shows a requested seed only when it $name',
		async ({ seed, requestedSeed, reproducibilityEntries }) => {
			const buildTakeRecipe = await importBuildTakeRecipe();
			const groups = buildTakeRecipe(
				generation({ model_mode: '', seed, generation_params: { seed: requestedSeed } }),
				song({ album_id: 'a-local', album_title: 'Local Album', vocal_language: '' })
			);
			expect(groups).toEqual([{ label: 'Reproducibility', entries: reproducibilityEntries }]);
		}
	);

	it('shows a VRAM-guard batch reduction next to Batch Size, not under Other', async () => {
		const buildTakeRecipe = await importBuildTakeRecipe();
		const groups = buildTakeRecipe(
			generation({
				seed: null,
				model_mode: '',
				generation_params: { batch_size: 2, delivered_batch_size: 1 }
			}),
			song({ album_id: 'a-local', album_title: 'Local Album', vocal_language: '' })
		);
		expect(groups).toEqual([
			{
				label: 'Model & Sampling',
				entries: [
					{ label: words['paramField.batchSize'], value: '2' },
					{ label: 'Delivered Batch Size', value: '1' }
				]
			}
		]);
	});

	it('shows no Delivered Batch Size row when the take carries none', async () => {
		const buildTakeRecipe = await importBuildTakeRecipe();
		const groups = buildTakeRecipe(
			generation({ seed: null, model_mode: '', generation_params: { batch_size: 2 } }),
			song({ album_id: 'a-local', album_title: 'Local Album', vocal_language: '' })
		);
		expect(groups).toEqual([
			{ label: 'Model & Sampling', entries: [{ label: words['paramField.batchSize'], value: '2' }] }
		]);
	});
});

describe('buildTakeRecipe reference', () => {
	const buildRecipe = async (reference: GenerationItem['reference']) => {
		const buildTakeRecipe = await importBuildTakeRecipe();
		return buildTakeRecipe(
			generation({ seed: null, model_mode: '', generation_params: {}, reference }),
			song({ album_id: 'a-local', album_title: 'Local Album', vocal_language: '' })
		);
	};

	it('shows the linked reference by its filename in the Version group', async () => {
		const groups = await buildRecipe({ id: 'r1', filename: 'demo take.wav' });
		expect(groups).toEqual([
			{
				label: 'Version',
				entries: [
					{
						label: words['referencePicker.label'],
						value: 'demo take.wav',
						link: { route: '/settings/references', query: { reference: 'r1' } }
					}
				]
			}
		]);
	});

	it.each([
		{ name: 'a null reference', reference: null },
		{ name: 'no reference', reference: undefined }
	])('shows no reference row for $name', async ({ reference }) => {
		expect(await buildRecipe(reference)).toEqual([]);
	});
});
