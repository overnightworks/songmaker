<script lang="ts">
	let { text }: { text: string } = $props();
	const lineId = $props.id();
</script>

<!-- Whitespace between the ring and the line would enter the text a caller reads. -->
<!-- prettier-ignore -->
<div class="busy" role="status" aria-labelledby={lineId}><span class="ring" aria-hidden="true"></span><p id={lineId}>{text}</p></div>

<style>
	.busy {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		flex: 1;
		gap: 10px;
		padding: 24px;
		text-align: center;
		color: var(--text-muted);
	}

	.ring {
		width: 24px;
		height: 24px;
		box-sizing: border-box;
		border: 2px solid var(--busy);
		border-top-color: transparent;
		border-radius: 50%;
		animation: turn 1.1s linear infinite;
	}

	.busy p {
		margin: 0;
		max-width: 28ch;
		font-size: 15px;
	}

	@keyframes turn {
		to {
			transform: rotate(360deg);
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.ring {
			animation: none;
		}
	}
</style>
