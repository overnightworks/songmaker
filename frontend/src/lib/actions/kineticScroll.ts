import type { Action } from 'svelte/action';

export type KineticScrollAxis = 'x' | 'y';

export interface KineticScrollOptions {
	itemSelector: string;
	onOpen?: (item: HTMLElement) => void;
}

const REDUCED_MOTION_MEDIA_QUERY = '(prefers-reduced-motion: reduce)';
const FRICTION_PER_FRAME = 0.94;
const FRAME_MS = 1000 / 60;
// Below this the row would still be technically "animating" (a click would only
// catch it, never open an item) for up to a second after a moderate flick, long
// after the remaining motion is visually imperceptible.
const MIN_VELOCITY_PX_PER_MS = 0.05;
const MAX_VELOCITY_PX_PER_MS = 2.6;
const WHEEL_VELOCITY_GAIN = 0.06;
export const DRAG_THRESHOLD_PX = 6;
const VELOCITY_SAMPLE_WINDOW_MS = 120;

interface PointerSample {
	pos: number;
	t: number;
}

interface DragState {
	pointerId: number;
	start: number;
	startScroll: number;
	dragged: boolean;
	samples: PointerSample[];
}

function readReducedMotion(): { matches: boolean } & Pick<
	MediaQueryList,
	'addEventListener' | 'removeEventListener'
> {
	if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
		return { matches: false, addEventListener: () => {}, removeEventListener: () => {} };
	}
	return window.matchMedia(REDUCED_MOTION_MEDIA_QUERY);
}

/**
 * Kinetic scrolling for a strip of items: 1:1 drag, release-velocity
 * momentum with friction, self-driven snap-to-centre, a click that catches a
 * still-rolling strip instead of opening an item, and wheel-to-scroll on
 * whichever axis the strip actually scrolls on. Touch and trackpad are left
 * to the OS — only mouse pointer events and the wheel are intercepted.
 *
 * The axis is never a caller-supplied option: a strip that lays out
 * horizontally today can be switched to a vertical list by a container
 * query or a viewport resize, so the only source of truth is the computed
 * style the node actually has at the moment of each gesture. Re-reading it
 * per gesture (rather than caching it once, or only at mount) means a resize
 * between interactions can never leave the action pointing at a stale axis.
 *
 * `flex-direction` is the signal, not `overflow-x`/`overflow-y` — measured
 * against a real container query in a real browser, not assumed: per the CSS
 * Overflow spec, a `visible` overflow paired with a scrolling sibling axis is
 * itself *computed* as `auto` (so the axis that isn't meant to scroll still
 * reports `auto`), which makes the overflow properties unable to tell the two
 * axes apart for exactly the row/column toggle this action exists for.
 * `flex-direction` carries no such ambiguity and is what both orientations
 * this action drives (TakeStrip's row and column layouts) already declare.
 */
