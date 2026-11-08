import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import BusyState from './BusyState.svelte';

let mounted: ReturnType<typeof mount> | undefined;

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
});

async function mountBusyState(text: string): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(BusyState, { target, props: { text } });
	await tick();
	const root = target.querySelector<HTMLElement>('[role="status"]');
	if (!root) throw new Error('Expected the busy state');
	return root;
}

describe('BusyState', () => {
	it('shows its ring above its one line of text', async () => {
		const root = await mountBusyState('Working...');
		const ring = root.firstElementChild;
		const line = root.querySelector('p');
		if (!ring || !line) throw new Error('Expected a ring and a line');
		expect(ring.compareDocumentPosition(line) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
	});

	it('is a status whose accessible name is its line', async () => {
		const root = await mountBusyState('Working...');
		expect(root.getAttribute('role')).toBe('status');
		expect(root).toHaveAccessibleName('Working...');
	});

	it('gives two instances each their own name target', async () => {
		const first = await mountBusyState('One');
		const second = await mountBusyState('Two');
		expect(first.getAttribute('aria-labelledby')).not.toBe(second.getAttribute('aria-labelledby'));
	});

	it('hides its ring from assistive technology', async () => {
		const root = await mountBusyState('Working...');
		expect(root.firstElementChild?.getAttribute('aria-hidden')).toBe('true');
	});
});
