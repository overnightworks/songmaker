import { expect, type Page } from '@playwright/test';

/** The computed colour of a CSS custom property, read through a probe element. */
export async function tokenColor(page: Page, token: string): Promise<string> {
	return page.evaluate((name) => {
		const probe = document.createElement('span');
		probe.style.color = `var(${name})`;
		document.body.append(probe);
		const { color } = getComputedStyle(probe);
		probe.remove();
		return color;
	}, token);
}

export function relativeLuminance(cssColor: string): number {
	const channels = cssColor
		.match(/[\d.]+/g)
		?.slice(0, 3)
		.map(Number);
	if (channels?.length !== 3) throw new Error(`not an rgb colour: ${cssColor}`);
	const [red, green, blue] = channels.map((channel) => {
		const unit = channel / 255;
		return unit <= 0.03928 ? unit / 12.92 : ((unit + 0.055) / 1.055) ** 2.4;
	});
	return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

/** WCAG contrast ratio between two computed `rgb()` colours. */
export function contrastRatio(foreground: string, background: string): number {
	const [lighter, darker] = [relativeLuminance(foreground), relativeLuminance(background)].sort(
		(a, b) => b - a
	);
	return (lighter + 0.05) / (darker + 0.05);
}

/** The page painted in the emulated device theme: no stored choice overrides it. */
export async function expectEmulatedTheme(
	page: Page,
	colorScheme: 'light' | 'dark'
): Promise<void> {
	const painted = await page.evaluate(() => ({
		dark: matchMedia('(prefers-color-scheme: dark)').matches,
		chosen: document.documentElement.dataset.theme
	}));
	expect(painted).toEqual({ dark: colorScheme === 'dark', chosen: undefined });
}
