import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import { APP_NAME } from '#lib/constants.ts';
import { LEGAL_SECTIONS } from '#lib/constants/legal.ts';
import Page from './+page.svelte';

let component: ReturnType<typeof mount> | undefined;

function renderPage(): HTMLElement {
	const target = document.createElement('div');
	document.body.append(target);
	component = mount(Page, { target });
	return target;
}

afterEach(async () => {
	if (component) await unmount(component);
	component = undefined;
	document.body.replaceChildren();
});

describe('signed-out page', () => {
	it('says the person is logged out and offers one way on, the sign-in start', async () => {
		const target = renderPage();
		await tick();

		expect(target.querySelector('h1')?.textContent).toBe('You are logged out.');
		const actions = Array.from(target.querySelectorAll('a, button')).filter(
			(action) => !action.closest('nav')
		);
		expect(actions.map((action) => action.textContent?.trim())).toEqual(['Log in']);
		expect(actions[0].getAttribute('href')).toBe('/login/oidc');
	});

	it('leaves the router out of the sign-in start, which the server answers with a redirect', async () => {
		const target = renderPage();
		await tick();

		expect(
			target.querySelector('a[href="/login/oidc"]')?.hasAttribute('data-sveltekit-reload')
		).toBe(true);
	});

	it('shows no failure', async () => {
		const target = renderPage();
		await tick();

		expect(target.querySelector('[role="alert"]')).toBeNull();
	});

	it('names the tab after the app, not the shared song the listener came from', async () => {
		document.title = 'Neon Tide — Mara Lind | Hallucinai';
		renderPage();
		await tick();

		expect(document.title).toBe(APP_NAME);
	});

	it('links every legal text the shared pages link', async () => {
		const target = renderPage();
		await tick();

		expect(Array.from(target.querySelectorAll('nav a')).map((a) => a.textContent)).toEqual(
			LEGAL_SECTIONS.map((section) => section.label)
		);
	});
});
