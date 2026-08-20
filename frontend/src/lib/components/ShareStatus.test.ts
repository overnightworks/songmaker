import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import ShareStatus from './ShareStatus.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

interface ShareStatusProps {
	kind: 'loading' | 'missing' | 'error';
	resource: string;
	onretry?: () => void;
}

function render(props: ShareStatusProps) {
	const target = document.createElement('div');
	document.body.appendChild(target);
	const component = mount(ShareStatus, { target, props });
	mounted.push(component);
	return target;
}

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
});

describe('ShareStatus', () => {
	it('names a missing resource, focuses the state, and offers one way out', async () => {
		const target = render({ kind: 'missing', resource: 'playlist' });
		await tick();
		const heading = target.querySelector('h1');
		expect(heading?.textContent).toBe('Playlist not found');
		expect(document.activeElement).toBe(heading);
		expect(target.querySelector('.status-mark.missing')).not.toBeNull();
		const links = target.querySelectorAll('a');
		expect(links).toHaveLength(1);
		expect(links[0].textContent).toBe('Open Hallucinai');
		expect(links[0].getAttribute('href')).toBe('/login');
	});

	it('offers retry plus a secondary exit for a technical error', async () => {
		const onretry = vi.fn();
		const target = render({ kind: 'error', resource: 'song', onretry });
		await tick();
		expect(target.querySelector('h1')?.textContent).toBe('Could not load this song');
		expect(target.querySelector('.status-mark.error')).not.toBeNull();
		const retry = target.querySelector('button');
		expect(retry?.textContent).toBe('Try again');
		retry?.click();
		expect(onretry).toHaveBeenCalledOnce();
		expect(target.querySelectorAll('a')).toHaveLength(1);
	});

	it('marks loading as busy without recovery actions', async () => {
		const target = render({ kind: 'loading', resource: 'album' });
		await tick();
		expect(target.querySelector('section')?.getAttribute('aria-busy')).toBe('true');
		expect(target.querySelector('.status-mark.loading')).not.toBeNull();
		expect(target.querySelector('a, button')).toBeNull();
	});
});
