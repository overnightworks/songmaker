<script lang="ts">
	import type {
		JobItem,
		OwnPlayableTakeResponse,
		UserLoraItem,
		UserLoraSampleItem
	} from '$lib/api/types';
	import { addLoraSample, patchLoraSample, deleteLoraSample, ApiError } from '$lib/api/client';
	import { cancelJob, fetchJob } from '$lib/api/jobs';
	import { addLoraSampleFromGeneration, listOwnPlayableTakes } from '$lib/api/loras';
	import { activeJobs, removeJob, trackJob } from '$lib/stores/jobs';
	import { refreshLora, trainLora, isLoraActive } from '$lib/stores/loras';
	import { addToast } from '$lib/stores/toast';
	import {
		LORA_AUDIO_EXTENSIONS,
		LORA_MAX_SAMPLES,
		LORA_MIN_SAMPLES_FOR_TRAINING,
		LORA_OWN_TAKES_CLOSE,
		LORA_OWN_TAKES_EMPTY,
		LORA_OWN_TAKES_LABEL,
		LORA_OWN_TAKES_LOAD_FAILED,
		LORA_OWN_TAKES_LOADING,
		LORA_OWN_TAKES_OPEN,
		LORA_OWN_TAKES_USE,
		LORA_SAMPLE_ADDING,
		LORA_SAMPLE_COPY_FAILED,
		LORA_SAMPLE_UPLOAD_FAILED,
		LORA_TAKE_LABEL_PREFIX,
		LORA_TRAINING_CANCEL_FAILED,
		LORA_TRAINING_CANCEL_LABEL,
		LORA_TRAINING_CANCELLED,
		LORA_TRAINING_FAILED_LABEL,
		LORA_TRAINING_PROGRESS_LOAD_FAILED,
		LORA_TRAINING_RETRY_LABEL,
		LORA_TRAINING_START_FAILED,
		LORA_TRAINING_PROGRESS_LABEL,
		LORA_TRAINING_QUEUED_TOAST,
		LORA_TRAINING_REMAINING_CALCULATING,
		LORA_TRAINING_STARTING,
		LORA_TRAINING_STATUS_LABEL,
		LORA_TRAINING_WAITING_DEFAULT_REASON,
		LORA_TRAINING_WAITING_LABEL,
		loraTrainingEpochLabel,
		loraTrainingQueuePositionLabel,
		loraTrainingRemainingLabel
	} from '$lib/constants';

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
	const atCapacity = $derived(samples.length >= LORA_MAX_SAMPLES);
	const canAddSample = $derived(!active && !deleted && !atCapacity);

	const sampleValidationProblems = $derived.by(() => {
		const problems: string[] = [];
		if (samples.length < LORA_MIN_SAMPLES_FOR_TRAINING) {
			problems.push(
				`Need at least ${LORA_MIN_SAMPLES_FOR_TRAINING} samples (have ${samples.length})`
			);
		}
		for (const s of samples) {
			if (!s.caption.trim() || !s.lyrics.trim()) {
				problems.push('Every sample needs a non-empty caption and lyrics');
				break;
			}
		}
		return problems;
	});

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
			if (job.status === 'queued' || job.status === 'running') trackJob(job, {});
		} catch {
			addToast(LORA_TRAINING_PROGRESS_LOAD_FAILED, 'error');
		}
	}

	function acceptsAudio(file: File): boolean {
		const name = file.name.toLowerCase();
		return LORA_AUDIO_EXTENSIONS.some((ext) => name.endsWith(ext));
	}

	function onFilePicked(e: Event) {
		const input = e.target as HTMLInputElement;
		const file = input.files?.[0] ?? null;
		if (file && !acceptsAudio(file)) {
			addToast(`Unsupported format. Accepted: ${LORA_AUDIO_EXTENSIONS.join(', ')}`, 'error');
			newFile = null;
			input.value = '';
			return;
		}
		newFile = file;
	}

	function onDrop(e: DragEvent) {
		e.preventDefault();
		dragOver = false;
		const file = e.dataTransfer?.files?.[0] ?? null;
		if (!file) return;
		if (!acceptsAudio(file)) {
			addToast(`Unsupported format. Accepted: ${LORA_AUDIO_EXTENSIONS.join(', ')}`, 'error');
			return;
		}
		newFile = file;
	}

	function onDragOver(e: DragEvent) {
		e.preventDefault();
		dragOver = true;
	}

	function onDragLeave() {
		dragOver = false;
	}

	async function submitNewSample() {
		if (!newFile) {
			addToast('Pick an audio file first', 'error');
			return;
		}
		if (!newCaption.trim() || !newLyrics.trim()) {
			addToast('Caption and lyrics are required', 'error');
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
			addToast('Sample added', 'success');
		} catch (e) {
			const message =
				e instanceof ApiError ? e.detail || LORA_SAMPLE_UPLOAD_FAILED : LORA_SAMPLE_UPLOAD_FAILED;
			sampleError = message;
			addToast(message, 'error');
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
			const message =
				e instanceof ApiError ? e.detail || LORA_OWN_TAKES_LOAD_FAILED : LORA_OWN_TAKES_LOAD_FAILED;
			sampleError = message;
			addToast(message, 'error');
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
			addToast('Sample added', 'success');
		} catch (e) {
			const message =
				e instanceof ApiError ? e.detail || LORA_SAMPLE_COPY_FAILED : LORA_SAMPLE_COPY_FAILED;
			sampleError = message;
			addToast(message, 'error');
		} finally {
			addingGenerationId = null;
		}
	}

	async function saveSample(sample: UserLoraSampleItem, caption: string, lyrics: string) {
		try {
			await patchLoraSample(lora.id, sample.id, { caption, lyrics });
			await refreshLora(lora.id);
		} catch (e) {
			addToast(e instanceof ApiError ? e.detail || 'Save failed' : 'Save failed', 'error');
		}
	}

	async function removeSample(sample: UserLoraSampleItem) {
		if (!confirm(`Remove sample at position ${sample.position + 1}?`)) return;
		try {
			await deleteLoraSample(lora.id, sample.id);
			await refreshLora(lora.id);
		} catch (e) {
			addToast(e instanceof ApiError ? e.detail || 'Delete failed' : 'Delete failed', 'error');
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
			addToast(LORA_TRAINING_QUEUED_TOAST, 'success');
		} catch (e) {
			const message =
				e instanceof ApiError ? e.detail || LORA_TRAINING_START_FAILED : LORA_TRAINING_START_FAILED;
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
			addToast(
				e instanceof ApiError
					? e.detail || LORA_TRAINING_CANCEL_FAILED
					: LORA_TRAINING_CANCEL_FAILED,
				'error'
			);
		} finally {
			cancellingTraining = false;
		}
	}
