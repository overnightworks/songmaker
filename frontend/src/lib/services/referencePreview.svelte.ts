import { onDestroy } from 'svelte';
import { referenceAudioUrl } from '#lib/api/references.ts';
import { audioPlayer, transportOffersPause } from '#lib/services/audioPlayer.svelte.ts';

// One preview per consumer; it must be called while a component initialises.
export function createReferencePreview(onPlaybackFailed: (referenceId: string) => void) {
	let activeId = $state<string | null>(null);
	let element: HTMLAudioElement | null = null;
	let loadedId: string | null = null;

	function audioElement(): HTMLAudioElement {
		if (element) return element;
		element = new Audio();
		element.addEventListener('ended', () => (activeId = null));
		element.addEventListener('error', () => fail(loadedId));
		return element;
	}

	function fail(referenceId: string | null) {
		if (referenceId === null) return;
		if (loadedId === referenceId) loadedId = null;
		if (referenceId !== activeId) return;
		activeId = null;
		onPlaybackFailed(referenceId);
	}

	function stop() {
		element?.pause();
		activeId = null;
	}

	// Pausing keeps the download open; a source of its own is dropped on leaving.
	function release() {
		stop();
		if (!element) return;
		element.removeAttribute('src');
		element.load();
		loadedId = null;
	}

	function toggle(referenceId: string) {
		if (activeId === referenceId) return stop();
		if (transportOffersPause(audioPlayer.transport)) audioPlayer.pause();
		const audio = audioElement();
		if (loadedId !== referenceId) {
			audio.src = referenceAudioUrl(referenceId);
			loadedId = referenceId;
		}
		activeId = referenceId;
		audio.play().catch(() => fail(referenceId));
	}

	function releaseIfLoaded(referenceId: string) {
		if (loadedId === referenceId) release();
	}

	// The global player starting ends a preview; the reverse is `toggle`.
	$effect(() => {
		if (transportOffersPause(audioPlayer.transport)) stop();
	});

	onDestroy(release);

	return {
		get activeId() {
			return activeId;
		},
		toggle,
		releaseIfLoaded
	};
}
