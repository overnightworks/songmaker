import { type Page } from '@playwright/test';
import { wallBody } from './helpers';

// The app captures the real scroll event; rendering finishes before callers leave.
export async function scrollWallTo(page: Page, position: 'halfway' | 'bottom'): Promise<number> {
	return wallBody(page).evaluate(
		(body, position) =>
			new Promise<number>((resolve, reject) => {
				const maximum = body.scrollHeight - body.clientHeight;
				if (maximum <= 0) return reject(new Error('The seeded wall must overflow'));
				const target = position === 'halfway' ? Math.round(maximum / 2) : maximum;
				const captured = () => {
					requestAnimationFrame(() => {
						requestAnimationFrame(() => resolve(Math.round(body.scrollTop)));
					});
				};
				if (Math.round(body.scrollTop) === target) return captured();
				body.addEventListener('scroll', captured, { once: true });
				body.scrollTop = target;
			}),
		position
	);
}
