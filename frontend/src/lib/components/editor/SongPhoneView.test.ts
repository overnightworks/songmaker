import { createRawSnippet, mount, tick, unmount, type ComponentProps } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { detailTab } from '$lib/stores/navigation';
import { coWriterOpen, type RecipeChip } from '$lib/stores/recipe';
import { makeGeneration, makeSong } from '$lib/test-utils/factories';
import { generationFailures } from '$lib/stores/jobs';
import { clearSelection } from '$lib/stores/selection';
import SongPhoneView from './SongPhoneView.svelte';
import songPhoneViewSource from './SongPhoneView.svelte?raw';
import { clearComponentStyles, injectComponentStyles } from '$lib/test-utils/component-styles';
import { EDITOR_GENERATE_MODE_LABELS } from '$lib/constants';

vi.mock('$lib/api/client', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/client')>()),
	fetchBuiltinDefaults: vi.fn().mockResolvedValue({}),
	fetchPresets: vi.fn().mockResolvedValue([]),
	fetchGenerationDefaults: vi.fn().mockResolvedValue({})
}));

const mounted: Array<ReturnType<typeof mount>> = [];
const snippets = {
	sharedLink: createRawSnippet(() => ({ render: () => '<div>Share link</div>' })),
	write: createRawSnippet(() => ({
		render: () => '<textarea aria-label="Lyrics">Draft</textarea>'
	})),
	cowriter: createRawSnippet(() => ({ render: () => '<div class="cowriter-screen">Chat</div>' })),
	expiryDigest: createRawSnippet(() => ({ render: () => '<div>Expiry digest</div>' }))
};

beforeEach(() => {
	detailTab.set('write');
	coWriterOpen.set(false);
	generationFailures.set({});
	clearSelection();
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	detailTab.set('write');
	coWriterOpen.set(false);
	clearComponentStyles();
});

const NO_CHIPS: RecipeChip[] = [];

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
				chips: NO_CHIPS,
				takeListProps: {
					song: makeSong({ generations: [], generation_count: 0 }),
					dirty: false,
					draftVersionNumber: 2,
					latestVersionNumber: 1,
					onsource: vi.fn(),
					...overrides
				}
			}
		})
	);
	await tick();
	return target;
}

function expectGenerateAsPrimaryAction(target: HTMLElement): void {
	const primaryAction = target
		.querySelector('[role="tabpanel"] > :last-child')
		?.querySelector('button');
	expect(primaryAction?.textContent?.trim()).toBe(EDITOR_GENERATE_MODE_LABELS.generate);
}

describe('SongPhoneView', () => {
	it('switches from the supplied Write surface to the real takes and back', async () => {
		const takes = [makeGeneration(), makeGeneration({ id: 'g2', generation_number: 2 })];
		const target = await render({ song: makeSong({ generations: takes, generation_count: 2 }) });
		expect(target.querySelector('textarea')?.value).toBe('Draft');
		expect(target.querySelector('section[aria-label="Recipe"]')).not.toBeNull();
		expectGenerateAsPrimaryAction(target);
		const tabs = target.querySelectorAll<HTMLButtonElement>('[role="tab"]');
		tabs[1].click();
		await tick();
		expect(target.querySelector('[role="tabpanel"]')?.getAttribute('aria-labelledby')).toBe(
			'song-tab-takes'
		);
		expect(target.querySelector('textarea')).toBeNull();
		expect(target.querySelector('section[aria-label="Recipe"]')).toBeNull();
		expect(target.querySelector('.generate-action')).toBeNull();
		expect(target.querySelector('header')).toBeNull();
		expect(target.textContent).toContain('Expiry digest');
		expect(target.querySelectorAll('.take-row')).toHaveLength(2);
		expect(target.querySelectorAll('.take-row .play-btn')).toHaveLength(2);
		tabs[0].click();
		await tick();
		expect(target.querySelector('textarea')?.value).toBe('Draft');
		expectGenerateAsPrimaryAction(target);
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
			expect(target.querySelector('.generate-action')).toBeNull();
		}
	);

	// #993: the Generate action used to scroll away with the rest of the Write
	// tab. jsdom computes no layout, so the real cascade has to be injected onto
	// the action bar before its position can be read back; this proves the
	// action sits in its own end-of-tab container and that container is the
	// one declared sticky.
	it('pins the Generate action in a sticky action bar at the end of the Write tab', async () => {
		const target = await render();
		const actionBar = target.querySelector('[role="tabpanel"] > :last-child');
		expect(actionBar?.classList.contains('write-actionbar')).toBe(true);
		expect(actionBar?.querySelector('.generate-action')).not.toBeNull();
		if (!actionBar) throw new Error('Expected an action bar');
		injectComponentStyles(songPhoneViewSource, 'SongPhoneView.svelte', actionBar);
		expect(getComputedStyle(actionBar).position).toBe('sticky');
	});

	it('raises the reserved Write space to match a taller action bar (#993 follow-up)', async () => {
		// jsdom ships no ResizeObserver (src/tests/setup.ts stubs an inert one); this
		// records the real callback so the test can fire it like the browser would
		// once the action bar changes size.
		const resizeCallbacks: ResizeObserverCallback[] = [];
		vi.stubGlobal(
			'ResizeObserver',
			class {
				constructor(callback: ResizeObserverCallback) {
					resizeCallbacks.push(callback);
				}
				observe(): void {}
				unobserve(): void {}
				disconnect(): void {}
			}
		);
		const triggerResize = () => {
			for (const callback of resizeCallbacks) callback([], {} as ResizeObserver);
		};
		const target = await render();
		const actionBar = target.querySelector<HTMLElement>('.write-actionbar');
		const writeScroll = target.querySelector<HTMLElement>('.write-scroll');
		if (!actionBar || !writeScroll) throw new Error('Expected the action bar and write scroll');

		vi.spyOn(actionBar, 'offsetHeight', 'get').mockReturnValue(140);
		triggerResize();
		await tick();

		expect(writeScroll.style.getPropertyValue('--generate-bar-height')).toBe('140px');
	});

	it('replaces the whole page with the Co-Writer screen instead of showing it beside the tabs', async () => {
		const target = await render();
		expect(target.querySelector('[role="tab"]')).not.toBeNull();

		coWriterOpen.set(true);
		await tick();

		expect(target.querySelector('.cowriter-screen')).not.toBeNull();
		expect(target.querySelector('[role="tab"]')).toBeNull();
		expect(target.querySelector('#song-phone-panel')).toBeNull();
		expect(target.querySelector('.generate-action')).toBeNull();

		coWriterOpen.set(false);
		await tick();

		expect(target.querySelector('.cowriter-screen')).toBeNull();
		expect(target.querySelector('[role="tab"]')).not.toBeNull();
	});
});
