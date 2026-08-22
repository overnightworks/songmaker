import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Breadcrumb from './Breadcrumb.svelte';

let component: ReturnType<typeof mount> | undefined;
let target: HTMLDivElement;

afterEach(async () => {
	if (component) await unmount(component);
	component = undefined;
	document.body.replaceChildren();
});

async function render(items: { label: string; onclick?: () => void }[]): Promise<HTMLElement> {
	target = document.createElement('div');
	document.body.append(target);
	component = mount(Breadcrumb, { target, props: { items } });
	await tick();
	return target;
}

describe('Breadcrumb', () => {
	it('renders every level as a labeled crumb', async () => {
		const root = await render([
			{ label: 'Library', onclick: vi.fn() },
			{ label: 'Sommerlicht', onclick: vi.fn() },
			{ label: 'Track 2 of 3' }
		]);
		const crumbs = Array.from(root.querySelectorAll('.crumb')).map((el) => el.textContent);
		expect(crumbs).toEqual(['Library', 'Sommerlicht', 'Track 2 of 3']);
	});

	it('marks only the last crumb as the current page', async () => {
		const root = await render([{ label: 'Library', onclick: vi.fn() }, { label: 'Album' }]);
		expect(root.querySelector('.crumb[aria-current="page"]')?.textContent).toBe('Album');
		expect(root.querySelectorAll('[aria-current="page"]')).toHaveLength(1);
	});

	it('calls onclick when a linked crumb is clicked', async () => {
		const onLibrary = vi.fn();
		const root = await render([{ label: 'Library', onclick: onLibrary }, { label: 'Album' }]);
		root.querySelector<HTMLButtonElement>('.crumb-link')?.click();
		expect(onLibrary).toHaveBeenCalledOnce();
	});

	it('renders a crumb with no onclick as static text, not a button', async () => {
		const root = await render([{ label: 'Library' }, { label: 'Album', onclick: vi.fn() }]);
		expect(root.querySelector('.crumb')?.tagName).toBe('SPAN');
	});
});
