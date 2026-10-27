<script lang="ts">
	import type { SongItem, GenerationItem, UserLoraItem } from '$lib/api/types';
	import type { SourceMode } from '$lib/stores/recipe';
	import {
		COARSE_POINTER_MEDIA,
		TAKE_DELETE_TITLE_TEMPLATE,
		TAKE_DELETE_MESSAGE,
		TAKE_DELETE_LABEL,
		TAKES_EMPTY,
		TAKES_ERROR,
		TAKES_LOADING,
		TAKES_MOBILE_HINT,
		TAKES_RETRY_LABEL,
		takesDraftBanner
	} from '$lib/constants';
	import {
		TAKE_SELECT_ALL_UNKEPT_LABEL,
		bulkDeleteLabel,
		bulkDeleteTitle,
		selectedCountLabel,
		openVersionLabel,
		currentVersionHeadLabel,
		foldedGroupLabel,
		takeRowLabel,
		EARLIER_VERSIONS_LABEL
	} from '$lib/constants/now-playing';
	import { removeGenerationFromSong } from '$lib/stores/libraryData';
	import { currentVersionIndex, versions } from '$lib/stores/editor';
	import { selectedGenerationId } from '$lib/stores/player';
	import { sourceGeneration } from '$lib/stores/recipe';
	import { clearGenerationSelection, persistLibraryHistory } from '$lib/stores/navigation';
	import { getGenerationActions, type GenerationActions } from '$lib/contexts/generation-actions';
	import {
		selectionMode,
		selectedIds,
		selectAllUnkept,
		clearSelection,
		keepOnlySelected
	} from '$lib/stores/selection';
	import {
		groupTakes,
		isGroupOpen,
		renderedTakes,
		revealTakeGroup,
		settleTakeFolds,
		takeFolds,
		takeGroupKey,
		toggleTakeGroup,
		type TakeGroup
	} from '$lib/stores/takeFolds';
	import { addToast } from '$lib/stores/toast';
	import { bulkDeleteGenerations } from '$lib/api/client';
	import { describeFailure } from '$lib/api/fetch';
	import { subscribeCompactLayout } from '$lib/utils/compact-layout';
	import Icon from '../Icon.svelte';
	import ConfirmDialog from '../ConfirmDialog.svelte';
	import GenerationStatusSlot from './GenerationStatusSlot.svelte';
	import { generateAction, isGenerateJobActive } from '$lib/stores/generateAction';
	import TakeRow from './TakeRow.svelte';
	import TakeTaskCard from './TakeTaskCard.svelte';

	// Varying row widths draw the shape of what is coming, not a grey rectangle.
	const SKELETON_ROW_WIDTHS_PX = [190, 150, 172];

	interface Props {
		song: SongItem;
		voices?: UserLoraItem[];
		loadStatus?: 'loading' | 'ready' | 'error';
		loadError?: string | null;
		dirty: boolean;
		draftVersionNumber: number;
		latestVersionNumber: number;
		onsource: (gen: GenerationItem, mode: SourceMode) => void;
		onretry?: () => void;
	}

	let {
		song,
		voices = [],
		loadStatus = 'ready',
		loadError = null,
		dirty,
		draftVersionNumber,
		latestVersionNumber,
		onsource,
		onretry
	}: Props = $props();

	const actions: GenerationActions = getGenerationActions();

	// "Tap play" is touch copy: a narrow desktop window is compact but still
	// has a mouse, so the hint asks the pointer, not the layout width.
	let touchPointer = $state(false);

	$effect(() => {
		return subscribeCompactLayout((value) => {
			touchPointer = value;
		}, COARSE_POINTER_MEDIA);
	});

	let playlistFor = $state<string | null>(null);
	let deleteFor = $state<GenerationItem | null>(null);

	const groups = $derived(
		groupTakes(song.generations, song.version_count > 0 ? latestVersionNumber : null)
	);

	// What the person sees: the current version's takes and those of every
	// unfolded version. Selecting, counting and deleting stay inside it.
	const renderedGenerations = $derived(renderedTakes($takeFolds, groups));
	const renderedIds = $derived(new Set(renderedGenerations.map((gen) => gen.id)));
	const tickedIds = $derived([...$selectedIds].filter((id) => renderedIds.has(id)));

	$effect.pre(() => settleTakeFolds(groups));

	// A card opened from Now Playing may sit under a folded version, and a press
	// that saves a draft folds the source's version: the card stays open.
	$effect(() => {
		void groups.current?.key;
		if ($sourceGeneration) revealTakeGroup(takeGroupKey($sourceGeneration));
	});

	// The version a press lands in: the unsaved draft's, else the loaded one.
	const landingVersionNumber = $derived(
		dirty
			? draftVersionNumber
			: ($versions[$currentVersionIndex]?.version_number ?? latestVersionNumber)
	);
	$effect.pre(() => {
		if ($selectedIds.size > 0) keepOnlySelected(renderedIds);
	});

	let confirmingBulkDelete = $state(false);

	$effect(() => {
		if (tickedIds.length === 0) confirmingBulkDelete = false;
	});

	function openBulkDelete(): void {
		if (tickedIds.length === 0) clearSelection();
		else confirmingBulkDelete = true;
	}

	async function handleBulkDelete(): Promise<void> {
		const ids = tickedIds;
		confirmingBulkDelete = false;
		if (ids.length === 0) {
			clearSelection();
			return;
		}
		const openGenerationId = $selectedGenerationId;
		try {
			await bulkDeleteGenerations(ids);
			for (const id of ids) {
				removeGenerationFromSong(song.id, id);
			}
			if (openGenerationId !== null && ids.includes(openGenerationId)) {
				clearGenerationSelection();
				persistLibraryHistory();
			}
			clearSelection();
			addToast(`Deleted ${ids.length} take${ids.length !== 1 ? 's' : ''}`, 'success');
		} catch (e) {
			addToast(describeFailure(e, 'Bulk delete failed'), 'error');
		}
	}

	async function onAddToPlaylist(playlistId: string): Promise<void> {
		if (!playlistFor) return;
		try {
			await actions.addToPlaylist(playlistId, playlistFor);
			addToast('Added to playlist', 'success');
		} catch (e) {
			addToast(describeFailure(e, 'Failed to add'), 'error');
		} finally {
			playlistFor = null;
		}
	}

	// The first generation of a song has zero takes; the empty state must not hide a job in flight.
	const jobRunning = $derived(isGenerateJobActive($generateAction));
