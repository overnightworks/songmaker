<script lang="ts">
	import Icon from './Icon.svelte';

	let {
		icon,
		activeIcon,
		label,
		active = false,
		destructive = false,
		confirm = false,
		showLabel = false,
		disabled = false,
		onclick
	}: {
		icon: string;
		activeIcon?: string;
		label: string;
		active?: boolean;
		destructive?: boolean;
		confirm?: boolean;
		showLabel?: boolean;
		disabled?: boolean;
		onclick: () => void;
	} = $props();

	let confirming = $state(false);
	let confirmTimeout: ReturnType<typeof setTimeout> | undefined = $state(undefined);
	let buttonEl = $state<HTMLButtonElement | null>(null);

	const displayedIcon = $derived(confirming ? 'check' : active && activeIcon ? activeIcon : icon);

	function handleClick() {
		if (disabled) return;

		if (!confirm) {
			onclick();
			return;
		}

		if (confirming) {
			clearTimeout(confirmTimeout);
			confirmTimeout = undefined;
			confirming = false;
			onclick();
		} else {
			confirming = true;
			confirmTimeout = setTimeout(() => {
				confirming = false;
				confirmTimeout = undefined;
			}, 3000);
		}
	}

	function handleClickOutside(event: MouseEvent) {
		if (confirming && event.target instanceof Node && !buttonEl?.contains(event.target)) {
			confirming = false;
			clearTimeout(confirmTimeout);
			confirmTimeout = undefined;
		}
	}

	$effect(() => {
		if (confirming) {
			document.addEventListener('click', handleClickOutside);
		}

		return () => {
			document.removeEventListener('click', handleClickOutside);
		};
	});

	$effect(() => {
		return () => {
			if (confirmTimeout) clearTimeout(confirmTimeout);
		};
	});
</script>

<button
	bind:this={buttonEl}
	class="action-btn"
	class:active
	class:destructive
	class:confirming
	title={label}
	aria-label={label}
	{disabled}
	onclick={handleClick}
>
	<Icon name={displayedIcon} size={14} />
	{#if showLabel}
		<span>{label}</span>
	{/if}
</button>

<style>
	.action-btn {
		display: flex;
		align-items: center;
		gap: 0.3rem;
		background: none;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		padding: 0.25rem 0.5rem;
		cursor: pointer;
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: var(--label-font-size, 0.8rem);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		transition:
			border-color 0.2s,
			color 0.2s;
	}

	.action-btn:has(span) {
		padding: 0.25rem 0.6rem;
	}

	.action-btn:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.action-btn.active {
		border-color: var(--accent);
		color: var(--accent);
		background: rgba(160, 32, 240, 0.1);
	}

	.action-btn.destructive:hover {
		border-color: var(--score-bad);
		color: var(--score-bad);
	}

	.action-btn.confirming {
		border-color: var(--score-bad);
		color: var(--score-bad);
		background: rgba(255, 68, 68, 0.1);
	}

	.action-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	span {
		white-space: nowrap;
	}
</style>
