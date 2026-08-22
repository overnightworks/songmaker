<script lang="ts">
	import ThemeToggle from '../ThemeToggle.svelte';

	let { username, onlogout }: { username: string; onlogout: () => void } = $props();
</script>

<div class="user-row">
	<span class="username">{username}</span>
	<ThemeToggle />
	<button class="logout" onclick={onlogout}>Logout</button>
</div>

<style>
	.user-row {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 8px 16px;
	}

	.username {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 0.85rem;
		color: var(--text);
	}

	.logout {
		flex-shrink: 0;
		background: none;
		border: none;
		color: var(--text-muted);
		font-size: 0.75rem;
	}

	.logout:hover {
		color: var(--score-bad);
	}
</style>
