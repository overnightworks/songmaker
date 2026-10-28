import { createRawSnippet, mount, tick, unmount } from 'svelte';
import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { detailTab, type DetailTab } from '$lib/stores/navigation';
import { makeSong } from '$lib/test-utils/factories';
import ListenTabs from './ListenTabs.svelte';
import listenTabsSource from './ListenTabs.svelte?raw';

const mounted: Array<ReturnType<typeof mount>> = [];
const paneSnippets = {
	expiryDigest: createRawSnippet(() => ({ render: () => '<div>Expiry digest</div>' })),
	cowriter: createRawSnippet(() => ({
		render: () => '<div class="cowriter-screen"><textarea aria-label="Message"></textarea></div>'
	}))
};

beforeEach(() => detailTab.set('edit'));

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	detailTab.set('edit');
});

async function render(generationCount = 11) {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(
		mount(ListenTabs, {
			target,
			props: {
				...paneSnippets,
				takeListProps: {
					song: makeSong({ generations: [], generation_count: generationCount }),
					dirty: false,
					draftVersionNumber: 2,
					latestVersionNumber: 1,
					onsource: vi.fn()
				}
			}
		})
	);
	await tick();
	return target;
}

function listenTab(target: HTMLElement, tab: 'takes' | 'cowriter'): HTMLButtonElement {
	const found = target.querySelector<HTMLButtonElement>(`[role="tab"][data-tab="${tab}"]`);
	if (!found) throw new Error(`Expected the ${tab} tab`);
	return found;
}

const takesPane = (target: HTMLElement) => target.querySelector('.takes-pane');
const cowriterPane = (target: HTMLElement) =>
	target.querySelector<HTMLElement>('.cowriter-screen')?.closest<HTMLElement>('[role="tabpanel"]');

describe('ListenTabs', () => {
	it.each<DetailTab>(['takes', 'edit'])(
		'selects Takes while the detail tab is %s (S9, #1927 acceptance 1)',
		async (tab) => {
			detailTab.set(tab);
			const target = await render();
			expect(listenTab(target, 'takes').getAttribute('aria-selected')).toBe('true');
			expect(listenTab(target, 'cowriter').getAttribute('aria-selected')).toBe('false');
		}
	);

	it('selects Co-writer while the detail tab is cowriter (S9, #1927 acceptance 1)', async () => {
		detailTab.set('cowriter');
		const target = await render();
		expect(listenTab(target, 'cowriter').getAttribute('aria-selected')).toBe('true');
		expect(listenTab(target, 'takes').getAttribute('aria-selected')).toBe('false');
	});

	it('labels the tabs with the take count (S9, #1927 acceptance 1)', async () => {
		const target = await render(11);
		const labels = Array.from(target.querySelectorAll('[role="tab"]')).map((tab) =>
			tab.textContent?.replace(/\s+/g, ' ').trim()
		);
		expect(labels).toEqual(['Takes 11', 'Co-writer']);
	});

	it('writes the clicked tab to the detail tab (S9, #1927 acceptance 5)', async () => {
		const target = await render();
		listenTab(target, 'cowriter').click();
		await tick();
		expect(get(detailTab)).toBe('cowriter');
		listenTab(target, 'takes').click();
		await tick();
		expect(get(detailTab)).toBe('takes');
	});

	it.each([
		['ArrowRight', 'takes', 'cowriter'],
		['ArrowRight', 'cowriter', 'takes'],
		['ArrowLeft', 'takes', 'cowriter'],
		['ArrowLeft', 'cowriter', 'takes'],
		['Home', 'cowriter', 'takes'],
		['End', 'takes', 'cowriter']
	] as const)(
		'moves and focuses the tab for %s from %s (S9, #1927 acceptance 10)',
		async (key, from, to) => {
			detailTab.set(from);
			const target = await render();
			const current = listenTab(target, from);
			current.focus();
			current.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));
			await tick();
			expect(get(detailTab)).toBe(to);
			expect(document.activeElement).toBe(listenTab(target, to));
		}
	);

	it('keeps tab targets and panel wiring of a real tablist (S9, #1927 acceptance 10)', async () => {
		const target = await render();
		expect(target.querySelector('[role="tablist"]')).not.toBeNull();
		const takes = listenTab(target, 'takes');
		expect(takes.tabIndex).toBe(0);
		expect(listenTab(target, 'cowriter').tabIndex).toBe(-1);
		const panel = document.getElementById(takes.getAttribute('aria-controls') ?? '');
		expect(panel?.getAttribute('role')).toBe('tabpanel');
	});

	it('names a panel in aria-controls only while that panel is in the page (C5, #1935 acceptance 10)', async () => {
		const target = await render();
		expect(listenTab(target, 'cowriter').hasAttribute('aria-controls')).toBe(false);
		for (const tab of ['takes', 'cowriter'] as const) {
			listenTab(target, tab).click();
			await tick();
			const controls = listenTab(target, tab).getAttribute('aria-controls') ?? '';
			expect(document.getElementById(controls)?.getAttribute('role')).toBe('tabpanel');
		}
		expect(listenTab(target, 'takes').hasAttribute('aria-controls')).toBe(false);
	});

	it('sums no pixel chrome height for the Co-writer pane (C5, #1935 acceptance 8)', () => {
		expect(listenTabsSource).not.toMatch(/calc\(100dvh - \d+px\)/);
	});

	it('mounts the Takes pane only while Takes is selected (S9, #1927 acceptance 4)', async () => {
		const target = await render();
		expect(takesPane(target)).not.toBeNull();
		expect(target.textContent).toContain('Expiry digest');
		listenTab(target, 'cowriter').click();
		await tick();
		expect(takesPane(target)).toBeNull();
	});

	it('does not mount the Co-writer before its first open and keeps it mounted, hidden, after leaving (S9, #1927 acceptance 3)', async () => {
		const target = await render();
		expect(target.querySelector('.cowriter-screen')).toBeNull();
		listenTab(target, 'cowriter').click();
		await tick();
		const composer = target.querySelector('.cowriter-screen textarea') as HTMLTextAreaElement;
		composer.value = 'mach den Chorus härter';
		expect(cowriterPane(target)?.hidden).toBe(false);
		listenTab(target, 'takes').click();
		await tick();
		expect(cowriterPane(target)?.hidden).toBe(true);
		listenTab(target, 'cowriter').click();
		await tick();
		expect(target.querySelector('.cowriter-screen textarea')).toBe(composer);
		expect(composer.value).toBe('mach den Chorus härter');
		expect(cowriterPane(target)?.hidden).toBe(false);
	});
});
