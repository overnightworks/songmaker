import { afterEach, describe, expect, it, vi } from 'vitest';

import { DRAG_THRESHOLD_PX, kineticScroll, type KineticScrollAxis } from './kineticScroll';

// jsdom performs no layout (clientWidth/scrollWidth are always 0) and ships
// neither requestAnimationFrame timing nor matchMedia by default. These
// helpers give the action a controllable, deterministic stand-in for all
// three so the momentum/friction math can be driven frame-by-frame instead
// of racing real timers.
let now = 0;
let pendingFrame: FrameRequestCallback | null = null;

function stubBrowserTiming() {
	now = 0;
	pendingFrame = null;
	vi.stubGlobal(
		'requestAnimationFrame',
		vi.fn((cb: FrameRequestCallback) => {
			pendingFrame = cb;
			return 1;
		})
	);
	vi.stubGlobal(
		'cancelAnimationFrame',
		vi.fn(() => {
			pendingFrame = null;
		})
	);
	vi.stubGlobal('performance', { now: () => now });
}

function runFrame(dtMs: number) {
	now += dtMs;
	const cb = pendingFrame;
	pendingFrame = null;
	cb?.(now);
}

function stubReducedMotion(matches: boolean) {
	vi.stubGlobal(
		'matchMedia',
		vi.fn(() => ({
			matches,
			media: '(prefers-reduced-motion: reduce)',
			onchange: null,
			addEventListener: vi.fn(),
			removeEventListener: vi.fn(),
			addListener: vi.fn(),
			removeListener: vi.fn(),
			dispatchEvent: vi.fn()
		}))
	);
}

function buildStrip(axis: KineticScrollAxis, itemCount = 4) {
	const container = document.createElement('div');
	const items: HTMLButtonElement[] = [];
	for (let i = 0; i < itemCount; i++) {
		const item = document.createElement('button');
		item.type = 'button';
		item.className = 'item';
		item.dataset.title = `item-${i}`;
		container.appendChild(item);
		items.push(item);
	}
	document.body.appendChild(container);
	setStripAxis(container, axis);
	if (axis === 'x') {
		Object.defineProperty(container, 'clientWidth', { value: 100, configurable: true });
		Object.defineProperty(container, 'scrollWidth', { value: 400, configurable: true });
	} else {
		Object.defineProperty(container, 'clientHeight', { value: 100, configurable: true });
		Object.defineProperty(container, 'scrollHeight', { value: 400, configurable: true });
	}
	return { container, items };
}

// The action reads its axis from computed flex-direction, never from a
// caller option (issue #358) — jsdom resolves this property from a plain
// inline style without needing real layout, which is the one part of
// "computed style" jsdom can honestly stand in for. overflow-x/overflow-y
// cannot stand in for it here: a real browser (not jsdom) showed that a
// `visible` overflow paired with a scrolling sibling axis is itself computed
// as `auto`, so those two properties can't tell the axes apart for this
// row/column toggle — see the reasoning on `readAxis` in kineticScroll.ts.
function setStripAxis(container: HTMLElement, axis: KineticScrollAxis) {
	container.style.display = 'flex';
	container.style.flexDirection = axis === 'y' ? 'column' : 'row';
}

function firePointer(
	target: EventTarget,
	type: 'pointerdown' | 'pointermove' | 'pointerup' | 'pointercancel',
	opts: {
		pos: number;
		axis: KineticScrollAxis;
		t: number;
		pointerId?: number;
		pointerType?: string;
		button?: number;
	}
) {
	const init: PointerEventInit = {
		pointerId: opts.pointerId ?? 1,
		pointerType: opts.pointerType ?? 'mouse',
		button: opts.button ?? 0,
		bubbles: true,
		cancelable: true,
		...(opts.axis === 'x' ? { clientX: opts.pos } : { clientY: opts.pos })
	};
	const event = new PointerEvent(type, init);
	Object.defineProperty(event, 'timeStamp', { value: opts.t, configurable: true });
	target.dispatchEvent(event);
	return event;
}

function fireWheel(target: EventTarget, deltaX: number, deltaY: number) {
	const event = new WheelEvent('wheel', { deltaX, deltaY, bubbles: true, cancelable: true });
	target.dispatchEvent(event);
	return event;
}

function fireClick(target: EventTarget) {
	const event = new MouseEvent('click', { bubbles: true, cancelable: true });
	target.dispatchEvent(event);
	return event;
}

afterEach(() => {
	document.body.replaceChildren();
	vi.unstubAllGlobals();
});

