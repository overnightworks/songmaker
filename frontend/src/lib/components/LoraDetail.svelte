<script lang="ts">
	import type {
		JobItem,
		OwnPlayableTakeResponse,
		UserLoraItem,
		UserLoraSampleItem
	} from '#lib/api/types.ts';
	import { addLoraSample, patchLoraSample, deleteLoraSample } from '#lib/api/client.ts';
	import { describeFailure } from '#lib/api/fetch.ts';
	import { cancelJob, fetchJob } from '#lib/api/jobs.ts';
	import { addLoraSampleFromGeneration, listOwnPlayableTakes } from '#lib/api/loras.ts';
	import { activeJobs, isActiveJobStatus, removeJob, trackJob } from '#lib/stores/jobs.ts';
	import { refreshLora, trainLora, isLoraActive } from '#lib/stores/loras.ts';
	import { addToast } from '#lib/stores/toast.ts';
	import { Marked } from 'overnightworks-design';
	import {
		LORA_AUDIO_EXTENSIONS,
		LORA_MAX_SAMPLES,
		LORA_MIN_SAMPLES_FOR_TRAINING
	} from '#lib/constants/lora.ts';
	import { formatDecimal, formatList, formatRemainingTime } from '#lib/utils/format.ts';
	import { pageParts, pageText } from '#lib/utils/page-words.ts';

	const ACTIVE_STATUS_KEYS = {
		queued: { banner: 'voiceDetail.lockedQueued', button: 'voiceDetail.trainButtonQueued' },
		preprocessing: {
			banner: 'voiceDetail.lockedPreprocessing',
			button: 'voiceDetail.trainButtonPreprocessing'
		},
		training: { banner: 'voiceDetail.lockedTraining', button: 'voiceDetail.trainButtonTraining' },
		exporting: {
			banner: 'voiceDetail.lockedExporting',
			button: 'voiceDetail.trainButtonExporting'
		}
	} as const;

	interface Props {
		lora: UserLoraItem;
	}

	let { lora }: Props = $props();

	let uploading = $state(false);
	let training = $state(false);
	let newCaption = $state('');
	let newLyrics = $state('');
	let newFile = $state<File | null>(null);
	let dragOver = $state(false);
	let fileInputEl = $state<HTMLInputElement | null>(null);
	let showOwnTakes = $state(false);
	let ownTakes = $state<OwnPlayableTakeResponse[]>([]);
	let ownTakesLoading = $state(false);
	let addingGenerationId = $state<string | null>(null);
	let sampleError = $state<string | null>(null);
	let cancellingTraining = $state(false);
	let cancelledTrainingJob = $state<JobItem | null>(null);
	let fetchedTrainingJobId = $state<string | null>(null);
	let trainingError = $state<string | null>(null);

	const samples = $derived([...lora.samples].sort((a, b) => a.position - b.position));
	const active = $derived(isLoraActive(lora.status));
	const deleted = $derived(lora.deleted_at !== null);
	const lockedStatus = $derived(isLoraActive(lora.status) ? lora.status : null);
	const atCapacity = $derived(samples.length >= LORA_MAX_SAMPLES);
	const canAddSample = $derived(!active && !deleted && !atCapacity);

	const sampleValidationProblems = $derived([
		...(samples.length < LORA_MIN_SAMPLES_FOR_TRAINING
			? [
					pageText('voiceDetail.needSamples', LORA_MIN_SAMPLES_FOR_TRAINING, {
						have: formatDecimal(samples.length, 0)
					})
				]
			: []),
		...(samples.some((s) => !s.caption.trim() || !s.lyrics.trim())
			? [pageText('voiceDetail.sampleTextsMissing')]
			: [])
	]);

	const canTrain = $derived(
		!active && !deleted && sampleValidationProblems.length === 0 && !training
	);
	const trainingJob = $derived.by(() => {
		const jobId = lora.training_job_id;
		if (!jobId) return null;
		return $activeJobs.find((entry) => entry.job.id === jobId)?.job ?? null;
	});
	const displayedTrainingJob = $derived(
		trainingJob ?? (cancelledTrainingJob?.id === lora.training_job_id ? cancelledTrainingJob : null)
	);
	const waitingForWorker = $derived(
		displayedTrainingJob?.status === 'queued' &&
			(displayedTrainingJob.queue_reason !== null || displayedTrainingJob.queue_position !== null)
	);
	const epochProgress = $derived.by(() => {
		const job = displayedTrainingJob;
		if (!job?.train_epochs || job.current_epoch === null || job.current_epoch === undefined)
			return 0;
		return Math.min(100, Math.max(0, (job.current_epoch / job.train_epochs) * 100));
	});

	$effect(() => {
		const jobId = active ? lora.training_job_id : null;
		if (!jobId || fetchedTrainingJobId === jobId) return;
		fetchedTrainingJobId = jobId;
		void beginTrainingJobStream(jobId);
	});

	async function beginTrainingJobStream(jobId: string) {
		try {
			const job = await fetchJob(jobId);
			if (job.status === 'cancelled') {
				cancelledTrainingJob = job;
				return;
			}
			if (isActiveJobStatus(job.status)) trackJob(job, {});
		} catch {
			addToast(pageText('voiceDetail.progressLoadFailed'), 'error');
		}
	}

	function isAudioOrToast(file: File): boolean {
		const name = file.name.toLowerCase();
		const accepted = LORA_AUDIO_EXTENSIONS.some((ext) => name.endsWith(ext));
		if (!accepted) {
			const formats = formatList(LORA_AUDIO_EXTENSIONS);
			addToast(pageText('voiceDetail.unsupportedFormat', { formats }), 'error');
		}
		return accepted;
	}

	function showSampleFailure(e: unknown, fallback: string) {
		sampleError = describeFailure(e, fallback);
		addToast(sampleError, 'error');
	}

	function onFilePicked(e: Event) {
		const input = e.target as HTMLInputElement;
		const file = input.files?.[0] ?? null;
		newFile = file && isAudioOrToast(file) ? file : null;
		if (file && !newFile) input.value = '';
	}

	function onDrop(e: DragEvent) {
		e.preventDefault();
		dragOver = false;
		const file = e.dataTransfer?.files?.[0] ?? null;
		if (file && isAudioOrToast(file)) newFile = file;
	}

	async function submitNewSample() {
		if (!newFile || !newCaption.trim() || !newLyrics.trim()) {
			addToast(
				pageText(newFile ? 'voiceDetail.captionLyricsRequired' : 'voiceDetail.pickFileFirst'),
				'error'
			);
			return;
		}
		sampleError = null;
		uploading = true;
		try {
			await addLoraSample(lora.id, newFile, newCaption.trim(), newLyrics.trim());
			await refreshLora(lora.id);
			newFile = null;
			newCaption = '';
			newLyrics = '';
			if (fileInputEl) fileInputEl.value = '';
			addToast(pageText('voiceDetail.sampleAdded'), 'success');
		} catch (e) {
			showSampleFailure(e, pageText('voiceDetail.uploadFailed'));
		} finally {
			uploading = false;
		}
	}

	async function toggleOwnTakes() {
		showOwnTakes = !showOwnTakes;
		if (!showOwnTakes || ownTakes.length > 0) return;

		ownTakesLoading = true;
		sampleError = null;
		try {
			ownTakes = await listOwnPlayableTakes();
		} catch (e) {
			showSampleFailure(e, pageText('voiceDetail.ownTakesLoadFailed'));
		} finally {
			ownTakesLoading = false;
		}
	}

	async function addOwnTake(take: OwnPlayableTakeResponse) {
		addingGenerationId = take.generation_id;
		sampleError = null;
		try {
			await addLoraSampleFromGeneration(lora.id, take.generation_id);
			await refreshLora(lora.id);
			addToast(pageText('voiceDetail.sampleAdded'), 'success');
		} catch (e) {
			showSampleFailure(e, pageText('voiceDetail.copyFailed'));
		} finally {
			addingGenerationId = null;
		}
	}

	async function saveSample(sample: UserLoraSampleItem, caption: string, lyrics: string) {
		try {
			await patchLoraSample(lora.id, sample.id, { caption, lyrics });
			await refreshLora(lora.id);
		} catch (e) {
			addToast(describeFailure(e, pageText('voiceDetail.saveFailed')), 'error');
		}
	}

	async function removeSample(sample: UserLoraSampleItem) {
		if (!confirm(pageText('voiceDetail.removeConfirm', { position: String(sample.position + 1) })))
			return;
		try {
			await deleteLoraSample(lora.id, sample.id);
			await refreshLora(lora.id);
		} catch (e) {
			addToast(describeFailure(e, pageText('voiceDetail.deleteFailed')), 'error');
		}
	}

	async function startTraining() {
		training = true;
		trainingError = null;
		try {
			const updated = await trainLora(lora.id);
			cancelledTrainingJob = null;
			if (updated.training_job_id) {
				fetchedTrainingJobId = updated.training_job_id;
				void beginTrainingJobStream(updated.training_job_id);
			}
			addToast(pageText('voiceDetail.queuedToast'), 'success');
		} catch (e) {
			const message = describeFailure(e, pageText('voiceDetail.startFailed'));
			trainingError = message;
			addToast(message, 'error');
		} finally {
			training = false;
		}
	}

	async function cancelTraining() {
		const job = trainingJob;
		if (!job) return;
		cancellingTraining = true;
		try {
			const cancelled = await cancelJob(job.id);
			cancelledTrainingJob = cancelled;
			removeJob(job.id);
		} catch (e) {
			addToast(describeFailure(e, pageText('voiceDetail.cancelFailed')), 'error');
		} finally {
			cancellingTraining = false;
		}
	}
