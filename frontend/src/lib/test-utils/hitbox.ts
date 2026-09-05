import { HITBOX_STYLE } from '$lib/styles/hitbox';

const STYLE_ATTRIBUTE = 'data-hitbox-styles';

// The hitbox primitive is a global stylesheet the app injects from its layout,
// so a component test that measures a target has to inject it too — jsdom
// applies no Svelte scoped styles, and without this sheet there is nothing to
// measure at all.
export function injectHitboxStyles(): void {
	const sheet = document.createElement('style');
	sheet.setAttribute(STYLE_ATTRIBUTE, 'true');
	sheet.textContent = HITBOX_STYLE;
	document.head.append(sheet);
}

export function clearHitboxStyles(): void {
	document.head.querySelectorAll(`[${STYLE_ATTRIBUTE}]`).forEach((el) => el.remove());
}

// jsdom hands a length declared as a custom property back verbatim, so a
// measurement has to resolve the token against the root element itself.
export function px(value: string, label = 'length'): number {
	const resolved = value.startsWith('var(')
		? getComputedStyle(document.documentElement)
				.getPropertyValue(value.slice('var('.length, -1).trim())
				.trim()
		: value;
	const parsed = Number.parseFloat(resolved);
	if (!Number.isFinite(parsed)) {
		throw new TypeError(`${label} is not a pixel length: ${value === '' ? '(empty)' : value}`);
	}
	return parsed;
}

// A labelled control's width is its label's, so only its height is a hitbox
// promise; an icon-only control promises both.
export function minHeightPx(el: Element, name: string): number {
	return px(getComputedStyle(el).minHeight, `${name} min-height`);
}

export function minSquarePx(el: Element, name: string): { width: number; height: number } {
	const style = getComputedStyle(el);
	return {
		width: px(style.minWidth, `${name} min-width`),
		height: px(style.minHeight, `${name} min-height`)
	};
}

export function setPointer(kind: 'coarse' | 'fine'): void {
	document.documentElement.dataset.pointer = kind;
}

export function clearPointer(): void {
	delete document.documentElement.dataset.pointer;
}
