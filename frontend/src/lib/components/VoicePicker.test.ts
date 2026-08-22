import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const listLoras = vi.fn();

vi.mock('$lib/api/loras', () => ({
	listLoras: (...args: unknown[]) => listLoras(...args)
}));

import { loras } from '$lib/stores/loras';
import VoicePicker from './VoicePicker.svelte';

let mounted: ReturnType<typeof mount> | undefined;

beforeEach(() => {
	listLoras.mockReset().mockResolvedValue([]);
	loras.set([]);
});

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
});

async function render(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(VoicePicker, { target });
	await tick();
	await Promise.resolve();
	await tick();
	return target;
}

describe('VoicePicker', () => {
	it('links "Create a voice" to the Settings Voices route', async () => {
		const target = await render();
		const hint = target.querySelector<HTMLAnchorElement>('.hint');
		expect(hint?.getAttribute('href')).toBe('/settings/voices');
	});
});