</script>

{#snippet browse({ text }: { text: string })}
	<label class="file-pick">
		<input
			type="file"
			accept={LORA_AUDIO_EXTENSIONS.join(',')}
			onchange={onFilePicked}
			bind:this={fileInputEl}
		/>
		{text}
	</label>
{/snippet}

<div class="lora-detail" class:deleted>
	{#if deleted}
		<p class="banner warn">{pageText('voiceDetail.deletedBanner')}</p>
	{:else if displayedTrainingJob?.status === 'cancelled'}
		<p class="banner info">{pageText('voiceDetail.trainingCancelled')}</p>
	{:else if lockedStatus}
		<p class="banner info">{pageText(ACTIVE_STATUS_KEYS[lockedStatus].banner)}</p>
	{:else if lora.status === 'failed' && lora.error}
		<p class="banner error">
			<strong>{pageText('voiceDetail.trainingFailed')}</strong><br />{lora.error}
		</p>
	{/if}

	<section class="samples-section">
		<header class="section-head">
			<h3>{pageText('voiceDetail.samples')}</h3>
			<span class="count"
				>{pageText('voiceDetail.sampleCapacity', {
					used: formatDecimal(samples.length, 0),
					max: formatDecimal(LORA_MAX_SAMPLES, 0)
				})}</span
			>
		</header>

		{#if samples.length === 0}
			<p class="empty">
				{pageText('voiceDetail.noSamples', { count: LORA_MIN_SAMPLES_FOR_TRAINING })}
			</p>
		{/if}

		<ul class="sample-list">
			{#each samples as sample, i (sample.id)}
				{@const captionId = `caption-${sample.id}`}
				{@const lyricsId = `lyrics-${sample.id}`}
				{@const position = String(i + 1)}
				<li class="sample-row">
					<div class="sample-head">
						<span class="pos">{pageText('voiceDetail.samplePosition', { position })}</span>
						<audio controls preload="none" src={`/audio/${sample.audio_path}`}></audio>
						<button
							class="remove-btn"
							disabled={active || deleted}
							onclick={() => removeSample(sample)}
							aria-label={pageText('voiceDetail.removeLabel')}
						>
							{pageText('voiceDetail.remove')}
						</button>
					</div>
					<label class="field">
						<span class="field-label">{pageText('voiceDetail.captionLabel')}</span>
						<textarea
							id={captionId}
							rows="2"
							disabled={active || deleted}
							value={sample.caption}
							onblur={(e) => {
								const v = (e.target as HTMLTextAreaElement).value.trim();
								if (v && v !== sample.caption) saveSample(sample, v, sample.lyrics);
							}}></textarea>
					</label>
					<label class="field">
						<span class="field-label">{pageText('voiceDetail.lyricsLabel')}</span>
						<textarea
							id={lyricsId}
							rows="4"
							disabled={active || deleted}
							value={sample.lyrics}
							onblur={(e) => {
								const v = (e.target as HTMLTextAreaElement).value.trim();
								if (v && v !== sample.lyrics) saveSample(sample, sample.caption, v);
							}}></textarea>
					</label>
				</li>
			{/each}
		</ul>

		{#if canAddSample}
			<div
				class="drop-zone"
				class:drag-over={dragOver}
				onsubmit={(e) => e.preventDefault()}
				ondrop={onDrop}
				ondragover={(e) => {
					e.preventDefault();
					dragOver = true;
				}}
				ondragleave={() => (dragOver = false)}
				role="region"
				aria-label={pageText('voiceDetail.addSample')}
			>
				<div class="drop-head">
					<strong>{pageText('voiceDetail.addSample')}</strong>
					<span class="drop-hint">
						<Marked parts={pageParts('voiceDetail.dropHint')} marked={{ browse }} />
					</span>
				</div>
				<p class="sample-sources">{pageText('voiceDetail.sources')}</p>
				{#if newFile}
					<p class="file-name">{newFile.name}</p>
				{/if}
				<label class="field">
					<span class="field-label">{pageText('voiceDetail.captionLabel')}</span>
					<textarea
						rows="2"
						placeholder={pageText('voiceDetail.captionPlaceholder')}
						bind:value={newCaption}></textarea>
				</label>
				<label class="field">
					<span class="field-label">{pageText('voiceDetail.lyricsLabel')}</span>
					<textarea
						rows="4"
						placeholder={pageText('voiceDetail.lyricsPlaceholder')}
						bind:value={newLyrics}></textarea>
				</label>
				<button
					class="add-sample-btn"
					disabled={uploading || !newFile || !newCaption.trim() || !newLyrics.trim()}
					onclick={submitNewSample}
				>
					{pageText(uploading ? 'voiceDetail.uploading' : 'voiceDetail.addSample')}
				</button>
				<button class="own-takes-toggle" aria-expanded={showOwnTakes} onclick={toggleOwnTakes}>
					{pageText(showOwnTakes ? 'voiceDetail.ownTakesClose' : 'voiceDetail.ownTakesOpen')}
				</button>
			</div>
			{#if sampleError}
				<p class="sample-error" role="alert">{sampleError}</p>
			{/if}
			{#if showOwnTakes}
				<section class="own-takes" aria-label={pageText('voiceDetail.ownTakes')}>
					<h4>{pageText('voiceDetail.ownTakes')}</h4>
					{#if ownTakesLoading}
						<p class="empty">{pageText('voiceDetail.ownTakesLoading')}</p>
					{:else if ownTakes.length === 0}
						<p class="empty">{pageText('voiceDetail.ownTakesEmpty')}</p>
					{:else}
						<ul>
							{#each ownTakes as take (take.generation_id)}
								{@const number = String(take.generation_number)}
								<li>
									<div>
										<strong>{take.song_title}</strong>
										<span>{pageText('voiceDetail.takeNumber', { number })}</span>
									</div>
									<button
										class="use-take-btn"
										disabled={addingGenerationId !== null}
										onclick={() => addOwnTake(take)}
									>
										{pageText(
											addingGenerationId === take.generation_id
												? 'voiceDetail.adding'
												: 'voiceDetail.useTake'
										)}
									</button>
								</li>
							{/each}
						</ul>
					{/if}
				</section>
			{/if}
		{:else if atCapacity && !deleted}
			<p class="hint">{pageText('voiceDetail.sampleLimit')}</p>
		{/if}
	</section>

	{#if displayedTrainingJob}
		<section class="training-progress" aria-live="polite">
			<div class="training-progress-head">
				<strong
					>{pageText(waitingForWorker ? 'voiceDetail.waiting' : 'voiceDetail.training')}</strong
				>
				{#if trainingJob}
					<button
						class="cancel-training-btn"
						disabled={cancellingTraining}
						onclick={cancelTraining}
					>
						{pageText('voiceDetail.cancel')}
					</button>
				{/if}
			</div>
			{#if displayedTrainingJob.status === 'cancelled'}
				<p>{pageText('voiceDetail.trainingCancelled')}</p>
			{:else if waitingForWorker}
				<p>{displayedTrainingJob.queue_reason || pageText('voiceDetail.waitingDefault')}</p>
				{#if displayedTrainingJob.queue_position !== null && displayedTrainingJob.queue_position !== undefined}
					<p class="training-detail">
						{pageText('voiceDetail.queuePosition', {
							position: formatDecimal(displayedTrainingJob.queue_position, 0)
						})}
					</p>
				{/if}
			{:else}
				<div class="progress-track" aria-label={pageText('voiceDetail.progressLabel')}>
					<span style:width={`${epochProgress}%`}></span>
				</div>
				<div class="training-progress-meta">
					{#if displayedTrainingJob.current_epoch !== null && displayedTrainingJob.current_epoch !== undefined && displayedTrainingJob.train_epochs}
						<strong>
							{pageText('voiceDetail.epoch', {
								current: formatDecimal(displayedTrainingJob.current_epoch, 0),
								total: formatDecimal(displayedTrainingJob.train_epochs, 0)
							})}
						</strong>
					{/if}
					{#if displayedTrainingJob.remaining_time_estimate === 'calculating'}
						<span>{pageText('voiceDetail.remainingCalculating')}</span>
					{:else if typeof displayedTrainingJob.remaining_time_estimate === 'number'}
						<span>{formatRemainingTime(displayedTrainingJob.remaining_time_estimate)}</span>
					{/if}
				</div>
			{/if}
		</section>
	{/if}

	<section class="train-section">
		<button class="train-btn" disabled={!canTrain} onclick={startTraining}>
			{training
				? pageText('voiceDetail.starting')
				: lockedStatus
					? pageText(ACTIVE_STATUS_KEYS[lockedStatus].button)
					: lora.status === 'failed'
						? pageText('voiceDetail.trainAgain')
						: pageText('voiceDetail.trainVoice')}
		</button>
		{#if trainingError}
			<p class="training-error" role="alert">{trainingError}</p>
		{/if}
		{#if sampleValidationProblems.length > 0 && !active && !deleted}
			<ul class="problems">
				{#each sampleValidationProblems as p (p)}
					<li>{p}</li>
				{/each}
			</ul>
		{/if}
	</section>
</div>

<style>
	.lora-detail {
		display: flex;
		flex-direction: column;
		gap: 1.2rem;
	}

	.lora-detail.deleted {
		opacity: 0.6;
	}

	.banner {
		margin: 0;
		padding: 0.6rem 0.9rem;
		border-radius: 4px;
		font-size: 0.85rem;
		overflow-wrap: anywhere;
	}

	.banner.info {
		border: 1px solid var(--border);
		background: var(--surface);
		color: var(--text-muted);
	}

	.banner.warn {
		border: 1px solid var(--fail);
		color: var(--fail);
	}

	.banner.error {
		border: 1px solid var(--fail);
		background: color-mix(in srgb, var(--fail) 8%, transparent);
		color: var(--fail);
	}

	.section-head {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		margin-bottom: 0.6rem;
	}

	h3 {
		margin: 0;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		font-size: 1rem;
		color: var(--text-muted);
	}

	.count {
		font-size: 0.75rem;
		color: var(--text-subtle);
	}

	.sample-list {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 0.8rem;
	}

	.sample-row {
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		padding: 0.75rem;
		background: var(--surface);
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.sample-head {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		flex-wrap: wrap;
	}

	.pos {
		font-family: var(--font-display);
		font-size: 0.75rem;
		color: var(--text-subtle);
		letter-spacing: 1px;
		min-width: 2rem;
	}

	.sample-head audio {
		flex: 1;
		min-width: 200px;
	}

	.remove-btn {
		padding: 0.25rem 0.7rem;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		background: transparent;
		color: var(--text-muted);
		cursor: pointer;
		font-size: 0.75rem;
		font-family: var(--font-display);
	}

	.remove-btn:hover:not(:disabled) {
		border-color: var(--accent);
		color: var(--accent);
	}

	.remove-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.field {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}

	.field-label {
		font-size: 0.7rem;
		color: var(--text-subtle);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		font-family: var(--font-display);
	}

	textarea {
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		padding: 0.4rem 0.5rem;
		font-family: var(--font-body);
		font-size: 0.85rem;
		resize: vertical;
	}

	textarea:focus {
		outline: none;
		border-color: var(--accent);
		box-shadow: 0 0 8px color-mix(in srgb, var(--accent) 20%, transparent);
	}

	textarea:disabled {
		opacity: 0.5;
	}

	.empty {
		color: var(--text-subtle);
		font-size: 0.85rem;
	}

	.drop-zone {
		margin-top: 0.9rem;
		border: 2px dashed var(--border);
		border-radius: var(--card-radius);
		padding: 1rem;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		background: var(--surface);
	}

	.drop-zone.drag-over {
		border-color: var(--accent);
		background: color-mix(in srgb, var(--accent) 8%, transparent);
	}

	.drop-head {
		display: flex;
		justify-content: space-between;
		align-items: center;
		flex-wrap: wrap;
		gap: 0.5rem;
	}

	.drop-hint {
		color: var(--text-subtle);
		font-size: 0.8rem;
	}

	.file-pick {
		color: var(--accent);
		cursor: pointer;
		text-decoration: underline;
	}

	.file-pick input[type='file'] {
		display: none;
	}

	.file-name {
		margin: 0;
		font-size: 0.8rem;
		color: var(--text-muted);
	}

	.add-sample-btn {
		align-self: flex-start;
		padding: 0.45rem 1rem;
		border: none;
		border-radius: var(--btn-radius-pill);
		background: var(--accent);
		color: var(--on-accent);
		font-family: var(--font-display);
		letter-spacing: 0.5px;
		font-size: 0.8rem;
		text-transform: uppercase;
		cursor: pointer;
	}

	.own-takes-toggle,
	.use-take-btn {
		padding: 0.4rem 0.8rem;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-pill);
		background: transparent;
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: 0.75rem;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		cursor: pointer;
	}

	.own-takes-toggle:hover,
	.use-take-btn:hover:not(:disabled) {
		border-color: var(--accent);
		color: var(--accent);
	}

	.use-take-btn:disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}

	.sample-error {
		margin: 0.7rem 0 0;
		padding: 0.6rem 0.75rem;
		border: 1px solid var(--fail);
		border-radius: 4px;
		color: var(--fail);
		font-size: 0.85rem;
	}

	.training-progress {
		padding: 0.85rem;
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		background: var(--surface);
	}

	.training-progress-head,
	.training-progress-meta {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.75rem;
		flex-wrap: wrap;
	}

	.training-progress-head strong {
		font-family: var(--font-display);
		letter-spacing: 0.5px;
		text-transform: uppercase;
	}

	.training-progress p {
		margin: 0.6rem 0 0;
		color: var(--text-muted);
	}

	.training-detail {
		font-size: 0.8rem;
		color: var(--text-subtle) !important;
	}

	.progress-track {
		height: 0.4rem;
		margin: 0.8rem 0 0.55rem;
		border-radius: 999px;
		overflow: hidden;
		background: var(--bg);
	}

	.progress-track span {
		display: block;
		height: 100%;
		border-radius: inherit;
		background: var(--accent);
		transition: width 180ms ease;
	}

	@media (prefers-reduced-motion: reduce) {
		.progress-track span {
			transition: none;
		}
	}

	.cancel-training-btn {
		padding: 0.3rem 0.75rem;
		border: 1px solid var(--accent);
		border-radius: var(--btn-radius-sm);
		background: transparent;
		color: var(--accent);
		font-family: var(--font-display);
		font-size: 0.75rem;
		letter-spacing: 0.5px;
		text-transform: uppercase;
		cursor: pointer;
	}

	.cancel-training-btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.sample-sources {
		margin: 0.35rem 0 0;
		font-size: 0.75rem;
		color: var(--text-subtle);
	}

	.own-takes {
		margin-top: 0.8rem;
		padding: 0.75rem;
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		background: var(--surface);
	}

	.own-takes h4 {
		margin: 0 0 0.6rem;
		font-family: var(--font-display);
		font-size: 0.8rem;
		letter-spacing: 0.5px;
		text-transform: uppercase;
		color: var(--text-muted);
	}

	.own-takes ul {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.own-takes li {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 0.75rem;
		padding-top: 0.5rem;
		border-top: 1px solid var(--border);
	}

	.own-takes li:first-child {
		padding-top: 0;
		border-top: 0;
	}

	.own-takes li div {
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
	}

	.own-takes li strong,
	.own-takes li span {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.own-takes li span {
		font-size: 0.75rem;
		color: var(--text-subtle);
	}

	.add-sample-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.hint {
		font-size: 0.8rem;
		color: var(--text-subtle);
	}

	.train-section {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.training-error {
		margin: 0;
		padding: 0.6rem 0.75rem;
		border: 1px solid var(--fail);
		border-radius: 4px;
		color: var(--fail);
		font-size: 0.85rem;
		overflow-wrap: anywhere;
		white-space: pre-line;
	}

	.train-btn {
		align-self: flex-start;
		padding: 0.55rem 1.3rem;
		border: none;
		border-radius: var(--btn-radius-pill);
		background: var(--accent);
		color: var(--on-accent);
		font-family: var(--font-display);
		letter-spacing: 0.75px;
		text-transform: uppercase;
		font-size: 0.85rem;
		cursor: pointer;
	}

	.train-btn:disabled {
		opacity: 0.35;
		cursor: not-allowed;
	}

	.problems {
		list-style: none;
		padding: 0;
		margin: 0;
		color: var(--fail);
		font-size: 0.8rem;
	}

	.problems li::before {
		content: '• ';
	}
</style>
