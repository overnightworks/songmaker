// Minimal accessible-name lookup for unit tests, covering the one rule these
// components rely on: an element's own aria-label wins over its content. Not
// a full accname implementation — for the real accessibility tree, the e2e
// suite drives a real browser instead.

export function accessibleName(element: Element): string {
	return element.getAttribute('aria-label')?.trim() ?? element.textContent?.trim() ?? '';
}

export function getByRoleHeading(root: ParentNode, name: string): HTMLHeadingElement {
	const heading = Array.from(
		root.querySelectorAll<HTMLHeadingElement>('h1, h2, h3, h4, h5, h6')
	).find((el) => accessibleName(el) === name);
	if (!heading) throw new Error(`Expected a heading named "${name}"`);
	return heading;
}

export function getByRoleButton(root: ParentNode, name: string): HTMLButtonElement {
	const button = Array.from(root.querySelectorAll<HTMLButtonElement>('button')).find(
		(el) => accessibleName(el) === name
	);
	if (!button) throw new Error(`Expected a button named "${name}"`);
	return button;
}
