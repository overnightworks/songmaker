import { closeTopLayer } from '#lib/stores/layers.ts';
import { handleGlobalEscape } from '#lib/utils/escape-level-up.ts';

// The app layout's window Escape listener, for a component mounted without
// the layout; `levelUp` stands in for the page level up it would take. The
// returned function stops listening.
export function listenForGlobalEscape(levelUp: () => void = () => undefined): () => void {
	function onWindowKeydown(event: KeyboardEvent): void {
		handleGlobalEscape(event, { closeTopLayer, levelUp });
	}
	window.addEventListener('keydown', onWindowKeydown);
	return () => window.removeEventListener('keydown', onWindowKeydown);
}
