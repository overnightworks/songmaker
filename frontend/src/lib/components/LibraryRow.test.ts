import { mount, tick, unmount } from 'svelte';
import { afterEach, expect, it, vi } from 'vitest';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import LibraryRow from './LibraryRow.svelte';

let mounted: ReturnType<typeof mount> | undefined;
afterEach(async () => {
	vi.useRealTimers();
	if (mounted) await unmount(mounted);
	document.body.replaceChildren();
	audioPlayer.status = 'idle';
});

it('1354_rule_10: open and play are separate keyboard buttons with separate outcomes', async () => {
	let opened = false;
	let played = false;
	mounted = mount(LibraryRow, {
		target: document.body,
		props: {
			title: 'Long album title',
			subtitle: '8 songs',
			coverAlt: 'Album cover',
			openLabel: 'Open album Long album title',
			onopen: () => {
				opened = true;
			},
			onplay: () => {
				played = true;
			}
		}
	});
	await tick();
	const buttons = document.querySelectorAll('button');
	expect(buttons).toHaveLength(2);
	expect(buttons[0].contains(buttons[1])).toBe(false);
	buttons[1].click();
	expect([opened, played]).toEqual([false, true]);
	buttons[0].click();
	expect(opened).toBe(true);
	expect(buttons[0]).toHaveAccessibleName('Open album Long album title');
	expect(buttons[0]).toHaveTextContent('8 songs');
});

it.each(['playing', 'paused', 'loading', 'recovering', 'waiting-for-network'] as const)(
	'1354_rule_10: the %s source keeps its mark and offers the matching transport',
	async (status) => {
		audioPlayer.status = status === 'paused' ? 'paused' : 'playing';
		mounted = mount(LibraryRow, {
			target: document.body,
			props: {
				title: 'Album',
				subtitle: '3 songs',
				coverAlt: 'Cover',
				openLabel: 'Open album Album',
				onopen: () => undefined,
				onplay: () => undefined,
				current: true,
				transport: status
			}
		});
		await tick();
		expect(document.querySelector('[role="img"]')).toHaveAccessibleName('Playing');
		expect(document.querySelector('.row-play')).toHaveAccessibleName(
			`${status === 'paused' ? 'Play' : 'Pause'} Album`
		);
		expect(document.querySelector('.tile-subtitle')).toHaveTextContent('3 songs');
	}
);

it('1354_rule_11: a row without a playable action has only its open button', async () => {
	mounted = mount(LibraryRow, {
		target: document.body,
		props: {
			title: 'Empty',
			subtitle: '0 songs',
			coverAlt: 'Cover',
			openLabel: 'Open album Empty',
			onopen: () => undefined
		}
	});
	await tick();
	expect(document.querySelectorAll('button')).toHaveLength(1);
	expect(document.body).toHaveTextContent('0 songs');
	expect(document.querySelector('.row-play-spacer')).toHaveAttribute('aria-hidden', 'true');
});

it.each([
	{ asked: true, litFirst: true, reports: 1 },
	{ asked: false, litFirst: false, reports: 0 }
])(
	'1354_rule_12: a row asked to light up ($asked) is lit at first, reports it and settles for good',
	async ({ asked, litFirst, reports }) => {
		vi.useFakeTimers();
		let reported = 0;
		mounted = mount(LibraryRow, {
			target: document.body,
			props: {
				title: 'Album',
				subtitle: '3 songs',
				coverAlt: 'Cover',
				openLabel: 'Open album Album',
				onopen: () => undefined,
				lightUp: asked,
				onlit: () => reported++
			}
		});
		await tick();
		const row = document.querySelector('.library-row');
		expect(row?.classList.contains('lit')).toBe(litFirst);
		expect(reported).toBe(reports);

		await vi.advanceTimersByTimeAsync(10_000);

		expect(row?.classList.contains('lit')).toBe(false);
	}
);
