<script lang="ts">
	import { describeFailure, NetworkError } from '$lib/api/fetch';
	import {
		createAlbumCoverSuggestions,
		discardAlbumCoverSuggestions,
		fetchAlbumCoverSuggestions,
		selectAlbumCoverSuggestion
	} from '$lib/api/albums';
	import type { AlbumItem, CoverSuggestionsResponse } from '$lib/api/types';
	import {
		albumCoverSuggestionAlt,
		ALBUM_COVER_SUGGESTIONS_DETAIL,
		ALBUM_COVER_SUGGESTIONS_DISCARD_LABEL,
		ALBUM_COVER_SUGGESTIONS_FAILED_FALLBACK,
		ALBUM_COVER_SUGGESTIONS_FAILED_TITLE,
		ALBUM_COVER_SUGGESTIONS_LOADING,
		ALBUM_COVER_SUGGESTIONS_PROGRESS_TEMPLATE,
		ALBUM_COVER_SUGGESTIONS_RETRY_LABEL,
		ALBUM_COVER_SUGGESTIONS_TITLE,
		ALBUM_COVER_SUGGESTING_LABEL,
		ALBUM_COVER_SUGGESTION_USE_LABEL,
		ALBUM_COVER_SUGGEST_LABEL
	} from '$lib/constants';
	import { updateAlbumInList } from '$lib/stores/libraryData';
	import { addToast } from '$lib/stores/toast';
	import { activeJobs, trackJob } from '$lib/stores/jobs';
	import { offline, reloadWhileUnreachable } from '$lib/stores/connectivity';

	interface Props {
		album: AlbumItem;
	}

	interface CoverSuggestionsState {
		albumId: string;
		data: CoverSuggestionsResponse | null;
		failure: string | null;
		unreachable: boolean;
		isLoading: boolean;
	}

	type CoverSuggestionsOutcome = Pick<CoverSuggestionsState, 'failure' | 'unreachable'>;

	const COVER_SUGGESTIONS_SETTLED: CoverSuggestionsOutcome = { failure: null, unreachable: false };

	let { album }: Props = $props();

	// A fresh album object with the same id (after a rename or a saved cover)
	// must not restart the suggestions; only a different album does.
	const currentAlbumId = $derived(album.id);

	let coverSuggestionsState = $state<CoverSuggestionsState | null>(null);
	let coverSuggestionsBusyAlbumId = $state<string | null>(null);
	let suggestionsRequest = 0;
	let coverSuggestionsBackoffSpent = $state(false);
	let completedCoverJobId: string | null = null;

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
	const coverSuggestionFailure = $derived(
		coverSuggestionsFailure ??
			(latestCoverJob?.status === 'failed'
				? (latestCoverJob.error ?? ALBUM_COVER_SUGGESTIONS_FAILED_FALLBACK)
				: null)
	);
	const coverSuggestionsProgress = $derived(
		activeCoverJob?.job.progress ?? latestCoverJob?.progress ?? 0
	);
	const hasSuggestions = $derived((coverSuggestions?.suggestions.length ?? 0) > 0);
	// A card that cannot reach the server is absent rather than an error of its
	// own: the one offline strip already says it, and it reloads once online.
	// Without the strip it reloads on a bounded backoff, then offers Try again.
	const showCoverSuggestionsPanel = $derived(
		coverSuggestionsReloadsExhausted ||
			(!coverSuggestionsUnreachable &&
				Boolean(
					coverSuggestionsLoading ||
					isCoverSuggestionGenerating ||
					hasSuggestions ||
					coverSuggestionFailure ||
					!album.cover
				))
	);
	const coverSuggestionsProgressMessage = $derived(
		coverSuggestions
			? formatCoverSuggestionProgress(coverSuggestions.used_today, coverSuggestions.daily_limit)
			: null
	);

	const coverSuggestionsReloads = reloadWhileUnreachable(reloadCoverSuggestions);
	$effect(() => () => coverSuggestionsReloads.stop());

	$effect(() => {
		const albumId = currentAlbumId;
		coverSuggestionsState = {
			albumId,
			data: null,
			...COVER_SUGGESTIONS_SETTLED,
			isLoading: true
		};
		coverSuggestionsReloads.stop();
		queueMicrotask(() => void loadCoverSuggestions(albumId));
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
			if (response.job?.status === 'queued' || response.job?.status === 'running') {
				trackJob(response.job, { albumId });
			}
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
		if (error instanceof NetworkError) return { failure: null, unreachable: true };
		return {
			failure: describeFailure(error, ALBUM_COVER_SUGGESTIONS_FAILED_FALLBACK),
			unreachable: false
		};
	}

	function formatCoverSuggestionProgress(used: number, limit: number): string {
		return ALBUM_COVER_SUGGESTIONS_PROGRESS_TEMPLATE.replace('{used}', String(used)).replace(
			'{limit}',
			String(limit)
		);
	}

	export async function suggestCover(): Promise<void> {
		if (isCoverSuggestionGenerating || coverSuggestionsLoading) return;
		const albumId = currentAlbumId;
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
			if (hasSuggestions) {
				await discardAlbumCoverSuggestions(albumId);
				updateCoverSuggestionsState(albumId, (state) => ({ ...state, data: null }));
			}
			const job = await createAlbumCoverSuggestions(albumId);
			if (albumId !== currentAlbumId) return;
			trackJob(job, { albumId });
			void loadCoverSuggestions(albumId);
		} catch (error) {
			if (albumId !== currentAlbumId) return;
			const outcome = coverSuggestionsOutcomeOf(error);
			updateCoverSuggestionsState(albumId, (state) => ({ ...state, ...outcome, isLoading: false }));
			reloadCoverSuggestionsAfter(outcome);
		}
	}

	async function discardCoverSuggestions(): Promise<void> {
		const albumId = currentAlbumId;
		coverSuggestionsBusyAlbumId = albumId;
		try {
			await discardAlbumCoverSuggestions(albumId);
			updateCoverSuggestionsState(albumId, (state) => ({
				...state,
				data: null,
				...COVER_SUGGESTIONS_SETTLED
			}));
		} catch (error) {
			addToast(describeFailure(error, ALBUM_COVER_SUGGESTIONS_FAILED_FALLBACK), 'error');
		} finally {
			if (coverSuggestionsBusyAlbumId === albumId) coverSuggestionsBusyAlbumId = null;
		}
	}

	async function selectCoverSuggestion(suggestionId: string): Promise<void> {
		const albumId = currentAlbumId;
		coverSuggestionsBusyAlbumId = albumId;
		try {
			const updated = await selectAlbumCoverSuggestion(albumId, {
				suggestion_id: suggestionId
			});
			try {
				await discardAlbumCoverSuggestions(albumId);
			} catch (error) {
				addToast(describeFailure(error, ALBUM_COVER_SUGGESTIONS_FAILED_FALLBACK), 'error');
			}
			updateAlbumInList(albumId, () => updated);
			updateCoverSuggestionsState(albumId, (state) => ({
				...state,
				data: null,
				...COVER_SUGGESTIONS_SETTLED
			}));
			addToast('Cover saved', 'success');
		} catch (error) {
			addToast(describeFailure(error, ALBUM_COVER_SUGGESTIONS_FAILED_FALLBACK), 'error');
		} finally {
			if (coverSuggestionsBusyAlbumId === albumId) coverSuggestionsBusyAlbumId = null;
		}
	}
