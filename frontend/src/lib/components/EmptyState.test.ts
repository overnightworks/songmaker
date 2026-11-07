import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import EmptyState from './EmptyState.svelte';

let mounted: ReturnType<typeof mount> | undefined;

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
});

async function mountEmptyState(icon: string, text: string): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(EmptyState, { target, props: { icon, text } });
	await tick();
	const root = target.querySelector<HTMLElement>('.empty');
	if (!root) throw new Error('Expected the empty state');
	return root;
}

describe('EmptyState', () => {
	it('shows its glyph above its one line of text', async () => {
		const root = await mountEmptyState('library', 'Nothing here yet.');
		expect(root.textContent).toBe('Nothing here yet.');
		const glyph = root.querySelector('svg');
		const line = root.querySelector('p');
		if (!glyph || !line) throw new Error('Expected a glyph and a line');
		expect(glyph.compareDocumentPosition(line) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
	});

	it('hides its glyph from assistive technology', async () => {
		const root = await mountEmptyState('library', 'Nothing here yet.');
		expect(root.querySelector('svg')?.closest('[aria-hidden="true"]')).not.toBeNull();
	});
});
