<script lang="ts">
	import { tick } from 'svelte';
	import {
		isDirty,
		setAsideVersionLoadUndo,
		versionDeleteEditorLoss,
		versionDeleteRequest,
		versions
	} from '$lib/stores/editor';
	import { historyLayerState } from '$lib/stores/layers';
	import { focusFirstIn, handleFocusTrapKeydown, refocusIfDropped } from '$lib/utils/focus-trap';
	import { activityTimeLabel } from '$lib/utils/format';
	import { isSungLine } from '$lib/utils/lyrics-align';
	import type { SongItem, VersionItem } from '$lib/api/types';
	import {
		VERSION_CURRENT_TAG,
		VERSION_NO_LYRICS,
		VERSION_PICKED_LABEL,
		VERSIONS_SHEET_CLOSE_LABEL,
		VERSIONS_SHEET_LABEL,
		versionChipLabel,
		versionDeleteLabel,
		versionLabel,
		versionTakesLabel,
		versionsChipAccessibleLabel
	} from '$lib/constants';
	import { takeVersion } from '$lib/constants/now-playing';
	import Icon from '../Icon.svelte';

	interface Props {
		song: SongItem;
		/** Loads the version as the draft; answers whether it loaded, the sheet closing only then. */
		onload: (versionId: string) => Promise<boolean>;
	}

	let { song, onload }: Props = $props();

	interface VersionTakes {
		count: number;
		holdsPick: boolean;
	}

	interface VersionRow {
		version: VersionItem;
		takes: VersionTakes;
		when: string;
		firstLine: string;
	}

	const POPOVER_WIDTH_PX = 340;
	const VIEWPORT_MARGIN_PX = 8;
	const CHIP_GAP_PX = 8;

	const open = historyLayerState('versions-sheet', false);
	let chip: HTMLButtonElement | undefined = $state();
	let panel: HTMLDivElement | undefined = $state();
	let popoverTop = $state(0);
	let popoverLeft = $state(0);

	const latest = $derived<VersionItem | null>($versions[0] ?? null);
	const chipLabel = $derived(latest ? versionChipLabel(latest.version_number, $isDirty) : '');

	const NO_TAKES: VersionTakes = { count: 0, holdsPick: false };

	function takesByVersion(): Record<number, VersionTakes> {
		const byVersion: Record<number, VersionTakes> = {};
		for (const take of song.generations) {
			const origin = takeVersion(take.version_id, take.version_number);
			if (!origin) continue;
			const takes = byVersion[origin.versionNumber] ?? NO_TAKES;
			byVersion[origin.versionNumber] = {
				count: takes.count + 1,
				holdsPick: takes.holdsPick || take.is_picked
			};
		}
		return byVersion;
	}

	const rows = $derived.by((): VersionRow[] => {
		const takes = takesByVersion();
		const now = new Date();
		return $versions.map((version) => ({
			version,
			takes: takes[version.version_number] ?? NO_TAKES,
			when: activityTimeLabel(version.created_at, now),
			firstLine: version.lyrics.split('\n').find(isSungLine)?.trim() ?? VERSION_NO_LYRICS
		}));
	});

	let wasOpen = false;
	$effect(() => {
		const isOpen = $open;
		if (wasOpen && !isOpen) refocusIfDropped(chip);
		wasOpen = isOpen;
	});

	// The editor body is a size container, and so the containing block of
	// every fixed box inside it: the backdrop would dim only the editor and the
	// popover would scroll and clip with it. The layer stands in the document
	// body instead. It must stay its block's only node, which Svelte removes.
	function standInDocumentBody(layer: HTMLElement): () => void {
		document.body.append(layer);
		return () => layer.remove();
	}

	// The desktop popover stands in the viewport under the chip, so the editor
	// column's own scroll box cannot clip it; the phone sheet ignores this.
	function placeUnderChip(): void {
		if (!chip) return;
		const anchor = chip.getBoundingClientRect();
		const lastLeft = window.innerWidth - VIEWPORT_MARGIN_PX - POPOVER_WIDTH_PX;
		popoverTop = anchor.bottom + CHIP_GAP_PX;
		popoverLeft = Math.max(VIEWPORT_MARGIN_PX, Math.min(anchor.left, lastLeft));
	}

	async function openSheet(): Promise<void> {
		setAsideVersionLoadUndo();
		placeUnderChip();
		$open = true;
		await tick();
		if (panel) focusFirstIn(panel);
	}

	async function choose(version: VersionItem): Promise<void> {
		if (await onload(version.id)) $open = false;
	}

	function askToDelete(row: VersionRow): void {
		versionDeleteRequest.set({
			songId: song.id,
			version: row.version,
			takeCount: row.takes.count,
			holdsPick: row.takes.holdsPick,
			editorLoss: versionDeleteEditorLoss(row.version)
		});
	}

	// A deleted row takes the focus with it; the open list keeps it.
	$effect(() => {
		if (rows.length > 0 && $open && panel) refocusIfDropped(panel);
	});

	function onPanelKeydown(event: KeyboardEvent): void {
		if (panel) handleFocusTrapKeydown(panel, event);
	}
