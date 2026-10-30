import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import {
	SIGN_IN_FAILED_HEADING,
	SIGN_IN_FAILED_MESSAGE,
	SIGN_IN_RETRY_LABEL
} from '#lib/constants/auth.ts';
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

		expect(target.querySelector('h1')?.textContent).toBe(SIGN_IN_FAILED_HEADING);
		expect(target.querySelector('[role="alert"]')?.textContent?.trim()).toBe(
			SIGN_IN_FAILED_MESSAGE
		);
		const actions = Array.from(target.querySelectorAll('.actions a, .actions button'));
		expect(actions.map((action) => action.textContent?.trim())).toEqual([SIGN_IN_RETRY_LABEL]);
		expect(actions[0].getAttribute('href')).toBe('/login/oidc');
		expect(actions[0].hasAttribute('data-sveltekit-reload')).toBe(true);
	});
});
