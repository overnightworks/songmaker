import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { get } from 'svelte/store';

import { RAIL_SEARCH_LABEL } from '$lib/constants';
import { railTreeQuery } from '$lib/stores/filter';
import { createComponentMount, requireElement } from './rail-test-fixtures';
import RailSearch from './RailSearch.svelte';

const { render, cleanup } = createComponentMount(RailSearch);

beforeEach(() => railTreeQuery.set(''));
afterEach(async () => {
	railTreeQuery.set('');
	await cleanup();
});

describe('RailSearch', () => {
	it('updates the transient rail query as the person types', async () => {
		const root = await render();
		const input = requireElement<HTMLInputElement>(root, 'input');

		input.value = 'stadion';
		input.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();

		expect(input.getAttribute('aria-label')).toBe(RAIL_SEARCH_LABEL);
		expect(get(railTreeQuery)).toBe('stadion');
	});

	it('clears the query on Escape without submitting a form', async () => {
		railTreeQuery.set('stadion');
		const root = await render();
		const input = requireElement<HTMLInputElement>(root, 'input');
		const escape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });

		input.dispatchEvent(escape);
		await tick();

		expect(escape.defaultPrevented).toBe(true);
		expect(input.value).toBe('');
		expect(get(railTreeQuery)).toBe('');
		expect(root.querySelector('form')).toBeNull();
	});
});