describe('kineticScroll', () => {
	it('opens an item on a plain click', () => {
		stubBrowserTiming();
		const { container, items } = buildStrip('x');
		const onOpen = vi.fn();
		kineticScroll(container, { itemSelector: '.item', onOpen });

		fireClick(items[1]);

		expect(onOpen).toHaveBeenCalledExactlyOnceWith(items[1]);
	});

	it('lets a plain item click reach its handler and document listener once', () => {
		stubBrowserTiming();
		const { container, items } = buildStrip('x');
		const existingHandler = vi.fn();
		const documentHandler = vi.fn();
		const onOpen = vi.fn();
		items[1].addEventListener('click', existingHandler);
		document.addEventListener('click', documentHandler);
		kineticScroll(container, { itemSelector: '.item', onOpen });

		try {
			fireClick(items[1]);
		} finally {
			document.removeEventListener('click', documentHandler);
		}

		expect(existingHandler).toHaveBeenCalledOnce();
		expect(documentHandler).toHaveBeenCalledOnce();
		expect(onOpen).toHaveBeenCalledExactlyOnceWith(items[1]);
	});

	it.each<KineticScrollAxis>(['x', 'y'])(
		'drags the %s axis 1:1 with the pointer once past the threshold',
		(axis) => {
			stubBrowserTiming();
			const { container } = buildStrip(axis);
			if (axis === 'x') container.scrollLeft = 100;
			else container.scrollTop = 100;
			kineticScroll(container, { itemSelector: '.item', onOpen: vi.fn() });

			firePointer(container, 'pointerdown', { pos: 200, axis, t: 1000 });
			firePointer(container, 'pointermove', { pos: 200 - (DRAG_THRESHOLD_PX + 4), axis, t: 1010 });
			expect(container.classList.contains('is-dragging')).toBe(true);
			expect(axis === 'x' ? container.scrollLeft : container.scrollTop).toBe(
				100 + (DRAG_THRESHOLD_PX + 4)
			);

			firePointer(container, 'pointermove', { pos: 150, axis, t: 1040 });
			expect(axis === 'x' ? container.scrollLeft : container.scrollTop).toBe(150);
		}
	);

	it('does not scroll or suppress the next click for movement under the drag threshold', () => {
		stubBrowserTiming();
		const { container, items } = buildStrip('x');
		const onOpen = vi.fn();
		kineticScroll(container, { itemSelector: '.item', onOpen });

		firePointer(container, 'pointerdown', { pos: 200, axis: 'x', t: 1000 });
		firePointer(container, 'pointermove', {
			pos: 200 - (DRAG_THRESHOLD_PX - 1),
			axis: 'x',
			t: 1010
		});
		firePointer(container, 'pointerup', { pos: 200 - (DRAG_THRESHOLD_PX - 1), axis: 'x', t: 1010 });

		expect(container.scrollLeft).toBe(0);
		fireClick(items[0]);
		expect(onOpen).toHaveBeenCalledExactlyOnceWith(items[0]);
	});

	it('suppresses the following click once movement passes the drag threshold', () => {
		stubBrowserTiming();
		const { container, items } = buildStrip('x');
		const onOpen = vi.fn();
		const itemHandler = vi.fn();
		const documentHandler = vi.fn();
		items[0].addEventListener('click', itemHandler);
		document.addEventListener('click', documentHandler);
		kineticScroll(container, { itemSelector: '.item', onOpen });

		firePointer(container, 'pointerdown', { pos: 200, axis: 'x', t: 1000 });
		firePointer(container, 'pointermove', { pos: 150, axis: 'x', t: 1010 });
		firePointer(container, 'pointerup', { pos: 150, axis: 'x', t: 1010 });

		try {
			fireClick(items[0]);
		} finally {
			document.removeEventListener('click', documentHandler);
		}
		expect(onOpen).not.toHaveBeenCalled();
		expect(itemHandler).not.toHaveBeenCalled();
		expect(documentHandler).not.toHaveBeenCalled();
	});

	it('rolls the strip on with momentum computed from the release, past where the drag stopped', () => {
		stubBrowserTiming();
		const { container } = buildStrip('x');
		container.scrollLeft = 100;
		kineticScroll(container, { itemSelector: '.item', onOpen: vi.fn() });

		firePointer(container, 'pointerdown', { pos: 200, axis: 'x', t: 1000 });
		firePointer(container, 'pointermove', { pos: 190, axis: 'x', t: 1010 });
		firePointer(container, 'pointermove', { pos: 150, axis: 'x', t: 1040 });
		firePointer(container, 'pointerup', { pos: 150, axis: 'x', t: 1040 });

		const scrollAtRelease = container.scrollLeft;
		runFrame(16);

		expect(container.scrollLeft).toBeGreaterThan(scrollAtRelease);
	});

	it('a new press catches a still-rolling strip and the paired click does not open an item', () => {
		stubBrowserTiming();
		const { container, items } = buildStrip('x');
		const onOpen = vi.fn();
		kineticScroll(container, { itemSelector: '.item', onOpen });

		firePointer(container, 'pointerdown', { pos: 200, axis: 'x', t: 1000 });
		firePointer(container, 'pointermove', { pos: 150, axis: 'x', t: 1040 });
		firePointer(container, 'pointerup', { pos: 150, axis: 'x', t: 1040 });
		// The release pairs with its own native click, which the drag-threshold
		// suppression already swallows — simulate it so only the later catch is
		// under test, matching how a real pointerup is always followed by click.
		fireClick(items[0]);
		const scrollAtRelease = container.scrollLeft;
		const itemHandler = vi.fn();
		const documentHandler = vi.fn();
		items[0].addEventListener('click', itemHandler);
		document.addEventListener('click', documentHandler);

		firePointer(container, 'pointerdown', { pos: 150, axis: 'x', t: 1100 });
		firePointer(container, 'pointerup', { pos: 150, axis: 'x', t: 1100 });
		runFrame(16);
		expect(container.scrollLeft).toBe(scrollAtRelease);

		try {
			fireClick(items[0]);
		} finally {
			document.removeEventListener('click', documentHandler);
		}
		expect(onOpen).not.toHaveBeenCalled();
		expect(itemHandler).not.toHaveBeenCalled();
		expect(documentHandler).not.toHaveBeenCalled();

		fireClick(items[0]);
		expect(onOpen).toHaveBeenCalledExactlyOnceWith(items[0]);
	});

	it('accelerates on repeated wheel ticks instead of restarting the swing', () => {
		stubBrowserTiming();
		const { container: single } = buildStrip('x');
		kineticScroll(single, { itemSelector: '.item', onOpen: vi.fn() });
		fireWheel(single, 0, 100);
		runFrame(16);
		const singleTickScroll = single.scrollLeft;

		stubBrowserTiming();
		const { container: doubled } = buildStrip('x');
		kineticScroll(doubled, { itemSelector: '.item', onOpen: vi.fn() });
		fireWheel(doubled, 0, 100);
		fireWheel(doubled, 0, 100);
		runFrame(16);

		expect(doubled.scrollLeft).toBeGreaterThan(singleTickScroll);
	});

	it('leaves vertical containers to native wheel scrolling without blocking the event', () => {
		stubBrowserTiming();
		const { container } = buildStrip('y');
		kineticScroll(container, { itemSelector: '.item', onOpen: vi.fn() });

		const event = fireWheel(container, 0, 100);

		expect(event.defaultPrevented).toBe(false);
		expect(container.scrollTop).toBe(0);
		expect(pendingFrame).toBeNull();
	});

	it('re-reads the axis on the next gesture after the layout changes underneath it', () => {
		stubBrowserTiming();
		const { container, items } = buildStrip('x', 3);
		for (const item of items) item.scrollIntoView = vi.fn();
		kineticScroll(container, { itemSelector: '.item', onOpen: vi.fn() });

		items[0].focus();
		container.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
		expect(document.activeElement).toBe(items[1]);

		// A container query or a window resize can flip the strip's own layout
		// between two interactions without the action ever being re-mounted —
		// nothing here re-creates the action, only the CSS the node resolves to.
		setStripAxis(container, 'y');

		container.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
		expect(document.activeElement).toBe(items[2]);

		// The stale x-axis key no longer does anything once the layout is vertical.
		items[0].focus();
		container.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
		expect(document.activeElement).toBe(items[0]);
	});

	it('moves focus to the first or last item on Home and End', () => {
		stubBrowserTiming();
		const { container, items } = buildStrip('x', 3);
		for (const item of items) item.scrollIntoView = vi.fn();
		kineticScroll(container, { itemSelector: '.item', onOpen: vi.fn() });

		items[1].focus();
		container.dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true }));
		expect(document.activeElement).toBe(items[2]);
		expect(items[2].scrollIntoView).toHaveBeenCalledOnce();

		container.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true }));
		expect(document.activeElement).toBe(items[0]);
		expect(items[0].scrollIntoView).toHaveBeenCalledOnce();
	});

	it('leaves a trackpad wheel tick (deltaX set) untouched', () => {
		stubBrowserTiming();
		const { container } = buildStrip('x');
		kineticScroll(container, { itemSelector: '.item', onOpen: vi.fn() });

		const event = fireWheel(container, 5, 5);

		expect(event.defaultPrevented).toBe(false);
		expect(container.scrollLeft).toBe(0);
		expect(pendingFrame).toBeNull();
	});

	it('leaves touch pointers to native handling', () => {
		stubBrowserTiming();
		const { container } = buildStrip('x');
		kineticScroll(container, { itemSelector: '.item', onOpen: vi.fn() });

		firePointer(container, 'pointerdown', { pos: 200, axis: 'x', t: 1000, pointerType: 'touch' });
		firePointer(container, 'pointermove', { pos: 100, axis: 'x', t: 1010, pointerType: 'touch' });

		expect(container.scrollLeft).toBe(0);
		expect(container.classList.contains('is-dragging')).toBe(false);
	});

	it('disables momentum after release when the user prefers reduced motion', () => {
		stubBrowserTiming();
		stubReducedMotion(true);
		const { container } = buildStrip('x');
		container.scrollLeft = 100;
		kineticScroll(container, { itemSelector: '.item', onOpen: vi.fn() });

		firePointer(container, 'pointerdown', { pos: 200, axis: 'x', t: 1000 });
		firePointer(container, 'pointermove', { pos: 150, axis: 'x', t: 1040 });
		firePointer(container, 'pointerup', { pos: 150, axis: 'x', t: 1040 });

		const scrollAtRelease = container.scrollLeft;
		expect(pendingFrame).toBeNull();
		runFrame(16);
		expect(container.scrollLeft).toBe(scrollAtRelease);
	});

	it('scrolls the wheel directly, without inertia, when the user prefers reduced motion', () => {
		stubBrowserTiming();
		stubReducedMotion(true);
		const { container } = buildStrip('x');
		kineticScroll(container, { itemSelector: '.item', onOpen: vi.fn() });

		fireWheel(container, 0, 50);

		expect(container.scrollLeft).toBe(50);
		expect(pendingFrame).toBeNull();
	});

	it('moves focus between items with the arrow keys and scrolls the target into view', () => {
		stubBrowserTiming();
		const { container, items } = buildStrip('x', 3);
		for (const item of items) item.scrollIntoView = vi.fn();
		kineticScroll(container, { itemSelector: '.item', onOpen: vi.fn() });

		items[0].focus();
		container.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
		expect(document.activeElement).toBe(items[1]);
		expect(items[1].scrollIntoView).toHaveBeenCalledOnce();

		container.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
		expect(document.activeElement).toBe(items[2]);

		container.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
		expect(document.activeElement).toBe(items[1]);
	});

	it('opens a non-native item on Enter without double-opening a real button', () => {
		stubBrowserTiming();
		const container = document.createElement('div');
		document.body.append(container);
		const customItem = document.createElement('div');
		customItem.className = 'item';
		customItem.setAttribute('role', 'button');
		customItem.tabIndex = 0;
		const buttonItem = document.createElement('button');
		buttonItem.type = 'button';
		buttonItem.className = 'item';
		container.append(customItem, buttonItem);
		const onOpen = vi.fn();
		kineticScroll(container, { itemSelector: '.item', onOpen });

		customItem.focus();
		customItem.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
		expect(onOpen).toHaveBeenCalledExactlyOnceWith(customItem);

		onOpen.mockClear();
		buttonItem.focus();
		buttonItem.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
		expect(onOpen).not.toHaveBeenCalled();

		fireClick(buttonItem);
		expect(onOpen).toHaveBeenCalledExactlyOnceWith(buttonItem);
	});

	it('stops reacting to input after destroy', () => {
		stubBrowserTiming();
		const { container, items } = buildStrip('x');
		const onOpen = vi.fn();
		const handle = kineticScroll(container, { itemSelector: '.item', onOpen });

		handle?.destroy?.();
		fireClick(items[0]);

		expect(onOpen).not.toHaveBeenCalled();
	});

	it('rebinds onOpen through update without losing click handling', () => {
		stubBrowserTiming();
		const { container, items } = buildStrip('x');
		const onOpenA = vi.fn();
		const onOpenB = vi.fn();
		const handle = kineticScroll(container, { itemSelector: '.item', onOpen: onOpenA });

		handle?.update?.({ itemSelector: '.item', onOpen: onOpenB });
		fireClick(items[0]);

		expect(onOpenA).not.toHaveBeenCalled();
		expect(onOpenB).toHaveBeenCalledExactlyOnceWith(items[0]);
	});
});
