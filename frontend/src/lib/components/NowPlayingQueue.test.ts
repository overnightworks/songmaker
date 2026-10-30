import { mount, tick, unmount, type ComponentProps } from 'svelte';
import { fromStore, writable } from 'svelte/store';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { QueueRowItem, QueueViewModel } from '#lib/stores/player.ts';
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
	const queue: QueueViewModel = props.queue ?? { items: [item()], currentIndex: 0, upNext: null };
	const queueStore = writable(queue);
	const reactiveQueue = fromStore(queueStore);
	const onChoosePool = vi.fn();
	const onJump = vi.fn();
	mounted = mount(NowPlayingQueue, {
		target,
		props: {
			contextLabel: null,
			currentSongTitle: 'Tide',
			takePool: { selected: 'picks', onChoose: onChoosePool },
			onJump,
			...props,
			get queue() {
				return reactiveQueue.current;
			}
		}
	});
	await tick();
	return { onChoosePool, onJump, setQueue: queueStore.set };
}

describe('NowPlayingQueue', () => {
	it('1374_rule_10 keeps subtitle wrappers with entry ids after reorder and preserves missing-key share rows', async () => {
		const first = item({ key: 'entry-first', songTitle: 'Tide' });
		const second = item({ key: 'entry-second', songTitle: 'Ebb' });
		const third = item({ key: 'entry-third', songTitle: 'Shore' });
		const subtitles = new Map([
			['entry-first', 'Night Drive'],
			['entry-second', 'Daybreak']
		]);
		const { setQueue } = await render({
			queue: { items: [first, second, third], currentIndex: 0, upNext: null },
			subtitleByEntryId: subtitles,
			showTakeLabel: false
		});
		setQueue({ items: [third, second, first], currentIndex: 2, upNext: null });
		await tick();
		const rows = target.querySelectorAll('.queue-row');
		expect(rows[0]).toHaveAccessibleName(/^Shore/);
		expect(Array.from(rows[0].children, (child) => child.tagName)).toEqual([
			'SPAN',
			'SPAN',
			'SPAN'
		]);
		expect(Array.from(rows[0].children, (child) => child.classList[0])).toEqual([
			'queue-position',
			'queue-title',
			'queue-duration'
		]);
		expect(rows[0].querySelector('.queue-label')).toBeNull();
		expect(rows[0].querySelector('.queue-subtitle')).toBeNull();
		expect(rows[1]).toHaveAccessibleName(/^Ebb Daybreak/);
		expect(rows[2]).toHaveAccessibleName(/^Tide Night Drive/);
		expect(rows[0].querySelector('.queue-title')?.textContent).toBe('Shore');
		expect(rows[1].querySelector('.queue-title')?.textContent).toBe('Ebb');
		expect(rows[1].querySelector('.queue-subtitle')?.textContent).toBe('Daybreak');
		for (const [index, title, subtitle] of [
			[1, 'Ebb', 'Daybreak'],
			[2, 'Tide', 'Night Drive']
		] as const) {
			const label = rows[index].querySelector(':scope > .queue-label');
			expect(label).not.toBeNull();
			expect(Array.from(label?.children ?? [], (child) => child.classList[0])).toEqual([
				'queue-title',
				'queue-subtitle'
			]);
			expect(label?.children[0].textContent).toBe(title);
			expect(label?.children[1].textContent).toBe(subtitle);
		}
	});

	it.each([
		['no map', undefined],
		['empty map', new Map<string, string>()],
		['missing key in populated map', new Map([['other-entry', 'Daybreak']])]
	])('1374_rule_10 preserves original row children with %s', async (_, subtitleByEntryId) => {
		await render({ subtitleByEntryId });
		const row = target.querySelector('.queue-row');
		expect(row).not.toBeNull();
		expect(Array.from(row?.children ?? [], (child) => child.tagName)).toEqual([
			'SPAN',
			'SPAN',
			'SPAN',
			'SPAN'
		]);
		expect(Array.from(row?.children ?? [], (child) => child.classList[0])).toEqual([
			'queue-position',
			'queue-title',
			'queue-take',
			'queue-duration'
		]);
		expect(row?.querySelector('.queue-label')).toBeNull();
		expect(row?.querySelector('.queue-subtitle')).toBeNull();
		expect(row?.querySelector(':scope > .queue-title')?.textContent).toBe('Tide');
		expect(row).toHaveAccessibleName(/^Tide/);
	});

	it('1374_rule_5 names an album list Songs and keeps row names starting with the title', async () => {
		await render({
			heading: 'Songs',
			takePool: undefined,
			showTakeLabel: false,
			queue: {
				items: [
					item({ key: 'first', songTitle: 'Tide' }),
					item({ key: 'second', songTitle: 'Ebb' })
				],
				currentIndex: 0,
				upNext: null
			}
		});
		expect(target.querySelector('.queue-heading')?.textContent).toBe('Songs');
		expect(target.querySelector('.np-queue')?.getAttribute('aria-label')).toBe('Songs');
		expect(target.querySelectorAll('.queue-take')).toHaveLength(0);
		const rows = Array.from(target.querySelectorAll('.queue-row'));
		expect(rows[0]).toHaveAccessibleName(/^Tide/);
		expect(rows[1]).toHaveAccessibleName(/^Ebb/);
	});

	it('offers the take pool trio when the queue is built from a pool', async () => {
		await render();
		expect(target.querySelectorAll('.pool-pill')).toHaveLength(3);
		expect(target.textContent).toContain('Picks');
		expect(target.textContent).toContain('+ Keeps');
		expect(target.textContent).toContain('All takes');
		expect(target.querySelector('.queue-heading')?.textContent).toBe('Queue');
	});

	it('names the collection in the heading and offers no pool when the queue has none', async () => {
		await render({ contextLabel: 'Night Drive', takePool: undefined });
		expect(target.querySelectorAll('.pool-pill')).toHaveLength(0);
		expect(target.querySelector('.queue-heading')?.textContent).toBe('Queue · Night Drive');
	});

	it('calls onChoosePool when a pool pill is clicked', async () => {
		const { onChoosePool } = await render();
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

	it('formats a row with its own measured duration', async () => {
		const queue: QueueViewModel = {
			items: [item({ durationSec: 195 })],
			currentIndex: 0,
			upNext: null
		};
		await render({ queue });
		expect(target.querySelector('.queue-duration')?.textContent).toBe('3:15');
	});

	it('shows no duration at all for a row whose length has not been measured (#258)', async () => {
		const queue: QueueViewModel = {
			items: [item({ durationSec: null })],
			currentIndex: 0,
			upNext: null
		};
		await render({ queue });
		const text = target.querySelector('.queue-duration')?.textContent ?? '';
		expect(text).toBe('');
		expect(text).not.toContain('0:00');
	});
});
