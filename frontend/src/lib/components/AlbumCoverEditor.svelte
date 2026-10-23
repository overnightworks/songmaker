<script lang="ts">
	import { ApiError, describeFailure } from '$lib/api/fetch';
	import { createAlbumCoverSuggestions, selectAlbumCoverSuggestion } from '$lib/api/albums';
	import type { AlbumItem } from '$lib/api/types';
	import {
		RATE_LIMITED_STATUS,
		albumCoverStageLabel,
		albumCoverSuggestionAlt,
		albumCoverSuggestionPosition,
		albumCoverSuggestionsLeftToday,
		ALBUM_COVER_ADD_LABEL,
		ALBUM_COVER_ALT_TYPE,
		ALBUM_COVER_DAILY_LIMIT_REACHED,
		ALBUM_COVER_EDITING_CLOSE_LABEL,
		ALBUM_COVER_EDITING_LABEL,
		ALBUM_COVER_EDITING_REMOVE_LABEL,
		ALBUM_COVER_EDITING_UPLOAD_LABEL,
		ALBUM_COVER_NEXT_SUGGESTION_LABEL,
		ALBUM_COVER_PREVIOUS_SUGGESTION_LABEL,
		ALBUM_COVER_SUGGEST_ANOTHER_LABEL,
		ALBUM_COVER_SUGGEST_LABEL,
		ALBUM_COVER_SUGGESTING_LABEL,
		ALBUM_COVER_SUGGESTION_FAILED_FALLBACK,
		ALBUM_COVER_SUGGESTION_FAILED_TITLE,
		ALBUM_COVER_SUGGESTION_USE_LABEL,
		ALBUM_COVER_SUGGESTIONS_LOADING,
		ALBUM_COVER_SUGGESTIONS_RETRY_LABEL,
		ALBUM_COVER_SWIPE_TRAVEL_PX
	} from '$lib/constants';
	import { updateAlbumInList } from '$lib/stores/libraryData';
	import { addToast } from '$lib/stores/toast';
	import { releaseCoverSuggestions } from '$lib/stores/coverRuns';
	import {
		beginCoverSave,
		beginCoverSuggestion,
		coverActivity,
		coverStanding,
		discardCoverSuggestions,
		endCoverSave,
		endCoverSuggestion,
		followCoverRun,
		isCoverAskRetired,
		knownAfterSave,
		knownCoverSuggestions,
		readCoverActivity,
		retryCoverActivity,
		savingCoverAlbumIds,
		showCoverActivityFailure,
		updateCoverActivity
	} from '$lib/stores/coverActivity';
	import { offline } from '$lib/stores/connectivity';
	import { holdOpenWhile } from '$lib/stores/layers';
	import CoverRunElapsed from './CoverRunElapsed.svelte';
	import Icon from './Icon.svelte';

	interface Props {
		album: AlbumItem;
		onclose: () => void;
		/** Upload; a successful upload releases what the cover state knows. */
		onupload: () => void;
		onremove: () => void;
		/** An upload or removal the album page is saving, which × waits for. */
		saving: boolean;
	}

	type StageSlot =
		{ kind: 'suggestion'; id: string; url: string } | { kind: 'making'; startedAt: string | null };

	const HTTP_CONFLICT = 409;

	let { album, onclose, onupload, onremove, saving }: Props = $props();

	const currentAlbumId = $derived(album.id);

	let chosenSlot = $state<number | null>(null);
	let followedRunId = $state<string | null>(null);
	let swipeStart: { pointerId: number; x: number; y: number } | null = null;

	const activity = $derived($coverActivity?.albumId === currentAlbumId ? $coverActivity : null);
	const standing = $derived($coverStanding?.albumId === currentAlbumId ? $coverStanding : null);
	const coverSuggestions = $derived(activity?.data ?? null);
	const coverSuggestionsFailure = $derived(activity?.failure ?? null);
	const coverSuggestionsLoading = $derived(activity?.isLoading ?? false);
	const coverSuggestionsReloadsExhausted = $derived(
		Boolean(activity?.unreachable && !$offline && activity.reloadsExhausted)
	);
	const coverSuggestionsBusy = $derived($savingCoverAlbumIds.has(currentAlbumId));
	const latestCoverJob = $derived(coverSuggestions?.job ?? null);
	const isCoverSuggestionGenerating = $derived(standing?.running ?? false);
	const dailySuggestionsSpent = $derived(
		coverSuggestions !== null && coverSuggestions.used_today >= coverSuggestions.daily_limit
	);
	const dailyLimitNote = $derived(
		dailySuggestionsSpent ? (activity?.limitNote ?? ALBUM_COVER_DAILY_LIMIT_REACHED) : null
	);
	const canSuggestCover = $derived(
		!isCoverSuggestionGenerating &&
			!coverSuggestionsLoading &&
			!coverSuggestionsBusy &&
			!dailyLimitNote
	);
	// At the daily limit the limit is the one word the editor says, so the
	// failure of a run from before this visit stays silent beside it; a run
	// this visit followed still names how it ended (#1202).
	const latestRunFailureShown = $derived(
		latestCoverJob?.status === 'failed' && (!dailyLimitNote || latestCoverJob.id === followedRunId)
	);
	const coverSuggestionFailure = $derived(
		coverSuggestionsFailure ??
			(latestRunFailureShown
				? (latestCoverJob?.error ?? ALBUM_COVER_SUGGESTION_FAILED_FALLBACK)
				: null)
	);
	const suggestionCount = $derived(coverSuggestions?.suggestions.length ?? 0);
	const hasSuggestions = $derived(suggestionCount > 0);
	const stageSlots = $derived<StageSlot[]>([
		...(coverSuggestions?.suggestions ?? []).map((suggestion): StageSlot => ({
			kind: 'suggestion',
			...suggestion
		})),
		...(isCoverSuggestionGenerating
			? [{ kind: 'making', startedAt: standing?.startedAt ?? null } as const]
			: [])
	]);
	const shownSlotIndex = $derived(
		Math.min(chosenSlot ?? stageSlots.length - 1, stageSlots.length - 1)
	);
	const shownSlot = $derived(stageSlots[shownSlotIndex] ?? null);
	const shownSuggestionId = $derived(shownSlot?.kind === 'suggestion' ? shownSlot.id : null);
	const shownSuggestionNumber = $derived(shownSuggestionId ? shownSlotIndex + 1 : null);
	const stageLabel = $derived(
		shownSuggestionNumber ? albumCoverStageLabel(shownSuggestionNumber, suggestionCount) : undefined
	);

	// The album page keeps the cover state read; the editor shows it. Opening
	// reads it once more, so a day that turned while the page stayed open frees
	// the quota; a read only looks, and only Suggest makes a suggestion. Leaving
	// the editor -- Back, Escape, another page or album -- stops and discards
	// nothing, and reads the state once more for the closed cover; only ×, Use
	// and Upload discard.
	$effect(() => {
		const albumId = currentAlbumId;
		followedRunId = null;
		void readCoverActivity(albumId);
		return () => void readCoverActivity(albumId);
	});

	$effect(() => {
		if (activity?.runId) followedRunId = activity.runId;
	});

	async function suggestCover(): Promise<void> {
		if (!canSuggestCover) return;
		const albumId = currentAlbumId;
		chosenSlot = null;
		const ask = beginCoverSuggestion(albumId);
		try {
			const job = await createAlbumCoverSuggestions(albumId);
			if (isCoverAskRetired(albumId, ask)) {
				// ×, Use or Upload came first: this run and what it made go.
				void releaseCoverSuggestions(albumId, { suggestionIds: [], jobIds: [job.id] }).then(
					() => readCoverActivity(albumId),
					(error: unknown) => {
						reportDiscardFailure(error);
						return readCoverActivity(albumId);
					}
				);
				return;
			}
			endCoverSuggestion(albumId);
			followedRunId = job.id;
			followCoverRun(job, albumId);
			if (albumId !== currentAlbumId) return;
			void readCoverActivity(albumId);
		} catch (error) {
			// A discard has already ended this ask's wait; its failure is not the newer state's.
			if (isCoverAskRetired(albumId, ask)) return;
			endCoverSuggestion(albumId);
			if (albumId !== currentAlbumId) return;
			if (isRefusal(error)) {
				await rereadAfterRefusal(albumId, error);
				return;
			}
			showCoverActivityFailure(albumId, error, { keepData: true });
		}
	}

	function isRefusal(error: unknown): error is ApiError {
		return (
			error instanceof ApiError &&
			(error.status === HTTP_CONFLICT || error.status === RATE_LIMITED_STATUS)
		);
	}

	// A refusal means the count and list the editor holds are stale -- another
	// tab or a new day may have moved them -- so both are read again. Only a
	// count that says today's suggestions are spent makes a 429 the daily
	// limit, with the server's words beside it. A 409 needs no word of its own:
	// the reread either follows the run that still goes or shows how it ended,
	// so that run counts as followed even when it already ended.
	// Any other 429 (the request throttle) is an ordinary failure that the next
	// Suggest may retry.
	async function rereadAfterRefusal(albumId: string, refusal: ApiError): Promise<void> {
		await readCoverActivity(albumId);
		if (albumId !== currentAlbumId || coverSuggestions === null) return;
		if (refusal.status === HTTP_CONFLICT) {
			followedRunId = latestCoverJob?.id ?? null;
			return;
		}
		if (refusal.status === RATE_LIMITED_STATUS && dailySuggestionsSpent) {
			const limitNote = describeFailure(refusal, ALBUM_COVER_DAILY_LIMIT_REACHED);
			updateCoverActivity(albumId, (state) => ({ ...state, limitNote }));
			return;
		}
		showCoverActivityFailure(albumId, refusal, { keepData: true });
	}

	// The server deletes the rows and commits before it removes the files, so
	// a failed or uncertain discard may come after the suggestions are gone;
	// the discard reads the state again, so the editor shows what is left.
	function reportDiscardFailure(error: unknown): void {
		addToast(describeFailure(error, ALBUM_COVER_SUGGESTION_FAILED_FALLBACK), 'error');
	}

	async function discardAndClose(): Promise<void> {
		const albumId = currentAlbumId;
		const known = knownCoverSuggestions(albumId);
		beginCoverSave(albumId);
		try {
			await discardCoverSuggestions(albumId, known);
			onclose();
		} catch (error) {
			reportDiscardFailure(error);
		} finally {
			endCoverSave(albumId);
		}
	}

	async function selectCoverSuggestion(suggestionId: string): Promise<void> {
		const albumId = currentAlbumId;
		const known = knownCoverSuggestions(albumId);
		beginCoverSave(albumId);
		try {
			const updated = await holdOpenWhile(
				'cover-saving',
				selectAlbumCoverSuggestion(albumId, { suggestion_id: suggestionId })
			);
			try {
				await discardCoverSuggestions(albumId, knownAfterSave(albumId, known));
			} catch (error) {
				reportDiscardFailure(error);
			}
			updateAlbumInList(albumId, () => updated);
			addToast('Cover saved', 'success');
		} catch (error) {
			addToast(describeFailure(error, ALBUM_COVER_SUGGESTION_FAILED_FALLBACK), 'error');
		} finally {
			endCoverSave(albumId);
		}
	}

	function showSlot(index: number): void {
		if (coverSuggestionsBusy || index < 0 || index >= stageSlots.length) return;
		chosenSlot = index;
	}

	function startSwipe(event: PointerEvent): void {
		swipeStart = { pointerId: event.pointerId, x: event.clientX, y: event.clientY };
	}

	function endSwipe(event: PointerEvent): void {
		if (swipeStart?.pointerId !== event.pointerId) return;
		const travel = event.clientX - swipeStart.x;
		const drift = Math.abs(event.clientY - swipeStart.y);
		swipeStart = null;
		if (Math.abs(travel) < ALBUM_COVER_SWIPE_TRAVEL_PX || Math.abs(travel) <= drift) return;
		showSlot(shownSlotIndex + (travel < 0 ? 1 : -1));
	}

	function cancelSwipe(): void {
		swipeStart = null;
	}