</script>

{#if showCoverSuggestionsPanel}
	<section class="cover-suggestions" aria-live="polite">
		{#if coverSuggestionsReloadsExhausted}
			<button class="cover-suggestions-retry" type="button" onclick={retryCoverSuggestions}
				>{ALBUM_COVER_SUGGESTIONS_RETRY_LABEL}</button
			>
		{:else if coverSuggestionsLoading && !isCoverSuggestionGenerating}
			<p class="cover-suggestions-loading" role="status">{ALBUM_COVER_SUGGESTIONS_LOADING}</p>
		{:else if isCoverSuggestionGenerating}
			<h3>{ALBUM_COVER_SUGGESTING_LABEL}</h3>
			{#if coverSuggestionsProgressMessage}
				<p>{coverSuggestionsProgressMessage}</p>
			{/if}
			<div class="suggestion-placeholders" aria-label={ALBUM_COVER_SUGGESTING_LABEL}>
				<span class="suggestion-placeholder"></span>
			</div>
			<div
				class="suggestion-progress"
				aria-label={`${Math.round(coverSuggestionsProgress * 100)}%`}
			>
				<span style:width={`${Math.max(4, coverSuggestionsProgress * 100)}%`}></span>
			</div>
		{:else if coverSuggestionFailure}
			<div class="cover-suggestion-failure" role="alert">
				<strong>{ALBUM_COVER_SUGGESTIONS_FAILED_TITLE}</strong>
				<p>{coverSuggestionFailure}</p>
				<button type="button" onclick={suggestCover}>{ALBUM_COVER_SUGGESTIONS_RETRY_LABEL}</button>
			</div>
		{:else if hasSuggestions}
			<h3>{ALBUM_COVER_SUGGESTIONS_TITLE}</h3>
			<p>{ALBUM_COVER_SUGGESTIONS_DETAIL}</p>
			<div class="suggestion-grid">
				{#each coverSuggestions?.suggestions ?? [] as suggestion (suggestion.id)}
					<article class="cover-suggestion">
						<img src={suggestion.url} alt={albumCoverSuggestionAlt(album.title)} />
						<button
							type="button"
							disabled={coverSuggestionsBusy}
							onclick={() => selectCoverSuggestion(suggestion.id)}
						>
							{ALBUM_COVER_SUGGESTION_USE_LABEL}
						</button>
					</article>
				{/each}
			</div>
			<button
				class="suggestion-discard"
				type="button"
				disabled={coverSuggestionsBusy}
				onclick={discardCoverSuggestions}>{ALBUM_COVER_SUGGESTIONS_DISCARD_LABEL}</button
			>
		{:else if !album.cover}
			<button class="suggest-cover" type="button" onclick={suggestCover}
				>{ALBUM_COVER_SUGGEST_LABEL}</button
			>
		{/if}
	</section>
{/if}

<style>
	.cover-suggestions {
		display: flex;
		flex-direction: column;
		gap: 0.65rem;
		margin: 0 1.5rem;
		padding: 1rem;
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		background: var(--surface);
	}

	.cover-suggestions h3,
	.cover-suggestions p {
		margin: 0;
	}

	.cover-suggestions h3 {
		font-family: var(--font-display);
		font-size: 1rem;
		letter-spacing: 0.04em;
		text-transform: uppercase;
	}

	.cover-suggestions p {
		color: var(--text-subtle);
		font-size: 0.83rem;
	}

	.cover-suggestions-loading {
		font-style: italic;
	}

	.suggest-cover,
	.cover-suggestion button,
	.suggestion-discard,
	.cover-suggestion-failure button {
		align-self: flex-start;
		padding: 0.45rem 0.8rem;
		border: 1px solid var(--accent);
		border-radius: var(--btn-radius-sm);
		background: var(--accent);
		color: #fff;
		font-family: var(--font-display);
		font-size: 0.78rem;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		cursor: pointer;
	}

	.cover-suggestions-retry {
		align-self: flex-start;
		padding: 0.45rem 0.8rem;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		background: transparent;
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: 0.78rem;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		cursor: pointer;
	}

	.suggestion-grid,
	.suggestion-placeholders {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 0.75rem;
	}

	.cover-suggestion {
		display: flex;
		flex-direction: column;
		gap: 0.45rem;
		min-width: 0;
		padding: 0.45rem;
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		background: var(--surface-hover);
	}

	.cover-suggestion img,
	.suggestion-placeholder {
		display: block;
		width: 100%;
		aspect-ratio: 1;
		border-radius: calc(var(--card-radius) / 2);
		object-fit: cover;
	}

	.suggestion-placeholder {
		background: linear-gradient(
			110deg,
			var(--surface-hover) 20%,
			var(--border) 45%,
			var(--surface-hover) 70%
		);
		background-size: 220% 100%;
		animation: cover-suggestion-loading 1.2s linear infinite;
	}

	.suggestion-progress {
		height: 0.25rem;
		overflow: hidden;
		border-radius: 999px;
		background: var(--border);
	}

	.suggestion-progress span {
		display: block;
		height: 100%;
		border-radius: inherit;
		background: var(--accent);
		transition: width 180ms ease-out;
	}

	.suggestion-discard {
		border-color: var(--border);
		background: transparent;
		color: var(--text-muted);
	}

	.cover-suggestion-failure {
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
		padding: 0.85rem;
		border: 1px solid var(--danger);
		border-left-width: 4px;
		border-radius: var(--card-radius);
		background: color-mix(in srgb, var(--danger) 12%, var(--surface));
	}

	.cover-suggestion-failure strong {
		color: var(--text);
	}

	@keyframes cover-suggestion-loading {
		to {
			background-position: -220% 0;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.suggestion-placeholder {
			animation: none;
		}

		.suggestion-progress span {
			transition: none;
		}
	}

	@media (max-width: 768px) {
		.cover-suggestions {
			margin: 0 0.8rem;
		}

		.suggestion-grid,
		.suggestion-placeholders {
			grid-template-columns: 1fr;
		}

		.cover-suggestion {
			display: grid;
			grid-template-columns: 4.4rem minmax(0, 1fr);
			align-items: center;
		}

		.cover-suggestion img {
			width: 4.4rem;
		}
	}
</style>
