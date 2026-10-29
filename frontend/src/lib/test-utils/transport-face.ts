import { mount, unmount } from 'svelte';
import Icon from '#lib/components/Icon.svelte';
import type { TransportButtonFace } from '#lib/services/audioPlayer.svelte.ts';

const ICON_FACES: readonly TransportButtonFace[] = ['play', 'pause', 'refresh-cw'];

function iconMarkup(name: TransportButtonFace): string {
	const host = document.createElement('div');
	const icon = mount(Icon, { target: host, props: { name } });
	const markup = host.querySelector('svg')?.innerHTML ?? '';
	unmount(icon);
	return markup;
}

// The face a transport button shows, read as the listener sees it: the
// spinner, or the icon its drawing matches.
export function shownTransportFace(button: Element | null): TransportButtonFace | null {
	if (button?.querySelector('.spinner')) return 'spinner';
	const shown = button?.querySelector('svg')?.innerHTML;
	return ICON_FACES.find((face) => iconMarkup(face) === shown) ?? null;
}
