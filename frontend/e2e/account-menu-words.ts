import type { Locator } from '@playwright/test';

// The kit's panel owns these words.
export const LOG_OUT_NAME = 'Log out';

export function themeChoiceRadio(menu: Locator, name: 'Follow system' | 'Light' | 'Dark'): Locator {
	return menu.getByRole('radio', { name, exact: true });
}
