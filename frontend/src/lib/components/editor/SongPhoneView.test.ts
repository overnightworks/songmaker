import { createRawSnippet, mount, tick, unmount, type ComponentProps } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { detailTab } from '$lib/stores/navigation';
import { makeGeneration, makeSong } from '$lib/test-utils/factories';
import { generationFailures } from '$lib/stores/jobs';
import { clearSelection } from '$lib/stores/selection';
import SongPhoneView from './SongPhoneView.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];
const snippets = {
	sharedLink: createRawSnippet(() => ({ render: () => '<div>Share link</div>' })),
	recipe: createRawSnippet(() => ({ render: () => '<div>Song recipe</div>' })),
	write: createRawSnippet(() => ({
		render: () => '<textarea aria-label="Lyrics">Draft</textarea>'
	})),
	expiryDigest: createRawSnippet(() => ({ render: () => '<div>Expiry digest</div>' }))
};

beforeEach(() => {
	detailTab.set('write');
	generationFailures.set({});
	clearSelection();
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	detailTab.set('write');
});

async function render(
	overrides: Partial<ComponentProps<typeof SongPhoneView>['takeListProps']> = {}
) {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(
		mount(SongPhoneView, {
			target,
			props: {
				...snippets,
				takeListProps: {
					song: makeSong({ generations: [], generation_count: 0 }),
					dirty: false,
					draftVersionNumber: 2,
					latestVersionNumber: 1,
					onagain: vi.fn(),
					onsource: vi.fn(),
					...overrides
				}
			}
		})
	);
	await tick();
	return target;
}

describe('SongPhoneView', () => {
	it('switches from the supplied Write surface to the real takes and back', async () => {
		const takes = [makeGeneration(), makeGeneration({ id: 'g2', generation_number: 2 })];
		const target = await render({ song: makeSong({ generations: takes, generation_count: 2 }) });
		expect(target.querySelector('textarea')?.value).toBe('Draft');
		expect(target.textContent).toContain('Song recipe');
		const tabs = target.querySelectorAll<HTMLButtonElement>('[role="tab"]');
		tabs[1].click();
		await tick();
		expect(target.querySelector('[role="tabpanel"]')?.getAttribute('aria-labelledby')).toBe(
			'song-tab-takes'
		);
		expect(target.querySelector('textarea')).toBeNull();
		expect(target.textContent).not.toContain('Song recipe');
		expect(target.querySelector('header')).toBeNull();
		expect(target.textContent).toContain('Expiry digest');
		expect(target.querySelectorAll('.take-row')).toHaveLength(2);
		expect(target.querySelectorAll('.take-row .play-btn')).toHaveLength(2);
		tabs[0].click();
		await tick();
		expect(target.querySelector('textarea')?.value).toBe('Draft');
		expect(target.querySelector('.takes-list')).toBeNull();
	});

	it.each([
		['ready', 'No takes yet · Generate on Write'],
		['loading', 'Loading takes…'],
		['error', 'Failed to load takes']
	] as const)(
		'shows the real list’s %s state when navigation restores Takes',
		async (loadStatus, text) => {
			detailTab.set('takes');
			const target = await render({ loadStatus });
			expect(target.textContent).toContain(text);
			expect(target.querySelector('[role="tab"][aria-selected="true"]')?.textContent?.trim()).toBe(
				'Takes (0)'
			);
			expect(target.querySelector('textarea')).toBeNull();
		}
	);
});
