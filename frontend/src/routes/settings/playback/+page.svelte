<script lang="ts">
	import {
		queuePlaybackMode,
		setQueuePlaybackMode,
		type QueuePlaybackMode
	} from '$lib/stores/playbackSettings';

	const playbackModes: { value: QueuePlaybackMode; label: string; note?: string }[] = [
		{ value: 'stream', label: 'Continuous stream', note: 'Recommended' },
		{ value: 'classic', label: 'Per-track (legacy)' }
	];
</script>

<div class="settings-page">
	<h1>Playback</h1>

	<section>
		<h2>Queue Mode</h2>
		<div class="mode-list" role="radiogroup" aria-label="Queue playback mode">
			{#each playbackModes as mode (mode.value)}
				<button
					type="button"
					class:active={$queuePlaybackMode === mode.value}
					role="radio"
					aria-checked={$queuePlaybackMode === mode.value}
					onclick={() => setQueuePlaybackMode(mode.value)}
				>
					<span>{mode.label}</span>
					{#if mode.note}
						<small>{mode.note}</small>
					{/if}
				</button>
			{/each}
		</div>
	</section>
</div>

<style>
	.settings-page {
		flex: 1;
		padding: 2rem;
		max-width: 560px;
	}

	h1 {
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.1em;
		background: linear-gradient(90deg, var(--primary), var(--accent));
		-webkit-background-clip: text;
		-webkit-text-fill-color: transparent;
		background-clip: text;
		font-size: 1.5rem;
		margin-bottom: 1.5rem;
	}

	h2 {
		font-size: 1rem;
		color: var(--text-muted);
		margin-bottom: 0.75rem;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.mode-list {
		display: grid;
		gap: 0.75rem;
	}

	.mode-list button {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.75rem;
		width: 100%;
		min-height: 58px;
		padding: 0.9rem 1rem;
		border: 1px solid var(--border);
		border-radius: var(--input-radius);
		background: var(--bg);
		color: var(--text);
		cursor: pointer;
		text-align: left;
		font-family: var(--font-body);
		transition:
			background 0.15s,
			border-color 0.15s,
			box-shadow 0.15s;
	}

	.mode-list button:hover {
		background: var(--surface-hover);
		border-color: var(--accent);
	}

	.mode-list button.active {
		border-color: var(--primary);
		box-shadow: 0 0 0 1px var(--primary);
	}

	.mode-list span {
		font-weight: 700;
		font-size: 0.95rem;
	}

	.mode-list small {
		color: var(--text-muted);
		border: 1px solid var(--border);
		border-radius: 999px;
		padding: 0.15rem 0.5rem;
		font-size: 0.82rem;
	}
</style>
