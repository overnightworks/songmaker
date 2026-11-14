import { words } from '#lib/words/en.ts';
import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import { HOME_ROUTE_PATH } from '#lib/routes/addresses.ts';
import { LEGAL_SECTIONS } from '#lib/constants/legal.ts';
import SharedFooter from './SharedFooter.svelte';

let mounted: ReturnType<typeof mount> | undefined;

async function render(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted = mount(SharedFooter, { target });
	await tick();
	return target;
}

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
});

describe('SharedFooter legal links', () => {
	it.each(LEGAL_SECTIONS)(
		'1785_rule_1 opens $labelKey on the central site in a new tab, so playback keeps running',
		async ({ labelKey, href }) => {
			const target = await render();

			const link = Array.from(target.querySelectorAll('a')).find(
				(anchor) => anchor.textContent === words[labelKey]
			);
			expect(link?.getAttribute('href')).toBe(href);
			expect(link?.getAttribute('target')).toBe('_blank');
			expect(target.querySelector('[role="dialog"]')).toBeNull();
		}
	);
});

describe('SharedFooter brand line', () => {
	it('links the app name to the home page inside the powered-by sentence', async () => {
		const target = await render();

		const lead = target.querySelector('.lead');
		const link = lead?.querySelector('a');
		const [leadText] = words['sharedFooter.poweredBy']({ app: words['app.name'] });
		expect(lead?.textContent?.startsWith(leadText as string)).toBe(true);
		expect(link?.textContent).toBe(words['app.name']);
		expect(link?.getAttribute('href')).toBe(HOME_ROUTE_PATH);
	});
});
