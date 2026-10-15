import { createRawSnippet, mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { getByRoleButton } from '$lib/test-utils/accessible-name';
import LegalLinks, { LEGAL_SECTIONS, type LegalSection } from './LegalLinks.svelte';
import legalLinksSource from './LegalLinks.svelte?raw';

let mounted: ReturnType<typeof mount> | undefined;

async function render(
	props: {
		onopen?: (section: LegalSection) => void;
		lead?: ReturnType<typeof createRawSnippet>;
	} = {}
): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(LegalLinks, { target, props });
	await tick();
	return target;
}

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
});

describe('LegalLinks', () => {
	it('links each legal text to its section of the legal page', async () => {
		const target = await render();

		expect(
			Array.from(target.querySelectorAll('a')).map((link) => [
				link.textContent,
				link.getAttribute('href')
			])
		).toEqual([
			['Impressum', '/legal#impressum'],
			['Datenschutz', '/legal#datenschutz'],
			['Nutzungsbedingungen', '/legal#nutzungsbedingungen']
		]);
	});

	it.each(LEGAL_SECTIONS)(
		'opens $label in place for a page that must not be left',
		async ({ id, label }) => {
			const onopen = vi.fn();
			const target = await render({ onopen });

			getByRoleButton(target, label).click();

			expect(onopen).toHaveBeenCalledWith(id);
			expect(target.querySelectorAll('a')).toHaveLength(0);
		}
	);

	it('puts what leads the row first, with the dot drawn by CSS rather than written', async () => {
		const lead = createRawSnippet(() => ({ render: () => '<span>Powered by</span>' }));
		const target = await render({ lead });

		const items = Array.from(target.querySelectorAll('.legal-item')).map((item) =>
			item.textContent?.trim()
		);
		expect(items).toEqual(['Powered by', ...LEGAL_SECTIONS.map((section) => section.label)]);
		expect(target.textContent).not.toContain('·');
	});

	it('draws the separator only before items after the first, so wrapping never strands a dot', () => {
		const selector = '.legal-item:not(:first-child)::before';
		const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
		const match = new RegExp(`${escaped}\\s*{([^}]*)}`).exec(legalLinksSource);

		expect(match?.[1]).toContain("content: '·'");
	});
});
