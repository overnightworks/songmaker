import { vi } from 'vitest';

export function browserReportsOnline(online: boolean): void {
	vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(online);
	window.dispatchEvent(new Event(online ? 'online' : 'offline'));
}
