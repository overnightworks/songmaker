<script lang="ts">
	import { flushSync } from 'svelte';
	import type { SongItem, GenerationItem, UserLoraItem } from '$lib/api/types';
	import type { SourceMode } from '$lib/stores/recipe';
	import {
		EXPIRY_WARN_DAYS,
		TAKE_ARCHIVED_TITLE,
		TAKE_PROVENANCE_COVER_PREFIX,
		TAKE_PROVENANCE_REPAINT_PREFIX,
		TAKE_KEEP_LABEL,
		TAKE_PICK_LABEL,
		TAKE_UNKEEP_LABEL,
		TAKE_RESCORING_LABEL
	} from '$lib/constants';
	import {
		nowPlayingTakeLabel,
		takeBatchReductionLabel,
		takeRowLabel,
		TAKE_SELECT_LABEL,
		NOW_PLAYING_UNPICK_LABEL
	} from '$lib/constants/now-playing';
	import { playTake, playTakeAndShowNowPlaying } from '$lib/stores/player';
	import { rescoringTakeIds } from '$lib/stores/takeActions';
	import {
		audioPlayer,
		transportButtonFace,
		transportButtonLabel,
		transportIsBusy
	} from '$lib/services/audioPlayer.svelte';
	import { formatScore, qualityFlag, scoreColor, scoreReadings } from '$lib/utils/scores';
	import { getGenerationActions, type GenerationActions } from '$lib/contexts/generation-actions';
	import { selectionMode, selectedIds, toggleSelection } from '$lib/stores/selection';
	import { revealTakeGroup, takeGroupKey } from '$lib/stores/takeFolds';
	import { formatTime } from '$lib/utils/format';
	import Icon from '../Icon.svelte';
	import TransportButtonIcon from '../TransportButtonIcon.svelte';
	import PlaylistPicker from '../PlaylistPicker.svelte';
	import TakeMenu from './TakeMenu.svelte';

	interface Props {
		gen: GenerationItem;
		song: SongItem;
		voices: UserLoraItem[];
		playlistOpen: boolean;
		onsource: (gen: GenerationItem, mode: SourceMode) => void;
		onaddtoplaylist: () => void;
		onselectplaylist: (playlistId: string) => void;
		onclosepicker: () => void;
		ondelete: () => void;
	}

	let {
		gen,
		song,
		voices,
		playlistOpen,
		onsource,
		onaddtoplaylist,
		onselectplaylist,
		onclosepicker,
		ondelete
	}: Props = $props();

	const actions: GenerationActions = getGenerationActions();

	const playingGenId = $derived(audioPlayer.current?.generation.id ?? null);
	const buffering = $derived(
		audioPlayer.status === 'loading' || audioPlayer.status === 'buffering'
	);

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
		return formatTime(seconds);
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
	// and score, everything except the ▶ symbol, the ★ and ♥ toggles and the
	// menu — plays the take and opens Now Playing on it. Selection mode
	// re-purposes it to a select tap instead, same as every other row control.
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
		source: GenerationItem | null;
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
			source: source ?? null
		};
	}

	function voiceForGeneration(gen: GenerationItem): UserLoraItem | undefined {
		const loraId = gen.generation_params?.user_lora_id;
		return loraId ? voices.find((voice) => voice.id === loraId) : undefined;
	}

	// An archived take is only a name in a list that cleanup will empty, so it
	// carries no control or detail that promises it will stay.
	const compact = $derived(gen.is_archived);
	const transport = $derived(isGenPlaying(gen) ? audioPlayer.transport : 'idle');
	const duration = $derived(formatDuration(gen));
	const provenance = $derived(compact ? null : takeProvenance(gen));
	const headline = $derived(compact ? null : headlineScore(gen));
	const flag = $derived(compact ? null : qualityFlag(gen.scores));
	const batchNotice = $derived(compact ? null : takeBatchReductionLabel(gen.generation_params));
	const voice = $derived(compact ? undefined : voiceForGeneration(gen));
	// A link into a folded version unfolds it first; the browser then follows the
	// hash to the take, which exists by the time it looks.
	function revealSource(source: GenerationItem): void {
		revealTakeGroup(takeGroupKey(source));
		flushSync();
	}

	const takeName = $derived(nowPlayingTakeLabel(gen.version_number, gen.generation_number));
</script>

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
					aria-busy={$selectionMode ? undefined : transportIsBusy(transport)}
					aria-label={`${$selectionMode ? TAKE_SELECT_LABEL : transportButtonLabel(transport)} ${takeName}`}
				>
					{#if $selectionMode}
						<Icon name={$selectedIds.has(gen.id) ? 'check-square' : 'square'} size={16} />
					{:else}
						<TransportButtonIcon face={transportButtonFace(transport)} size={16} />
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
					<span class="score-badge {headline.color}" title={`${headline.label} ${headline.text}`}>
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

			{#if !compact && $rescoringTakeIds.has(gen.id)}
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
						title="Expires in {daysLeft} day{daysLeft === 1 ? '' : 's'} — pick or keep to preserve"
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
					{#if provenance.source}
						{@const source = provenance.source}
						<a href={`#take-${source.id}`} onclick={() => revealSource(source)}
							>{provenance.label}</a
						>
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
		{#if !compact}
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
				aria-label={`${gen.is_picked ? NOW_PLAYING_UNPICK_LABEL : TAKE_PICK_LABEL} ${takeName}`}
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
				aria-label={`${gen.is_kept ? TAKE_UNKEEP_LABEL : TAKE_KEEP_LABEL} ${takeName}`}
			>
				<Icon name={gen.is_kept ? 'heart-filled' : 'heart'} size={16} />
			</button>
		{/if}
		{#if !$selectionMode}
			<TakeMenu
				{gen}
				onrepaint={() => onsource(gen, 'repaint')}
				oncover={() => onsource(gen, 'cover')}
				onshare={() => actions.share(gen.id)}
				onunshare={() => actions.unshare(gen.id)}
				{onaddtoplaylist}
				{ondelete}
			/>
			{#if playlistOpen}
				<div
					class="take-picker-anchor"
					onclick={(e) => e.stopPropagation()}
					onkeydown={(e) => e.stopPropagation()}
					role="presentation"
				>
					<PlaylistPicker onselect={onselectplaylist} onclose={onclosepicker} />
				</div>
			{/if}
		{/if}
	</span>
</div>

<style>
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
	.keep-btn,
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

	.keep-btn:hover,
	.keep-btn.kept {
		color: var(--keep);
	}

	@media (prefers-reduced-motion: reduce) {
		.take-row.buffering {
			animation: none;
		}
	}
</style>
