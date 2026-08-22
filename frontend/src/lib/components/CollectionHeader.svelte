<script lang="ts">
	import type { ShareResult } from '$lib/api/types';
	import Breadcrumb from './Breadcrumb.svelte';
	import CollectionMenu from './CollectionMenu.svelte';
	import EditableTitle from './EditableTitle.svelte';
	import Icon from './Icon.svelte';
	import { RAIL_LIBRARY_LABEL } from '$lib/constants';
	import { openLibraryWall } from '$lib/stores/navigation';

	interface Props {
		kind: 'album' | 'playlist';
		title: string;
		coverUrl: string | null;
		coverAlt: string;
		initials: string;
		artFill: string | null;
		onplay: () => void;
		onrename: (title: string) => Promise<void>;
		isShared: boolean;
		shareSlug: string | null | undefined;
		onshare: () => Promise<ShareResult>;
		onunshare: () => Promise<void>;
		ondelete: () => void;
		oncover?: () => void;
		onremovecover?: () => void;
		onaddtoplaylist?: () => void;
		onsaveoffline?: () => void;
		offlineSaved?: boolean;
		offlineSaving?: boolean;
		offlineProgressLabel?: string | null;
	}

	let {
		kind,
		title,
		coverUrl,
		coverAlt,
		initials,
		artFill,
		onplay,
		onrename,
		isShared,
		shareSlug,
		onshare,
		onunshare,
		ondelete,
		oncover,
		onremovecover,
		onaddtoplaylist,
		onsaveoffline,
		offlineSaved = false,
		offlineSaving = false,
		offlineProgressLabel = null
	}: Props = $props();

	let titleContainer: HTMLElement | undefined = $state();
	let coverFailed = $state(false);

	$effect(() => {
		void coverUrl;
		coverFailed = false;
	});

	const showCover = $derived(Boolean(coverUrl) && !coverFailed);
	const breadcrumbItems = $derived([
		{ label: RAIL_LIBRARY_LABEL, onclick: () => void openLibraryWall() },
		{ label: title }
	]);

	// EditableTitle owns its own click-to-edit state and exposes no external
	// trigger; the menu's "Rename" entry forwards to the same public
	// interaction (clicking the title button) instead of duplicating the
	// rename UI.
	function triggerRename(): void {
		const button = titleContainer?.querySelector<HTMLButtonElement>('.editable-title-display');
		button?.click();
	}
</script>

<div class="collection-header">
	<span class="header-cover">
		{#if showCover && coverUrl}
			<img src={coverUrl} alt={coverAlt} onerror={() => (coverFailed = true)} />
		{:else if artFill}
			<span class="header-cover-fallback" style:background={artFill} aria-hidden="true"></span>
		{:else}
			<span class="header-cover-fallback header-cover-initials" aria-hidden="true">{initials}</span>
		{/if}
	</span>
	<div class="header-titles">
		<h2 class="header-title" bind:this={titleContainer}>
			<EditableTitle value={title} onsave={onrename} ariaLabel={`${kind} title`} />
		</h2>
		<Breadcrumb items={breadcrumbItems} />
	</div>
	<div class="header-actions">
		<button class="play-btn" onclick={onplay} aria-label="Play">
			<Icon name="play" size={16} />
			<span>Play</span>
		</button>
		<CollectionMenu
			{kind}
			{title}
			{isShared}
			{shareSlug}
			{onshare}
			{onunshare}
			{ondelete}
			{oncover}
			hasCover={showCover}
			{onremovecover}
			{onaddtoplaylist}
			{onsaveoffline}
			{offlineSaved}
			{offlineSaving}
			{offlineProgressLabel}
			onrename={triggerRename}
		/>
	</div>
</div>

<style>
	.collection-header {
		display: flex;
		align-items: center;
		gap: 1rem;
		flex-wrap: wrap;
		padding: 1.2rem 1.5rem 0.8rem;
	}

	.header-cover {
		display: block;
		width: 56px;
		height: 56px;
		flex-shrink: 0;
		overflow: hidden;
		background: var(--surface-hover);
	}

	.header-cover img,
	.header-cover-fallback {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.header-cover-initials {
		font-family: var(--font-display);
		font-size: 1.1rem;
		letter-spacing: 0.06em;
		color: var(--text);
		user-select: none;
	}

	.header-titles {
		min-width: 0;
		flex: 1;
	}

	.header-title {
		font-family: var(--font-display);
		font-size: 1.55rem;
		color: var(--text);
		text-transform: uppercase;
		letter-spacing: 1.5px;
	}

	.header-actions {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		flex-shrink: 0;
	}

	.play-btn {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		padding: 0.5rem 1.1rem;
		border-radius: var(--btn-radius-pill);
		border: none;
		background: linear-gradient(135deg, var(--primary), var(--accent));
		color: #fff;
		font-family: var(--font-display);
		font-size: 0.85rem;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		cursor: pointer;
	}

	.play-btn:hover {
		box-shadow: 0 0 14px color-mix(in srgb, var(--accent) 40%, transparent);
	}

	@media (max-width: 768px) {
		.collection-header {
			padding: 0.8rem 0.8rem 0.6rem;
		}

		.header-title {
			font-size: 1.2rem;
		}
	}
</style>
