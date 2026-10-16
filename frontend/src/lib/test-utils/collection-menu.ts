// The rows of an open collection menu as a person reads them: each row's
// word, without the hint or state its right edge shows.

function rowLabel(row: Element): string {
	const hint = row.querySelector('.menu-item-hint')?.textContent ?? '';
	return (row.textContent ?? '').replace(hint, '').trim();
}

export function menuRowLabels(menu: ParentNode): string[] {
	return Array.from(menu.querySelectorAll('.menu-item')).map(rowLabel);
}

export function menuRow(menu: ParentNode, label: string): HTMLButtonElement {
	const row = Array.from(menu.querySelectorAll<HTMLButtonElement>('.menu-item')).find(
		(candidate) => rowLabel(candidate) === label
	);
	if (!row) throw new Error(`Expected a menu row named "${label}"`);
	return row;
}
