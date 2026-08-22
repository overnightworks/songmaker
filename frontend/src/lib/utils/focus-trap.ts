const FOCUSABLE_SELECTOR = 'a[href], button:not(:disabled), [tabindex]:not([tabindex="-1"])';

export function focusableElements(container: HTMLElement): HTMLElement[] {
	return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
}

export function focusFirstIn(container: HTMLElement): void {
	const first = focusableElements(container)[0];
	(first ?? container).focus();
}

function trapTabKey(container: HTMLElement, event: KeyboardEvent): void {
	const focusable = focusableElements(container);
	if (focusable.length === 0) {
		event.preventDefault();
		container.focus();
		return;
	}
	const first = focusable[0];
	const last = focusable[focusable.length - 1];
	const active = document.activeElement;
	const outside = !container.contains(active);
	if (event.shiftKey && (active === first || active === container || outside)) {
		event.preventDefault();
		last.focus();
	} else if (!event.shiftKey && (active === last || outside)) {
		event.preventDefault();
		first.focus();
	}
}

/**
 * Keeps focus inside `container` while it acts as a modal-like surface
 * (drawer, dropdown menu, dialog): Escape calls `onEscape`, Tab/Shift+Tab
 * wrap at the container's edges instead of leaving it.
 */
export function handleFocusTrapKeydown(
	container: HTMLElement,
	event: KeyboardEvent,
	onEscape: () => void
): void {
	if (event.key === 'Escape') {
		event.preventDefault();
		onEscape();
		return;
	}
	if (event.key !== 'Tab') return;
	trapTabKey(container, event);
}
