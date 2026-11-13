<script lang="ts">
	import Icon from './Icon.svelte';
	import { addToast } from '#lib/stores/toast.ts';
	import { LIBRARY_SHARES_COPY_KEY } from '#lib/constants/library.ts';
	import { pageText } from '#lib/utils/page-words.ts';

	interface Props {
		url: string;
	}

	let { url }: Props = $props();

	async function copyLink(): Promise<void> {
		try {
			await navigator.clipboard.writeText(url);
			addToast(pageText('shareLink.copiedToast'), 'success');
		} catch {
			addToast(pageText('shareLink.copyFailedToast'), 'error');
		}
	}
</script>

<button type="button" class="share-link-chip" onclick={copyLink} title={url}>
	<Icon name="link" size={13} />
	<span>{pageText(LIBRARY_SHARES_COPY_KEY)}</span>
</button>

<style>
	.share-link-chip {
		display: inline-flex;
		align-items: center;
		align-self: flex-start;
		gap: 0.35rem;
		max-width: 100%;
		padding: 0.3rem 0.65rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		background: var(--surface);
		color: var(--text-subtle);
		font-size: 0.75rem;
		cursor: pointer;
	}

	.share-link-chip:hover {
		border-color: var(--accent);
		color: var(--accent);
	}
</style>
