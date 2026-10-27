import { createRawSnippet, mount, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { CowriterOfferResponse } from '$lib/api/types';
import { signInAddress } from '$lib/api/fetch';

const api = vi.hoisted(() => ({ fetchCowriterOffer: vi.fn() }));
vi.mock('$lib/api/client', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/client')>()),
	...api
}));

import ModelsCowriterRow from './ModelsCowriterRow.svelte';

const mounted: ReturnType<typeof mount>[] = [];

beforeEach(() => {
	api.fetchCowriterOffer.mockReset();
});

afterEach(() => {
	for (const component of mounted.splice(0)) unmount(component);
	document.body.innerHTML = '';
});

function offerOf(state: CowriterOfferResponse['state'], model = 'opus'): CowriterOfferResponse {
	return { state, model };
}

function renderRow(): HTMLElement {
	const target = document.createElement('div');
	document.body.appendChild(target);
	const advanced = createRawSnippet(() => ({ render: () => '<span>24000</span>' }));
	mounted.push(mount(ModelsCowriterRow, { target, props: { model: 'page-model', advanced } }));
	return target;
}

function rowText(target: HTMLElement): string {
	return (target.querySelector('.tt-row')?.textContent ?? '').replace(/\s+/g, ' ').trim();
}

async function settledRow(offer: CowriterOfferResponse | Error): Promise<HTMLElement> {
	if (offer instanceof Error) api.fetchCowriterOffer.mockRejectedValue(offer);
	else api.fetchCowriterOffer.mockResolvedValue(offer);
	const target = renderRow();
	await vi.waitFor(() => expect(rowText(target)).not.toContain('Checking…'));
	return target;
}

describe('M12 while the offer loads', () => {
	it('shows the pages model as text and Checking, with no light', () => {
		api.fetchCowriterOffer.mockReturnValue(new Promise(() => {}));

		const target = renderRow();

		expect(rowText(target)).toBe(
			'Co-Writer Provider Claude Route Agent service Model page-model Status ○Checking…'
		);
		expect(target.querySelector('.st.ok, .st .mark')?.textContent).not.toBe('✓');
		expect(target.querySelector('.st.ok')).toBeNull();
	});
});

describe('the answered offer', () => {
	it('M1 says opus is ready, with the check mark', async () => {
		const target = await settledRow(offerOf('ready'));

		expect(rowText(target)).toBe(
			'Co-Writer Provider Claude Route Agent service Model opus Status ✓Ready'
		);
		expect(target.querySelector('.st')?.classList.contains('ok')).toBe(true);
	});

	it('A9 shows the model the offer route names, not the pages', async () => {
		const target = await settledRow(offerOf('ready', 'sonnet'));

		expect(rowText(target)).toContain('Model sonnet');
		expect(rowText(target)).not.toContain('page-model');
	});

	it('M2 says not set up in the service in grey, without a check mark', async () => {
		const target = await settledRow(offerOf('not_built'));

		expect(rowText(target)).toContain('Not set up in the service');
		expect(rowText(target)).not.toContain('✓');
		expect(rowText(target)).not.toContain('not_built');
		expect(target.querySelector('.st')?.classList.contains('off')).toBe(true);
	});

	it('M3 warns under the model that it is no longer offered and leaves the status empty', async () => {
		const target = await settledRow(offerOf('no_longer_offered'));

		expect(target.querySelector('.why.warn')?.textContent).toBe(
			'No longer offered by the agent service'
		);
		expect(target.querySelector('.st')).toBeNull();
		expect(rowText(target)).not.toContain('✓');
	});

	it('M8 says not available for you in grey', async () => {
		const target = await settledRow(offerOf('not_available'));

		expect(rowText(target)).toContain('Not available for you');
		expect(target.querySelector('.st')?.classList.contains('off')).toBe(true);
	});

	it.each([
		{ name: 'M6 says the state', answer: offerOf('not_reachable'), shown: 'opus' },
		{
			name: 'A2 a failed request to songmaker says the same',
			answer: new Error('network'),
			shown: 'page-model'
		}
	])('$name: the offer is not reachable, no light, not red', async ({ answer, shown }) => {
		const target = await settledRow(answer);

		expect(rowText(target)).toBe(
			`Co-Writer Provider Claude Route Agent service Model ${shown} Status The agent service's offer is not reachable`
		);
		expect(target.querySelector('.st .mark')).toBeNull();
		expect(target.querySelector('.st')?.classList.contains('plain')).toBe(true);
	});

	it('M10 asks to sign in again with a link back to the Models tab', async () => {
		const target = await settledRow(offerOf('sign_in_again'));

		expect(rowText(target)).toContain('Sign in again to check the offer');
		const link = target.querySelector<HTMLAnchorElement>('.st a');
		expect(link?.getAttribute('href')).toBe(signInAddress('/settings/users?tab=models'));
		expect(rowText(target)).not.toContain('✓');
	});
});

describe('the rest of the row', () => {
	it('A1 reads the offer once per opening', async () => {
		await settledRow(offerOf('ready'));

		expect(api.fetchCowriterOffer).toHaveBeenCalledTimes(1);
	});

	it('A8 keeps the not selectable note and the history tail under Advanced', async () => {
		const target = await settledRow(offerOf('ready'));

		expect(target.querySelector('.note')?.textContent).toBe('Grok, Codex: not selectable yet');
		expect(target.querySelector('details summary')?.textContent).toBe('Advanced');
		expect(target.querySelector('details')?.textContent).toContain('24000');
	});

	it('A8 offers nothing to choose', async () => {
		const target = await settledRow(offerOf('ready'));

		expect(target.querySelector('select, input, button, [role="group"]')).toBeNull();
	});
});
