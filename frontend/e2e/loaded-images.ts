import { expect, type Locator } from '@playwright/test';

export async function loadedImages(images: Locator) {
	for (const image of await images.all()) {
		await expect
			.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth))
			.toBeGreaterThan(0);
	}
}
