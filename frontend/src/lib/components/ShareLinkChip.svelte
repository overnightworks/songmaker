<script lang="ts">
	import Icon from './Icon.svelte';
	import { addToast } from '$lib/stores/toast';
	import {
		LIBRARY_SHARES_COPY_LABEL,
		SHARE_LINK_COPIED_TOAST,
		SHARE_LINK_COPY_FAILED_TOAST
	} from '$lib/constants';

	interface Props {
		url: string;
	}

	let { url }: Props = $props();

	async function copyLink(): Promise<void> {
		try {
			await navigator.clipboard.writeText(url);
			addToast(SHARE_LINK_COPIED_TOAST, 'success');
		} catch {
			addToast(SHARE_LINK_COPY_FAILED_TOAST, 'error');
		}
	}
</script>

<button type="button" class="share-link-chip" onclick={copyLink} title={url}>
	<Icon name="link" size={13} />
	<span>{LIBRARY_SHARES_COPY_LABEL}</span>
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
		border-color: var(--primary);
		color: var(--primary);
	}
</style>
