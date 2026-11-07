<script lang="ts">
	import Icon from './Icon.svelte';

	let { icon, text }: { icon: string; text: string } = $props();
</script>

<!-- Whitespace between the glyph and the line would enter the text a caller reads. -->
<!-- prettier-ignore -->
<div class="empty"><Icon name={icon} size={40} /><p>{text}</p></div>

<style>
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
</style>
