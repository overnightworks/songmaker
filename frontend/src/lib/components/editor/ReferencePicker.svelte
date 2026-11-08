<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import type { Snippet } from 'svelte';
	import { describeFailure } from '#lib/api/fetch.ts';
	import { listReferences, uploadReference } from '#lib/api/references.ts';
	import type { ReferenceListRowResponse, ReferenceResponse } from '#lib/api/types.ts';
	import Icon from '#lib/components/Icon.svelte';
	import LoadFailure from '#lib/components/LoadFailure.svelte';
	import ReferenceExpiry from '#lib/components/ReferenceExpiry.svelte';
	import {
		REFERENCE_AUDIO_ACCEPT,
		TRANSPORT_PAUSE_LABEL,
		TRANSPORT_PLAY_LABEL
	} from '#lib/constants.ts';
	import {
		RECIPE_REFERENCE_ALL_LABEL,
		RECIPE_REFERENCE_LABEL,
		RECIPE_REFERENCE_LOAD_ERROR,
		RECIPE_REFERENCE_LOADING,
		RECIPE_REFERENCE_NONE_LABEL,
		RECIPE_REFERENCE_PLAY_ERROR,
		RECIPE_REFERENCE_UPLOAD,
		RECIPE_REFERENCE_UPLOAD_ERROR,
		RECIPE_REFERENCE_UPLOADING,
		RECIPE_RETRY_LABEL
	} from '#lib/constants/recipe.ts';
	import { createReferencePreview } from '#lib/services/referencePreview.svelte.ts';
	import { followAppPageLink } from '#lib/stores/navigation.ts';
	import { historyLayerState } from '#lib/stores/layers.ts';
	import { refocusIfDropped } from '#lib/utils/focus-trap.ts';
	import { formatTime } from '#lib/utils/format.ts';

	const REFERENCES_PATH = '/settings/references';
	const CHOICE_GROUP = 'reference-choice';

	let {
		reference,
		onchange,
		trailing
	}: {
		reference: ReferenceResponse | null;
		onchange: (next: ReferenceResponse | null) => void;
		trailing?: Snippet;
	} = $props();

	const open = historyLayerState('reference-picker', false);
	const preview = createReferencePreview(() => (playFault = RECIPE_REFERENCE_PLAY_ERROR));

	let references = $state<ReferenceListRowResponse[]>([]);
	let loaded = $state(false);
	let loadFailure = $state<string | null>(null);
	let now = $state(new Date());
	let uploading = $state(false);
	let uploadError = $state<string | null>(null);
	let playFault = $state<string | null>(null);
	let triggerButton: HTMLButtonElement | undefined = $state();

	async function load(): Promise<void> {
		loadFailure = null;
		try {
			references = (await listReferences()).references;
			loaded = true;
			now = new Date();
		} catch (error) {
			loadFailure = describeFailure(error, RECIPE_REFERENCE_LOAD_ERROR);
		}
	}

	let wasOpen = false;
	$effect(() => {
		const isOpen = $open;
		if (isOpen && !wasOpen) {
			playFault = null;
			void load();
		}
		if (!isOpen && wasOpen) {
			if (preview.activeId !== null) preview.toggle(preview.activeId);
			refocusIfDropped(triggerButton);
		}
		wasOpen = isOpen;
	});

	function choose(next: ReferenceListRowResponse | null): void {
		onchange(next ? { id: next.id, filename: next.filename } : null);
	}

	async function attach(event: Event): Promise<void> {
		const input = event.currentTarget as HTMLInputElement;
		const file = input.files?.[0];
		if (!file) return;
		uploading = true;
		uploadError = null;
		try {
			const result = await uploadReference(file);
			onchange({ id: result.id, filename: result.filename });
			await load();
		} catch (error) {
			uploadError = describeFailure(error, RECIPE_REFERENCE_UPLOAD_ERROR);
		} finally {
			uploading = false;
			input.value = '';
		}
	}
</script>

<div class="kv" class:open={$open} data-field="reference">
	<span class="k">{RECIPE_REFERENCE_LABEL}</span>
	<span class="v">
		<button
			bind:this={triggerButton}
			type="button"
			class="trigger"
			aria-expanded={$open}
			aria-controls="reference-picker-options"
			aria-label={`${RECIPE_REFERENCE_LABEL}: ${reference?.filename ?? RECIPE_REFERENCE_NONE_LABEL}`}
			onclick={() => ($open = !$open)}
		>
			<span class="name">{reference?.filename ?? RECIPE_REFERENCE_NONE_LABEL}</span>
			<Icon name={$open ? 'chevron-up' : 'chevron-down'} size={16} />
		</button>
		{@render trailing?.()}
	</span>