</script>

<div class="cover-editor" role="group" aria-label={ALBUM_COVER_EDITING_LABEL}>
	<div
		class="cover-stage"
		role="group"
		aria-label={stageLabel}
		onpointerdown={startSwipe}
		onpointerup={endSwipe}
		onpointercancel={cancelSwipe}
	>
		{#if stageSlots.length > 1}
			<button
				type="button"
				class="stage-nav"
				aria-label={ALBUM_COVER_PREVIOUS_SUGGESTION_LABEL}
				disabled={coverSuggestionsBusy || shownSlotIndex === 0}
				onclick={() => showSlot(shownSlotIndex - 1)}>‹</button
			>
		{:else}
			<span class="stage-nav-gap"></span>
		{/if}
		<div class="stage-art" class:stage-art-empty={!shownSlot && !album.cover}>
			{#if shownSlot?.kind === 'suggestion'}
				<img src={shownSlot.url} alt={albumCoverSuggestionAlt(album.title)} draggable="false" />
			{:else if shownSlot?.kind === 'making'}
				<div class="stage-making" role="status">
					<span class="stage-ring" aria-hidden="true"></span>
					<span
						>{ALBUM_COVER_SUGGESTING_LABEL}{#if shownSlot.startedAt}<CoverRunElapsed
								startedAt={shownSlot.startedAt}
							/>{/if}</span
					>
				</div>
			{:else if album.cover}
				<img
					src={album.cover.detail}
					alt={`${ALBUM_COVER_ALT_TYPE} ${album.title}`}
					draggable="false"
				/>
			{:else}
				<button type="button" class="stage-empty" onclick={() => onupload()}
					>{ALBUM_COVER_ADD_LABEL}</button
				>
			{/if}
		</div>
		{#if stageSlots.length > 1}
			<button
				type="button"
				class="stage-nav"
				aria-label={ALBUM_COVER_NEXT_SUGGESTION_LABEL}
				disabled={coverSuggestionsBusy || shownSlotIndex === stageSlots.length - 1}
				onclick={() => showSlot(shownSlotIndex + 1)}>›</button
			>
		{:else}
			<span class="stage-nav-gap"></span>
		{/if}
	</div>

	<p class="cover-count" aria-live="polite">
		{#if coverSuggestionsReloadsExhausted}
			<button
				class="cover-suggestions-retry"
				type="button"
				onclick={() => retryCoverActivity(currentAlbumId)}
				>{ALBUM_COVER_SUGGESTIONS_RETRY_LABEL}</button
			>
		{:else if coverSuggestions}
			{#if shownSuggestionNumber}
				<b>{albumCoverSuggestionPosition(shownSuggestionNumber, suggestionCount)}</b>
				<span aria-hidden="true">·</span>
			{/if}
			<span
				>{albumCoverSuggestionsLeftToday(
					coverSuggestions.used_today,
					coverSuggestions.daily_limit
				)}</span
			>
		{:else if coverSuggestionsLoading}
			<span role="status">{ALBUM_COVER_SUGGESTIONS_LOADING}</span>
		{/if}
		{#if dailyLimitNote}
			<span class="cover-limit">{dailyLimitNote}</span>
		{/if}
		{#if coverSuggestionFailure}
			<span class="cover-failure" role="alert">
				<strong>{ALBUM_COVER_SUGGESTION_FAILED_TITLE}</strong>
				{coverSuggestionFailure}
			</span>
		{/if}
	</p>

	<div class="cover-actions">
		<button
			type="button"
			class="cover-action"
			data-hitbox="frequent"
			disabled={coverSuggestionsBusy}
			onclick={() => onupload()}>{ALBUM_COVER_EDITING_UPLOAD_LABEL}</button
		>
		<button
			type="button"
			class="cover-action"
			data-hitbox="frequent"
			disabled={!canSuggestCover}
			onclick={suggestCover}
			>{hasSuggestions ? ALBUM_COVER_SUGGEST_ANOTHER_LABEL : ALBUM_COVER_SUGGEST_LABEL}</button
		>
		{#if hasSuggestions}
			<button
				type="button"
				class="cover-action cover-use"
				data-hitbox="frequent"
				disabled={!shownSuggestionId || coverSuggestionsBusy}
				onclick={() => shownSuggestionId && selectCoverSuggestion(shownSuggestionId)}
				>{ALBUM_COVER_SUGGESTION_USE_LABEL}</button
			>
		{/if}
		{#if album.cover}
			<button
				type="button"
				class="cover-action cover-remove"
				data-hitbox="frequent"
				disabled={coverSuggestionsBusy}
				onclick={onremove}>{ALBUM_COVER_EDITING_REMOVE_LABEL}</button
			>
		{/if}
		<button
			type="button"
			class="cover-close"
			data-hitbox="frequent"
			aria-label={ALBUM_COVER_EDITING_CLOSE_LABEL}
			title={ALBUM_COVER_EDITING_CLOSE_LABEL}
			disabled={coverSuggestionsBusy || saving}
			onclick={discardAndClose}
		>
			<Icon name="x" size={20} />
		</button>
	</div>
</div>

<style>
	/* The editor's parts sit in the header's own grid areas (stage, count,
	   tryrow), so the header can lay them out beside or above its titles. */
	.cover-editor {
		display: contents;
	}

	.cover-stage {
		grid-area: stage;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 0.6rem;
		touch-action: pan-y;
	}

	.stage-art {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 200px;
		height: 200px;
		flex: none;
		overflow: hidden;
		border-radius: 4px;
		outline: 2px solid var(--accent);
		outline-offset: 3px;
		background: var(--surface-hover);
	}

	.stage-art-empty {
		outline-style: dashed;
		outline-color: var(--text-subtle);
	}

	.stage-art img {
		display: block;
		width: 100%;
		height: 100%;
		object-fit: cover;
		user-select: none;
	}

	.stage-nav,
	.stage-nav-gap {
		width: var(--hitbox-frequent);
		height: var(--hitbox-frequent);
		flex: none;
	}

	.stage-nav {
		border: 1px solid var(--border);
		border-radius: 50%;
		background: var(--surface);
		color: var(--text);
		font-size: 1.4rem;
		line-height: 1;
	}

	.stage-nav:disabled {
		border-color: transparent;
		background: none;
		color: var(--text-disabled);
	}

	.stage-empty {
		width: 100%;
		height: 100%;
		border: none;
		background: none;
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: 0.85rem;
		letter-spacing: 0.04em;
		text-transform: uppercase;
	}

	.stage-making {
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
		width: 100%;
		padding: 1rem;
		color: var(--text-muted);
		font-size: 0.83rem;
		text-align: center;
	}

	.stage-ring {
		align-self: center;
		width: 2rem;
		height: 2rem;
		border: 3px solid var(--border);
		border-top-color: var(--accent);
		border-radius: 50%;
		animation: stage-turn 2.4s linear infinite;
	}

	@keyframes stage-turn {
		to {
			transform: rotate(360deg);
		}
	}

	.cover-failure {
		flex-basis: 100%;
		padding-top: 0.3rem;
		border-top: 2px solid var(--score-bad);
		text-align: center;
	}

	.cover-failure strong {
		display: block;
		color: var(--text);
		font-size: 0.8rem;
	}

	.cover-count {
		grid-area: count;
		display: flex;
		flex-wrap: wrap;
		justify-content: center;
		gap: 0.2rem 0.6rem;
		margin: 0;
		color: var(--text-subtle);
		font-size: 0.75rem;
	}

	.cover-count b {
		color: var(--text);
		font-weight: 600;
	}

	.cover-limit {
		flex-basis: 100%;
		text-align: center;
	}

	.cover-actions {
		grid-area: tryrow;
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.4rem;
	}

	.cover-action,
	.cover-suggestions-retry {
		height: var(--hitbox-frequent);
		padding: 0 0.7rem;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		background: none;
		color: var(--text-light);
		font-family: var(--font-display);
		font-size: 0.8rem;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		white-space: nowrap;
	}

	.cover-suggestions-retry {
		color: var(--text-muted);
	}

	.cover-action.cover-use {
		padding: 0 1rem;
		border-color: var(--primary);
		background: var(--primary);
		color: #fff;
	}

	.cover-action.cover-use:disabled {
		border-color: var(--border);
		background: none;
		color: var(--text-disabled);
	}

	.cover-action.cover-remove {
		border-color: transparent;
		color: var(--text-muted);
	}

	.cover-action:disabled {
		opacity: 0.5;
	}

	.cover-close {
		width: var(--hitbox-frequent);
		height: var(--hitbox-frequent);
		border: none;
		background: none;
		color: var(--text-muted);
	}

	@media (max-width: 768px) {
		.cover-action.cover-use {
			margin-left: auto;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.stage-ring {
			animation: none;
		}
	}
</style>
