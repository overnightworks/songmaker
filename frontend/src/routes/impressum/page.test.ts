import { mount, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import Page from './+page.svelte';

let component: ReturnType<typeof mount> | undefined;

afterEach(() => {
	if (component) unmount(component);
	component = undefined;
	document.body.replaceChildren();
});

describe('the imprint address', () => {
	it.each(['', '#hopin'])('shows the imprint whatever the hash %j', (hash) => {
		history.replaceState(null, '', `/impressum${hash}`);
		component = mount(Page, { target: document.body });

		expect(document.querySelector('h1')?.textContent).toBe('Impressum');
		expect(document.querySelector('#datenschutz')).toBeNull();
	});
});
