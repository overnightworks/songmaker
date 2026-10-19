import { mount, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import Page from './+page.svelte';

let component: ReturnType<typeof mount> | undefined;

afterEach(() => {
	if (component) unmount(component);
	component = undefined;
	document.body.replaceChildren();
});

describe('the privacy notice address', () => {
	it.each(['', '#hopin'])('shows the privacy notice whatever the hash %j', (hash) => {
		history.replaceState(null, '', `/datenschutz${hash}`);
		component = mount(Page, { target: document.body });

		expect(document.querySelector('h1')?.textContent).toBe('Datenschutzerklärung');
		expect(document.querySelector('#impressum')).toBeNull();
	});
});
