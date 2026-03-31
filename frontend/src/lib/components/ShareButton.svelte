<script lang="ts">
	import type { ShareResult } from '$lib/api/types';
	import { addToast } from '$lib/stores/toast';

	interface Props {
		isShared: boolean;
		shareSlug: string | null | undefined;
		onshare: () => Promise<ShareResult>;
		onunshare: () => Promise<void>;
	}

	let { isShared, shareSlug, onshare, onunshare }: Props = $props();
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
				await navigator.clipboard.writeText(result.share_url);
				addToast('Link copied to clipboard', 'success');
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
	onclick={toggle}
	disabled={busy}
	title={isShared ? `Shared: /share/${shareSlug ?? ''}` : 'Share'}
>
	{isShared ? '🔗' : '↗'}
</button>

<style>
	.share-btn {
		background: none;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		color: var(--text-muted);
		font-size: 14px;
		padding: 4px 10px;
		cursor: pointer;
		line-height: 1;
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
