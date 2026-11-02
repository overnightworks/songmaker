<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { listReferences, referenceAudioUrl } from '#lib/api/references.ts';
	import type { ReferenceRecordingResponse } from '#lib/api/types.ts';
	import Icon from '#lib/components/Icon.svelte';
	import { APP_NAME, TRANSPORT_PAUSE_LABEL, TRANSPORT_PLAY_LABEL } from '#lib/constants.ts';
	import { audioPlayer, transportOffersPause } from '#lib/services/audioPlayer.svelte.ts';
	import { reloadWhileUnreachable } from '#lib/stores/connectivity.ts';
	import { formatTime, localDayAndMonth } from '#lib/utils/format.ts';

	const LOAD_FAILED = 'Failed to load references';
	const LOADING = 'Loading references…';
	const RETRY_LABEL = 'Try again';
	const SKELETON_ROWS = 3;
	const NO_LENGTH = '—';
	const PLAY_FAULT = "Can't play this recording";

	let references = $state<ReferenceRecordingResponse[] | null>(null);
	const referenceReloads = reloadWhileUnreachable(() => void load());
	const loadFailure = referenceReloads.loadFailure;

	async function load() {
		try {
			references = await listReferences();
			referenceReloads.stop();
		} catch (e) {
			referenceReloads.nameLoadFailure(e, LOAD_FAILED);
		}
	}

	function lengthLabel(durationSec: number | null): string {
		return durationSec === null ? NO_LENGTH : formatTime(durationSec);
	}

	function metaLabel(reference: ReferenceRecordingResponse, now: Date): string {
		const uploaded = localDayAndMonth(new Date(reference.created_at), now);
		return `${lengthLabel(reference.duration_sec)} · ${uploaded}`;
	}

	let activeId = $state<string | null>(null);
	let faultId = $state<string | null>(null);
	let preview: HTMLAudioElement | null = null;
	let previewId: string | null = null;

	function previewElement(): HTMLAudioElement {
		if (preview) return preview;
		preview = new Audio();
		preview.addEventListener('ended', () => (activeId = null));
		preview.addEventListener('error', () => fail(previewId));
		return preview;
	}

	function fail(referenceId: string | null) {
		if (referenceId === null || referenceId !== activeId) return;
		activeId = null;
		previewId = null;
		faultId = referenceId;
	}

	function stop() {
		preview?.pause();
		activeId = null;
	}

	// Pausing keeps the download open; a source of its own is dropped on leaving.
	function release() {
		stop();
		if (!preview) return;
		preview.removeAttribute('src');
		preview.load();
		previewId = null;
	}

	function toggle(referenceId: string) {
		if (activeId === referenceId) return stop();
		if (transportOffersPause(audioPlayer.transport)) audioPlayer.pause();
		const element = previewElement();
		if (previewId !== referenceId) {
			element.src = referenceAudioUrl(referenceId);
			previewId = referenceId;
		}
		faultId = null;
		activeId = referenceId;
		element.play().catch(() => fail(referenceId));
	}

	// The global player starting ends a preview; the reverse is `toggle`.
	$effect(() => {
		if (transportOffersPause(audioPlayer.transport)) stop();
	});

	function retry() {
		referenceReloads.stop();
		void load();
	}

	onMount(() => void load());
	onDestroy(() => {
		referenceReloads.dispose();
		release();
	});
</script>

<svelte:head>
	<title>References — {APP_NAME}</title>
</svelte:head>

<header class="page-head">
	<h1>References</h1>
</header>

