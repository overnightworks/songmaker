<script lang="ts">
	import { ApiError, describeFailure, NetworkError } from '$lib/api/fetch';
	import {
		createAlbumCoverSuggestions,
		discardAlbumCoverSuggestions,
		fetchAlbumCoverSuggestions,
		selectAlbumCoverSuggestion
	} from '$lib/api/albums';
	import { cancelJob } from '$lib/api/jobs';
	import type { AlbumItem, CoverSuggestionsResponse, JobItem } from '$lib/api/types';
	import {
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
	import { activeJobs, removeJob, trackJob } from '$lib/stores/jobs';
	import { offline, reloadWhileUnreachable } from '$lib/stores/connectivity';
	import { holdOpenWhile } from '$lib/stores/layers';
	import Icon from './Icon.svelte';

	interface Props {
		album: AlbumItem;
		onclose: () => void;
		onupload: () => void;
		onremove: () => void;
		/** An upload or removal the album page is saving, which × waits for. */
		saving: boolean;
	}

	interface CoverSuggestionsState {
		albumId: string;
		data: CoverSuggestionsResponse | null;
		failure: string | null;
		unreachable: boolean;
		limitNote: string | null;
		isLoading: boolean;
	}

	type CoverSuggestionsOutcome = Pick<
		CoverSuggestionsState,
		'failure' | 'unreachable' | 'limitNote'
	>;

	type StageSlot =
		{ kind: 'suggestion'; id: string; url: string } | { kind: 'making'; progress: number };

	const HTTP_CONFLICT = 409;
	const HTTP_TOO_MANY_REQUESTS = 429;

	const COVER_SUGGESTIONS_SETTLED: CoverSuggestionsOutcome = {
		failure: null,
		unreachable: false,
		limitNote: null
	};

	let { album, onclose, onupload, onremove, saving }: Props = $props();

	const currentAlbumId = $derived(album.id);

	let coverSuggestionsState = $state<CoverSuggestionsState | null>(null);
	let coverSuggestionsBusyAlbumId = $state<string | null>(null);
	let suggestionsRequest = 0;
	let coverSuggestionsBackoffSpent = $state(false);
	let completedCoverJobId: string | null = null;
	let chosenSlot = $state<number | null>(null);
	let runningSuggestionJobId: string | null = null;
	let followedRunId = $state<string | null>(null);
	let discardedAlbumId: string | null = null;
	let albumVisit = new AbortController();
	let swipeStart: { pointerId: number; x: number; y: number } | null = null;

	const activeCoverJob = $derived(
		$activeJobs.find((active) => active.albumId === currentAlbumId) ?? null
	);
	const coverSuggestions = $derived(
		coverSuggestionsState?.albumId === currentAlbumId ? coverSuggestionsState.data : null
	);
	const coverSuggestionsFailure = $derived(
		coverSuggestionsState?.albumId === currentAlbumId ? coverSuggestionsState.failure : null
	);
	const coverSuggestionsUnreachable = $derived(
		coverSuggestionsState?.albumId === currentAlbumId && coverSuggestionsState.unreachable
	);
	const coverSuggestionsLoading = $derived(
		coverSuggestionsState?.albumId === currentAlbumId && coverSuggestionsState.isLoading
	);
	const coverSuggestionsReloadsExhausted = $derived(
		coverSuggestionsUnreachable && !$offline && coverSuggestionsBackoffSpent
	);
	const coverSuggestionsBusy = $derived(coverSuggestionsBusyAlbumId === currentAlbumId);
	const latestCoverJob = $derived(coverSuggestions?.job ?? null);
	const isCoverSuggestionGenerating = $derived(
		Boolean(activeCoverJob) ||
			latestCoverJob?.status === 'queued' ||
			latestCoverJob?.status === 'running'
	);
	const dailySuggestionsSpent = $derived(
		coverSuggestions !== null && coverSuggestions.used_today >= coverSuggestions.daily_limit
	);
	const dailyLimitNote = $derived(
		dailySuggestionsSpent
			? ((coverSuggestionsState?.albumId === currentAlbumId
					? coverSuggestionsState.limitNote
					: null) ?? ALBUM_COVER_DAILY_LIMIT_REACHED)
			: null
	);
	const canSuggestCover = $derived(
		!isCoverSuggestionGenerating && !coverSuggestionsLoading && !dailyLimitNote
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
	const coverSuggestionsProgress = $derived(
		activeCoverJob?.job.progress ?? latestCoverJob?.progress ?? 0
	);
	const suggestionCount = $derived(coverSuggestions?.suggestions.length ?? 0);
	const hasSuggestions = $derived(suggestionCount > 0);
	const stageSlots = $derived<StageSlot[]>([
		...(coverSuggestions?.suggestions ?? []).map((suggestion): StageSlot => ({
			kind: 'suggestion',
			...suggestion
		})),
		...(isCoverSuggestionGenerating
			? [{ kind: 'making', progress: coverSuggestionsProgress } as const]
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

	const coverSuggestionsReloads = reloadWhileUnreachable(reloadCoverSuggestions);
	$effect(() => () => coverSuggestionsReloads.stop());

	// Opening the editor only reads what exists: a suggestion spends today's
	// quota, so only Suggest makes one, and a mistap closed at once costs
	// nothing (#1186). However the editor leaves an album -- ×, Back, Upload,
	// Use or another album -- it leaves nothing unused behind: a suggestion
	// still running is stopped and what × or Use did not already discard goes.
	$effect(() => {
		const albumId = currentAlbumId;
		coverSuggestionsState = {
			albumId,
			data: null,
			...COVER_SUGGESTIONS_SETTLED,
			isLoading: true
		};
		followedRunId = null;
		coverSuggestionsReloads.stop();
		const visit = new AbortController();
		albumVisit = visit;
		queueMicrotask(() => void loadCoverSuggestions(albumId));
		return () => {
			visit.abort();
			discardUnusedOnLeave(albumId);
		};
	});

	function reloadCoverSuggestions(): void {
		void loadCoverSuggestions(currentAlbumId);
	}

	function reloadCoverSuggestionsAfter(outcome: CoverSuggestionsOutcome): void {
		if (!outcome.unreachable) {
			coverSuggestionsReloads.stop();
			return;
		}
		coverSuggestionsBackoffSpent = coverSuggestionsReloads.afterNetworkFailure() === 'exhausted';
	}

	$effect(() => {
		if (activeCoverJob) {
			completedCoverJobId = activeCoverJob.job.id;
			return;
		}
		if (completedCoverJobId) {
			const albumId = currentAlbumId;
			completedCoverJobId = null;
			queueMicrotask(() => void loadCoverSuggestions(albumId));
		}
	});

	async function loadCoverSuggestions(albumId: string): Promise<void> {
		const request = ++suggestionsRequest;
		coverSuggestionsBackoffSpent = false;
		updateCoverSuggestionsState(albumId, (state) => ({ ...state, isLoading: true }));
		try {
			const response = await fetchAlbumCoverSuggestions(albumId);
			if (request !== suggestionsRequest || albumId !== currentAlbumId) return;
			coverSuggestionsState = {
				albumId,
				data: response,
				...COVER_SUGGESTIONS_SETTLED,
				isLoading: false
			};
			coverSuggestionsReloads.stop();
			const runningJob =
				response.job?.status === 'queued' || response.job?.status === 'running'
					? response.job
					: null;
			runningSuggestionJobId = runningJob?.id ?? null;
			if (runningJob) followRun(runningJob, albumId);
		} catch (error) {
			if (request !== suggestionsRequest || albumId !== currentAlbumId) return;
			const outcome = coverSuggestionsOutcomeOf(error);
			coverSuggestionsState = { albumId, data: null, ...outcome, isLoading: false };
			reloadCoverSuggestionsAfter(outcome);
		}
	}

	function updateCoverSuggestionsState(
		albumId: string,
		update: (state: CoverSuggestionsState) => CoverSuggestionsState
	): void {
		if (albumId !== currentAlbumId) return;
		const state =
			coverSuggestionsState?.albumId === albumId
				? coverSuggestionsState
				: { albumId, data: null, ...COVER_SUGGESTIONS_SETTLED, isLoading: false };
		coverSuggestionsState = update(state);
	}

	function retryCoverSuggestions(): void {
		const albumId = currentAlbumId;
		updateCoverSuggestionsState(albumId, (state) => ({ ...state, ...COVER_SUGGESTIONS_SETTLED }));
		void loadCoverSuggestions(albumId);
	}

	function coverSuggestionsOutcomeOf(error: unknown): CoverSuggestionsOutcome {
		if (error instanceof NetworkError) {
			return { ...COVER_SUGGESTIONS_SETTLED, unreachable: true };
		}
		return {
			...COVER_SUGGESTIONS_SETTLED,
			failure: describeFailure(error, ALBUM_COVER_SUGGESTION_FAILED_FALLBACK)
		};
	}

	async function suggestCover(): Promise<void> {
		if (!canSuggestCover) return;
		const albumId = currentAlbumId;
		const left = albumVisit.signal;
		chosenSlot = null;
		// A page-load GET can resolve after this deliberate POST. Its older
		// snapshot must not erase the just-created job and make progress vanish.
		suggestionsRequest += 1;
		coverSuggestionsReloads.stop();
		updateCoverSuggestionsState(albumId, (state) => ({
			...state,
			...COVER_SUGGESTIONS_SETTLED,
			isLoading: true
		}));
		try {
			const job = await createAlbumCoverSuggestions(albumId);
			if (left.aborted) {
				discardUnusedInBackground(albumId, job.id);
				return;
			}
			runningSuggestionJobId = job.id;
			followRun(job, albumId);
			void loadCoverSuggestions(albumId);
		} catch (error) {
			if (albumId !== currentAlbumId) return;
			if (isRefusal(error)) {
				await rereadAfterRefusal(albumId, error);
				return;
			}
			showSuggestFailure(albumId, error);
		}
	}

	function followRun(job: JobItem, albumId: string): void {
		followedRunId = job.id;
		trackJob(job, { albumId });
	}

	function showSuggestFailure(albumId: string, error: unknown): void {
		const outcome = coverSuggestionsOutcomeOf(error);
		updateCoverSuggestionsState(albumId, (state) => ({ ...state, ...outcome, isLoading: false }));
		reloadCoverSuggestionsAfter(outcome);
	}

	function isRefusal(error: unknown): error is ApiError {
		return (
			error instanceof ApiError &&
			(error.status === HTTP_CONFLICT || error.status === HTTP_TOO_MANY_REQUESTS)
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
		await loadCoverSuggestions(albumId);
		if (albumId !== currentAlbumId || coverSuggestions === null) return;
		if (refusal.status === HTTP_CONFLICT) {
			followedRunId = latestCoverJob?.id ?? null;
			return;
		}
		if (refusal.status === HTTP_TOO_MANY_REQUESTS && dailySuggestionsSpent) {
			const limitNote = describeFailure(refusal, ALBUM_COVER_DAILY_LIMIT_REACHED);
			updateCoverSuggestionsState(albumId, (state) => ({ ...state, limitNote }));
			return;
		}
		showSuggestFailure(albumId, refusal);
	}

	// A load still answering from before the stop would report the run as
	// running and track the job being cancelled again, so it is dropped.
	async function stopSuggestionRun(jobId: string): Promise<void> {
		suggestionsRequest += 1;
		runningSuggestionJobId = null;
		try {
			await cancelJob(jobId);
		} catch (error) {
			const alreadyEnded = error instanceof ApiError && error.status === HTTP_CONFLICT;
			if (!alreadyEnded) {
				runningSuggestionJobId = jobId;
				throw error;
			}
		}
		removeJob(jobId);
	}

	// The run stops before the discard, and a run that ended just before
	// its stop may already have landed its suggestion, so the discard
	// follows every stopped run.
	async function discardUnused(albumId: string, runToStop: string | null): Promise<void> {
		if (runToStop) await stopSuggestionRun(runToStop);
		await discardAlbumCoverSuggestions(albumId);
		discardedAlbumId = albumId;
	}

	function discardUnusedInBackground(albumId: string, runToStop: string | null): void {
		discardUnused(albumId, runToStop).catch((error: unknown) =>
			addToast(describeFailure(error, ALBUM_COVER_SUGGESTION_FAILED_FALLBACK), 'error')
		);
	}

	function discardUnusedOnLeave(albumId: string): void {
		const runToStop = runningSuggestionJobId;
		const unusedLeft =
			discardedAlbumId !== albumId &&
			coverSuggestionsState?.albumId === albumId &&
			(coverSuggestionsState.data?.suggestions.length ?? 0) > 0;
		if (runToStop || unusedLeft) discardUnusedInBackground(albumId, runToStop);
	}

	async function discardAndClose(): Promise<void> {
		const runToStop = runningSuggestionJobId;
		if (!hasSuggestions && !runToStop) {
			onclose();
			return;
		}
		const albumId = currentAlbumId;
		coverSuggestionsBusyAlbumId = albumId;
		try {
			await discardUnused(albumId, runToStop);
			onclose();
		} catch (error) {
			addToast(describeFailure(error, ALBUM_COVER_SUGGESTION_FAILED_FALLBACK), 'error');
		} finally {
			if (coverSuggestionsBusyAlbumId === albumId) coverSuggestionsBusyAlbumId = null;
		}
	}

	async function selectCoverSuggestion(suggestionId: string): Promise<void> {
		const albumId = currentAlbumId;
		coverSuggestionsBusyAlbumId = albumId;
		try {
			const updated = await holdOpenWhile(
				'cover-saving',
				selectAlbumCoverSuggestion(albumId, { suggestion_id: suggestionId })
			);
			try {
				await discardUnused(albumId, null);
			} catch (error) {
				addToast(describeFailure(error, ALBUM_COVER_SUGGESTION_FAILED_FALLBACK), 'error');
			}
			updateAlbumInList(albumId, () => updated);
			addToast('Cover saved', 'success');
		} catch (error) {
			addToast(describeFailure(error, ALBUM_COVER_SUGGESTION_FAILED_FALLBACK), 'error');
		} finally {
			if (coverSuggestionsBusyAlbumId === albumId) coverSuggestionsBusyAlbumId = null;
		}
	}

	function showSlot(index: number): void {
		if (index < 0 || index >= stageSlots.length) return;
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
				disabled={shownSlotIndex === 0}
				onclick={() => showSlot(shownSlotIndex - 1)}>‹</button
			>
		{:else}
			<span class="stage-nav-gap"></span>
		{/if}
		<div class="stage-art" class:stage-art-empty={!shownSlot && !album.cover}>
			{#if shownSlot?.kind === 'suggestion'}
				<img src={shownSlot.url} alt={albumCoverSuggestionAlt(album.title)} draggable="false" />
			{:else if shownSlot?.kind === 'making'}
				<div class="stage-making">
					<span>{ALBUM_COVER_SUGGESTING_LABEL}</span>
					<div
						class="stage-progress"
						role="progressbar"
						aria-label={ALBUM_COVER_SUGGESTING_LABEL}
						aria-valuemin={0}
						aria-valuemax={100}
						aria-valuenow={Math.round(shownSlot.progress * 100)}
					>
						<span style:width={`${Math.max(4, shownSlot.progress * 100)}%`}></span>
					</div>
				</div>
			{:else if album.cover}
				<img
					src={album.cover.detail}
					alt={`${ALBUM_COVER_ALT_TYPE} ${album.title}`}
					draggable="false"
				/>
			{:else}
				<button type="button" class="stage-empty" onclick={onupload}>{ALBUM_COVER_ADD_LABEL}</button
				>
			{/if}
		</div>
		{#if stageSlots.length > 1}
			<button
				type="button"
				class="stage-nav"
				aria-label={ALBUM_COVER_NEXT_SUGGESTION_LABEL}
				disabled={shownSlotIndex === stageSlots.length - 1}
				onclick={() => showSlot(shownSlotIndex + 1)}>›</button
			>
		{:else}
			<span class="stage-nav-gap"></span>
		{/if}
	</div>

	<p class="cover-count" aria-live="polite">
		{#if coverSuggestionsReloadsExhausted}
			<button class="cover-suggestions-retry" type="button" onclick={retryCoverSuggestions}
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
		<button type="button" class="cover-action" data-hitbox="frequent" onclick={onupload}
			>{ALBUM_COVER_EDITING_UPLOAD_LABEL}</button
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

	.stage-progress {
		height: 0.25rem;
		overflow: hidden;
		border-radius: 999px;
		background: var(--border);
	}

	.stage-progress span {
		display: block;
		height: 100%;
		border-radius: inherit;
		background: var(--accent);
		transition: width 180ms ease-out;
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
		height: auto;
		padding: 0.3rem 0.7rem;
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
		.stage-progress span {
			transition: none;
		}
	}
</style>
