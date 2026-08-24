<script lang="ts">
	import type { SongItem, GenerationItem, JobItem } from '$lib/api/types';
	import {
		COARSE_POINTER_MEDIA,
		EXPIRY_WARN_DAYS,
		LIBRARY_RETRY_LABEL,
		TAKE_ARCHIVED_TITLE,
		TAKE_KEEP_LABEL,
		TAKE_PICK_LABEL,
		TAKE_RESCORING_LABEL,
		TAKES_DELETE_VERSION_LABEL,
		TAKES_DRAFT_BANNER_TEMPLATE,
		TAKES_EMPTY,
		TAKES_ERROR,
		TAKES_GENERATING_LABEL,
		TAKES_LOADING,
		TAKES_MOBILE_HINT
	} from '$lib/constants';
	import {
		nowPlayingTakeLabel,
		takeBatchReductionLabel,
		takeModelModeLabel
	} from '$lib/constants/now-playing';
	import { removeGenerationFromSong, replaceSongInList } from '$lib/stores/libraryData';
	import { playTakeAndShowNowPlaying, selectedGenerationId } from '$lib/stores/player';
	import { clearGenerationSelection, persistLibraryHistory } from '$lib/stores/navigation';
	// Re-score comes straight from its owner rather than through
	// GenerationActions: Now Playing has no such context and calls the same
	// function, and routing one surface through the context would put a second
	// path to the same mutation back in the tree.
	import { rescore, rescoringTakeIds } from '$lib/stores/takeActions';
	import { audioPlayer } from '$lib/services/audioPlayer.svelte';
	import { formatScore, qualityFlag, scoreColor, scoreReadings } from '$lib/utils/scores';
	import { getGenerationActions } from '$lib/contexts/generation-actions';
	import {
		selectionMode,
		selectedIds,
		toggleSelection,
		selectAllUnkept,
		clearSelection,
		selectionCount
	} from '$lib/stores/selection';
	import { addToast } from '$lib/stores/toast';
	import { dismissGenerationFailure, generationFailures } from '$lib/stores/jobs';
	import { handleDeleteVersion } from '$lib/stores/editor';
	import {
		bulkDeleteGenerations,
		cancelJob,
		fetchSong,
		remasterGeneration,
		unarchiveGeneration
	} from '$lib/api/client';
	import { subscribeCompactLayout } from '$lib/utils/compact-layout';
	import Icon from '../Icon.svelte';
	import PlaylistPicker from '../PlaylistPicker.svelte';
	import ConfirmDeleteDialog from '../ConfirmDeleteDialog.svelte';
	import TakeMenu from './TakeMenu.svelte';

	interface Props {
		song: SongItem;
		loadStatus?: 'loading' | 'ready' | 'error';
		loadError?: string | null;
		dirty: boolean;
		draftVersionNumber: number;
		latestVersionNumber: number;
		generateJob?: JobItem | null;
		onagain: (gen: GenerationItem) => void;
		onuseasreference: (gen: GenerationItem) => void;
		onretry?: () => void;
	}

	let {
		song,
		loadStatus = 'ready',
		loadError = null,
		dirty,
		draftVersionNumber,
		latestVersionNumber,
		generateJob = null,
		onagain,
		onuseasreference,
		onretry
	}: Props = $props();

	const actions = getGenerationActions();

	const GENERATION_FAILED_DISMISS_LABEL = 'Dismiss generation error';

	const generationFailure = $derived($generationFailures[song.id] ?? null);

	const playingGenId = $derived(audioPlayer.current?.generation.id ?? null);
	const buffering = $derived(
		audioPlayer.status === 'loading' || audioPlayer.status === 'buffering'
	);

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
	let deleteVersionFor = $state<VersionGroup | null>(null);
	let remasteringId = $state<string | null>(null);

	interface VersionGroup {
		label: string;
		versionNumber: number | null;
		generations: GenerationItem[];
	}

	const groups = $derived.by((): VersionGroup[] => {
		const map: Record<string, VersionGroup> = {};
		for (const gen of song.generations) {
			const key = gen.version_number !== null ? `v${gen.version_number}` : 'unknown';
			if (!map[key]) {
				map[key] = {
					label:
						gen.version_number !== null
							? `v${gen.version_number} · ${countTakes(gen.version_number)} take${countTakes(gen.version_number) === 1 ? '' : 's'}`
							: 'Unknown version',
					versionNumber: gen.version_number,
					generations: []
				};
			}
			map[key].generations.push(gen);
		}
		const result = Object.values(map);
		result.sort((a, b) => (b.versionNumber ?? -1) - (a.versionNumber ?? -1));
		return result;
	});

	function countTakes(versionNumber: number): number {
		return song.generations.filter((g) => g.version_number === versionNumber).length;
	}

	interface HeadlineScore {
		label: string;
		text: string;
		color: string;
	}

	// The row has room for one number, so it shows the take's headline score:
	// the highest-ranked metric the take actually carries, read off the shared
	// table in utils/scores.ts — the listener's own rating when they gave one,
	// otherwise the most telling automatic score. A take only some scorers have
	// reached still gets a pill instead of nothing (#163/4).
	function headlineScore(gen: GenerationItem): HeadlineScore | null {
		const [reading] = scoreReadings(gen.scores);
		if (!reading) return null;
		const { metric, value } = reading;
		return {
			label: metric.label,
			text: formatScore(metric, value, 'pill'),
			color: scoreColor(metric.key, value)
		};
	}

	function formatDuration(gen: GenerationItem): string | null {
		const seconds = gen.generation_params?.audio_duration;
		if (seconds == null) return null;
		const whole = Math.round(seconds);
		const m = Math.floor(whole / 60);
		const s = whole % 60;
		return `${m}:${s.toString().padStart(2, '0')}`;
	}

	function daysUntilExpiry(gen: GenerationItem): number | null {
		if (gen.is_picked || gen.is_kept || !gen.expires_at) return null;
		const ms = new Date(gen.expires_at).getTime() - Date.now();
		return Math.max(0, Math.ceil(ms / (1000 * 60 * 60 * 24)));
	}

	function isGenPlaying(gen: GenerationItem): boolean {
		return playingGenId === gen.id;
	}

	function isGenLoading(gen: GenerationItem): boolean {
		return isGenPlaying(gen) && buffering;
	}

	// An archived take has nothing for a row activation to do, so the row stops
	// announcing itself as a button — except in selection mode, where ticking
	// it is still a real action.
	function rowIsActionable(gen: GenerationItem): boolean {
		return $selectionMode || !gen.is_archived;
	}

	function handleRowClick(gen: GenerationItem, e: MouseEvent): void {
		if (e.ctrlKey || e.metaKey) {
			toggleSelection(gen.id);
			return;
		}
		if ($selectionMode) {
			toggleSelection(gen.id);
			return;
		}
		if (gen.is_archived) return;
		void playTakeAndShowNowPlaying(gen, song);
	}

	function handleRowKeydown(gen: GenerationItem, e: KeyboardEvent): void {
		if (e.target !== e.currentTarget) return;
		if (e.key !== 'Enter' && e.key !== ' ') return;
		e.preventDefault();
		if ($selectionMode) {
			toggleSelection(gen.id);
			return;
		}
		if (gen.is_archived) return;
		void playTakeAndShowNowPlaying(gen, song);
	}

	async function handleBulkDelete(): Promise<void> {
		const ids = [...$selectedIds];
		if (ids.length === 0) return;
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
			addToast(e instanceof Error ? e.message : 'Bulk delete failed', 'error');
		}
	}

	async function copyShareUrl(gen: GenerationItem): Promise<void> {
		if (!gen.share_slug) return;
		await navigator.clipboard.writeText(`${window.location.origin}/share/gen/${gen.share_slug}`);
		addToast('Link copied', 'success');
	}

	async function onShare(gen: GenerationItem): Promise<void> {
		try {
			const result = await actions.share(gen.id);
			await navigator.clipboard.writeText(result.share_url);
			addToast('Link copied', 'success');
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Share failed', 'error');
		}
	}

	async function onUnshare(gen: GenerationItem): Promise<void> {
		try {
			await actions.unshare(gen.id);
			addToast('Sharing disabled', 'success');
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Unshare failed', 'error');
		}
	}

	async function onRemaster(gen: GenerationItem): Promise<void> {
		if (remasteringId) return;
		remasteringId = gen.id;
		try {
			await remasterGeneration(gen.id);
			const updated = await fetchSong(song.id);
			replaceSongInList(updated);
			addToast('Remastered', 'success');
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Remaster failed', 'error');
		} finally {
			remasteringId = null;
		}
	}

	async function onRestore(gen: GenerationItem): Promise<void> {
		try {
			await unarchiveGeneration(gen.id);
			const updated = await fetchSong(song.id);
			replaceSongInList(updated);
			addToast('Take restored', 'success');
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Restore failed', 'error');
		}
	}

	async function onAddToPlaylist(playlistId: string): Promise<void> {
		if (!playlistFor) return;
		try {
			await actions.addToPlaylist(playlistId, playlistFor);
			addToast('Added to playlist', 'success');
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Failed to add', 'error');
		} finally {
			playlistFor = null;
		}
	}

	async function onCancelGenerateJob(): Promise<void> {
		if (!generateJob) return;
		try {
			await cancelJob(generateJob.id);
		} catch {
			/* best effort */
		}
	}

	async function confirmDeleteVersion(): Promise<void> {
		const group = deleteVersionFor;
		deleteVersionFor = null;
		const versionId = group?.generations[0]?.version_id;
		if (!group || !versionId) return;
		try {
			await handleDeleteVersion(song.id, versionId, true);
			addToast(`Deleted v${group.versionNumber}`, 'success');
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Delete failed', 'error');
		}
	}
