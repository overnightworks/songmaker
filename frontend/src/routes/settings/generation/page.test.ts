import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { AuthUser, PresetItem } from '#lib/api/types.ts';
import { currentUser } from '#lib/stores/auth.ts';
import { listenForGlobalEscape } from '#lib/test-utils/global-escape.ts';
import { makeAuthUser } from '#lib/test-utils/factories.ts';
import { words } from '#lib/words/en.ts';

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
let stopListeningForEscape: () => void = () => undefined;

interface OpenedPage {
	target: HTMLElement;
	requested: string[];
	savedPresets: PresetItem[];
	deleted: string[];
}

interface StubbedApi {
	requested: string[];
	savedPresets: PresetItem[];
	deleted: string[];
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
	const deleted: string[] = [];
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
			if (init?.method === 'DELETE') {
				deleted.push(path);
				return new Response(JSON.stringify({ status: 'ok' }), { status: 200 });
			}
			if (path === DEFAULT_CONFIG_PATH && init?.method === 'PUT') {
				return new Response(String(init.body), { status: 200 });
			}
			return new Response(JSON.stringify(responses[path]), { status: 200 });
		})
	);
	return { requested, savedPresets, deleted };
}

async function openPageAs(
	user: AuthUser,
	failing: ReadonlySet<string> = new Set(),
	responses: Record<string, unknown> = RESPONSES
): Promise<OpenedPage> {
	currentUser.set(user);
	const { requested, savedPresets, deleted } = stubApi(failing, responses);
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(GenerationSettingsPage, { target });
	await tick();
	await vi.waitFor(() => expect(requested).toContain('/api/settings/default-config'));
	return { target, requested, savedPresets, deleted };
}

afterEach(async () => {
	stopListeningForEscape();
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
			expect(target.querySelector('.error')?.textContent).toBe(
				words['generationPage.loadDefaultsFailed']
			)
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
			expect(target.querySelector(`[id="${labelId}"]`)?.textContent).toBe(
				words['generationPage.defaultHeading']
			);
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

	describe('deleting a preset', () => {
		const PRESET_ID = 'doomed';
		const DELETE_PATH = `${PRESETS_PATH}/${PRESET_ID}`;

		async function openWithOnePreset(): Promise<{
			target: HTMLElement;
			deleted: string[];
			rowDelete: HTMLButtonElement;
		}> {
			const preset: PresetItem = {
				...savedPreset(
					JSON.stringify({ name: 'Warm', model_mode: MODEL, params: {}, is_default: false })
				),
				id: PRESET_ID
			};
			const { target, deleted } = await openPageAs(makeAuthUser(), new Set(), {
				...RESPONSES,
				[PRESETS_PATH]: [preset]
			});
			const rowDelete = await vi.waitFor(() => {
				const button = target.querySelector<HTMLButtonElement>('.preset-action.delete');
				if (!button) throw new Error('no delete button yet');
				return button;
			});
			rowDelete.focus();
			rowDelete.click();
			await tick();
			return { target, deleted, rowDelete };
		}

		const dialogButton = (label: string): HTMLButtonElement => {
			const found = [
				...document.querySelectorAll<HTMLButtonElement>('[role="dialog"] button')
			].find((button) => button.textContent?.trim() === label);
			if (!found) throw new Error(`no ${label} button`);
			return found;
		};

		it('asks first with the preset name and sends no delete', async () => {
			const { deleted } = await openWithOnePreset();

			expect(document.querySelector('[role="dialog"] h3')?.textContent).toBe('Delete preset?');
			expect(document.querySelector('[role="dialog"] li')?.textContent).toBe('Warm');
			expect(deleted).toEqual([]);
		});

		it.each([
			['Cancel', () => dialogButton('Cancel').click()],
			[
				'Escape',
				() =>
					dialogButton('Cancel').dispatchEvent(
						new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })
					)
			]
		])('keeps the preset and returns focus to its delete button on %s', async (_how, close) => {
			stopListeningForEscape = listenForGlobalEscape();
			const { target, deleted, rowDelete } = await openWithOnePreset();

			close();
			await tick();

			expect(document.querySelector('[role="dialog"]')).toBeNull();
			expect(deleted).toEqual([]);
			expect(target.querySelector('.preset-name')?.textContent).toBe('Warm');
			expect(document.activeElement).toBe(rowDelete);
		});

		it('deletes the preset and drops its row only on Delete', async () => {
			const { target, deleted } = await openWithOnePreset();

			dialogButton('Delete').click();

			await vi.waitFor(() => expect(deleted).toEqual([DELETE_PATH]));
			await vi.waitFor(() => expect(target.querySelector('.preset-name')).toBeNull());
		});
	});
});
