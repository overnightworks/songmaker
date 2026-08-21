<script lang="ts">
	import { theme, toggleTheme } from '$lib/stores/ui';
</script>

<button class="theme-toggle" data-hitbox="frequent" onclick={toggleTheme} aria-label="Toggle theme">
	{$theme === 'dark' ? '☀' : '☾'}
</button>

<style>
	.theme-toggle {
		background: none;
		border: none;
		color: var(--text-muted);
		font-size: 1rem;
		line-height: 1;
	}

	.theme-toggle:hover {
		color: var(--text);
	}
</style>
