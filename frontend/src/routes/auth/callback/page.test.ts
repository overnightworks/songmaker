import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import Page from './+page.svelte';

let component: ReturnType<typeof mount> | undefined;

afterEach(async () => {
	if (component) await unmount(component);
	component = undefined;
	document.body.replaceChildren();
});

describe('failed sign-in page', () => {
	it('tells the failure and offers one way on, a new sign-in start', async () => {
		const target = document.createElement('div');
		document.body.append(target);
		component = mount(Page, { target });
		await tick();

		expect(target.querySelector('h1')?.textContent).toBe('Login failed');
		expect(target.querySelector('[role="alert"]')?.textContent?.trim()).toBe(
			'Sign-in did not work. Please try again.'
		);
		const retry = Array.from(target.querySelectorAll('a')).find(
			(link) => link.textContent?.trim() === 'Try again'
		);
		expect(retry?.getAttribute('href')).toBe('/login/oidc');
		expect(retry?.hasAttribute('data-sveltekit-reload')).toBe(true);
	});
});
