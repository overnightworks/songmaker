import { createRawSnippet, mount, tick, unmount, type Snippet } from 'svelte';
import { fromStore, writable } from 'svelte/store';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { makeGeneration } from '#lib/test-utils/factories.ts';
import { words } from '#lib/words/en.ts';
import NowPlayingFrame from './NowPlayingFrame.svelte';

let mounted: ReturnType<typeof mount> | undefined;

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
	delete document.documentElement.dataset.pointer;
});

describe('NowPlayingFrame', () => {
	it('1374_rule_10 shows page artwork in the cover and restores the URL cover when absent', async () => {
		const artwork = writable<Snippet | undefined>(
			createRawSnippet(() => ({ render: () => '<span>Collection mosaic</span>' }))
		);
		const reactiveArtwork = fromStore(artwork);
		const target = document.createElement('div');
		document.body.append(target);
		mounted = mount(NowPlayingFrame, {
			target,
			props: {
				surface: 'page',
				info: {
					generation: makeGeneration(),
					songId: 'song-1',
					songTitle: 'Tide',
					albumTitle: 'Night Drive',
					artist: '',
					lyrics: null
				},
				coverUrl: '/cover.webp',
				get artwork() {
					return reactiveArtwork.current;
				}
			}
		});
		await tick();
		const cover = target.querySelector('.cover-art');
		expect(cover).toHaveTextContent('Collection mosaic');
		expect(cover?.querySelector('img')).toBeNull();
		artwork.set(undefined);
		await tick();
		expect(cover).not.toHaveTextContent('Collection mosaic');
		expect(cover?.querySelector('img')).toHaveAttribute('src', '/cover.webp');
	});
	it.each([{ stacked: true }, { stacked: false }])(
		'stands the take menu in the title row beside the title when stacked is $stacked',
		async ({ stacked }) => {
			if (stacked) document.documentElement.dataset.pointer = 'coarse';
			const target = document.createElement('div');
			document.body.append(target);
			mounted = mount(NowPlayingFrame, {
				target,
				props: {
					surface: 'full',
					stacked,
					coverUrl: null,
					takeMenu: createRawSnippet(() => ({ render: () => '<button id="menu">More</button>' })),
					info: {
						generation: makeGeneration(),
						songId: 'song-1',
						songTitle: 'Tide',
						albumTitle: 'Night Drive',
						artist: '',
						lyrics: null
					}
				}
			});
			await tick();
			const titleRow = target.querySelector('.title-line');
			expect(titleRow).toHaveTextContent('Tide');
			expect(titleRow?.querySelector('#menu')).not.toBeNull();
		}
	);
	it.each([
		{ stacked: true, card: 'before' },
		{ stacked: false, card: 'after' }
	])(
		'puts the judging card $card the progress bar when stacked is $stacked',
		async ({ stacked, card }) => {
			if (stacked) document.documentElement.dataset.pointer = 'coarse';
			const target = document.createElement('div');
			document.body.append(target);
			mounted = mount(NowPlayingFrame, {
				target,
				props: {
					surface: 'full',
					stacked,
					coverUrl: null,
					judging: createRawSnippet(() => ({ render: () => '<section id="card"></section>' })),
					info: {
						generation: makeGeneration(),
						songId: 'song-1',
						songTitle: 'Tide',
						albumTitle: 'Night Drive',
						artist: '',
						lyrics: null
					}
				}
			});
			await tick();
			const progress = target.querySelector('.progress');
			const cardElement = target.querySelector('#card');
			if (!progress || !cardElement) throw new Error('Expected the card and the progress bar');
			const progressFollowsCard = cardElement.compareDocumentPosition(progress);
			expect(Boolean(progressFollowsCard & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(
				card === 'before'
			);
		}
	);
	it.each([
		{
			name: 'a share song page',
			props: { surface: 'page' as const, showTakeLabel: false },
			line: 'Night Drive'
		},
		{
			name: 'the full player',
			props: { surface: 'full' as const, showTakeLabel: true },
			line: ''
		},
		{
			name: 'a collection page',
			props: {
				surface: 'page' as const,
				collectionHead: { title: 'Night Drive', subtitle: 'Nina · Album', nowPlaying: 'Tide' }
			},
			line: 'Nina · Album'
		}
	])(
		'1906_P1: $name carries the KI-generiert badge beside the line that names what plays',
		async ({ props, line }) => {
			const target = document.createElement('div');
			document.body.append(target);
			mounted = mount(NowPlayingFrame, {
				target,
				props: {
					...props,
					coverUrl: '/cover.webp',
					info: {
						generation: makeGeneration(),
						songId: 'song-1',
						songTitle: 'Tide',
						albumTitle: 'Night Drive',
						artist: '',
						lyrics: null
					}
				}
			});
			await tick();
			const badges = target.querySelectorAll('.ai-notice');
			expect(badges).toHaveLength(1);
			expect(badges[0]).toHaveTextContent(words['aiNotice.generated']);
			const row = badges[0].closest('.cover-line');
			expect(row).not.toBeNull();
			if (line) expect(row).toHaveTextContent(line);
		}
	);
	it('shows no sung marks on a share page, though its take was sung differently', async () => {
		const target = document.createElement('div');
		document.body.append(target);
		mounted = mount(NowPlayingFrame, {
			target,
			props: {
				surface: 'page',
				coverUrl: null,
				lyricsCues: [
					{
						start: 0,
						end: 1,
						text: 'the lantern hums',
						words: [{ start: 0, end: 1, text: 'the' }]
					}
				],
				info: {
					generation: makeGeneration(),
					songId: 'song-1',
					songTitle: 'Tide',
					albumTitle: 'Night Drive',
					artist: '',
					lyrics: 'the lantern hums quietly'
				}
			}
		});
		await tick();
		await vi.waitFor(() => expect(target.querySelector('.lyrics-line')).not.toBeNull());
		expect(target.querySelector('.lyrics-line')).toHaveTextContent('the lantern hums quietly');
		expect(target.querySelectorAll('.lyrics-line button')).toHaveLength(0);
	});
});
