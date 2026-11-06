<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { ApiError, describeFailure } from '#lib/api/fetch.ts';
	import {
		deleteReference,
		listReferences,
		referenceAudioUrl,
		uploadReference
	} from '#lib/api/references.ts';
	import type { ReferenceRecordingResponse, ReferenceUsageResponse } from '#lib/api/types.ts';
	import ConfirmDeleteDialog from '#lib/components/ConfirmDeleteDialog.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import ReferenceMenu from '#lib/components/ReferenceMenu.svelte';
	import ReferenceUses from '#lib/components/ReferenceUses.svelte';
	import {
		APP_NAME,
		REFERENCE_AUDIO_ACCEPT,
		TRANSPORT_PAUSE_LABEL,
		TRANSPORT_PLAY_LABEL
	} from '#lib/constants.ts';
	import { audioPlayer, transportOffersPause } from '#lib/services/audioPlayer.svelte.ts';
	import { reloadWhileUnreachable } from '#lib/stores/connectivity.ts';
	import { formatTime, localDayAndMonth } from '#lib/utils/format.ts';

	const LOAD_FAILED = 'Failed to load references';
	const LOADING = 'Loading references…';
	const RETRY_LABEL = 'Try again';
	const SKELETON_ROWS = 3;
	const NO_LENGTH = '—';
	const PLAY_FAULT = "Can't play this recording";
	const IN_USE_FAULT = 'In use — not deleted.';
	const DELETE_FAILED = "Couldn't delete this recording";
	const DELETE_TITLE = 'Delete reference?';
	const DELETE_CONSEQUENCE = 'its audio file';
	const UPLOAD_LABEL = 'Upload';
	const PROGRESS_SEPARATOR = ' · ';
	const UPLOAD_FAILED = "Couldn't upload this file";
	const METER_FROM_SHARE = 0.8;
	const CONFLICT_STATUS = 409;
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

	function fullFigure(used: ReferenceUsageResponse): string | null {
		if (used.files >= used.file_limit) return filesFigure(used);
		if (used.bytes >= used.byte_limit) return sizeFigure(used);
		return null;
	}

	// A refusal holds no words: they come from the usage current when read.
	type UploadFailure = { kind: 'refused' } | { kind: 'failed'; words: string };

	let fileInput = $state<HTMLInputElement | null>(null);
	let uploading = $state<{ name: string; percent: number } | null>(null);
	let uploadFailure = $state<UploadFailure | null>(null);

	function uploadReason(used: ReferenceUsageResponse): string | null {
		if (uploadFailure?.kind === 'failed') return uploadFailure.words;
		const full = fullFigure(used);
		if (full !== null) return `Reference storage is full (${full}) — delete one first.`;
		return uploadFailure === null
			? null
			: `That file doesn't fit (${sizeFigure(used)} used) — delete one first.`;
	}

	async function failureOf(error: unknown): Promise<UploadFailure> {
		if (error instanceof ApiError && error.status === CONFLICT_STATUS) {
			await load();
			return { kind: 'refused' };
		}
		return { kind: 'failed', words: describeFailure(error, UPLOAD_FAILED) };
	}

	async function upload(file: File) {
		uploadFailure = null;
		uploading = { name: file.name, percent: 0 };
		try {
			await uploadReference(file, (fraction) => {
				uploading = { name: file.name, percent: Math.round(fraction * 100) };
			});
		} catch (error) {
			uploadFailure = await failureOf(error);
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
	let rowFault = $state<{ id: string; words: string } | null>(null);
	let pendingDelete = $state<ReferenceRecordingResponse | null>(null);
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
		rowFault = { id: referenceId, words: PLAY_FAULT };
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
		rowFault = null;
		activeId = referenceId;
		element.play().catch(() => fail(referenceId));
	}

	let openUsesId = $state<string | null>(null);

	function usedLabel(reference: ReferenceRecordingResponse): string {
		const counts = [
			[reference.used_by_takes, 'take'],
			[reference.used_by_versions, 'version']
		] as const;
		const kinds = counts
			.filter(([count]) => count > 0)
			.map(([count, noun]) => `${count} ${noun}${count === 1 ? '' : 's'}`);
		return `Used in ${kinds.join(', ')}`;
	}

	async function confirmDelete(reference: ReferenceRecordingResponse) {
		pendingDelete = null;
		rowFault = null;
		try {
			await deleteReference(reference.id);
		} catch (error) {
			if (error instanceof ApiError && error.status === CONFLICT_STATUS) {
				await load();
				rowFault = { id: reference.id, words: IN_USE_FAULT };
			} else {
				rowFault = { id: reference.id, words: describeFailure(error, DELETE_FAILED) };
			}
			return;
		}
		if (previewId === reference.id) release();
		references = references?.filter((candidate) => candidate.id !== reference.id) ?? null;
		await load();
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
		{@const reason = uploadReason(usage)}
		<div class="upload-area">
			<button
				type="button"
				class="upload-button"
				class:busy={uploading !== null}
				class:failed={uploading === null && reason !== null}
				style:--progress={uploading ? `${uploading.percent}%` : undefined}
				disabled={uploading !== null}
				onclick={() => fileInput?.click()}
			>
				{#if uploading}
					<span class="upload-name">Uploading {uploading.name}</span><span class="upload-percent"
						>{PROGRESS_SEPARATOR}{uploading.percent}%</span
					>
				{:else}
					<Icon name={reason !== null ? 'triangle-alert' : 'arrow-up'} size={16} />{UPLOAD_LABEL}
				{/if}
			</button>
			<input
				bind:this={fileInput}
				type="file"
				accept={REFERENCE_AUDIO_ACCEPT}
				hidden
				onchange={fileChosen}
			/>
			{#if uploading === null && reason !== null}
				<p class="upload-reason" role="alert">{reason}</p>
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
	{/if}

	{#if references === null}
		{#if !$loadFailure}
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
		{#if !$loadFailure}
			<div class="empty">
				<Icon name="audio-lines" size={40} />
				<p>No references yet — upload a recording to guide a song's sound.</p>
			</div>
		{/if}
	{:else}
		{@const now = new Date()}
		<ul class="reference-list">
			{#each references as reference (reference.id)}
				{@const playing = activeId === reference.id}
				<!-- Keyboard users reach the row through its button, so the row takes no focus. -->
				<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
				<li
					class="reference-row"
					class:playing
					onclick={(event) => {
						if ((event.target as Element).closest('.reference-uses')) return;
						toggle(reference.id);
					}}
				>
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
						<span class="reference-meta"
							>{metaLabel(reference, now)}{#if reference.in_use}{PROGRESS_SEPARATOR}<button
									type="button"
									class="reference-used"
									aria-expanded={openUsesId === reference.id}
									aria-controls={openUsesId === reference.id ? `uses-${reference.id}` : undefined}
									onclick={(event) => {
										event.stopPropagation();
										openUsesId = openUsesId === reference.id ? null : reference.id;
									}}>{usedLabel(reference)}</button
								>
							{/if}</span
						>
						{#if rowFault?.id === reference.id}
							<span class="reference-meta reference-fault" role="alert">{rowFault.words}</span>
						{/if}
					</span>
					<!-- The menu's clicks are the menu's own, never the row's preview toggle. -->
					<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
					<span class="reference-menu" onclick={(event) => event.stopPropagation()}>
						<ReferenceMenu
							filename={reference.filename}
							inUse={reference.in_use}
							usesCount={reference.used_by_takes + reference.used_by_versions}
							onshowuses={() => (openUsesId = reference.id)}
							ondelete={() => (pendingDelete = reference)}
						/>
					</span>
					{#if openUsesId === reference.id}
						<div class="reference-uses">
							<ReferenceUses id={`uses-${reference.id}`} referenceId={reference.id} />
						</div>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}
</div>

{#if pendingDelete}
	{@const doomed = pendingDelete}
	<ConfirmDeleteDialog
		title={DELETE_TITLE}
		items={[`${doomed.filename} — ${DELETE_CONSEQUENCE}`]}
		onconfirm={() => void confirmDelete(doomed)}
		oncancel={() => (pendingDelete = null)}
	/>
{/if}

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
		font-size: 15px;
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
		font-size: 15px;
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
		font-size: 13px;
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
		background: var(--score-ok-bg);
	}

	.quota-figures {
		color: color-mix(in srgb, var(--score-ok) 80%, var(--text));
		display: flex;
		justify-content: space-between;
		gap: 10px;
		font-size: 13px;
		font-variant-numeric: tabular-nums;
	}

	.quota-bar {
		height: 4px;
		border-radius: var(--btn-radius-sm);
		background: color-mix(in srgb, var(--score-ok) 22%, transparent);
	}

	.quota-bar i {
		display: block;
		height: 100%;
		border-radius: var(--btn-radius-sm);
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
		font-size: 22px;
	}

	.load-error {
		display: flex;
		flex-direction: column;
		gap: 9px;
		margin-bottom: 12px;
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
		border-radius: var(--btn-radius-sm);
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
		font-size: 15px;
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
		flex-wrap: wrap;
		align-items: center;
		gap: 12px;
		min-width: 0;
		min-height: 56px;
		padding: 6px 14px;
		cursor: pointer;
	}

	.reference-uses {
		flex: 1 0 100%;
		margin: 0 -14px -6px;
		cursor: default;
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

	.reference-menu {
		display: flex;
		flex: none;
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
		font-size: 12px;
		color: var(--text-muted);
		font-variant-numeric: tabular-nums;
	}

	.reference-used {
		position: relative;
		padding: 0;
		background: none;
		border: none;
		font: inherit;
		color: var(--accent);
		text-decoration: underline;
		text-underline-offset: 2px;
		cursor: pointer;
	}

	/* The text stays 12px in the meta line; the pointer target grows around it. */
	.reference-used::after {
		content: '';
		position: absolute;
		inset: calc((100% - var(--hitbox-frequent)) / 2) 0;
	}

	.reference-fault {
		color: var(--score-bad);
	}

	@media (max-width: 640px) {
		.page {
			display: flex;
			flex-direction: column;
			align-items: stretch;
			min-height: 100%;
		}

		.page > .upload-area {
			order: 1;
			position: sticky;
			bottom: calc(-1 * var(--settings-content-padding));
			z-index: 1;
			align-items: stretch;
			max-width: none;
			margin: auto calc(-1 * var(--settings-content-padding))
				calc(-1 * var(--settings-content-padding));
			padding: 8px 12px;
			background: var(--header-bg);
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