</script>

<div class="lora-detail" class:deleted>
	{#if deleted}
		<p class="banner warn">This voice has been deleted. Editing is disabled.</p>
	{:else if displayedTrainingJob?.status === 'cancelled'}
		<p class="banner info">{LORA_TRAINING_CANCELLED}</p>
	{:else if active}
		<p class="banner info">Voice is {lora.status} — editing is locked until training finishes.</p>
	{:else if lora.status === 'failed' && lora.error}
		<p class="banner error"><strong>{LORA_TRAINING_FAILED_LABEL}</strong><br />{lora.error}</p>
	{/if}

	<section class="samples-section">
		<header class="section-head">
			<h3>Samples</h3>
			<span class="count">{samples.length} / {LORA_MAX_SAMPLES}</span>
		</header>

		{#if samples.length === 0}
			<p class="empty">No samples yet. Add at least {LORA_MIN_SAMPLES_FOR_TRAINING} to train.</p>
		{/if}

		<ul class="sample-list">
			{#each samples as sample, i (sample.id)}
				{@const captionId = `caption-${sample.id}`}
				{@const lyricsId = `lyrics-${sample.id}`}
				<li class="sample-row">
					<div class="sample-head">
						<span class="pos">#{i + 1}</span>
						<audio controls preload="none" src={`/audio/${sample.audio_path}`}></audio>
						<button
							class="remove-btn"
							disabled={active || deleted}
							onclick={() => removeSample(sample)}
							aria-label="Remove sample"
						>
							Remove
						</button>
					</div>
					<label class="field">
						<span class="field-label">Caption (style prompt)</span>
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
						<span class="field-label">Lyrics</span>
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
				ondragover={onDragOver}
				ondragleave={onDragLeave}
				role="region"
				aria-label="Add sample"
			>
				<div class="drop-head">
					<strong>Add sample</strong>
					<span class="drop-hint">
						Drag audio here, or
						<label class="file-pick">
							<input
								type="file"
								accept={LORA_AUDIO_EXTENSIONS.join(',')}
								onchange={onFilePicked}
								bind:this={fileInputEl}
							/>
							browse
						</label>
					</span>
				</div>
				<p class="sample-sources">Your takes and uploads only.</p>
				{#if newFile}
					<p class="file-name">{newFile.name}</p>
				{/if}
				<label class="field">
					<span class="field-label">Caption (style prompt)</span>
					<textarea rows="2" placeholder="e.g. warm male vocal, folk guitar" bind:value={newCaption}
					></textarea>
				</label>
				<label class="field">
					<span class="field-label">Lyrics</span>
					<textarea rows="4" placeholder="Lyrics present in this audio clip" bind:value={newLyrics}
					></textarea>
				</label>
				<button
					class="add-sample-btn"
					disabled={uploading || !newFile || !newCaption.trim() || !newLyrics.trim()}
					onclick={submitNewSample}
				>
					{uploading ? 'Uploading...' : 'Add sample'}
				</button>
				<button class="own-takes-toggle" aria-expanded={showOwnTakes} onclick={toggleOwnTakes}>
					{showOwnTakes ? LORA_OWN_TAKES_CLOSE : LORA_OWN_TAKES_OPEN}
				</button>
			</div>
			{#if sampleError}
				<p class="sample-error" role="alert">{sampleError}</p>
			{/if}
			{#if showOwnTakes}
				<section class="own-takes" aria-label={LORA_OWN_TAKES_LABEL}>
					<h4>{LORA_OWN_TAKES_LABEL}</h4>
					{#if ownTakesLoading}
						<p class="empty">{LORA_OWN_TAKES_LOADING}</p>
					{:else if ownTakes.length === 0}
						<p class="empty">{LORA_OWN_TAKES_EMPTY}</p>
					{:else}
						<ul>
							{#each ownTakes as take (take.generation_id)}
								<li>
									<div>
										<strong>{take.song_title}</strong>
										<span>{LORA_TAKE_LABEL_PREFIX} {take.generation_number}</span>
									</div>
									<button
										class="use-take-btn"
										disabled={addingGenerationId !== null}
										onclick={() => addOwnTake(take)}
									>
										{addingGenerationId === take.generation_id
											? LORA_SAMPLE_ADDING
											: LORA_OWN_TAKES_USE}
									</button>
								</li>
							{/each}
						</ul>
					{/if}
				</section>
			{/if}
		{:else if atCapacity && !deleted}
			<p class="hint">Sample limit reached.</p>
		{/if}
	</section>

	{#if displayedTrainingJob}
		<section class="training-progress" aria-live="polite">
			<div class="training-progress-head">
				<strong
					>{waitingForWorker ? LORA_TRAINING_WAITING_LABEL : LORA_TRAINING_STATUS_LABEL}</strong
				>
				{#if trainingJob}
					<button
						class="cancel-training-btn"
						disabled={cancellingTraining}
						onclick={cancelTraining}
					>
						{LORA_TRAINING_CANCEL_LABEL}
					</button>
				{/if}
			</div>
			{#if displayedTrainingJob.status === 'cancelled'}
				<p>{LORA_TRAINING_CANCELLED}</p>
			{:else if waitingForWorker}
				<p>{displayedTrainingJob.queue_reason || LORA_TRAINING_WAITING_DEFAULT_REASON}</p>
				{#if displayedTrainingJob.queue_position !== null && displayedTrainingJob.queue_position !== undefined}
					<p class="training-detail">
						{loraTrainingQueuePositionLabel(displayedTrainingJob.queue_position)}
					</p>
				{/if}
			{:else}
				<div class="progress-track" aria-label={LORA_TRAINING_PROGRESS_LABEL}>
					<span style:width={`${epochProgress}%`}></span>
				</div>
				<div class="training-progress-meta">
					{#if displayedTrainingJob.current_epoch !== null && displayedTrainingJob.current_epoch !== undefined && displayedTrainingJob.train_epochs}
						<strong>
							{loraTrainingEpochLabel(
								displayedTrainingJob.current_epoch,
								displayedTrainingJob.train_epochs
							)}
						</strong>
					{/if}
					{#if displayedTrainingJob.remaining_time_estimate === 'calculating'}
						<span>{LORA_TRAINING_REMAINING_CALCULATING}</span>
					{:else if typeof displayedTrainingJob.remaining_time_estimate === 'number'}
						<span>{loraTrainingRemainingLabel(displayedTrainingJob.remaining_time_estimate)}</span>
					{/if}
				</div>
			{/if}
		</section>
	{/if}

	<section class="train-section">
		<button class="train-btn" disabled={!canTrain} onclick={startTraining}>
			{training
				? LORA_TRAINING_STARTING
				: active
					? `Training (${lora.status})`
					: lora.status === 'failed'
						? LORA_TRAINING_RETRY_LABEL
						: 'Train voice'}
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
		border: 1px solid var(--score-bad);
		color: var(--score-bad);
	}

	.banner.error {
		border: 1px solid var(--score-bad);
		background: rgba(255, 68, 68, 0.08);
		color: var(--score-bad);
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
		border-color: var(--score-bad);
		color: var(--score-bad);
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
		box-shadow: 0 0 8px rgba(160, 32, 240, 0.2);
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
		background: rgba(160, 32, 240, 0.08);
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
		color: var(--primary);
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
		background: linear-gradient(135deg, var(--primary), var(--accent));
		color: #fff;
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
		border-color: var(--primary);
		color: var(--primary);
	}

	.use-take-btn:disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}

	.sample-error {
		margin: 0.7rem 0 0;
		padding: 0.6rem 0.75rem;
		border: 1px solid var(--score-bad);
		border-radius: 4px;
		color: var(--score-bad);
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
		background: linear-gradient(90deg, var(--primary), var(--accent));
		transition: width 180ms ease;
	}

	@media (prefers-reduced-motion: reduce) {
		.progress-track span {
			transition: none;
		}
	}

	.cancel-training-btn {
		padding: 0.3rem 0.75rem;
		border: 1px solid var(--score-bad);
		border-radius: var(--btn-radius-sm);
		background: transparent;
		color: var(--score-bad);
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
		border: 1px solid var(--score-bad);
		border-radius: 4px;
		color: var(--score-bad);
		font-size: 0.85rem;
		overflow-wrap: anywhere;
		white-space: pre-line;
	}

	.train-btn {
		align-self: flex-start;
		padding: 0.55rem 1.3rem;
		border: none;
		border-radius: var(--btn-radius-pill);
		background: linear-gradient(135deg, var(--primary), var(--accent));
		color: #fff;
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
		color: var(--score-bad);
		font-size: 0.8rem;
	}

	.problems li::before {
		content: '• ';
	}
</style>
