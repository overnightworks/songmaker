import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
	installHistoryController,
	leaveByPostingForm,
	loadAfresh,
	pushEntry,
	reloadAfresh,
	resetHistoryControllerForTests,
	standInForDocumentLoadsForTests
} from '$lib/history/historyController';
import { holdLayer, resetLayersForTests } from '$lib/stores/layers';
import { documentLoadsStandIn } from '$lib/test-utils/document-loads';

// Issue #1340, ruling A: a sign-out or a lost session leaves by a fresh
// document load. Over a layer's entry the load replaces it, so Back finds no
// copy of the page to step off and nothing steps back meanwhile; over a page
// entry it keeps the page, so Back loads it afresh. A sign-out leaves by a form
// POST, which cannot replace an entry and is pushed over either kind (#1807, K1).
describe('leaving for a fresh document', () => {
	const loads = documentLoadsStandIn();

	beforeEach(() => {
		sessionStorage.clear();
		history.replaceState(null, '', '/settings/voices');
		resetHistoryControllerForTests();
		installHistoryController();
		standInForDocumentLoadsForTests(loads);
		for (const load of Object.values(loads)) load.mockClear();
	});

	afterEach(() => {
		resetHistoryControllerForTests();
		resetLayersForTests();
		vi.restoreAllMocks();
	});

	const origin = window.location.origin;

	// A `#` part reaches the address through a take's provenance link or a
	// bookmark; a load to an address that differs only in it would scroll to
	// the anchor and load nothing.
	it.each([
		{
			leave: 'sign-in',
			over: 'a page entry',
			standing: '/settings/voices',
			openLayer: false,
			go: () => loadAfresh('/login'),
			load: 'assign',
			args: [`${origin}/login`]
		},
		{
			leave: 'sign-in',
			over: "an open layer's entry",
			standing: '/settings/voices',
			openLayer: true,
			go: () => loadAfresh('/login'),
			load: 'replace',
			args: [`${origin}/login`]
		},
		{
			leave: 'an address that differs from the standing one only in its `#` part',
			over: 'a page entry',
			standing: '/album/a1/song-1#take-12',
			openLayer: false,
			go: () => loadAfresh('/album/a1/song-1#take-3'),
			load: 'assign',
			args: [`${origin}/album/a1/song-1`]
		},
		{
			leave: 'the standing address',
			over: 'a page entry',
			standing: '/settings/voices',
			openLayer: false,
			go: reloadAfresh,
			load: 'reload',
			args: []
		},
		{
			leave: 'the standing address',
			over: "an open layer's entry",
			standing: '/settings/voices',
			openLayer: true,
			go: reloadAfresh,
			load: 'replace',
			args: [`${origin}/settings/voices`]
		},
		{
			leave: 'the standing address with a `#` part',
			over: 'a page entry',
			standing: '/album/a1/song-1#take-12',
			openLayer: false,
			go: reloadAfresh,
			load: 'reload',
			args: []
		},
		{
			leave: 'the standing address with a `#` part',
			over: "an open layer's entry",
			standing: '/album/a1/song-1#take-12',
			openLayer: true,
			go: reloadAfresh,
			load: 'replace',
			args: [`${origin}/album/a1/song-1`]
		},
		{
			leave: 'the sign-out form',
			over: 'a page entry',
			standing: '/settings/voices',
			openLayer: false,
			go: () => leaveByPostingForm('/auth/logout'),
			load: 'submitPost',
			args: ['/auth/logout']
		},
		{
			leave: 'the sign-out form',
			over: "an open layer's entry",
			standing: '/settings/voices',
			openLayer: true,
			go: () => leaveByPostingForm('/auth/logout'),
			load: 'submitPost',
			args: ['/auth/logout']
		}
	] as const)(
		'loads $leave afresh over $over by $load, and steps back nowhere',
		async ({ standing, openLayer, go, load, args }) => {
			pushEntry(standing, {});
			if (openLayer) holdLayer('account-menu', () => undefined);
			const backs = vi.spyOn(history, 'back');

			await go();

			expect(loads[load]).toHaveBeenCalledExactlyOnceWith(...args);
			const others = Object.entries(loads).filter(([name]) => name !== load);
			for (const [, other] of others) expect(other).not.toHaveBeenCalled();
			expect(backs).not.toHaveBeenCalled();
		}
	);

	// Two library requests refused together each react to the lost session;
	// every further load would abort the one before it (CI run 38602720334).
	it.each([
		{
			first: 'the standing address',
			then: 'the standing address',
			go: [reloadAfresh, reloadAfresh],
			load: 'reload'
		},
		{
			first: 'sign-in',
			then: 'the standing address',
			go: [() => loadAfresh('/login'), reloadAfresh],
			load: 'assign'
		},
		{
			first: 'the standing address',
			then: 'sign-in',
			go: [reloadAfresh, () => loadAfresh('/login')],
			load: 'reload'
		},
		{
			first: 'the sign-out form',
			then: 'the standing address',
			go: [() => leaveByPostingForm('/auth/logout'), reloadAfresh],
			load: 'submitPost'
		}
	] as const)('leaves once when $first and $then are asked for together', async ({ go, load }) => {
		pushEntry('/settings/voices', {});

		await Promise.all(go.map((leave) => leave()));
		await reloadAfresh();

		expect(loads[load]).toHaveBeenCalledOnce();
		const others = Object.entries(loads).filter(([name]) => name !== load);
		for (const [, other] of others) expect(other).not.toHaveBeenCalled();
	});

	// Playwright runs without the back-forward cache, so this row is the guard's
	// only proof: Back onto the page a sign-out left would otherwise show it
	// again with the signed-in state still in memory.
	it.each([
		{
			shown: 'restored from the back-forward cache after leaving',
			left: true,
			persisted: true,
			reloads: 1
		},
		{
			shown: 'restored from the back-forward cache without leaving',
			left: false,
			persisted: true,
			reloads: 0
		},
		{ shown: 'loaded anew after leaving', left: true, persisted: false, reloads: 0 },
		{
			shown: 'restored from the back-forward cache after leaving by form',
			left: true,
			persisted: true,
			reloads: 1,
			leaveWith: () => leaveByPostingForm('/auth/logout')
		}
	])('a page $shown is loaded afresh $reloads time(s)', async (row) => {
		const { left, persisted, reloads } = row;
		pushEntry('/settings/voices', {});
		if (left) await (row.leaveWith?.() ?? loadAfresh('/login'));

		window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted }));

		expect(loads.reload).toHaveBeenCalledTimes(reloads);
	});
});
