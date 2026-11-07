import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { AuthUser, PresetItem } from '#lib/api/types.ts';
import { currentUser } from '#lib/stores/auth.ts';
import { makeAuthUser } from '#lib/test-utils/factories.ts';

import GenerationSettingsPage from './+page.svelte';

const INSTANCE_DEFAULTS_PATH = '/api/settings/generation-defaults';
const PRESETS_PATH = '/api/settings/presets';
const MODEL = 'turbo';

const DEFAULT_CONFIG_PATH = '/api/settings/default-config';

const RESPONSES: Record<string, unknown> = {
	[PRESETS_PATH]: [],
	'/api/settings/generation-builtins': { [MODEL]: { inference_steps: 8, guidance_scale: 7 } },
	'/api/settings/models': [{ id: MODEL, is_active: true }],
	[DEFAULT_CONFIG_PATH]: { config: null },
	[INSTANCE_DEFAULTS_PATH]: { [MODEL]: { inference_steps: 20, shift: 3 } }
};

let mounted: ReturnType<typeof mount> | undefined;

interface OpenedPage {
	target: HTMLElement;
	requested: string[];
	savedPresets: PresetItem[];
}

interface StubbedApi {
	requested: string[];
	savedPresets: PresetItem[];
}

function savedPreset(body: string): PresetItem {
	const { name, model_mode, params, is_default } = JSON.parse(body);
	return {
		id: 'p1',
		name,
		model_mode,
		params,
		is_default,
		is_shared: false,
		created_at: '2026-10-01T00:00:00Z',
		updated_at: '2026-10-01T00:00:00Z'
	};
}

function stubApi(
	failing: ReadonlySet<string>,
	responses: Record<string, unknown> = RESPONSES
): StubbedApi {
	const requested: string[] = [];
	const savedPresets: PresetItem[] = [];
	vi.stubGlobal(
		'fetch',
		vi.fn(async (path: string, init?: RequestInit) => {
			requested.push(path);
			if (failing.has(path)) return new Response('{}', { status: 500 });
			if (path === PRESETS_PATH && init?.method === 'POST') {
				const preset = savedPreset(String(init.body));
				savedPresets.push(preset);
				return new Response(JSON.stringify(preset), { status: 201 });
			}
			if (path === DEFAULT_CONFIG_PATH && init?.method === 'PUT') {
				return new Response(String(init.body), { status: 200 });
			}
			return new Response(JSON.stringify(responses[path]), { status: 200 });
		})
	);
	return { requested, savedPresets };
}

async function openPageAs(
	user: AuthUser,
	failing: ReadonlySet<string> = new Set(),
	responses: Record<string, unknown> = RESPONSES
): Promise<OpenedPage> {
	currentUser.set(user);
	const { requested, savedPresets } = stubApi(failing, responses);
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(GenerationSettingsPage, { target });
	await tick();
	await vi.waitFor(() => expect(requested).toContain('/api/settings/default-config'));
	return { target, requested, savedPresets };
}

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	currentUser.set(null);
	vi.unstubAllGlobals();
});

async function saveNewPreset(target: HTMLElement, name: string): Promise<void> {
	target.querySelector<HTMLButtonElement>('.add-btn')?.click();
	await vi.waitFor(() =>
		expect(target.querySelector<HTMLSelectElement>('.model-select')?.value).toBe(MODEL)
	);
	const nameInput = target.querySelector<HTMLInputElement>('.preset-name-input');
	if (!nameInput) throw new Error('preset form did not open');
	nameInput.value = name;
	nameInput.dispatchEvent(new Event('input', { bubbles: true }));
	await tick();
	target.querySelector<HTMLButtonElement>('.save-btn')?.click();
}

describe('generation settings', () => {
	it.each([
		['a non-admin', makeAuthUser()],
		['an administrator', makeAuthUser({ role: 'admin' })]
	])('reads the instance generation defaults for %s', async (_role, user) => {
		const { requested } = await openPageAs(user);

		expect(requested).toContain(INSTANCE_DEFAULTS_PATH);
	});

	it("a non-admin's preset merges the instance defaults", async () => {
		const { target, savedPresets } = await openPageAs(makeAuthUser());

		await saveNewPreset(target, 'Warm');

		await vi.waitFor(() => expect(savedPresets).toHaveLength(1));
		expect(savedPresets[0]).toMatchObject({
			name: 'Warm',
			model_mode: MODEL,
			params: { inference_steps: 20, guidance_scale: 7, shift: 3 }
		});
	});

	it('tells an administrator when the global generation defaults cannot be read', async () => {
		const { target } = await openPageAs(
			makeAuthUser({ role: 'admin' }),
			new Set([INSTANCE_DEFAULTS_PATH])
		);

		await vi.waitFor(() =>
			expect(target.querySelector('.error')?.textContent).toBe('Failed to load generation defaults')
		);
	});

	describe('the default chooser', () => {
		const presetNamed = (id: string, name: string): PresetItem => ({
			...savedPreset(JSON.stringify({ name, model_mode: MODEL, params: {}, is_default: false })),
			id
		});

		async function openChooserWithDefault(defaultId = 'a'): Promise<{
			chips: () => HTMLElement[];
			checked: () => (string | undefined)[];
		}> {
			const { target } = await openPageAs(makeAuthUser(), new Set(), {
				...RESPONSES,
				[PRESETS_PATH]: [presetNamed('a', 'Warm'), presetNamed('b', 'Bright')],
				[DEFAULT_CONFIG_PATH]: { config: defaultId }
			});
			const group = target.querySelector('[role="radiogroup"]');
			const labelId = group?.getAttribute('aria-labelledby') ?? '';
			expect(target.querySelector(`[id="${labelId}"]`)?.textContent).toBe('Default for New Songs');
			const chips = () => [...(group?.querySelectorAll<HTMLElement>('[role="radio"]') ?? [])];
			const checked = () =>
				chips()
					.filter((chip) => chip.getAttribute('aria-checked') === 'true')
					.map((chip) => chip.textContent?.trim());
			await vi.waitFor(() => expect(chips()).toHaveLength(3));
			return { chips, checked };
		}

		it('checks exactly the current default and moves the check when another is chosen', async () => {
			const { chips, checked } = await openChooserWithDefault();
			await vi.waitFor(() => expect(checked()).toEqual(['Warm']));

			chips()
				.find((chip) => chip.textContent?.trim() === 'Bright')
				?.click();

			await vi.waitFor(() => expect(checked()).toEqual(['Bright']));
		});

		it('moves the check to the next chip on ArrowRight and back on ArrowLeft', async () => {
			const { chips, checked } = await openChooserWithDefault();
			await vi.waitFor(() => expect(checked()).toEqual(['Warm']));

			chips()[1].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
			await vi.waitFor(() => expect(checked()).toEqual(['Bright']));

			chips()[2].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
			await vi.waitFor(() => expect(checked()).toEqual(['Warm']));
		});

		it('keeps the first chip in the tab order when no chip is checked', async () => {
			const { chips, checked } = await openChooserWithDefault('deleted');

			await vi.waitFor(() => expect(checked()).toEqual([]));
			const tabbable = chips().filter((chip) => chip.getAttribute('tabindex') === '0');
			expect(tabbable).toEqual([chips()[0]]);
		});
	});
});
