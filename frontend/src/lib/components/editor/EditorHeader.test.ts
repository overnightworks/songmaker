import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { SongItem } from '$lib/api/types';
import { HITBOX_COMPACT_PX, HITBOX_FREQUENT_PX } from '$lib/constants';
import {
	clearHitboxStyles,
	clearPointer,
	injectHitboxStyles,
	minHeightPx,
	setPointer
} from '$lib/test-utils/hitbox';
import EditorHeader from './EditorHeader.svelte';
import editorHeaderSource from './EditorHeader.svelte?raw';
import { getByRoleButton, getByRoleHeading } from '$lib/test-utils/accessible-name';

const mounted: Array<ReturnType<typeof mount>> = [];

beforeEach(() => {
	injectHitboxStyles();
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	clearHitboxStyles();
	clearPointer();
});

function song(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 's1',
		slug: 'sommerlicht',
		title: 'Sommerlicht',
		album_id: 'a1',
		album_title: 'Album',
		artist: 'Artist',
		track_number: 1,
		vocal_language: 'en',
		lyrics: '',
		prompt: '',
		bpm: 120,
		audio_duration: 180,
		key_scale: 'Am',
		generation_params: null,
		version_count: 1,
		generation_count: 1,
		best_scores: null,
		best_rating: null,
		generations: [],
		created_at: '2026-01-01T00:00:00+00:00',
		is_shared: false,
		share_slug: null,
		...overrides
	};
}

function defaultProps() {
	return {
		song: song(),
		coverUrl: null,
		coverFailed: false,
		coverAlt: 'Song',
		artFill: null,
		initials: 'SO',
		hasOwnCover: false,
		coverBusy: false,
		coverActionLabel: 'Upload song cover',
		onrenamesong: vi.fn(async () => undefined),
		oncoverfile: vi.fn(),
		oncoverremove: vi.fn(),
		oncovererror: vi.fn(),
		breadcrumbItems: [
			{ label: 'Library', onclick: vi.fn() },
			{ label: 'Album', onclick: vi.fn() },
			{ label: 'Track 1 of 3' }
		],
		songRail: false,
		albumTitle: 'Album',
		albumSongCount: 3,
		albumCoverUrl: null,
		albumArtFill: null,
		albumInitials: 'AL',
		previousDisabled: true,
		nextDisabled: false,
		onselectprevious: vi.fn(),
		onselectnext: vi.fn(),
		isShared: false,
		shareSlug: null,
		onshare: vi.fn(async () => ({
			status: 'ok',
			share_url: '',
			share_slug: 's',
			songs_without_playable_take: []
		})),
		onunshare: vi.fn(async () => undefined),
		onaddtoplaylist: vi.fn(),
		ondeletesong: vi.fn(),
		recipeOpen: false,
		coWriterOpen: false,
		ontogglerecipe: vi.fn(),
		ontogglecowriter: vi.fn(),
		ongenerate: vi.fn(),
		generateLabel: 'Generate',
		generateDisabled: false,
		generateTitle: '',
		generateQueueReason: null as string | null,
		generating: false,
		compact: false
	};
}

async function render(overrides: Partial<ReturnType<typeof defaultProps>> = {}) {
	const target = document.createElement('div');
	document.body.append(target);
	const props = { ...defaultProps(), ...overrides };
	mounted.push(mount(EditorHeader, { target, props }));
	await tick();
	return { target, props };
}

