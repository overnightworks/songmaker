// jsdom has no visual viewport; this stands in for a phone's 844 px one,
// which the on-screen keyboard shortens while the layout viewport stays put.
// That shortening is what sends the bars away while a field has focus.
export const PHONE_VIEWPORT_HEIGHT_PX = 844;
const PHONE_KEYBOARD_HEIGHT_PX = 300;

export interface PhoneViewport {
	openKeyboard(): void;
	closeKeyboard(): void;
	show(height: number, scale?: number): void;
}

export function phoneViewport(): PhoneViewport {
	const viewport = Object.assign(new EventTarget(), {
		height: PHONE_VIEWPORT_HEIGHT_PX,
		scale: 1
	});
	Object.defineProperty(window, 'visualViewport', { configurable: true, value: viewport });
	Object.defineProperty(document.documentElement, 'clientHeight', {
		configurable: true,
		value: PHONE_VIEWPORT_HEIGHT_PX
	});
	function show(height: number, scale = 1): void {
		viewport.height = height;
		viewport.scale = scale;
		viewport.dispatchEvent(new Event('resize'));
	}
	return {
		openKeyboard: () => show(PHONE_VIEWPORT_HEIGHT_PX - PHONE_KEYBOARD_HEIGHT_PX),
		closeKeyboard: () => show(PHONE_VIEWPORT_HEIGHT_PX),
		show
	};
}

export function removePhoneViewport(): void {
	Reflect.deleteProperty(window, 'visualViewport');
	Reflect.deleteProperty(document.documentElement, 'clientHeight');
}

export function openOnScreenKeyboard(): () => void {
	phoneViewport().openKeyboard();
	return removePhoneViewport;
}
