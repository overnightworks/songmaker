<script lang="ts">
	import type { ShareResult } from '#lib/api/types.ts';
	import { SONG_SHARE_LABEL } from '#lib/constants.ts';
	import { createShareToggle } from '#lib/stores/shareToggle.svelte.ts';
	import Icon from './Icon.svelte';

	interface Props {
		iconOnly?: boolean;
		isShared: boolean;
		shareSlug: string | null | undefined;
		onshare: () => Promise<ShareResult>;
		onunshare: () => Promise<void>;
	}

	let { iconOnly = false, isShared, shareSlug, onshare, onunshare }: Props = $props();
	const shareToggle = createShareToggle(() => ({
		kind: 'song',
		isShared,
		shareSlug,
		onshare,
		onunshare
	}));
</script>

<button
	class="share-btn"
	class:active={isShared}
	class:icon-only={iconOnly}
	data-hitbox={iconOnly ? 'frequent' : undefined}
	aria-label={iconOnly ? SONG_SHARE_LABEL : undefined}
	aria-pressed={iconOnly ? isShared : undefined}
	onclick={shareToggle.toggle}
	disabled={shareToggle.busy}
	title={shareToggle.sharedTooltip ?? 'Share'}
>
	<Icon name={shareToggle.iconName} size={14} />
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
