<script lang="ts">
	import { pageText, type TextKey } from '#lib/utils/page-words.ts';

	const MAX_TITLE_LENGTH = 200;

	interface Props {
		value: string;
		onsave: (newValue: string) => Promise<void>;
		/** The key of the field's name, and of the name of the button that starts the edit. */
		labelKey: TextKey;
		editLabelKey: TextKey;
	}

	let { value, onsave, labelKey, editLabelKey }: Props = $props();

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
		if (saving) return;
		const trimmed = draft.trim();
		if (trimmed === value || !trimmed) {
			editing = false;
			return;
		}
		saving = true;
		try {
			await onsave(trimmed);
			editing = false;
		} catch {
			// The caller already surfaces the failure (e.g. a toast); leave
			// the field in edit mode with the draft intact so the user can fix it.
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
		maxlength={MAX_TITLE_LENGTH}
		aria-label={pageText(labelKey)}
		disabled={saving}
		onblur={commit}
		onkeydown={onKeyDown}
	/>
{:else}
	<button
		type="button"
		class="editable-title-display"
		onclick={startEdit}
		aria-label={pageText(editLabelKey)}
		title={pageText('editableTitle.hint')}
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
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}

	.editable-title-input {
		font: inherit;
		color: inherit;
		background: var(--surface, transparent);
		border: 1px solid var(--accent);
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
