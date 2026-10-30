import { createRawSnippet, mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import { LEGAL_SECTIONS } from '#lib/constants/legal.ts';
import LegalLinks from './LegalLinks.svelte';

let mounted: ReturnType<typeof mount> | undefined;

async function render(
	props: {
		newTab?: boolean;
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
	it('1785_rule_1 links each legal text to its section on the central site, in the same tab', async () => {
		const target = await render();

		const links = Array.from(target.querySelectorAll('a'));
		expect(links.map((link) => [link.textContent, link.getAttribute('href')])).toEqual([
			['Impressum', 'https://hallucinai.de/impressum#songmaker'],
			['Datenschutz', 'https://hallucinai.de/datenschutz#songmaker'],
			['Nutzungsbedingungen', 'https://hallucinai.de/nutzungsbedingungen#songmaker']
		]);
		expect(links.map((link) => link.getAttribute('target'))).toEqual([null, null, null]);
	});

	it('1785_rule_1 opens the links in a new tab for a page that must not be left', async () => {
		const target = await render({ newTab: true });

		const links = Array.from(target.querySelectorAll('a'));
		expect(links).toHaveLength(LEGAL_SECTIONS.length);
		for (const link of links) {
			expect(link.getAttribute('target')).toBe('_blank');
			expect(link.getAttribute('rel')).toContain('noopener');
		}
		expect(target.querySelectorAll('button')).toHaveLength(0);
	});

	it('puts what leads the row first, with the dot drawn by CSS rather than written', async () => {
		const lead = createRawSnippet(() => ({ render: () => '<span>Powered by</span>' }));
		const target = await render({ lead });

		const items = Array.from(target.querySelectorAll('.legal-item')).map((item) =>
			item.textContent?.trim()
		);
		expect(items).toEqual(['Powered by', ...LEGAL_SECTIONS.map((section) => section.label)]);
		expect(target.textContent).not.toContain('·');
	});
});
