import { mount, tick, unmount, type ComponentProps } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { QueueContext, QueueRowItem, QueueViewModel } from '$lib/stores/player';
import NowPlayingQueue from './NowPlayingQueue.svelte';

type NowPlayingQueueProps = ComponentProps<typeof NowPlayingQueue>;

function item(overrides: Partial<QueueRowItem> = {}): QueueRowItem {
	return {
		key: 'g1',
		songId: 's1',
		songTitle: 'Tide',
		generationId: 'g1',
		durationSec: 195,
		versionNumber: 2,
		generationNumber: 3,
		...overrides
	};
}

let mounted: ReturnType<typeof mount> | undefined;
let target: HTMLDivElement;

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
});

async function render(props: Partial<NowPlayingQueueProps> = {}) {
	target = document.createElement('div');
	document.body.append(target);
	const ctx: QueueContext = props.ctx ?? { type: 'library' };
	const queue: QueueViewModel = props.queue ?? { items: [item()], currentIndex: 0, upNext: null };
	const onChoosePool = vi.fn();
	const onJump = vi.fn();
	mounted = mount(NowPlayingQueue, {
		target,
		props: {
			ctx,
			queue,
			contextLabel: null,
			currentSongTitle: 'Tide',
			pool: 'picks',
			onChoosePool,
			onJump,
			...props
		}
	});
	await tick();
	return { onChoosePool, onJump };
}

describe('NowPlayingQueue', () => {
	it('shows the pool trio only for the library context', async () => {
		await render({ ctx: { type: 'library' } });
		expect(target.querySelectorAll('.pool-pill')).toHaveLength(3);
		expect(target.textContent).toContain('Picks');
		expect(target.textContent).toContain('+ Keeps');
		expect(target.textContent).toContain('All takes');
	});

	it('hides the pool trio for an album context and shows the album name instead', async () => {
		await render({ ctx: { type: 'album', albumId: 'a1' }, contextLabel: 'Nachtstrom' });
		expect(target.querySelectorAll('.pool-pill')).toHaveLength(0);
		expect(target.querySelector('.queue-heading')?.textContent).toBe('Queue · Nachtstrom');
	});

	it('hides the pool trio for a playlist context and shows the playlist name instead', async () => {
		await render({
			ctx: { type: 'playlist', entries: [], index: 0 },
			contextLabel: 'Night Drive'
		});
		expect(target.querySelectorAll('.pool-pill')).toHaveLength(0);
		expect(target.querySelector('.queue-heading')?.textContent).toBe('Queue · Night Drive');
	});

	it('calls onChoosePool when a pool pill is clicked', async () => {
		const { onChoosePool } = await render({ ctx: { type: 'library' } });
		const allPill = Array.from(target.querySelectorAll<HTMLButtonElement>('.pool-pill')).find(
			(btn) => btn.textContent === 'All takes'
		);
		allPill?.click();
		expect(onChoosePool).toHaveBeenCalledWith('all');
	});

	it('renders the queue as an ordered list and jumps to the clicked take', async () => {
		const queue: QueueViewModel = {
			items: [item({ key: 'g1', songTitle: 'Tide' }), item({ key: 'g2', songTitle: 'Ebb' })],
			currentIndex: 0,
			upNext: item({ key: 'g2', songTitle: 'Ebb' })
		};
		const { onJump } = await render({ queue });
		const rows = target.querySelectorAll('.queue-row');
		expect(rows).toHaveLength(2);
		expect(rows[0]?.classList.contains('current')).toBe(true);
		expect(target.textContent).toContain('Up next: Ebb');
		(rows[1] as HTMLButtonElement).click();
		expect(onJump).toHaveBeenCalledWith(1);
	});

	it('renders current-only, no up next, when the classic queue has not built takes yet', async () => {
		const queue: QueueViewModel = { items: [], currentIndex: -1, upNext: null };
		await render({ queue, currentSongTitle: 'Tide' });
		const rows = target.querySelectorAll('.queue-row');
		expect(rows).toHaveLength(1);
		expect(rows[0]?.textContent).toContain('Tide');
		expect(target.textContent).not.toContain('Up next');
	});

	it('labels a versioned row with version and take number', async () => {
		const queue: QueueViewModel = {
			items: [item({ versionNumber: 2, generationNumber: 3 })],
			currentIndex: 0,
			upNext: null
		};
		await render({ queue });
		expect(target.querySelector('.queue-take')?.textContent?.trim()).toBe('v2 · take 3');
	});

	it('labels a library-pool row (no version) with take number only, never "vnull"', async () => {
		const queue: QueueViewModel = {
			items: [item({ versionNumber: null, generationNumber: 4 })],
			currentIndex: 0,
			upNext: null
		};
		await render({ queue });
		const label = target.querySelector('.queue-take')?.textContent?.trim();
		expect(label).toBe('take 4');
		expect(label).not.toContain('vnull');
	});
});
