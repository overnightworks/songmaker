import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ALBUM_COVER_EDIT_LABEL } from '$lib/constants';
import { albumCoverMarkedLabel } from '$lib/constants/album-cover-mark';
import CoverActivityMark, { type CoverMark } from './CoverActivityMark.svelte';

const STARTED_ONE_MINUTE_AGO = '2026-10-22T09:59:00Z';
const NOW = '2026-10-22T10:00:00Z';

let mounted: ReturnType<typeof mount> | undefined;
let target: HTMLElement;

async function render(mark: CoverMark): Promise<string> {
	target = document.createElement('div');
	document.body.append(target);
	mounted = mount(CoverActivityMark, { target, props: mark });
	await tick();
	return (target.textContent ?? '').replace(/\s+/g, ' ').trim();
}

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	vi.useRealTimers();
});

describe('the closed cover mark', () => {
	it('shows the ring and the time since the server started the run', async () => {
		vi.useFakeTimers({ now: Date.parse(NOW) });

		const text = await render({ running: true, startedAt: STARTED_ONE_MINUTE_AGO, waiting: 0 });

		expect(text).toBe('1:00');
		expect(target.querySelector('.mark-ring')).not.toBeNull();
	});

	it('counts the waiting suggestions while no run goes', async () => {
		const text = await render({ running: false, startedAt: null, waiting: 3 });

		expect(text).toBe('3 waiting');
		expect(target.querySelector('.mark-dot')).not.toBeNull();
	});

	it('shows the run rather than the waiting count while a run goes', async () => {
		vi.useFakeTimers({ now: Date.parse(NOW) });

		const text = await render({ running: true, startedAt: STARTED_ONE_MINUTE_AGO, waiting: 2 });

		expect(text).not.toContain('waiting');
	});

	it('shows nothing when no run goes and nothing waits', async () => {
		const text = await render({ running: false, startedAt: null, waiting: 0 });

		expect(text).toBe('');
		expect(target.querySelector('.cover-mark')).toBeNull();
	});

	it('is not announced, since the cover button names what it carries', async () => {
		await render({ running: false, startedAt: null, waiting: 1 });

		expect(target.querySelector('.cover-mark')?.getAttribute('aria-hidden')).toBe('true');
	});
});

describe('the closed cover name', () => {
	it.each([
		{
			state: 'a running suggestion',
			mark: { running: true, waiting: 0 },
			suffix: ' · making a suggestion'
		},
		{ state: 'waiting suggestions', mark: { running: false, waiting: 3 }, suffix: ' · 3 waiting' },
		{ state: 'nothing', mark: { running: false, waiting: 0 }, suffix: '' },
		{ state: 'no mark', mark: undefined, suffix: '' }
	])('carries $state without a ticking time', ({ mark, suffix }) => {
		const label = albumCoverMarkedLabel(ALBUM_COVER_EDIT_LABEL, mark);

		expect(label).toBe(`${ALBUM_COVER_EDIT_LABEL}${suffix}`);
		expect(label).not.toMatch(/\d:\d\d/);
	});
});