</script>

{#snippet openLink(group: TakeGroup)}
	{#if group.version}
		{@const version = group.version}
		<button
			type="button"
			class="version-link"
			data-hitbox="text"
			onclick={() => void actions.clickVersion(version.versionId)}
		>
			<span class="version-open"
				>{openVersionLabel(version.versionNumber)}<Icon name="chevron-right" size={14} /></span
			>
		</button>
	{/if}
{/snippet}

{#snippet takeRows(generations: GenerationItem[])}
	{#each generations as gen (gen.id)}
		<TakeRow
			{gen}
			{song}
			{voices}
			playlistOpen={playlistFor === gen.id}
			{onsource}
			onaddtoplaylist={() => (playlistFor = gen.id)}
			onselectplaylist={onAddToPlaylist}
			onclosepicker={() => (playlistFor = null)}
			ondelete={() => (deleteFor = gen)}
		/>
		{#if $sourceGeneration?.id === gen.id}
			<TakeTaskCard {gen} {landingVersionNumber} />
		{/if}
	{/each}
{/snippet}

<GenerationStatusSlot {latestVersionNumber} />

{#if loadStatus === 'error' && song.generations.length === 0}
	<div class="empty" role="alert">
		<p>{loadError || TAKES_ERROR}</p>
		{#if onretry}
			<button
				type="button"
				class="retry-btn"
				data-hitbox="frequent"
				data-hitbox-face
				onclick={onretry}
				aria-label={TAKES_RETRY_LABEL}
				title={TAKES_RETRY_LABEL}
			>
				<Icon name="refresh-cw" size={16} />
			</button>
		{/if}
	</div>
{:else if loadStatus === 'loading' && song.generations.length === 0}
	<div class="skeleton" role="status">
		{#each SKELETON_ROW_WIDTHS_PX as width (width)}
			<div class="skeleton-row">
				<span class="skeleton-bar skeleton-disc"></span>
				<span class="skeleton-bar skeleton-text" style:max-width={`${width}px`}></span>
				<span class="skeleton-bar skeleton-badge"></span>
			</div>
		{/each}
		<p class="skeleton-caption">{TAKES_LOADING}</p>
	</div>
{:else if song.generations.length === 0 && !groups.current && !dirty && !jobRunning}
	<div class="empty">{TAKES_EMPTY}</div>
{:else}
	<div class="takes-list">
		{#if loadStatus === 'error'}
			<div class="load-error" role="alert">
				<span>{loadError || TAKES_ERROR}</span>
				{#if onretry}
					<button
						type="button"
						class="retry-btn"
						data-hitbox="frequent"
						data-hitbox-face
						onclick={onretry}
						aria-label={TAKES_RETRY_LABEL}
						title={TAKES_RETRY_LABEL}
					>
						<Icon name="refresh-cw" size={16} />
					</button>
				{/if}
			</div>
		{/if}

		{#if dirty}
			<div class="draft-banner">
				{takesDraftBanner(song.version_count > 0 ? latestVersionNumber : null, draftVersionNumber)}
			</div>
		{/if}

		{#if groups.current}
			{@const current = groups.current}
			<div class="version-section">
				<div class="version-header-row version-head">
					<span class="version-header">
						{currentVersionHeadLabel(current.versionNumber ?? 0, current.generations.length)}
					</span>
					{@render openLink(current)}
				</div>
				{#if current.generations.length === 0 && !jobRunning}
					<div class="version-empty">{TAKES_EMPTY}</div>
				{/if}
				{@render takeRows(current.generations)}
			</div>
		{/if}

		{#if groups.current && groups.earlier.length > 0}
			<p class="earlier-label">{EARLIER_VERSIONS_LABEL}</p>
		{/if}

		{#each groups.earlier as group (group.key)}
			{@const open = isGroupOpen($takeFolds, groups, group.key)}
			<div class="version-section">
				<div class="version-header-row">
					<button
						type="button"
						class="version-toggle"
						data-hitbox="text"
						aria-expanded={open}
						onclick={() => toggleTakeGroup(group.key, groups)}
					>
						<Icon name={open ? 'chevron-down' : 'chevron-right'} size={14} />
						<span class="version-header">
							{foldedGroupLabel(group.versionNumber, group.generations.length, group.archivedCount)}
						</span>
						{#if !open && group.pick}
							<span class="version-pick"
								><Icon name="star-filled" size={12} />{takeRowLabel(
									group.pick.generation_number
								)}</span
							>
						{/if}
					</button>
					{#if open}{@render openLink(group)}{/if}
				</div>
				{#if open}
					<div class="version-takes">{@render takeRows(group.generations)}</div>
				{/if}
			</div>
		{/each}

		{#if touchPointer && song.generations.length > 0}
			<p class="mobile-hint">{TAKES_MOBILE_HINT}</p>
		{/if}

		{#if $selectionMode}
			<div class="selection-toolbar">
				<button
					type="button"
					class="toolbar-btn select-all"
					onclick={() => selectAllUnkept(renderedGenerations)}
				>
					{TAKE_SELECT_ALL_UNKEPT_LABEL}
				</button>
				<span class="toolbar-count">{selectedCountLabel(tickedIds.length)}</span>
				<button type="button" class="toolbar-btn destructive" onclick={openBulkDelete}>
					{bulkDeleteLabel(tickedIds.length)}
				</button>
				<button type="button" class="toolbar-btn cancel" onclick={clearSelection}>Cancel</button>
			</div>
		{/if}
	</div>
{/if}

{#if deleteFor}
	<ConfirmDialog
		title={TAKE_DELETE_TITLE_TEMPLATE.replace('{number}', String(deleteFor.generation_number))}
		message={TAKE_DELETE_MESSAGE}
		confirmLabel={TAKE_DELETE_LABEL}
		onconfirm={() => {
			const id = deleteFor?.id;
			deleteFor = null;
			if (id && renderedIds.has(id)) actions.del(id);
		}}
		oncancel={() => (deleteFor = null)}
	/>
{/if}

{#if confirmingBulkDelete}
	<ConfirmDialog
		title={bulkDeleteTitle(tickedIds.length)}
		message={TAKE_DELETE_MESSAGE}
		confirmLabel={TAKE_DELETE_LABEL}
		onconfirm={handleBulkDelete}
		oncancel={() => (confirmingBulkDelete = false)}
	/>
{/if}

<style>
	.takes-list {
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
	}

	.draft-banner {
		padding: 0.5rem 0.8rem;
		background: rgba(220, 180, 20, 0.12);
		border: 1px solid rgba(220, 180, 20, 0.4);
		border-radius: var(--card-radius);
		font-size: 0.8rem;
		color: #d8b020;
	}

	.version-section {
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
	}

	.version-header-row {
		display: flex;
		align-items: center;
		gap: 0.4rem;
	}

	.version-header {
		font-size: var(--label-font-size);
		color: var(--text-subtle);
		font-family: var(--font-body);
		padding: 0.3rem 0;
	}

	.version-toggle {
		display: flex;
		flex: 1;
		align-items: center;
		gap: 0.3rem;
		min-width: 0;
		padding: 0;
		background: none;
		border: none;
		color: inherit;
		text-align: left;
		cursor: pointer;
	}

	.version-pick {
		display: inline-flex;
		align-items: center;
		gap: 0.2rem;
		margin-left: auto;
		font-size: var(--label-font-size);
		color: var(--accent);
	}

	.version-takes {
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
		padding-left: 1rem;
	}

	.earlier-label {
		margin: 0.4rem 0 0;
		font-size: var(--label-font-size);
		color: var(--text-subtle);
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.version-empty {
		padding: 0.6rem 0;
		color: var(--text-subtle);
		font-style: italic;
		font-size: 0.87rem;
	}

	.version-link {
		display: flex;
		align-items: center;
		margin-left: auto;
		padding: 0;
		background: none;
		border: none;
		text-align: left;
		cursor: pointer;
	}

	.version-open {
		display: inline-flex;
		align-items: center;
		gap: 0.1rem;
		font-size: var(--label-font-size);
		color: var(--accent);
	}

	.selection-toolbar {
		display: flex;
		align-items: center;
		gap: 0.7rem;
		padding: 0.7rem 0.8rem;
		background: var(--surface);
		border: 1px solid var(--accent);
		border-radius: var(--card-radius);
		position: sticky;
		bottom: 0;
	}

	.toolbar-btn {
		min-height: var(--hitbox-frequent);
		padding: 0.3rem 0.8rem;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		background: none;
		color: var(--text-muted);
		font-size: var(--label-font-size);
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		cursor: pointer;
	}

	.toolbar-btn:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.toolbar-btn.destructive {
		border-color: var(--score-bad);
		color: var(--score-bad);
	}

	.toolbar-btn.destructive:hover {
		background: rgba(255, 68, 68, 0.1);
	}

	.toolbar-count {
		font-size: var(--label-font-size);
		color: var(--text-muted);
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	/* UP3: the count and Cancel over Select all unkept and Delete N. */
	@media (max-width: 768px) {
		.selection-toolbar {
			display: grid;
			grid-template-columns: 1fr 1fr;
			gap: 0.4rem 0.7rem;
		}

		.toolbar-count {
			grid-area: 1 / 1;
		}

		.cancel {
			grid-area: 1 / 2;
			justify-self: end;
		}

		.select-all {
			grid-area: 2 / 1;
		}

		.destructive {
			grid-area: 2 / 2;
		}
	}

	.mobile-hint {
		margin: 0;
		text-align: center;
		font-size: 0.72rem;
		color: var(--text-subtle);
		font-style: italic;
	}

	.empty,
	.load-error {
		padding: 2.7rem 1.3rem;
		text-align: center;
		color: var(--text-subtle);
		font-style: italic;
		font-size: 0.87rem;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.7rem;
	}

	.load-error {
		padding: 0.6rem 0.8rem;
		font-style: normal;
		color: var(--score-bad);
		flex-direction: row;
		justify-content: space-between;
	}

	.retry-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		flex: none;
		padding: 0;
		background: none;
		border: none;
		color: inherit;
		cursor: pointer;
	}

	.retry-btn:hover {
		color: var(--primary);
	}

	.skeleton {
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
		padding: 0.9rem 0.6rem;
	}

	.skeleton-row {
		display: flex;
		align-items: center;
		gap: 0.6rem;
	}

	.skeleton-bar {
		border-radius: 4px;
		background: linear-gradient(
			110deg,
			var(--surface-hover) 20%,
			var(--border) 45%,
			var(--surface-hover) 70%
		);
		background-size: 220% 100%;
		animation: takes-skeleton-shimmer 1.2s linear infinite;
	}

	.skeleton-disc {
		flex: none;
		width: 32px;
		height: 32px;
		border-radius: 50%;
	}

	.skeleton-text {
		flex: 1;
		height: 14px;
	}

	.skeleton-badge {
		flex: none;
		width: 38px;
		height: 14px;
	}

	.skeleton-caption {
		margin: 0.4rem 0 0;
		text-align: center;
		font-size: var(--label-font-size);
		font-style: italic;
		color: var(--text-subtle);
	}

	@keyframes takes-skeleton-shimmer {
		to {
			background-position: -220% 0;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.skeleton-bar {
			animation: none;
		}
	}
</style>
