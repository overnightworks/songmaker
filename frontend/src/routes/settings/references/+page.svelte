<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { ApiError, describeFailure } from '#lib/api/fetch.ts';
	import { listReferences, referenceAudioUrl, uploadReference } from '#lib/api/references.ts';
	import type { ReferenceRecordingResponse, ReferenceUsageResponse } from '#lib/api/types.ts';
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
	const UPLOAD_LABEL = 'Upload';
	const PROGRESS_SEPARATOR = ' · ';
	const UPLOAD_FAILED = "Couldn't upload this file";
	// The recipe's picker takes the same files.
	const UPLOAD_ACCEPT = '.mp3,.wav,.flac,.ogg';
	const METER_FROM_SHARE = 0.8;
	const STORAGE_CONFLICT_STATUS = 409;
	const BYTES_PER_MB = 1_000_000;

	let references = $state<ReferenceRecordingResponse[] | null>(null);
	let usage = $state<ReferenceUsageResponse | null>(null);
	const referenceReloads = reloadWhileUnreachable(() => void load());
	const loadFailure = referenceReloads.loadFailure;

	async function load() {
		try {
			const answer = await listReferences();
			references = answer.references;
			usage = answer.usage;
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

	const megabytes = (bytes: number) => Math.floor(bytes / BYTES_PER_MB);
	const filesFigure = (used: ReferenceUsageResponse) => `${used.files} of ${used.file_limit} files`;
	const sizeFigure = (used: ReferenceUsageResponse) =>
		`${megabytes(used.bytes)} of ${megabytes(used.byte_limit)} MB`;

	const storageShare = $derived(
		usage ? Math.max(usage.files / usage.file_limit, usage.bytes / usage.byte_limit) : 0
	);
	const meterShown = $derived(storageShare >= METER_FROM_SHARE);
	const fullFigure = $derived.by(() => {
		if (!usage) return null;
		if (usage.files >= usage.file_limit) return filesFigure(usage);
		if (usage.bytes >= usage.byte_limit) return sizeFigure(usage);
		return null;
	});

	let fileInput = $state<HTMLInputElement | null>(null);
	let uploading = $state<{ name: string; percent: number } | null>(null);
	let uploadFailure = $state<string | null>(null);
	const uploadReason = $derived(
		uploadFailure ??
			(fullFigure === null ? null : `Reference storage is full (${fullFigure}) — delete one first.`)
	);

	function failureWording(error: unknown): string {
		if (error instanceof ApiError && error.status === STORAGE_CONFLICT_STATUS && usage) {
			return `That file doesn't fit (${sizeFigure(usage)} used) — delete one first.`;
		}
		return describeFailure(error, UPLOAD_FAILED);
	}

	async function upload(file: File) {
		uploadFailure = null;
		uploading = { name: file.name, percent: 0 };
		try {
			await uploadReference(file, (fraction) => {
				uploading = { name: file.name, percent: Math.round(fraction * 100) };
			});
		} catch (error) {
			uploadFailure = failureWording(error);
			return;
		} finally {
			uploading = null;
		}
		await load();
	}

	function fileChosen(event: Event & { currentTarget: HTMLInputElement }) {
		const input = event.currentTarget;
		const file = input.files?.[0];
		input.value = '';
		if (file) void upload(file);
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
		if (referenceId === null) return;
		if (previewId === referenceId) previewId = null;
		if (referenceId !== activeId) return;
		activeId = null;
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

<div class="page">
	<header class="page-head">
		<h1>References</h1>
	</header>

	{#if usage}
		<div class="upload-area">
			<button
				type="button"
				class="upload-button"
				class:busy={uploading !== null}
				class:failed={uploading === null && uploadReason !== null}
				style:--progress={uploading ? `${uploading.percent}%` : undefined}
				disabled={uploading !== null}
				onclick={() => fileInput?.click()}
			>
				{#if uploading}
					<span class="upload-name">Uploading {uploading.name}</span><span class="upload-percent"
						>{PROGRESS_SEPARATOR}{uploading.percent}%</span
					>
				{:else}
					{#if uploadReason !== null}<Icon name="triangle-alert" size={16} />{/if}{UPLOAD_LABEL}
				{/if}
			</button>
			<input
				bind:this={fileInput}
				type="file"
				accept={UPLOAD_ACCEPT}
				hidden
				onchange={fileChosen}
			/>
			{#if uploading === null && uploadReason !== null}
				<p class="upload-reason" role="alert">{uploadReason}</p>
			{/if}
		</div>
	{/if}

	{#if usage && meterShown}
		<div class="quota">
			<div class="quota-figures">
				<span>{filesFigure(usage)}</span><span>{sizeFigure(usage)}</span>
			</div>
			<div class="quota-bar" aria-hidden="true">
				<i style:width={`${Math.min(storageShare, 1) * 100}%`}></i>
			</div>
		</div>
	{/if}

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
</div>

<style>
	.page {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		align-items: start;
		column-gap: 1rem;
	}

	.page > :global(*) {
		grid-column: 1 / -1;
	}

	.page > .page-head {
		grid-column: 1;
		grid-row: 1;
	}

	.page > .upload-area {
		grid-column: 2;
		grid-row: 1;
	}

	.page-head {
		margin-bottom: 1.5rem;
	}

	.upload-area {
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		gap: 6px;
		max-width: 22rem;
	}

	.upload-button {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 8px;
		min-width: 0;
		max-width: 100%;
		height: 36px;
		padding: 0 18px;
		border: 1px solid var(--accent);
		border-radius: var(--btn-radius-sm);
		background: var(--accent);
		color: var(--on-accent);
		font-family: var(--font-display);
		font-size: 0.95rem;
		letter-spacing: var(--btn-letter-spacing);
		text-transform: uppercase;
		white-space: nowrap;
	}

	.upload-button.busy {
		background:
			linear-gradient(
					90deg,
					var(--on-accent) 0 var(--progress),
					color-mix(in srgb, var(--on-accent) 30%, transparent) var(--progress) 100%
				)
				bottom / 100% 4px no-repeat,
			var(--accent);
		gap: 0;
		font-family: var(--font-body);
		font-size: 0.9rem;
		letter-spacing: 0;
		text-transform: none;
		cursor: progress;
	}

	.upload-button.failed {
		background: transparent;
		border-color: var(--score-bad);
		color: var(--score-bad);
	}

	.upload-name {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.upload-percent {
		flex: none;
	}

	.upload-reason {
		display: flex;
		gap: 6px;
		margin: 0;
		font-size: 0.84rem;
		line-height: 1.35;
		color: var(--score-bad);
	}

	.quota {
		display: flex;
		flex-direction: column;
		gap: 6px;
		margin-bottom: 12px;
		padding: 10px 12px;
		border: 1px solid color-mix(in srgb, var(--score-ok) 50%, transparent);
		border-radius: var(--card-radius);
		background: color-mix(in srgb, var(--score-ok) 15%, transparent);
		color: var(--score-ok);
	}

	.quota-figures {
		display: flex;
		justify-content: space-between;
		gap: 10px;
		font-size: 0.84rem;
		font-variant-numeric: tabular-nums;
	}

	.quota-bar {
		height: 4px;
		border-radius: 2px;
		background: color-mix(in srgb, var(--score-ok) 22%, transparent);
	}

	.quota-bar i {
		display: block;
		height: 100%;
		border-radius: 2px;
		background: var(--score-ok);
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
		.page > .page-head {
			grid-column: 1 / -1;
		}

		.page > .upload-area {
			grid-column: 1 / -1;
			grid-row: auto;
			order: 1;
			position: sticky;
			bottom: 0;
			z-index: 1;
			align-items: stretch;
			max-width: none;
			margin-top: 12px;
			padding: 8px 0;
			background: var(--bg);
			border-top: 1px solid var(--border);
		}

		.upload-button {
			width: 100%;
			height: 44px;
		}

		.reference-row {
			min-height: 64px;
		}

		.reference-play {
			width: 40px;
			height: 40px;
		}
	}
</style>