</div>
{#if $open}
	<div class="picker" id="reference-picker-options">
		<ul class="choices">
			<li class="po" class:on={reference === null}>
				<input
					type="radio"
					name={CHOICE_GROUP}
					id="reference-choice-none"
					checked={reference === null}
					onchange={() => choose(null)}
				/>
				<label class="fn" for="reference-choice-none">{RECIPE_REFERENCE_NONE_LABEL}</label>
			</li>
			{#each references as row (row.id)}
				{@const playing = preview.activeId === row.id}
				<li class="po" class:on={reference?.id === row.id}>
					<input
						type="radio"
						name={CHOICE_GROUP}
						id={`reference-choice-${row.id}`}
						checked={reference?.id === row.id}
						onchange={() => choose(row)}
					/>
					<button
						type="button"
						class="face"
						aria-label={`${playing ? TRANSPORT_PAUSE_LABEL : TRANSPORT_PLAY_LABEL} ${row.filename}`}
						onclick={() => preview.toggle(row.id)}
					>
						<Icon name={playing ? 'pause' : 'play'} size={12} />
					</button>
					<label class="fn" for={`reference-choice-${row.id}`}>{row.filename}</label>
					{#if row.deletes_at !== null}<ReferenceExpiry deletesAt={row.deletes_at} {now} />{/if}
					{#if row.duration_sec !== null}<small>{formatTime(row.duration_sec)}</small>{/if}
				</li>
			{/each}
			{#if !loaded && loadFailure === null}
				<li class="quiet">{RECIPE_REFERENCE_LOADING}</li>
			{/if}
			{#if loadFailure !== null}
				<li class="failure">
					<LoadFailure message={loadFailure} retryLabel={RECIPE_RETRY_LABEL} onretry={load} />
				</li>
			{/if}
			<li class="po up">
				<label class="upload"
					><Icon name="arrow-up" size={16} />{uploading
						? RECIPE_REFERENCE_UPLOADING
						: RECIPE_REFERENCE_UPLOAD}<input
						type="file"
						accept={REFERENCE_AUDIO_ACCEPT}
						disabled={uploading}
						onchange={attach}
					/></label
				>
			</li>
			<li class="po more">
				<a href={REFERENCES_PATH} onclick={(event) => followAppPageLink(event, REFERENCES_PATH)}
					>{RECIPE_REFERENCE_ALL_LABEL}<Icon name="chevron-right" size={16} /></a
				>
			</li>
		</ul>
		{#if playFault}<p class="error" role="alert">{playFault}</p>{/if}
	</div>
{/if}
{#if uploadError}<p class="error" role="alert">{uploadError}</p>{/if}

<style>
	.kv {
		display: flex;
		align-items: center;
		gap: var(--row-gap);
		min-height: var(--hitbox-frequent);
		padding: 0 var(--row-padding);
		border-bottom: 1px solid var(--border);
	}

	.kv.open {
		background: var(--surface-hover, var(--bg));
	}

	.k {
		flex: 1;
		min-width: 0;
		color: var(--text-muted);
		font-size: var(--label-font-size);
	}

	.v {
		display: inline-flex;
		align-items: center;
		justify-content: flex-end;
		gap: var(--row-gap);
		min-width: 0;
	}

	.trigger {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		min-width: 0;
		min-height: var(--hitbox-frequent);
		padding: 0;
		border: none;
		background: none;
		color: var(--text);
		font-size: var(--label-font-size);
		cursor: pointer;
	}

	.name {
		min-width: 0;
		max-width: 12rem;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.picker {
		border-bottom: 1px solid var(--border);
		background: var(--bg);
	}

	.choices {
		margin: 0;
		padding: 0;
		list-style: none;
		max-height: 18rem;
		overflow-y: auto;
	}

	.po {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		min-height: var(--hitbox-frequent);
		padding: 0 0.65rem 0 0.9rem;
		font-size: var(--label-font-size);
	}

	.po .fn {
		flex: 1;
		min-width: 0;
		overflow-wrap: anywhere;
		cursor: pointer;
	}

	.po.on .fn {
		color: var(--accent);
	}

	.po small {
		color: var(--text-muted);
		font-variant-numeric: tabular-nums;
	}

	.po input[type='radio'] {
		appearance: none;
		flex: none;
		width: 1rem;
		height: 1rem;
		margin: 0;
		border: 1.5px solid var(--text-subtle);
		border-radius: 50%;
		cursor: pointer;
	}

	.po input[type='radio']:checked {
		border-color: var(--accent);
		background: radial-gradient(circle, var(--accent) 45%, transparent 50%);
	}

	.po input[type='radio']:focus-visible,
	.face:focus-visible,
	.trigger:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}

	.face {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex: none;
		width: 1.75rem;
		height: 1.75rem;
		padding: 0;
		border: 1px solid var(--border);
		border-radius: 50%;
		background: none;
		color: var(--text);
		cursor: pointer;
	}

	.up,
	.more {
		color: var(--accent);
	}

	.upload {
		display: inline-flex;
		align-items: center;
		gap: 0.5rem;
		flex: 1;
		min-height: var(--hitbox-frequent);
		cursor: pointer;
	}

	.upload input {
		display: none;
	}

	.more {
		justify-content: flex-end;
		border-top: 1px solid var(--border);
	}

	.more a {
		display: inline-flex;
		align-items: center;
		color: inherit;
		text-decoration: none;
	}

	.quiet {
		padding: 0.5rem 0.9rem;
		color: var(--text-muted);
		font-size: var(--label-font-size);
	}

	.error {
		margin: 0;
		padding: var(--row-padding);
		color: var(--fail);
		font-size: var(--label-font-size);
	}

	@media (max-width: 500px) {
		.po small {
			display: none;
		}
	}
</style>
