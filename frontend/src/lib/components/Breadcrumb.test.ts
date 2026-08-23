import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Breadcrumb from './Breadcrumb.svelte';
import breadcrumbSource from './Breadcrumb.svelte?raw';
import { clearComponentStyles, injectComponentStyles } from '$lib/test-utils/component-styles';
import { clearHitboxStyles, injectHitboxStyles, minSquarePx } from '$lib/test-utils/hitbox';
import { HITBOX_COMPACT_PX } from '$lib/constants';

let component: ReturnType<typeof mount> | undefined;
let target: HTMLDivElement;

afterEach(async () => {
	if (component) await unmount(component);
	component = undefined;
	document.body.replaceChildren();
	clearComponentStyles();
	clearHitboxStyles();
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

	// The trail's own stylesheet has to out-rank the global hitbox sheet, which
	// pins every `frequent` target, so these read the values out of the real
	// cascade rather than out of the source. jsdom still computes no layout;
	// the browser gate on #185 shows the trail beside a docked Now Playing.
	async function renderStyledTrail(): Promise<HTMLElement> {
		injectHitboxStyles();
		const root = await render([
			{ label: 'Sommerlicht', onclick: vi.fn() },
			{ label: 'Track 2 of 3' }
		]);
		const scoped = root.querySelector('.crumb');
		if (!scoped) throw new Error('no crumb rendered');
		injectComponentStyles(breadcrumbSource, 'Breadcrumb.svelte', scoped);
		return root;
	}

	it('yields a linked crumb faster than the current crumb the reader needs', async () => {
		const root = await renderStyledTrail();
		const link = root.querySelector('.crumb-link');
		if (!link) throw new Error('no linked crumb rendered');
		// Pinned at 0 by the hitbox sheet, a link took the whole trail; at the
		// default 1 it still takes its proportional share of it.
		expect(Number(getComputedStyle(link).flexShrink)).toBeGreaterThan(1);
	});

	it('stops a shrinking link at the touch target that keeps it clickable', async () => {
		const root = await renderStyledTrail();
		const link = root.querySelector('.crumb-link');
		if (!link) throw new Error('no linked crumb rendered');
		expect(minSquarePx(link, 'crumb link').width).toBe(HITBOX_COMPACT_PX);
	});

	it('never shrinks the current crumb, capping its width instead', async () => {
		const root = await renderStyledTrail();
		const current = root.querySelector('.crumb-current');
		if (!current) throw new Error('no current crumb rendered');
		const style = getComputedStyle(current);
		expect(Number(style.flexShrink)).toBe(0);
		expect(style.maxWidth).toBe('60%');
	});

	it('ellipsizes every crumb label in a block of its own', async () => {
		const root = await renderStyledTrail();
		const labels = Array.from(root.querySelectorAll('.crumb-label'));
		expect(labels).toHaveLength(2);
		for (const label of labels) {
			const style = getComputedStyle(label);
			expect([style.display, style.overflow, style.textOverflow]).toEqual([
				'block',
				'hidden',
				'ellipsis'
			]);
		}
	});
});
