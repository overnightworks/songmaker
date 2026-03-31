<script lang="ts">
	interface MenuItem {
		label: string;
		onclick: () => void;
		destructive?: boolean;
	}

	interface Props {
		items: MenuItem[];
		onclose?: () => void;
	}

	let { items, onclose }: Props = $props();
	let open = $state(false);
	let menuRef = $state<HTMLDivElement | null>(null);

	function toggle(): void {
		open = !open;
	}

	function handleClick(item: MenuItem): void {
		close();
		item.onclick();
	}

	function close(): void {
		open = false;
		onclose?.();
	}

	function handleClickOutside(event: MouseEvent): void {
		if (menuRef && !menuRef.contains(event.target as Node)) {
			close();
		}
	}

	$effect(() => {
		if (open) {
			document.addEventListener('click', handleClickOutside, true);
			return () => document.removeEventListener('click', handleClickOutside, true);
		}
	});
</script>

{#if items.length > 0}
	<div class="overflow-menu" bind:this={menuRef}>
		<button class="overflow-trigger" onclick={toggle} aria-label="More actions">
			&middot;&middot;&middot;
		</button>
		{#if open}
			<div class="overflow-dropdown">
				{#each items as item (item.label)}
					<button
						class="overflow-item"
						class:destructive={item.destructive}
						onclick={() => handleClick(item)}
					>
						{item.label}
					</button>
				{/each}
			</div>
		{/if}
	</div>
{/if}

<style>
	.overflow-menu {
		position: relative;
	}

	.overflow-trigger {
		background: none;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		color: var(--text-muted);
		font-size: 16px;
		letter-spacing: 2px;
		padding: 2px 8px;
		cursor: pointer;
		line-height: 1;
	}

	.overflow-trigger:hover {
		border-color: var(--primary);
		color: var(--text);
	}

	.overflow-dropdown {
		position: absolute;
		top: 100%;
		right: 0;
		margin-top: 4px;
		min-width: 160px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
		z-index: 100;
		display: flex;
		flex-direction: column;
		padding: 4px 0;
	}

	.overflow-item {
		background: none;
		border: none;
		padding: 8px 14px;
		color: var(--text-light);
		font-size: 12px;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: var(--btn-letter-spacing);
		text-align: left;
		cursor: pointer;
		white-space: nowrap;
	}

	.overflow-item:hover {
		background: var(--surface-hover);
		color: var(--text);
	}

	.overflow-item.destructive {
		color: var(--score-bad);
	}

	.overflow-item.destructive:hover {
		background: rgba(255, 68, 68, 0.1);
	}
</style>
