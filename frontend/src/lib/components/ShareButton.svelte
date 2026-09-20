<script lang="ts">
	import type { ShareResult } from '$lib/api/types';
	import { addToast } from '$lib/stores/toast';
	import { SHARE_BUTTON_COPY_FAILED_TOAST, SONG_SHARE_LABEL } from '$lib/constants';
	import Icon from './Icon.svelte';

	interface Props {
		iconOnly?: boolean;
		isShared: boolean;
		shareSlug: string | null | undefined;
		onshare: () => Promise<ShareResult>;
		onunshare: () => Promise<void>;
	}

	let { iconOnly = false, isShared, shareSlug, onshare, onunshare }: Props = $props();
	let busy = $state(false);

	async function toggle(): Promise<void> {
		if (busy) return;
		busy = true;
		try {
			if (isShared) {
				await onunshare();
				addToast('Sharing disabled', 'success');
			} else {
				const result = await onshare();
				try {
					await navigator.clipboard.writeText(result.share_url);
					addToast('Link copied to clipboard', 'success');
				} catch {
					addToast(SHARE_BUTTON_COPY_FAILED_TOAST, 'success');
				}
			}
		} catch {
			addToast('Share failed', 'error');
		} finally {
			busy = false;
		}
	}
</script>

<button
	class="share-btn"
	class:active={isShared}
	class:icon-only={iconOnly}
	data-hitbox={iconOnly ? 'frequent' : undefined}
	aria-label={iconOnly ? SONG_SHARE_LABEL : undefined}
	aria-pressed={iconOnly ? isShared : undefined}
	onclick={toggle}
	disabled={busy}
	title={isShared ? `Shared: /share/${shareSlug ?? ''}` : 'Share'}
>
	{#if isShared}<Icon name="link" size={14} />{:else}<Icon name="share" size={14} />{/if}
</button>

<style>
	.share-btn {
		background: none;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		color: var(--text-muted);
		font-size: var(--btn-font-size);
		padding: 0.3rem 0.7rem;
		cursor: pointer;
		line-height: 1;
	}

	.share-btn.icon-only {
		border: none;
		padding: 0;
	}

	.share-btn:hover:not(:disabled) {
		border-color: var(--primary);
		color: var(--primary);
	}

	.share-btn.active {
		border-color: var(--accent);
		color: var(--accent);
	}

	.share-btn:disabled {
		opacity: 0.4;
	}
</style>