</script>

<svelte:window onresize={() => $open && placeUnderChip()} />

{#if latest}
	<span class="versions">
		<button
			bind:this={chip}
			type="button"
			class="version-chip"
			class:draft={$isDirty}
			data-hitbox="text"
			aria-haspopup="dialog"
			aria-expanded={$open}
			aria-label={versionsChipAccessibleLabel(chipLabel)}
			onclick={() => ($open ? ($open = false) : void openSheet())}
		>
			<span class="chip-face">
				<span class="chip-text">{chipLabel}</span>
				<Icon name="chevron-down" size={14} />
			</span>
		</button>
		{#if $open}
			<div class="versions-layer" {@attach standInDocumentBody}>
				<button
					type="button"
					class="versions-backdrop"
					tabindex="-1"
					aria-label={VERSIONS_SHEET_CLOSE_LABEL}
					onclick={() => ($open = false)}
				></button>
				<div
					bind:this={panel}
					class="versions-panel"
					role="dialog"
					aria-modal="true"
					aria-label={VERSIONS_SHEET_LABEL}
					tabindex="-1"
					style:--popover-top="{popoverTop}px"
					style:--popover-left="{popoverLeft}px"
					style:--popover-width="{POPOVER_WIDTH_PX}px"
					onkeydown={onPanelKeydown}
				>
					<div class="versions-head">
						<span class="versions-title">{VERSIONS_SHEET_LABEL}</span>
						<button
							type="button"
							class="versions-close"
							data-hitbox="frequent"
							aria-label={VERSIONS_SHEET_CLOSE_LABEL}
							onclick={() => ($open = false)}
						>
							<Icon name="x" size={18} />
						</button>
					</div>
					<ul class="versions-list">
						{#each rows as row (row.version.id)}
							{@const isCurrent = row.version.id === latest.id}
							<li class="version-item" class:current={isCurrent}>
								<button type="button" class="version-row" onclick={() => void choose(row.version)}>
									<span class="version-number">{versionLabel(row.version.version_number)}</span>
									<span class="version-lines">
										<span class="version-takes">
											{versionTakesLabel(row.takes.count)}
											{#if row.takes.holdsPick}
												· ★ {VERSION_PICKED_LABEL}
											{/if}
											{#if isCurrent}<span class="version-current">{VERSION_CURRENT_TAG}</span>{/if}
										</span>
										<span class="version-meta">
											{row.when} · {row.firstLine}
										</span>
									</span>
								</button>
								<button
									type="button"
									class="version-delete"
									data-hitbox="frequent"
									aria-label={versionDeleteLabel(row.version.version_number)}
									onclick={() => askToDelete(row)}
								>
									<Icon name="trash" size={16} />
								</button>
							</li>
						{/each}
					</ul>
				</div>
			</div>
		{/if}
	</span>
{/if}

<style>
	.versions {
		display: inline-flex;
	}

	/* The chip draws 24px but answers on the whole touch-height box around it. */
	.version-chip {
		display: inline-flex;
		align-items: center;
		padding: 0;
		background: none;
		border: none;
		color: var(--text);
		font-family: var(--font-body);
		font-size: 0.74rem;
		text-transform: none;
		letter-spacing: 0;
		cursor: pointer;
	}

	.chip-face {
		display: inline-flex;
		align-items: center;
		gap: 0.2rem;
		height: 24px;
		padding: 0 0.35rem 0 0.5rem;
		border: 1px solid var(--border);
		border-radius: 12px;
		background: var(--surface);
	}

	.chip-face :global(svg) {
		color: var(--text-subtle);
	}

	.version-chip:hover .chip-face,
	.version-chip[aria-expanded='true'] .chip-face {
		border-color: var(--accent);
	}

	.version-chip.draft .chip-text {
		color: var(--accent);
	}

	.versions-backdrop {
		position: fixed;
		inset: 0;
		z-index: 300;
		width: 100%;
		border: 0;
		background: none;
		cursor: default;
	}

	.versions-panel {
		position: fixed;
		top: var(--popover-top);
		left: var(--popover-left);
		z-index: 301;
		width: var(--popover-width);
		--version-row-height: calc(3.75rem + 1px);
		--versions-room: min(60vh, 28rem);
		display: flex;
		flex-direction: column;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		box-shadow: 0 6px 24px rgba(0, 0, 0, 0.18);
		text-transform: none;
		letter-spacing: 0;
		font-family: var(--font-body);
	}

	.versions-head {
		display: flex;
		align-items: center;
		padding: 0.2rem 0.25rem 0.4rem 1rem;
	}

	.versions-title {
		flex: 1;
		font-family: var(--font-display);
		font-size: 1rem;
		letter-spacing: 0.4px;
		color: var(--text);
	}

	.versions-close {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		background: none;
		border: none;
		color: var(--text-muted);
	}

	/* The list shows whole rows only and comes to rest on a row's top edge,
	   so no row stands half hidden under the head with its glyphs cut. The
	   first max-height is for a browser without round(). */
	.versions-list {
		margin: 0;
		padding: 0;
		list-style: none;
		overflow-y: auto;
		scroll-snap-type: y mandatory;
		max-height: calc(var(--versions-room) - 3.5rem);
		max-height: round(down, calc(var(--versions-room) - 3.5rem), var(--version-row-height));
	}

	.version-item {
		display: flex;
		align-items: center;
		height: var(--version-row-height);
		padding-right: 0.25rem;
		border-top: 1px solid var(--border);
		scroll-snap-align: start;
	}

	.version-item.current {
		background: color-mix(in srgb, var(--accent) 5%, var(--surface));
	}

	.version-row {
		flex: 1;
		min-width: 0;
		display: flex;
		align-items: center;
		gap: 0.6rem;
		align-self: stretch;
		padding: 0.35rem 0.25rem 0.35rem 1rem;
		background: none;
		border: none;
		color: var(--text);
		text-align: left;
		cursor: pointer;
	}

	.version-row:hover {
		background: var(--surface-hover);
	}

	.version-delete {
		background: none;
		border: none;
		color: var(--text-subtle);
	}

	.version-delete:hover {
		color: var(--score-bad);
	}

	.version-number {
		flex: none;
		width: 2.1rem;
		font-family: var(--font-display);
		font-size: 1.05rem;
	}

	.version-item.current .version-number {
		color: var(--accent);
	}

	.version-lines {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 0.1rem;
	}

	.version-takes,
	.version-meta {
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.version-takes {
		font-size: 0.86rem;
	}

	.version-meta {
		font-size: 0.74rem;
		color: var(--text-subtle);
	}

	.version-current {
		margin-left: 0.3rem;
		padding: 0 0.35rem;
		border: 1px solid var(--accent);
		border-radius: 8px;
		color: var(--accent);
		font-size: 0.68rem;
	}

	/* A phone opens the list as a sheet along the screen's bottom edge; a
	   wider window keeps it as a popover under the chip. The sheet dims the
	   page as the phone's rail drawer does: the picture's light grey left the
	   dark theme undimmed. */
	@media (max-width: 768px) {
		.versions-backdrop {
			background: color-mix(in srgb, #000 42%, transparent);
		}

		.versions-panel {
			top: auto;
			left: 0;
			right: 0;
			bottom: 0;
			width: auto;
			--versions-room: 70vh;
			padding-bottom: calc(10px + env(safe-area-inset-bottom, 0px));
			border-radius: 14px 14px 0 0;
			box-shadow: 0 -10px 30px rgba(0, 0, 0, 0.18);
		}
	}
</style>