export const kineticScroll: Action<HTMLElement, KineticScrollOptions> = (node, initial) => {
	let options = initial;
	const reducedMotion = readReducedMotion();
	let axis: KineticScrollAxis = readAxis();

	function readAxis(): KineticScrollAxis {
		return getComputedStyle(node).flexDirection.startsWith('column') ? 'y' : 'x';
	}

	function clientSize() {
		return axis === 'x' ? node.clientWidth : node.clientHeight;
	}
	function scrollSize() {
		return axis === 'x' ? node.scrollWidth : node.scrollHeight;
	}
	function getScroll() {
		return axis === 'x' ? node.scrollLeft : node.scrollTop;
	}
	function setScroll(value: number): number {
		const max = Math.max(0, scrollSize() - clientSize());
		const clamped = Math.max(0, Math.min(max, value));
		if (axis === 'x') node.scrollLeft = clamped;
		else node.scrollTop = clamped;
		return clamped;
	}
	function pointerPos(event: PointerEvent) {
		return axis === 'x' ? event.clientX : event.clientY;
	}
	function visibleItems(): HTMLElement[] {
		return Array.from(node.querySelectorAll<HTMLElement>(options.itemSelector)).filter(
			(el) => !el.hidden
		);
	}
	function focusAndReveal(item: HTMLElement) {
		item.focus();
		if (typeof item.scrollIntoView === 'function') {
			item.scrollIntoView({
				inline: axis === 'x' ? 'center' : 'nearest',
				block: axis === 'y' ? 'center' : 'nearest',
				behavior: reducedMotion.matches ? 'auto' : 'smooth'
			});
		}
	}

	let velocity = 0;
	let rafId: number | null = null;
	let lastFrameTime: number | null = null;
	let isAnimating = false;
	let dragState: DragState | null = null;
	let suppressNextClick = false;
	// A click is pointerdown+pointerup: by the time the paired 'click' event
	// fires, isAnimating has already been cleared by the pointerdown handler —
	// so whether this press interrupted a still-rolling strip has to be
	// captured there, not in the click handler.
	let caughtMomentumOnDown = false;

	function snapToNearest() {
		if (reducedMotion.matches) return;
		const items = visibleItems();
		if (items.length === 0) return;
		const containerRect = node.getBoundingClientRect();
		const containerCenter =
			axis === 'x'
				? containerRect.left + containerRect.width / 2
				: containerRect.top + containerRect.height / 2;
		let nearest: HTMLElement | null = null;
		let nearestDist = Infinity;
		for (const item of items) {
			const r = item.getBoundingClientRect();
			const itemCenter = axis === 'x' ? r.left + r.width / 2 : r.top + r.height / 2;
			const dist = Math.abs(itemCenter - containerCenter);
			if (dist < nearestDist) {
				nearestDist = dist;
				nearest = item;
			}
		}
		if (nearest && typeof nearest.scrollIntoView === 'function') {
			nearest.scrollIntoView({
				inline: axis === 'x' ? 'center' : 'nearest',
				block: axis === 'y' ? 'center' : 'nearest',
				behavior: 'smooth'
			});
		}
	}

	function stopMomentum(snap = false) {
		isAnimating = false;
		velocity = 0;
		lastFrameTime = null;
		if (rafId !== null) {
			cancelAnimationFrame(rafId);
			rafId = null;
		}
		if (snap) snapToNearest();
	}

	function step(now: number) {
		// lastFrameTime is always primed by the caller that starts the loop (see
		// startMomentum and the wheel handler below) — a fresh dt=0 first frame
		// would look identical to "clamped at the scroll boundary" and stop the
		// animation before it ever moves.
		const dt = Math.min(48, now - (lastFrameTime as number));
		lastFrameTime = now;

		const before = getScroll();
		const after = setScroll(before + velocity * dt);
		velocity *= Math.pow(FRICTION_PER_FRAME, dt / FRAME_MS);

		const stuckAtBoundary = after === before && dt > 0;
		if (stuckAtBoundary || Math.abs(velocity) < MIN_VELOCITY_PX_PER_MS) {
			stopMomentum(true);
			return;
		}
		rafId = requestAnimationFrame(step);
	}

	function startMomentum(initialVelocity: number): boolean {
		if (reducedMotion.matches) return false;
		velocity = Math.max(-MAX_VELOCITY_PX_PER_MS, Math.min(MAX_VELOCITY_PX_PER_MS, initialVelocity));
		if (Math.abs(velocity) < MIN_VELOCITY_PX_PER_MS) return false;
		lastFrameTime = performance.now();
		isAnimating = true;
		rafId ??= requestAnimationFrame(step);
		return true;
	}

	function onWheel(event: WheelEvent) {
		axis = readAxis();
		// A vertical strip already scrolls natively on a plain wheel's deltaY —
		// converting it would fight the browser instead of helping it, and the
		// bug this guards against is exactly that: preventDefault() on an axis
		// the action doesn't itself move blocks native scrolling for nothing.
		if (axis !== 'x') return;
		if (event.deltaX !== 0) return; // trackpad already sends its own horizontal delta — leave it to the OS
		event.preventDefault();
		if (reducedMotion.matches) {
			setScroll(getScroll() + event.deltaY);
			return;
		}
		const injected = (event.deltaY * WHEEL_VELOCITY_GAIN) / FRAME_MS;
		velocity = Math.max(
			-MAX_VELOCITY_PX_PER_MS,
			Math.min(MAX_VELOCITY_PX_PER_MS, velocity + injected)
		);
		isAnimating = true;
		// Only (re)prime the clock and (re)schedule when nothing is running yet —
		// repeated rapid ticks must add to the existing swing, not restart it, or
		// every tick would reset dt to ~0 and the row would never accelerate.
		if (rafId === null) {
			lastFrameTime = performance.now();
			rafId = requestAnimationFrame(step);
		}
	}

	function onPointerDown(event: PointerEvent) {
		if (event.pointerType !== 'mouse' || event.button !== 0) return; // touch/trackpad keep native handling
		axis = readAxis();
		caughtMomentumOnDown = isAnimating;
		stopMomentum(caughtMomentumOnDown); // catch it where it is, then settle on the nearest item
		dragState = {
			pointerId: event.pointerId,
			start: pointerPos(event),
			startScroll: getScroll(),
			dragged: false,
			samples: [{ pos: pointerPos(event), t: event.timeStamp }]
		};
		// Pointer capture is only taken once movement crosses the drag threshold
		// (see onPointerMove) — capturing on every mousedown would retarget the
		// matching click event to the container, breaking a plain click on an item.
	}

	function onPointerMove(event: PointerEvent) {
		if (event.pointerId !== dragState?.pointerId) return;
		const pos = pointerPos(event);
		const delta = pos - dragState.start;
		if (!dragState.dragged && Math.abs(delta) > DRAG_THRESHOLD_PX) {
			dragState.dragged = true;
			node.classList.add('is-dragging');
			if (typeof node.setPointerCapture === 'function') {
				node.setPointerCapture(dragState.pointerId);
			}
		}
		if (dragState.dragged) {
			setScroll(dragState.startScroll - delta);
		}
		dragState.samples.push({ pos, t: event.timeStamp });
		const cutoff = event.timeStamp - VELOCITY_SAMPLE_WINDOW_MS;
		while (dragState.samples.length > 2 && dragState.samples[1].t < cutoff) {
			dragState.samples.shift();
		}
	}

	function endDrag(event: PointerEvent) {
		if (event.pointerId !== dragState?.pointerId) return;
		node.classList.remove('is-dragging');
		if (dragState.dragged) {
			const samples = dragState.samples;
			const first = samples[0];
			const last = samples.at(-1);
			if (!last) return;
			const dt = last.t - first.t;
			const dx = last.pos - first.pos;
			const releaseVelocity = dt > 0 ? -dx / dt : 0;
			suppressNextClick = true;
			if (!startMomentum(releaseVelocity)) snapToNearest(); // too gentle to coast — settle right away
		}
		dragState = null;
	}

	function onClickCapture(event: MouseEvent) {
		if (suppressNextClick) {
			suppressNextClick = false;
			event.preventDefault();
			event.stopPropagation();
			return;
		}
		if (caughtMomentumOnDown) {
			caughtMomentumOnDown = false;
			event.preventDefault();
			event.stopPropagation();
		}
	}

	function onClick(event: MouseEvent) {
		if (!(event.target instanceof Element)) return;
		const item = event.target.closest<HTMLElement>(options.itemSelector);
		if (!item || item.hidden) return;
		options.onOpen?.(item);
	}

	function boundaryKeyTarget(key: string): HTMLElement | null | undefined {
		if (key !== 'Home' && key !== 'End') return undefined;
		const items = visibleItems();
		if (items.length === 0) return null;
		return key === 'Home' ? items[0] : (items.at(-1) ?? null);
	}

	function navigationDirection(key: string): -1 | 0 | 1 {
		const forwardKey = axis === 'x' ? 'ArrowRight' : 'ArrowDown';
		const backwardKey = axis === 'x' ? 'ArrowLeft' : 'ArrowUp';
		if (key === forwardKey) return 1;
		if (key === backwardKey) return -1;
		return 0;
	}

	function openNonNativeKeyboardItem(event: KeyboardEvent): void {
		if (event.key !== 'Enter' && event.key !== ' ') return;
		const target = event.target;
		if (!(target instanceof HTMLElement) || !target.matches(options.itemSelector)) return;
		if (target instanceof HTMLButtonElement || target instanceof HTMLAnchorElement) return;
		event.preventDefault();
		options.onOpen?.(target);
	}

	function focusNextItem(direction: -1 | 1): void {
		const items = visibleItems();
		const currentIndex = items.indexOf(document.activeElement as HTMLElement);
		const nextIndex = Math.max(
			0,
			Math.min(items.length - 1, (currentIndex === -1 ? 0 : currentIndex) + direction)
		);
		const next = items[nextIndex];
		if (next) focusAndReveal(next);
	}

	function onKeyDown(event: KeyboardEvent) {
		axis = readAxis();
		const boundaryTarget = boundaryKeyTarget(event.key);
		if (boundaryTarget !== undefined) {
			if (boundaryTarget) {
				event.preventDefault();
				stopMomentum();
				focusAndReveal(boundaryTarget);
			}
			return;
		}
		const direction = navigationDirection(event.key);
		if (direction === 0) {
			openNonNativeKeyboardItem(event);
			return;
		}
		event.preventDefault();
		stopMomentum();
		focusNextItem(direction);
	}

	function onReducedMotionChange() {
		stopMomentum(false);
	}

	node.addEventListener('wheel', onWheel, { passive: false });
	node.addEventListener('pointerdown', onPointerDown);
	node.addEventListener('pointermove', onPointerMove);
	node.addEventListener('pointerup', endDrag);
	node.addEventListener('pointercancel', endDrag);
	node.addEventListener('click', onClickCapture, true);
	node.addEventListener('click', onClick);
	node.addEventListener('keydown', onKeyDown);
	reducedMotion.addEventListener('change', onReducedMotionChange);

	return {
		update(next) {
			options = next;
		},
		destroy() {
			stopMomentum(false);
			node.removeEventListener('wheel', onWheel);
			node.removeEventListener('pointerdown', onPointerDown);
			node.removeEventListener('pointermove', onPointerMove);
			node.removeEventListener('pointerup', endDrag);
			node.removeEventListener('pointercancel', endDrag);
			node.removeEventListener('click', onClickCapture, true);
			node.removeEventListener('click', onClick);
			node.removeEventListener('keydown', onKeyDown);
			reducedMotion.removeEventListener('change', onReducedMotionChange);
		}
	};
};