</script>

{#if loadStatus === 'error' && song.generations.length === 0}
	<div class="empty" role="alert">
		<p>{loadError || TAKES_ERROR}</p>
		{#if onretry}
			<button type="button" class="retry-btn" onclick={onretry}>{LIBRARY_RETRY_LABEL}</button>
		{/if}
	</div>
{:else if loadStatus === 'loading' && song.generations.length === 0}
	<div class="empty" role="status">{TAKES_LOADING}</div>
{:else if song.generations.length === 0 && !dirty && !generationFailure}
	<div class="empty">{TAKES_EMPTY}</div>
{:else}
	<div class="takes-list">
		{#if loadStatus === 'error'}
			<div class="load-error" role="alert">
				<span>{loadError || TAKES_ERROR}</span>
				{#if onretry}
					<button type="button" class="retry-btn" onclick={onretry}>{LIBRARY_RETRY_LABEL}</button>
				{/if}
			</div>
		{/if}

		{#if dirty}
			<div class="draft-banner">
				{TAKES_DRAFT_BANNER_TEMPLATE.replace('{version}', String(draftVersionNumber))}
			</div>
		{/if}

		{#if generationFailure}
			<div class="failed-row" role="alert">
				<span class="failed-cause" title={generationFailure}>{generationFailure}</span>
				<button
					type="button"
					class="failed-dismiss"
					onclick={() => dismissGenerationFailure(song.id)}
					aria-label={GENERATION_FAILED_DISMISS_LABEL}>×</button
				>
			</div>
		{/if}

		{#if generateJob && (generateJob.status === 'queued' || generateJob.status === 'running')}
			<div class="generating-row">
				<span class="generating-label">
					v{latestVersionNumber} · {TAKES_GENERATING_LABEL}
					{#if generateJob.status === 'queued'}
						{generateJob.queue_position ? `· queued #${generateJob.queue_position}` : '· queued'}
					{/if}
				</span>
				<span class="generating-bar">
					<span class="generating-fill" style="width: {Math.round(generateJob.progress * 100)}%"
					></span>
				</span>
				<button type="button" class="generating-cancel" onclick={onCancelGenerateJob}>×</button>
			</div>
		{/if}

		{#each groups as group (group.versionNumber ?? 'unknown')}
			<div class="version-section">
				<div class="version-header-row">
					<span class="version-header">{group.label}</span>
					{#if group.versionNumber !== null}
						<button
							type="button"
							class="version-delete-btn"
							data-hitbox="frequent"
							data-hitbox-face
							onclick={() => (deleteVersionFor = group)}
							aria-label={`${TAKES_DELETE_VERSION_LABEL} v${group.versionNumber}`}
							title={TAKES_DELETE_VERSION_LABEL}
						>
							<Icon name="trash" size={12} />
						</button>
					{/if}
				</div>
				{#each group.generations as gen (gen.id)}
					{@const duration = formatDuration(gen)}
					{@const headline = headlineScore(gen)}
					{@const flag = qualityFlag(gen.scores)}
					{@const modelMode = takeModelModeLabel(gen.model_mode)}
					{@const batchNotice = takeBatchReductionLabel(gen.generation_params)}
					<!-- `role` and `tabindex` move together with rowIsActionable, which the
					     a11y check cannot narrow through a dynamic role. -->
					<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
					<div
						class="take-row"
						class:playing={isGenPlaying(gen)}
						class:buffering={isGenLoading(gen)}
						class:selected={$selectedIds.has(gen.id)}
						class:archived={gen.is_archived}
						onclick={(e) => handleRowClick(gen, e)}
						onkeydown={(e) => handleRowKeydown(gen, e)}
						role={rowIsActionable(gen) ? 'button' : undefined}
						tabindex={rowIsActionable(gen) ? 0 : undefined}
						title={gen.is_archived ? TAKE_ARCHIVED_TITLE : undefined}
					>
						<span class="take-body">
							{#if $selectionMode}
								<span class="selection-checkbox">
									<Icon name={$selectedIds.has(gen.id) ? 'check-square' : 'square'} size={16} />
								</span>
							{:else if !gen.is_archived}
								<Icon name={isGenPlaying(gen) ? 'pause' : 'play'} size={14} />
							{/if}

							<span class="take-label">
								{nowPlayingTakeLabel(gen.version_number, gen.generation_number)}
							</span>

							{#if duration}
								<span class="take-duration">{duration}</span>
							{/if}

							{#if modelMode}
								<span class="model-badge" title="Model: {modelMode}">{modelMode}</span>
							{/if}

							{#if batchNotice}
								<span
									class="batch-badge"
									title="Batch size reduced by ACE-Step due to available VRAM: delivered {batchNotice}"
								>
									⚠ {batchNotice}
								</span>
							{/if}

							{#if headline}
								<span
									class="score-badge {headline.color}"
									title={`${headline.label} ${headline.text}`}
								>
									{headline.text}
								</span>
							{/if}

							{#if flag}
								<span class="quality-flag-badge" title={flag.title}>
									⚠ {flag.label}
								</span>
							{/if}

							{#if $rescoringTakeIds.has(gen.id)}
								<span class="rescoring-badge">{TAKE_RESCORING_LABEL}</span>
							{/if}

							{#if gen.is_archived}
								<span class="expiry-badge archived" title="Archived — will be hard-deleted">
									archived
								</span>
							{:else}
								{@const daysLeft = daysUntilExpiry(gen)}
								{#if daysLeft !== null && daysLeft <= EXPIRY_WARN_DAYS}
									<span
										class="expiry-badge warn"
										title="Expires in {daysLeft} day{daysLeft === 1
											? ''
											: 's'} — pick or keep to preserve"
									>
										⏳ {daysLeft}d
									</span>
								{/if}
							{/if}
						</span>

						<span class="take-actions">
							<button
								type="button"
								class="pick-btn"
								class:picked={gen.is_picked}
								data-hitbox="frequent"
								onclick={(e) => {
									e.stopPropagation();
									actions.pick(gen.id, !gen.is_picked);
								}}
								aria-pressed={gen.is_picked}
								aria-label={gen.is_picked ? 'Unpick' : TAKE_PICK_LABEL}
							>
								<Icon name={gen.is_picked ? 'star-filled' : 'star'} size={16} />
							</button>
							<button
								type="button"
								class="keep-btn"
								class:kept={gen.is_kept}
								data-hitbox="frequent"
								onclick={(e) => {
									e.stopPropagation();
									actions.keep(gen.id, !gen.is_kept);
								}}
								aria-pressed={gen.is_kept}
								aria-label={gen.is_kept ? 'Unkeep' : TAKE_KEEP_LABEL}
							>
								<Icon name={gen.is_kept ? 'heart-filled' : 'heart'} size={16} />
							</button>
							{#if !$selectionMode}
								<TakeMenu
									{gen}
									onagain={() => onagain(gen)}
									onuseasreference={() => onuseasreference(gen)}
									onshare={() => void onShare(gen)}
									onunshare={() => void onUnshare(gen)}
									oncopylink={() => void copyShareUrl(gen)}
									onpinseed={() => gen.seed != null && actions.pinSeed(gen.seed)}
									onaddtoplaylist={() => (playlistFor = gen.id)}
									onremaster={() => void onRemaster(gen)}
									onrescore={() => void rescore(song.id, gen.id)}
									rescoring={$rescoringTakeIds.has(gen.id)}
									onrestore={() => void onRestore(gen)}
									ondelete={() => (deleteFor = gen)}
								/>
								{#if playlistFor === gen.id}
									<div
										class="take-picker-anchor"
										onclick={(e) => e.stopPropagation()}
										onkeydown={(e) => e.stopPropagation()}
										role="presentation"
									>
										<PlaylistPicker
											onselect={onAddToPlaylist}
											onclose={() => (playlistFor = null)}
										/>
									</div>
								{/if}
							{/if}
						</span>
					</div>
				{/each}
			</div>
		{/each}

		{#if touchPointer}
			<p class="mobile-hint">{TAKES_MOBILE_HINT}</p>
		{/if}

		{#if $selectionMode}
			<div class="selection-toolbar">
				<button type="button" class="toolbar-btn" onclick={() => selectAllUnkept(song.generations)}>
					Select All Unkept
				</button>
				<span class="toolbar-count">{$selectionCount} selected</span>
				<button type="button" class="toolbar-btn destructive" onclick={handleBulkDelete}>
					Delete Selected
				</button>
				<button type="button" class="toolbar-btn" onclick={clearSelection}> Cancel </button>
			</div>
		{/if}
	</div>
{/if}

{#if deleteFor}
	<ConfirmDeleteDialog
		title={`Delete take ${deleteFor.generation_number}?`}
		items={['Audio files will be permanently deleted']}
		confirmLabel="Delete Take"
		onconfirm={() => {
			const id = deleteFor?.id;
			deleteFor = null;
			if (id) actions.del(id);
		}}
		oncancel={() => (deleteFor = null)}
	/>
{/if}

{#if deleteVersionFor}
	<ConfirmDeleteDialog
		title={`Delete v${deleteVersionFor.versionNumber}?`}
		items={[
			`${deleteVersionFor.generations.length} take${deleteVersionFor.generations.length !== 1 ? 's' : ''} will be deleted permanently`
		]}
		confirmLabel="Delete Version"
		onconfirm={() => void confirmDeleteVersion()}
		oncancel={() => (deleteVersionFor = null)}
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

	.failed-row {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		padding: 0.5rem 0.8rem;
		background: rgba(220, 60, 60, 0.08);
		border: 1px solid var(--score-bad);
		border-radius: var(--card-radius);
		font-size: 0.8rem;
		color: var(--score-bad);
	}

	.failed-cause {
		flex: 1;
		display: -webkit-box;
		-webkit-box-orient: vertical;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		overflow: hidden;
	}

	.failed-dismiss {
		background: none;
		border: 1px solid var(--score-bad);
		border-radius: 3px;
		color: var(--score-bad);
		cursor: pointer;
		flex-shrink: 0;
		line-height: 1;
		padding: 0.1rem 0.35rem;
	}

	.generating-row {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		padding: 0.5rem 0.8rem;
		background: var(--surface);
		border: 1px dashed var(--border);
		border-radius: var(--card-radius);
		font-size: 0.75rem;
		color: var(--text-muted);
	}

	.generating-label {
		flex-shrink: 0;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.4px;
	}

	.generating-bar {
		flex: 1;
		height: 4px;
		background: var(--border);
		border-radius: 2px;
		overflow: hidden;
	}

	.generating-fill {
		display: block;
		height: 100%;
		background: var(--score-ok);
		transition: width 0.3s ease;
	}

	.generating-cancel {
		background: none;
		border: 1px solid var(--border);
		border-radius: 3px;
		color: var(--text-muted);
		cursor: pointer;
		line-height: 1;
		padding: 0.1rem 0.35rem;
	}

	.generating-cancel:hover {
		color: var(--score-bad);
		border-color: var(--score-bad);
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
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		padding: 0.3rem 0;
	}

	.version-delete-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		background: none;
		border: none;
		color: var(--text-subtle);
		cursor: pointer;
		padding: 0.15rem;
	}

	.version-delete-btn:hover {
		color: var(--score-bad);
	}

	.take-row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.6rem;
		padding: 0.45rem 0.7rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		cursor: pointer;
		text-align: left;
		color: var(--text);
		font: inherit;
		width: 100%;
		min-width: 0;
	}

	.take-row:hover {
		border-color: rgba(160, 32, 240, 0.3);
		background: var(--surface-hover);
	}

	.take-row.playing {
		border-color: var(--accent);
		background: rgba(160, 32, 240, 0.1);
	}

	.take-row.buffering {
		border-color: var(--accent);
		animation: buffer-pulse 1.5s ease-in-out infinite;
	}

	.take-row.selected {
		border-color: var(--accent);
		background: rgba(160, 32, 240, 0.05);
	}

	@keyframes buffer-pulse {
		0%,
		100% {
			border-color: rgba(160, 32, 240, 0.2);
			box-shadow: 0 0 0 rgba(160, 32, 240, 0);
		}
		50% {
			border-color: var(--accent);
			box-shadow: 0 0 12px rgba(160, 32, 240, 0.15);
		}
	}

	/* Everything that describes the take, and nothing that acts on it: this is
	   what a tap on the row hits. It keeps a floor of --take-body-min, so a row
	   too narrow to hold both wraps its actions onto their own line instead of
	   letting three 44px touch targets take the row's centre — on 320px that
	   turned a tap meant for the row into a Pick or Keep (#163/2). */
	.take-body {
		--take-body-min: 11rem;
		display: flex;
		align-items: center;
		gap: 0.6rem;
		flex: 1 1 var(--take-body-min);
		min-width: var(--take-body-min);
	}

	.take-label {
		font-family: var(--font-display);
		font-size: 0.85rem;
		letter-spacing: 0.3px;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.take-duration {
		font-size: 0.75rem;
		color: var(--text-subtle);
		flex: 1;
		flex-shrink: 0;
		white-space: nowrap;
	}

	.score-badge {
		font-family: var(--font-display);
		font-size: 0.95rem;
		min-width: 24px;
		text-align: center;
	}

	.score-badge.good {
		color: var(--score-good);
	}

	.score-badge.ok {
		color: var(--score-ok);
	}

	.score-badge.bad {
		color: var(--score-bad);
	}

	.model-badge {
		font-size: 0.6rem;
		padding: 0.1rem 0.35rem;
		border-radius: 3px;
		letter-spacing: 0.3px;
		background: var(--surface-hover);
		border: 1px solid var(--border);
		color: var(--text-subtle);
		white-space: nowrap;
		flex-shrink: 0;
	}

	.rescoring-badge {
		font-size: 0.6rem;
		padding: 0.1rem 0.35rem;
		border-radius: 3px;
		letter-spacing: 0.3px;
		background: color-mix(in srgb, var(--accent) 14%, transparent);
		border: 1px solid var(--accent);
		color: var(--accent);
		white-space: nowrap;
		flex-shrink: 0;
	}

	.batch-badge {
		font-size: 0.6rem;
		padding: 0.1rem 0.35rem;
		border-radius: 3px;
		letter-spacing: 0.3px;
		background: rgba(220, 140, 20, 0.15);
		border: 1px solid rgba(220, 140, 20, 0.5);
		color: #f0a030;
		white-space: nowrap;
		flex-shrink: 0;
	}

	.quality-flag-badge {
		font-size: 0.6rem;
		padding: 0.1rem 0.35rem;
		border-radius: 3px;
		letter-spacing: 0.3px;
		background: rgba(220, 60, 60, 0.12);
		border: 1px solid var(--score-bad);
		color: var(--score-bad);
		white-space: nowrap;
		flex-shrink: 0;
	}

	.expiry-badge {
		font-size: 0.6rem;
		padding: 0.1rem 0.35rem;
		border-radius: 3px;
		letter-spacing: 0.3px;
	}

	.expiry-badge.warn {
		background: rgba(220, 140, 20, 0.15);
		border: 1px solid rgba(220, 140, 20, 0.5);
		color: #f0a030;
	}

	.expiry-badge.archived {
		background: rgba(200, 60, 60, 0.15);
		border: 1px solid rgba(200, 60, 60, 0.5);
		color: #e07070;
		text-transform: uppercase;
	}

	.take-actions {
		display: flex;
		align-items: center;
		gap: 0.35rem;
		flex-shrink: 0;
		margin-left: auto;
	}

	/* The picker is `position: absolute` against its anchor — without one it
	   escapes the row and lands wherever the nearest positioned ancestor is. */
	.take-picker-anchor {
		position: relative;
	}

	/* Dims the row's own identity, never the row box: `opacity` on the row
	   would create a stacking context and clip its own popovers (take menu,
	   playlist picker) under the next row. */
	.take-row.archived {
		cursor: default;
	}

	.take-row.archived .take-label,
	.take-row.archived .take-duration,
	.take-row.archived .score-badge,
	.take-row.archived .model-badge,
	.take-row.archived .batch-badge,
	.take-row.archived .quality-flag-badge {
		color: var(--text-disabled);
	}

	.take-row.archived:hover {
		border-color: var(--border);
		background: var(--surface);
	}

	.pick-btn,
	.keep-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		background: none;
		border: none;
		color: var(--text-muted);
		cursor: pointer;
		padding: 0.15rem;
	}

	.pick-btn:hover,
	.pick-btn.picked {
		color: var(--accent);
	}

	.keep-btn:hover,
	.keep-btn.kept {
		color: var(--keep);
	}

	.selection-checkbox {
		display: flex;
		align-items: center;
		color: var(--text-decoration);
		flex-shrink: 0;
	}

	.take-row.selected .selection-checkbox {
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
		padding: 0.3rem 0.7rem;
		background: none;
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text-muted);
		font-size: var(--label-font-size);
		font-family: var(--font-body);
		cursor: pointer;
	}

	.retry-btn:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	@media (max-width: 768px) {
		.take-row {
			padding: 0.55rem 0.6rem;
		}
	}
</style>
