import { createRawSnippet, mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';

import SettingsLayout from './+layout.svelte';

let mounted: ReturnType<typeof mount> | undefined;
const children = createRawSnippet(() => ({
	render: () => `<div data-settings-child="true"></div>`
}));

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
});

describe('settings layout', () => {
	it('renders its page inside a single main landmark, without a second navigation column', async () => {
		const target = document.createElement('div');
		document.body.append(target);
		mounted = mount(SettingsLayout, { target, props: { children } });
		await tick();

		const main = target.querySelector('main.settings-content');
		expect(main).not.toBeNull();
		expect(main?.querySelector('[data-settings-child="true"]')).not.toBeNull();
		expect(target.querySelectorAll('nav')).toHaveLength(0);
		expect(target.querySelector('select')).toBeNull();
	});
});
