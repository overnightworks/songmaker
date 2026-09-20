<script lang="ts">
	import type { SongItem, GenerationItem, JobItem, UserLoraItem } from '$lib/api/types';
	import type { SourceMode } from '$lib/stores/recipe';
	import {
		COARSE_POINTER_MEDIA,
		EXPIRY_WARN_DAYS,
		LIBRARY_RETRY_LABEL,
		TAKE_ARCHIVED_TITLE,
		TAKE_PROVENANCE_COVER_PREFIX,
		TAKE_PROVENANCE_REPAINT_PREFIX,
		TAKE_PICK_LABEL,
		TAKE_RESCORING_LABEL,
		TAKES_DELETE_VERSION_LABEL,
		TAKES_DRAFT_BANNER_TEMPLATE,
		TAKES_EMPTY,
		TAKES_ERROR,
		TAKES_GENERATING_LABEL,
		TAKES_LOADING,
		TAKES_MOBILE_HINT,
		TRANSPORT_PLAY_LABEL,
		TRANSPORT_PAUSE_LABEL,
		TAKES_QUEUED_LABEL
	} from '$lib/constants';
	import {
		nowPlayingTakeLabel,
		takeBatchReductionLabel,
		takeRowLabel,
		takeGroupLabel,
		TAKE_KEPT_MARKER_LABEL,
		TAKE_SELECT_LABEL,
		NOW_PLAYING_UNPICK_LABEL
	} from '$lib/constants/now-playing';
	import { removeGenerationFromSong, replaceSongInList } from '$lib/stores/libraryData';
	import { playTake, playTakeAndShowNowPlaying, selectedGenerationId } from '$lib/stores/player';
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
		voices?: UserLoraItem[];
		loadStatus?: 'loading' | 'ready' | 'error';
		loadError?: string | null;
		dirty: boolean;
		draftVersionNumber: number;
		latestVersionNumber: number;
		generateJob?: JobItem | null;
		onagain: (gen: GenerationItem) => void;
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
		generateJob = null,
		onagain,
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
		versionNumber: number | null;
		generations: GenerationItem[];
	}

	const groups = $derived.by((): VersionGroup[] => {
		const map: Record<string, VersionGroup> = {};
		for (const gen of song.generations) {
			const key = gen.version_number !== null ? `v${gen.version_number}` : 'unknown';
			if (!map[key]) {
				map[key] = {
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
		const seconds = gen.audio_duration_sec;
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

	function handlePlayClick(gen: GenerationItem, e: MouseEvent): void {
		e.stopPropagation();
		if (e.ctrlKey || e.metaKey) {
			toggleSelection(gen.id);
			return;
		}
		if ($selectionMode) {
			toggleSelection(gen.id);
			return;
		}
		if (gen.is_archived) return;
		void playTake(gen, song);
	}

	// The row's click rule (#140): a tap on the row body — its name, duration
	// and score, everything except the ▶ symbol, the pick star and the menu —
	// plays the take and opens Now Playing on it. Selection mode re-purposes
	// it to a select tap instead, same as every other row control.
	function handleRowBodyClick(gen: GenerationItem): void {
		if ($selectionMode) {
			toggleSelection(gen.id);
			return;
		}
		if (gen.is_archived) return;
		void playTakeAndShowNowPlaying(gen, song);
	}

	// An archived take has nothing for a row activation to do, so the row
	// stops announcing itself as reachable — except in selection mode, where
	// ticking it is still a real action.
	function rowIsActionable(gen: GenerationItem): boolean {
		return $selectionMode || !gen.is_archived;
	}

	function handleRowKeydown(gen: GenerationItem, e: KeyboardEvent): void {
		if (e.key !== 'Enter' && e.key !== ' ') return;
		e.preventDefault();
		handleRowBodyClick(gen);
	}

	interface TakeProvenance {
		label: string;
		sourceId: string | null;
	}

	function takeProvenance(gen: GenerationItem): TakeProvenance | null {
		const taskType = gen.generation_params?.task_type;
		if ((taskType !== 'repaint' && taskType !== 'cover') || gen.src_generation_number == null) {
			return null;
		}
		const source = song.generations.find((candidate) => candidate.id === gen.src_generation_id);
		const sourceVersionNumber = source?.version_number ?? gen.src_generation_version_number ?? null;
		return {
			label: `${taskType === 'repaint' ? TAKE_PROVENANCE_REPAINT_PREFIX : TAKE_PROVENANCE_COVER_PREFIX} ${nowPlayingTakeLabel(sourceVersionNumber, gen.src_generation_number)}`,
			sourceId: source?.id ?? null
		};
	}

	function voiceForGeneration(gen: GenerationItem): UserLoraItem | undefined {
		const loraId = gen.generation_params?.user_lora_id;
		return loraId ? voices.find((voice) => voice.id === loraId) : undefined;
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
						{generateJob.queue_position
							? `· ${TAKES_QUEUED_LABEL} #${generateJob.queue_position}`
							: `· ${TAKES_QUEUED_LABEL}`}
						{#if generateJob.queue_reason}
							· {generateJob.queue_reason}
						{/if}
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
					<span class="version-header"
						>{takeGroupLabel(group.versionNumber, group.generations.length)}</span
					>
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
					{@const playing = isGenPlaying(gen) && audioPlayer.status === 'playing'}
					{@const duration = formatDuration(gen)}
					{@const provenance = takeProvenance(gen)}
					{@const headline = headlineScore(gen)}
					{@const flag = qualityFlag(gen.scores)}
					{@const batchNotice = takeBatchReductionLabel(gen.generation_params)}
					{@const voice = voiceForGeneration(gen)}
					<div
						id={`take-${gen.id}`}
						class="take-row"
						data-hitbox-size="frequent"
						class:playing={isGenPlaying(gen)}
						class:buffering={isGenLoading(gen)}
						class:selected={$selectedIds.has(gen.id)}
						class:archived={gen.is_archived}
						title={gen.is_archived ? TAKE_ARCHIVED_TITLE : undefined}
					>
						<span class="take-main">
							<span class="take-headline">
								{#if $selectionMode || !gen.is_archived}
									<button
										type="button"
										class="play-btn"
										data-hitbox="frequent"
										data-hitbox-face
										onclick={(event) => handlePlayClick(gen, event)}
										aria-pressed={$selectionMode ? $selectedIds.has(gen.id) : undefined}
										aria-label={`${$selectionMode ? TAKE_SELECT_LABEL : playing ? TRANSPORT_PAUSE_LABEL : TRANSPORT_PLAY_LABEL} ${nowPlayingTakeLabel(gen.version_number, gen.generation_number)}`}
									>
										{#if $selectionMode}
											<Icon name={$selectedIds.has(gen.id) ? 'check-square' : 'square'} size={16} />
										{:else}
											<Icon name={playing ? 'pause' : 'play'} size={16} />
										{/if}
									</button>
								{/if}

								<span
									class="take-summary"
									role="button"
									tabindex={rowIsActionable(gen) ? 0 : -1}
									aria-disabled={rowIsActionable(gen) ? undefined : true}
									data-hitbox="text"
									onclick={() => handleRowBodyClick(gen)}
									onkeydown={(e) => handleRowKeydown(gen, e)}
								>
									<span class="take-label">
										{takeRowLabel(gen.generation_number)}
									</span>

									{#if duration}
										<span class="take-duration">{duration}</span>
									{/if}

									{#if headline}
										<span
											class="score-badge {headline.color}"
											title={`${headline.label} ${headline.text}`}
										>
											<span class="score-shape" aria-hidden="true"></span>
											{headline.text}
										</span>
									{/if}
								</span>
							</span>
							<span class="take-details">
								{#if batchNotice}
									<span
										class="batch-badge"
										title="Batch size reduced by ACE-Step due to available VRAM: delivered {batchNotice}"
									>
										⚠ {batchNotice}
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

							{#if provenance}
								{#if $selectionMode}
									<button type="button" class="take-origin" onclick={() => toggleSelection(gen.id)}>
										{provenance.label}
									</button>
								{:else}
									<span class="take-origin">
										{#if provenance.sourceId}
											<a href={`#take-${provenance.sourceId}`}>{provenance.label}</a>
										{:else}
											{provenance.label}
										{/if}
									</span>
								{/if}
							{/if}

							{#if voice}
								<span class:deleted-voice={voice.deleted_at !== null} class="take-voice">
									Voice: {voice.name}{voice.deleted_at ? ' — voice deleted' : ''}
								</span>
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
								aria-label={gen.is_picked ? NOW_PLAYING_UNPICK_LABEL : TAKE_PICK_LABEL}
							>
								<Icon name={gen.is_picked ? 'star-filled' : 'star'} size={16} />
							</button>
							{#if gen.is_kept}
								<span class="keep-marker" role="img" aria-label={TAKE_KEPT_MARKER_LABEL}>
									<Icon name="heart-filled" size={16} />
								</span>
							{/if}
							{#if !$selectionMode}
								<TakeMenu
									{gen}
									onagain={() => onagain(gen)}
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
		font-family: var(--font-body);
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
		align-items: center;
		gap: 0.25rem;
		padding: 0.25rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		text-align: left;
		color: var(--text);
		font: inherit;
		width: 100%;
		min-width: 0;
	}

	.take-row:hover {
		border-color: var(--accent);
		background: var(--surface-hover);
	}

	.take-row.playing {
		border-color: var(--accent);
		background: color-mix(in srgb, var(--accent) 10%, var(--surface));
	}

	.take-row.buffering {
		border-color: var(--accent);
		animation: buffer-pulse 1.5s ease-in-out infinite;
	}

	.take-row.selected {
		border-color: var(--accent);
		background: color-mix(in srgb, var(--accent) 5%, var(--surface));
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

	.take-main {
		display: flex;
		flex-direction: column;
		flex: 1;
		min-width: 0;
	}

	.take-headline,
	.take-details {
		display: flex;
		align-items: center;
		gap: 0.35rem;
		min-width: 0;
	}

	.take-details {
		flex-wrap: wrap;
	}

	.take-summary {
		display: flex;
		align-items: center;
		gap: 0.35rem;
		flex: 1;
		min-width: 0;
		cursor: pointer;
	}

	.take-summary[aria-disabled='true'] {
		cursor: default;
	}

	.take-origin {
		background: none;
		border: 0;
		color: var(--accent);
		cursor: pointer;
		font: inherit;
		font-size: 0.68rem;
		margin: 0.2rem 0 0 1.25rem;
		padding: 0;
		text-align: left;
	}

	.take-origin:not(button) {
		cursor: default;
	}

	.take-voice {
		color: var(--text-subtle);
		font-size: 0.68rem;
		margin: 0.2rem 0 0 1.25rem;
	}

	.take-voice.deleted-voice {
		color: var(--score-bad);
	}

	.take-origin a {
		color: inherit;
		text-decoration: underline;
		text-underline-offset: 0.15em;
	}

	.take-label {
		font-family: var(--font-body);
		font-size: var(--btn-font-size);
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.take-duration {
		font-size: var(--label-font-size);
		color: var(--text-subtle);
		flex-shrink: 0;
		white-space: nowrap;
	}

	.score-badge {
		display: inline-flex;
		align-items: center;
		gap: 0.25rem;
		font-size: var(--label-font-size);
		flex-shrink: 0;
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

	.score-shape {
		width: 0.5em;
		height: 0.5em;
		border: 1px solid currentColor;
	}

	.score-badge.good .score-shape {
		border-radius: 50%;
		background: currentColor;
	}

	.score-badge.ok .score-shape {
		border-radius: 50%;
	}

	.score-badge.bad .score-shape {
		background: currentColor;
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
		gap: 0;
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
	.take-row.archived .take-origin,
	.take-row.archived .take-voice,
	.take-row.archived .take-duration,
	.take-row.archived .score-badge,
	.take-row.archived .batch-badge,
	.take-row.archived .quality-flag-badge {
		color: var(--text-disabled);
	}

	.take-row.archived:hover {
		border-color: var(--border);
		background: var(--surface);
	}

	.pick-btn,
	.play-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		background: none;
		border: none;
		color: var(--text-muted);
		cursor: pointer;
		padding: 0;
	}

	.pick-btn:hover,
	.pick-btn.picked,
	.play-btn:hover,
	.take-row.selected .play-btn {
		color: var(--accent);
	}

	.keep-marker {
		display: inline-flex;
		color: var(--text);
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

	@media (prefers-reduced-motion: reduce) {
		.take-row.buffering {
			animation: none;
		}
	}
</style>
