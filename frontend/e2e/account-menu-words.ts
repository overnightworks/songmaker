import type { Locator } from '@playwright/test';
// The package root re-exports Svelte components, which Node cannot load; the words entry loads under plain Node.
import { loadKitWords } from 'overnightworks-design/words';

export const kitWords = await loadKitWords('en');

export const LOG_OUT_NAME = kitWords['account.logOut'];

export function themeChoiceRadio(
	menu: Locator,
	choice: 'account.followSystem' | 'account.light' | 'account.dark'
): Locator {
	return menu.getByRole('radio', { name: kitWords[choice], exact: true });
}
