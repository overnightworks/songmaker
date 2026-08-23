<script lang="ts">
	import type { ShareResult } from '$lib/api/types';
	import CollectionHeaderFrame from './CollectionHeaderFrame.svelte';
	import Breadcrumb from './Breadcrumb.svelte';
	import CollectionMenu from './CollectionMenu.svelte';
	import EditableTitle from './EditableTitle.svelte';
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

	let editableTitle: EditableTitle | undefined = $state();
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

	function triggerRename(): void {
		editableTitle?.startEdit();
	}
</script>

{#snippet titleArea()}
	<h2 class="header-title">
		<EditableTitle
			bind:this={editableTitle}
			value={title}
			onsave={onrename}
			ariaLabel={`${kind} title`}
		/>
	</h2>
	<Breadcrumb items={breadcrumbItems} />
{/snippet}

{#snippet actions()}
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
{/snippet}

<CollectionHeaderFrame
	{coverUrl}
	{showCover}
	onCoverError={() => (coverFailed = true)}
	{coverAlt}
	{initials}
	{artFill}
	{onplay}
	{titleArea}
	{actions}
/>

<style>
	.header-title {
		font-family: var(--font-display);
		font-size: 1.55rem;
		color: var(--text);
		text-transform: uppercase;
		letter-spacing: 1.5px;
	}

	@media (max-width: 768px) {
		.header-title {
			font-size: 1.2rem;
		}
	}
</style>
