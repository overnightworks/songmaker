// Every legal link points to the central site, with songmaker's section
// anchor (#1785). The hrefs are read, never followed: the central pages are
// served by another repository.

import { expect, test, type Locator, type Page } from '@playwright/test';
import { LEGAL_SECTIONS } from '../src/lib/constants/legal';
import { FlowGuard } from './helpers';
import { MOCK_STREAM_REFUSAL, openMockSharedAlbum } from './share-album-fixtures';

const EXPECTED_ADDRESSES = [
	['Impressum', 'https://hallucinai.de/impressum#songmaker'],
	['Datenschutz', 'https://hallucinai.de/datenschutz#songmaker'],
	['Nutzungsbedingungen', 'https://hallucinai.de/nutzungsbedingungen#songmaker']
];

function shareLegalLinks(page: Page): Locator {
	return page.locator('.legal-links .legal-link');
}

async function legalLinks(links: Locator): Promise<(string | null)[][]> {
	return links.evaluateAll((elements) =>
		elements.map((link) => [
			link.textContent,
			link.getAttribute('href'),
			link.getAttribute('target')
		])
	);
}

test('1785_rule_1 the legal links name the central addresses', () => {
	expect(LEGAL_SECTIONS.map(({ label, href }) => [label, href])).toEqual(EXPECTED_ADDRESSES);
});

test.describe('anonymous visitor', () => {
	test.use({ storageState: { cookies: [], origins: [] } });

	test('1785_rule_3 the sign-in page links the central legal pages in the same tab', async ({
		page
	}) => {
		const guard = new FlowGuard(page);
		await page.goto('/login');
		const signInLegalLinks = page.getByRole('navigation').getByRole('link');
		await expect(signInLegalLinks).toHaveCount(EXPECTED_ADDRESSES.length);

		expect(await legalLinks(signInLegalLinks)).toEqual(
			EXPECTED_ADDRESSES.map((row) => [...row, null])
		);
		guard.assertClean();
	});

	test('1785_rule_3 a share page links them in new tabs, so playback keeps running', async ({
		page
	}) => {
		const guard = new FlowGuard(page, { refusalsExpectedOn: [MOCK_STREAM_REFUSAL] });
		await openMockSharedAlbum(page);

		expect(await legalLinks(shareLegalLinks(page))).toEqual(
			EXPECTED_ADDRESSES.map((row) => [...row, '_blank'])
		);
		guard.assertClean();
	});
});

test('1785_rule_3 a share page opened while signed in links them the same way', async ({
	page
}) => {
	const guard = new FlowGuard(page, { refusalsExpectedOn: [MOCK_STREAM_REFUSAL] });
	await openMockSharedAlbum(page);

	expect(await legalLinks(shareLegalLinks(page))).toEqual(
		EXPECTED_ADDRESSES.map((row) => [...row, '_blank'])
	);
	guard.assertClean();
});
