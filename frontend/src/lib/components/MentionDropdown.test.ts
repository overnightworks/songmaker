import { makeVersion } from '#lib/test-utils/factories.ts';
import { mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import MentionDropdown from './MentionDropdown.svelte';

let mounted: ReturnType<typeof mount> | undefined;

afterEach(async () => {
	if (mounted) await unmount(mounted);
	mounted = undefined;
	document.body.replaceChildren();
});

describe('MentionDropdown', () => {
	it('titles the album row @album and a version row @v with its number', async () => {
		const target = document.createElement('div');
		document.body.append(target);
		mounted = mount(MentionDropdown, {
			target,
			props: {
				items: [{ type: 'album' }, { type: 'version', item: makeVersion({ version_number: 3 }) }],
				selectedIndex: 0,
				albumTitle: 'Night Drive',
				onselect: () => undefined
			}
		});
		await tick();

		expect(Array.from(target.querySelectorAll('.mention-title'), (el) => el.textContent)).toEqual([
			'@album',
			'@v3'
		]);
	});
});
