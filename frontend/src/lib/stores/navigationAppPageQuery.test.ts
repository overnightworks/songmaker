import { get } from 'svelte/store';
import { goto } from '$app/navigation';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { discardDraft, loadSongData, setDraftLyrics } from '#lib/stores/editor.ts';
import {
	followAppPageLink,
	openAppPage,
	pendingDirtyNavigation,
	resetNavigationForTests
} from '#lib/stores/navigation.ts';
import { makeSong as song } from '#lib/test-utils/factories.ts';

vi.mock('$app/navigation', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppNavigation()
);
vi.mock('$app/state', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppState()
);
vi.mock('$app/paths', () => ({
	resolve: vi.fn((path: string) => path)
}));

const REFERENCES_PAGE = '/settings/references';

beforeEach(() => {
	resetNavigationForTests();
	vi.mocked(goto).mockClear();
});

afterEach(discardDraft);

describe('an app page opened with a query', () => {
	it('reaches the address with the query', async () => {
		await openAppPage(REFERENCES_PAGE, { reference: 'r 1' });

		expect(vi.mocked(goto)).toHaveBeenCalledWith(`${REFERENCES_PAGE}?reference=r+1`);
	});

	it('reaches the bare address without one', async () => {
		await openAppPage(REFERENCES_PAGE);

		expect(vi.mocked(goto)).toHaveBeenCalledWith(REFERENCES_PAGE);
	});

	it('follows a plain click with the query', async () => {
		followAppPageLink(new MouseEvent('click', { button: 0 }), REFERENCES_PAGE, {
			reference: 'r1'
		});

		await vi.waitFor(() =>
			expect(vi.mocked(goto)).toHaveBeenCalledWith(`${REFERENCES_PAGE}?reference=r1`)
		);
	});

	it('waits for the unsaved-changes answer before it leaves', async () => {
		loadSongData(song({ slug: 's1' }));
		setDraftLyrics('unsaved edit');

		await openAppPage(REFERENCES_PAGE, { reference: 'r1' });

		expect(vi.mocked(goto)).not.toHaveBeenCalled();
		await get(pendingDirtyNavigation)?.();
		expect(vi.mocked(goto)).toHaveBeenCalledWith(`${REFERENCES_PAGE}?reference=r1`);
	});
});
