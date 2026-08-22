import { COMPACT_LAYOUT_MEDIA } from '$lib/constants';

export function readCompactLayout(
	media: Pick<MediaQueryList, 'matches'>,
	root: { dataset: DOMStringMap } = document.documentElement
): boolean {
	return media.matches || root.dataset.pointer === 'coarse';
}

export function subscribeCompactLayout(
	onChange: (compact: boolean) => void,
	mediaQuery: string = COMPACT_LAYOUT_MEDIA
): () => void {
	if (typeof window === 'undefined') return () => {};
	const media = typeof window.matchMedia === 'function' ? window.matchMedia(mediaQuery) : null;
	const sync = () => {
		onChange(
			media ? readCompactLayout(media) : document.documentElement.dataset.pointer === 'coarse'
		);
	};
	sync();
	media?.addEventListener('change', sync);
	const observer = new MutationObserver(sync);
	observer.observe(document.documentElement, {
		attributes: true,
		attributeFilter: ['data-pointer']
	});
	return () => {
		media?.removeEventListener('change', sync);
		observer.disconnect();
	};
}