{#if references === null}
	{#if $loadFailure}
		<div class="load-error" role="alert">
			<span class="load-error-title">
				<Icon name="triangle-alert" size={16} />{LOAD_FAILED}
			</span>
			<div class="load-error-foot">
				<button
					type="button"
					class="retry-btn"
					data-hitbox="frequent"
					data-hitbox-face
					onclick={retry}
					aria-label={RETRY_LABEL}
					title={RETRY_LABEL}
				>
					<Icon name="refresh-cw" size={16} />
				</button>
			</div>
		</div>
	{:else}
		<div class="skeleton" role="status">
			{#each { length: SKELETON_ROWS } as _, index (index)}
				<div class="skeleton-row">
					<span class="skeleton-bar skeleton-name"></span>
					<span class="skeleton-bar skeleton-meta"></span>
				</div>
			{/each}
			<p class="skeleton-caption">{LOADING}</p>
		</div>
	{/if}
{:else if references.length === 0}
	<div class="empty">
		<Icon name="audio-lines" size={40} />
		<p>No references yet — upload a recording to guide a song's sound.</p>
	</div>
{:else}
	{@const now = new Date()}
	<ul class="reference-list">
		{#each references as reference (reference.id)}
			{@const playing = activeId === reference.id}
			<!-- Keyboard users reach the row through its button, so the row takes no focus. -->
			<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
			<li class="reference-row" class:playing onclick={() => toggle(reference.id)}>
				<button
					type="button"
					class="reference-play"
					aria-label={`${playing ? TRANSPORT_PAUSE_LABEL : TRANSPORT_PLAY_LABEL} ${reference.filename}`}
					onclick={(event) => {
						event.stopPropagation();
						toggle(reference.id);
					}}
				>
					<Icon name={playing ? 'pause' : 'play'} size={16} />
				</button>
				<span class="reference-text">
					<span class="reference-name" title={reference.filename}>{reference.filename}</span>
					<span class="reference-meta">{metaLabel(reference, now)}</span>
					{#if faultId === reference.id}
						<span class="reference-meta reference-fault" role="alert">{PLAY_FAULT}</span>
					{/if}
				</span>
			</li>
		{/each}
	</ul>
{/if}

<style>
	.page-head {
		margin-bottom: 1.5rem;
	}

	h1 {
		margin: 0;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.1em;
		background: linear-gradient(90deg, var(--primary), var(--accent));
		-webkit-background-clip: text;
		-webkit-text-fill-color: transparent;
		background-clip: text;
		font-size: 1.5rem;
	}

	.load-error {
		display: flex;
		flex-direction: column;
		gap: 9px;
		padding: 12px;
		background: var(--surface);
		border: 1px solid var(--score-bad);
		border-radius: var(--card-radius);
	}

	.load-error-title {
		display: flex;
		align-items: center;
		gap: 6px;
		font-size: 15px;
		color: var(--score-bad);
	}

	.load-error-foot {
		display: flex;
		justify-content: flex-end;
		color: var(--score-bad);
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
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		background: var(--surface);
	}

	.skeleton-row {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	.skeleton-bar {
		height: 12px;
		border-radius: 4px;
		background: linear-gradient(
			110deg,
			var(--surface-hover) 20%,
			var(--border) 45%,
			var(--surface-hover) 70%
		);
		background-size: 220% 100%;
		animation: references-skeleton-shimmer 1.2s linear infinite;
	}

	.skeleton-name {
		width: 60%;
	}

	.skeleton-meta {
		width: 25%;
	}

	.skeleton-caption {
		margin: 0.4rem 0 0;
		text-align: center;
		font-size: var(--label-font-size);
		font-style: italic;
		color: var(--text-subtle);
	}

	@keyframes references-skeleton-shimmer {
		to {
			background-position: -220% 0;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.skeleton-bar {
			animation: none;
		}
	}

	.empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 10px;
		padding: 24px;
		text-align: center;
		color: var(--text-muted);
	}

	.empty :global(svg) {
		color: var(--text-subtle);
	}

	.empty p {
		margin: 0;
		max-width: 28ch;
		font-size: 0.95rem;
	}

	.reference-list {
		list-style: none;
		margin: 0;
		padding: 0;
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		background: var(--surface);
		overflow: hidden;
	}

	.reference-row {
		display: flex;
		align-items: center;
		gap: 12px;
		min-width: 0;
		min-height: 56px;
		padding: 6px 14px;
		cursor: pointer;
	}

	.reference-row.playing {
		background: color-mix(in srgb, var(--accent) 10%, var(--surface));
	}

	.reference-play {
		display: flex;
		align-items: center;
		justify-content: center;
		flex: none;
		width: 32px;
		height: 32px;
		padding: 0;
		background: none;
		border: 1px solid var(--border);
		border-radius: 50%;
		color: var(--text);
		cursor: pointer;
	}

	.reference-row.playing .reference-play {
		border-color: var(--accent);
		color: var(--accent);
	}

	.reference-text {
		display: flex;
		flex-direction: column;
		gap: 2px;
		flex: 1;
		min-width: 0;
	}

	.reference-row + .reference-row {
		border-top: 1px solid var(--border);
	}

	.reference-name {
		font-size: 15px;
		color: var(--text);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.reference-meta {
		font-size: 12.5px;
		color: var(--text-muted);
		font-variant-numeric: tabular-nums;
	}

	.reference-fault {
		color: var(--score-bad);
	}

	@media (max-width: 640px) {
		.reference-row {
			min-height: 64px;
		}

		.reference-play {
			width: 40px;
			height: 40px;
		}
	}
</style>
