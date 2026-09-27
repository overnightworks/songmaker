<script lang="ts">
	import { audioPlayer } from '$lib/services/audioPlayer.svelte';
	import { PLAYING_MARK_LABEL } from '$lib/constants';

	interface Props {
		/** Whether this row holds the take the transport is on. */
		current: boolean;
	}

	let { current }: Props = $props();

	const sounding = $derived(current && audioPlayer.status === 'playing');
</script>

{#if sounding}
	<span class="playing-mark" role="img" aria-label={PLAYING_MARK_LABEL}>
		<span></span><span></span><span></span>
	</span>
{/if}

<style>
	.playing-mark {
		display: inline-flex;
		align-items: flex-end;
		gap: 2px;
		width: 12px;
		height: 12px;
		flex-shrink: 0;
	}

	.playing-mark span {
		width: 2px;
		background: var(--primary);
		animation: equalize 0.9s ease-in-out infinite;
	}

	.playing-mark span:nth-child(1) {
		height: 40%;
		animation-delay: -0.6s;
	}

	.playing-mark span:nth-child(2) {
		height: 100%;
		animation-delay: -0.3s;
	}

	.playing-mark span:nth-child(3) {
		height: 65%;
	}

	@media (prefers-reduced-motion: reduce) {
		.playing-mark span {
			animation: none;
		}
	}

	@keyframes equalize {
		0%,
		100% {
			height: 30%;
		}
		50% {
			height: 100%;
		}
	}
</style>