describe('EditorHeader', () => {
	it('renders one header row with stacked view toggles and Generate alone', async () => {
		const { target } = await render();
		const rows = target.querySelectorAll('.detail-header');
		expect(rows).toHaveLength(1);
		const toggles = target.querySelectorAll('.view-toggle');
		expect(toggles).toHaveLength(2);
		expect(toggles[0].textContent).toContain('Co-Writer');
		expect(toggles[1].textContent).toContain('Recipe');
		const generateButtons = target.querySelectorAll('.generate-btn');
		expect(generateButtons).toHaveLength(1);
		expect(generateButtons[0].textContent).toContain('Generate');
	});

	it('does not render Share as a standalone action outside the song menu', async () => {
		const { target } = await render();
		expect(target.querySelector('.share-btn, [aria-label="Share"]')).toBeNull();
		expect(target.querySelector('.song-menu')).not.toBeNull();
	});

	it('navigates breadcrumb levels via their onclick handlers', async () => {
		const onclick = vi.fn();
		const { target } = await render({
			breadcrumbItems: [{ label: 'Library', onclick }, { label: 'Track 1 of 1' }]
		});
		const libraryCrumb = Array.from(target.querySelectorAll<HTMLButtonElement>('.crumb-link')).find(
			(el) => el.textContent === 'Library'
		);
		libraryCrumb?.click();
		expect(onclick).toHaveBeenCalledTimes(1);
	});

	it('renders one compact album line with album skip controls', async () => {
		const onselectprevious = vi.fn();
		const onselectnext = vi.fn();
		const { target } = await render({
			songRail: true,
			albumTitle: 'Anfield',
			albumSongCount: 2,
			previousDisabled: false,
			onselectprevious,
			onselectnext
		});

		const line = target.querySelector('.mobile-album-line');
		if (!line) throw new Error('Expected mobile album line');
		expect(line.textContent).toContain('Anfield · 2 songs');
		expect(line.querySelector('.album-line-cover')).not.toBeNull();
		expect(line.querySelector('.breadcrumb')).toBeNull();
		line.querySelector<HTMLButtonElement>(`[aria-label="Previous song"]`)?.click();
		line.querySelector<HTMLButtonElement>(`[aria-label="Next song"]`)?.click();
		expect(onselectprevious).toHaveBeenCalledTimes(1);
		expect(onselectnext).toHaveBeenCalledTimes(1);
	});

	it('reflects toggle state via aria-pressed and calls the right handler', async () => {
		const ontogglerecipe = vi.fn();
		const { target } = await render({ ontogglerecipe, recipeOpen: true });
		const recipeToggle = target.querySelectorAll<HTMLButtonElement>('.view-toggle')[1];
		expect(recipeToggle.getAttribute('aria-pressed')).toBe('true');
		recipeToggle.click();
		expect(ontogglerecipe).toHaveBeenCalledTimes(1);
	});

	it('opens the song menu whose first row names the song', async () => {
		const { target } = await render();
		target.querySelector<HTMLButtonElement>('.menu-trigger')?.click();
		await tick();
		expect(target.querySelector('.menu-heading')?.textContent).toBe('Song · Sommerlicht');
	});

	it('grows the view toggles to the touch height on a coarse pointer, keeping their label width', async () => {
		const { target } = await render();
		const toggle = target.querySelector<HTMLButtonElement>('.view-toggle');
		if (!toggle) throw new Error('Expected a view toggle button');
		setPointer('coarse');
		expect(minHeightPx(toggle, 'view toggle')).toBe(HITBOX_FREQUENT_PX);
		setPointer('fine');
		expect(minHeightPx(toggle, 'view toggle')).toBeGreaterThanOrEqual(HITBOX_COMPACT_PX);
	});

	it('draws no hitbox face across a labelled control', async () => {
		// #163/1: the face is a fixed 24/44px box, so on a text label it cuts
		// straight through the word. Labelled buttons carry their own border.
		const { target } = await render();
		for (const labelled of target.querySelectorAll('.view-toggle, .generate-btn')) {
			expect(
				labelled.hasAttribute('data-hitbox-face'),
				`${labelled.textContent?.trim()} draws a face over its label`
			).toBe(false);
		}
	});

	it('sizes Generate to the frequent hitbox on a coarse pointer, in both its places', async () => {
		for (const compact of [false, true]) {
			const { target } = await render({ compact });
			const generate = target.querySelector<HTMLButtonElement>('.generate-btn');
			if (!generate) throw new Error('Expected the Generate button');
			setPointer('coarse');
			expect(minHeightPx(generate, 'Generate')).toBe(HITBOX_FREQUENT_PX);
		}
	});

	it('announces the song title as the heading name, with a separately named edit button', async () => {
		const { target } = await render({ song: song({ title: 'Sommerlicht' }) });
		const heading = getByRoleHeading(target, 'Sommerlicht');
		expect(heading.tagName).toBe('H2');
		const editButton = getByRoleButton(heading, 'Edit song title');
		expect(editButton.textContent?.trim()).toBe('Sommerlicht');
	});

	it('moves Generate to a fixed bottom bar and drops it from the header row in compact mode', async () => {
		const { target } = await render({ compact: true });
		expect(target.querySelector('.detail-header .generate-btn')).toBeNull();
		expect(target.querySelector('.editor-generate-bar .generate-btn')).not.toBeNull();
	});

	it('puts the compact queue reason on a second flex row below Generate', async () => {
		const { target } = await render({
			compact: true,
			generateQueueReason: 'Waiting for LoRA training.'
		});
		const bar = target.querySelector('.editor-generate-bar');
		if (!bar) throw new Error('Expected the compact Generate bar');

		expect(bar.querySelector('.generate-btn')?.nextElementSibling?.textContent).toBe(
			'Waiting for LoRA training.'
		);
		expect(editorHeaderSource).toMatch(
			/\.editor-generate-bar \{[^}]*display: flex;[^}]*flex-wrap: wrap;/
		);
		expect(editorHeaderSource).toMatch(
			/\.editor-generate-bar \.generate-queue-reason \{[^}]*flex-basis: 100%;/
		);
	});
});

describe('EditorHeader in a narrow editor', () => {
	// jsdom computes no flex layout, so this pins the stylesheet; the browser
	// gate on #185 — 1100 and 1280 with Now Playing docked — is the proof.
	it('gives the title and breadcrumb a floor the actions have to wrap around', () => {
		expect(editorHeaderSource).toMatch(/\.detail-header \{[^}]*flex-wrap: wrap;/);
		// With a basis of 0 the views and Generate always won the line and left
		// the identity a sliver of it.
		expect(editorHeaderSource).toMatch(/\.detail-identity \{[^}]*flex: 1 1 22rem;/);
	});
});
