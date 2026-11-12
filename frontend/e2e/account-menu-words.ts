import type { Locator } from '@playwright/test';
// The package root re-exports Svelte components, which Node cannot load, and the package exports no words entry.
import { words as kitWords } from '../node_modules/overnightworks-design/svelte-dist/words/en.js';

export { kitWords };

export const LOG_OUT_NAME = kitWords['account.logOut'];

export function themeChoiceRadio(
	menu: Locator,
	choice: 'account.followSystem' | 'account.light' | 'account.dark'
): Locator {
	return menu.getByRole('radio', { name: kitWords[choice], exact: true });
}
