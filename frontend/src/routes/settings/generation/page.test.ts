import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { PresetItem } from '$lib/api/types';
import { currentUser } from '$lib/stores/auth';

import GenerationSettingsPage from './+page.svelte';

const ADMIN = { id: 'u1', username: 'felix', role: 'admin' as const };
const USER = { id: 'u2', username: 'jane', role: 'user' as const };
const INSTANCE_DEFAULTS_PATH = '/api/settings/generation-defaults';
const PRESETS_PATH = '/api/settings/presets';
const MODEL = 'turbo';

const RESPONSES: Record<string, unknown> = {
	[PRESETS_PATH]: [],
	'/api/settings/generation-builtins': { [MODEL]: { inference_steps: 8, guidance_scale: 7 } },
	'/api/settings/models': [{ id: MODEL, is_active: true }],
	'/api/settings/default-config': { config: null },
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

function stubApi(failing: ReadonlySet<string>): StubbedApi {
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
			return new Response(JSON.stringify(RESPONSES[path]), { status: 200 });
		})
	);
	return { requested, savedPresets };
}

async function openPageAs(
	user: typeof ADMIN | typeof USER,
	failing: ReadonlySet<string> = new Set()
): Promise<OpenedPage> {
	currentUser.set(user);
	const { requested, savedPresets } = stubApi(failing);
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
		['a non-admin', USER],
		['an administrator', ADMIN]
	])('reads the instance generation defaults for %s', async (_role, user) => {
		const { requested } = await openPageAs(user);

		expect(requested).toContain(INSTANCE_DEFAULTS_PATH);
	});

	it("a non-admin's preset merges the instance defaults", async () => {
		const { target, savedPresets } = await openPageAs(USER);

		await saveNewPreset(target, 'Warm');

		await vi.waitFor(() => expect(savedPresets).toHaveLength(1));
		expect(savedPresets[0]).toMatchObject({
			name: 'Warm',
			model_mode: MODEL,
			params: { inference_steps: 20, guidance_scale: 7, shift: 3 }
		});
	});

	it('tells an administrator when the global generation defaults cannot be read', async () => {
		const { target } = await openPageAs(ADMIN, new Set([INSTANCE_DEFAULTS_PATH]));

		await vi.waitFor(() =>
			expect(target.querySelector('.error')?.textContent).toBe('Failed to load generation defaults')
		);
	});
});
