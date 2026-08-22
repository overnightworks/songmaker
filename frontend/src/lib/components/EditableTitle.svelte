<script lang="ts">
	interface Props {
		value: string;
		onsave: (newTitle: string) => Promise<void>;
		ariaLabel?: string;
	}

	let { value, onsave, ariaLabel = 'Title' }: Props = $props();

	let editing = $state(false);
	let draft = $state('');
	let saving = $state(false);
	let inputEl = $state<HTMLInputElement | null>(null);

	export function startEdit(): void {
		if (saving) return;
		draft = value;
		editing = true;
		queueMicrotask(() => {
			inputEl?.focus();
			inputEl?.select();
		});
	}

	async function commit(): Promise<void> {
		const trimmed = draft.trim();
		if (!trimmed || trimmed === value) {
			editing = false;
			return;
		}
		saving = true;
		try {
			await onsave(trimmed);
			editing = false;
		} finally {
			saving = false;
		}
	}

	function cancel(): void {
		editing = false;
	}

	function onKeyDown(e: KeyboardEvent): void {
		if (e.key === 'Enter') {
			e.preventDefault();
			commit();
		} else if (e.key === 'Escape') {
			e.preventDefault();
			cancel();
		}
	}
</script>

{#if editing}
	<input
		bind:this={inputEl}
		bind:value={draft}
		class="editable-title-input"
		type="text"
		maxlength="200"
		aria-label={ariaLabel}
		disabled={saving}
		onblur={commit}
		onkeydown={onKeyDown}
	/>
{:else}
	<button
		type="button"
		class="editable-title-display"
		onclick={startEdit}
		aria-label={`Edit ${ariaLabel.toLowerCase()}`}
		title="Click to rename"
	>
		{value}
	</button>
{/if}

<style>
	.editable-title-display {
		all: unset;
		cursor: text;
		font: inherit;
		color: inherit;
		display: inline-block;
		padding: 2px 4px;
		margin: -2px -4px;
		border-radius: 4px;
		border: 1px solid transparent;
	}

	.editable-title-display:hover {
		background: var(--surface-hover, rgba(255, 255, 255, 0.04));
		border-color: var(--border, rgba(255, 255, 255, 0.1));
	}

	.editable-title-display:focus-visible {
		outline: 2px solid var(--accent, #a020f0);
		outline-offset: 2px;
	}

	.editable-title-input {
		font: inherit;
		color: inherit;
		background: var(--surface, transparent);
		border: 1px solid var(--accent, #a020f0);
		border-radius: 4px;
		padding: 2px 4px;
		margin: -3px -5px;
		width: 100%;
		max-width: 100%;
		box-sizing: border-box;
	}

	.editable-title-input:disabled {
		opacity: 0.6;
	}
</style>
