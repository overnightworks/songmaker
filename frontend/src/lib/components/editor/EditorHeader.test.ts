import { makeSong as song } from '$lib/test-utils/factories';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { clearHitboxStyles, clearPointer, injectHitboxStyles } from '$lib/test-utils/hitbox';
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

function defaultProps() {
	return {
		song: song({
			slug: 'sommerlicht',
			title: 'Sommerlicht',
			bpm: 120,
			audio_duration: 180,
			key_scale: 'Am',
			generation_params: null,
			best_scores: null,
			best_rating: null,
			share_slug: null
		}),
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
		saveDisabled: true,
		onsave: vi.fn()
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
	it('renders one header row with Generate alone and no Recipe toggle (C4, #1935 acceptance 6)', async () => {
		const { target } = await render();
		const rows = target.querySelectorAll('.detail-header');
		expect(rows).toHaveLength(1);
		expect(target.querySelector('.view-toggle')).toBeNull();
		expect(target.querySelector('.editor-views')).toBeNull();
		const generateButtons = target.querySelectorAll('.generate-action .primary-button');
		expect(generateButtons).toHaveLength(1);
		expect(generateButtons[0].textContent).toContain('Generate');
	});

	it('keeps Share beside the desktop song menu', async () => {
		const { target } = await render();
		expect(target.querySelector('.title-row > .share-btn')).not.toBeNull();
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

	it('opens the song menu whose first row names the song', async () => {
		const { target } = await render();
		target.querySelector<HTMLButtonElement>('.menu-trigger')?.click();
		await tick();
		expect(target.querySelector('.menu-heading')?.textContent).toBe('Song · Sommerlicht');
	});

	it('draws no hitbox face across a labelled control', async () => {
		// #163/1: the face is a fixed 24/44px box, so on a text label it cuts
		// straight through the word. Labelled buttons carry their own border.
		const { target } = await render();
		for (const labelled of target.querySelectorAll('.generate-action .primary-button')) {
			expect(
				labelled.hasAttribute('data-hitbox-face'),
				`${labelled.textContent?.trim()} draws a face over its label`
			).toBe(false);
		}
	});

	it('announces the song title as the heading name, with a separately named edit button', async () => {
		const { target } = await render({
			song: song({
				slug: 'sommerlicht',
				bpm: 120,
				audio_duration: 180,
				key_scale: 'Am',
				generation_params: null,
				best_scores: null,
				best_rating: null,
				share_slug: null,
				title: 'Sommerlicht'
			})
		});
		const heading = getByRoleHeading(target, 'Sommerlicht');
		expect(heading.tagName).toBe('H2');
		const editButton = getByRoleButton(heading, 'Edit song title');
		expect(editButton.textContent?.trim()).toBe('Sommerlicht');
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
