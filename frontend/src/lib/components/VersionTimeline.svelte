<script lang="ts">
	import type { VersionItem } from '$lib/api/types';

	interface Props {
		versions: VersionItem[];
		currentIndex: number;
		dirty?: boolean;
		onselect: (index: number) => void;
		ondiff: (pair: [VersionItem, VersionItem] | null) => void;
		ondelete?: (versionId: string, deleteGenerations: boolean) => void;
	}

	let { versions, currentIndex, dirty = false, onselect, ondiff, ondelete }: Props = $props();

	let diffAnchor: number | null = $state(null);
	let waitingForSecond = $state(false);
	let confirmDeleteId: string | null = $state(null);

	const sorted = $derived([...versions].reverse());
	const selectedVersionNum = $derived(versions[currentIndex]?.version_number ?? null);
	const selectedVersion = $derived(versions[currentIndex] ?? null);

	function handleDotClick(sortedIndex: number): void {
		const ver = sorted[sortedIndex];
		if (!ver) return;
		const origIndex = versions.findIndex((v) => v.id === ver.id);

		if (waitingForSecond && diffAnchor !== null && sortedIndex !== diffAnchor) {
			if (origIndex !== -1) onselect(origIndex);
			waitingForSecond = false;
			const anchorVer = sorted[diffAnchor];
			if (anchorVer) {
				const a = anchorVer.version_number;
				const b = ver.version_number;
				ondiff(a < b ? [anchorVer, ver] : [ver, anchorVer]);
			}
			return;
		}

		clearDiff();
		confirmDeleteId = null;
		if (origIndex !== -1) onselect(origIndex);
	}

	function handleDblClick(sortedIndex: number): void {
		if (diffAnchor === sortedIndex) {
			clearDiff();
			return;
		}
		diffAnchor = sortedIndex;
		waitingForSecond = true;
		ondiff(null);
	}

	function clearDiff(): void {
		diffAnchor = null;
		waitingForSecond = false;
		ondiff(null);
	}

	function isInDiffRange(sortedIndex: number): boolean {
		if (diffAnchor === null) return false;
		const currentSortedIndex = sorted.findIndex((v) => v.version_number === selectedVersionNum);
		if (currentSortedIndex === -1) return false;
		const lo = Math.min(diffAnchor, currentSortedIndex);
		const hi = Math.max(diffAnchor, currentSortedIndex);
		return sortedIndex >= lo && sortedIndex <= hi;
	}

	function handleDeleteClick(): void {
		if (!selectedVersion) return;
		confirmDeleteId = selectedVersion.id;
	}

	function handleDeleteConfirm(deleteGens: boolean): void {
		if (!confirmDeleteId || !ondelete) return;
		ondelete(confirmDeleteId, deleteGens);
		confirmDeleteId = null;
	}
</script>

<div class="timeline">
	<div class="track">
		<div class="line"></div>
		{#each sorted as ver, i (ver.id)}
			<div
				class="point-group"
				class:selected={ver.version_number === selectedVersionNum}
				class:anchor={i === diffAnchor}
				class:in-range={isInDiffRange(i)}
				class:latest={i === sorted.length - 1}
			>
				<button
					class="dot"
					onclick={() => handleDotClick(i)}
					ondblclick={() => handleDblClick(i)}
					title="v{ver.version_number}{i === sorted.length - 1
						? ' (latest)'
						: ''} — double-click to compare"
					aria-label="Version {ver.version_number}"
				></button>
				<span class="label">v{ver.version_number}</span>
			</div>
		{/each}
		{#if dirty}
			<div class="point-group dirty">
				<span class="dot dirty-dot"></span>
				<span class="label">*</span>
			</div>
		{/if}
	</div>

	<div class="actions-row">
		{#if diffAnchor !== null}
			<div class="diff-hint">
				{#if waitingForSecond}
					Click another version to compare
				{:else}
					Comparing v{sorted[diffAnchor]?.version_number}
				{/if}
				<button class="clear-diff" onclick={clearDiff} aria-label="Clear comparison">✕</button>
			</div>
		{/if}

		{#if selectedVersion && ondelete && confirmDeleteId === null}
			<button class="delete-version-btn" onclick={handleDeleteClick}>
				Delete v{selectedVersion.version_number}
			</button>
		{/if}
	</div>

	{#if confirmDeleteId && selectedVersion}
		<div class="delete-confirm">
			<span>Delete v{selectedVersion.version_number}?</span>
			<div class="delete-choices">
				<button class="choice keep" onclick={() => handleDeleteConfirm(false)}>
					Keep generations
				</button>
				<button class="choice destroy" onclick={() => handleDeleteConfirm(true)}>
					Delete all
				</button>
				<button class="choice cancel" onclick={() => (confirmDeleteId = null)}>Cancel</button>
			</div>
		</div>
	{/if}
</div>

<style>
	.timeline {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.track {
		position: relative;
		display: flex;
		align-items: center;
		gap: 0;
		padding: 8px 12px;
		background: var(--surface);
		border-radius: 4px;
		min-height: 40px;
	}

	.line {
		position: absolute;
		left: 20px;
		right: 20px;
		top: 50%;
		height: 2px;
		background: var(--border);
		transform: translateY(-50%);
		pointer-events: none;
	}

	.point-group {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 2px;
		z-index: 1;
		min-width: 24px;
	}

	.dot {
		width: 12px;
		height: 12px;
		border-radius: 50%;
		border: 2px solid var(--border);
		background: var(--bg);
		cursor: pointer;
		padding: 0;
		transition: all 0.15s;
	}

	.dot:hover {
		border-color: var(--text-muted);
		transform: scale(1.3);
	}

	.point-group.selected .dot {
		border-color: var(--primary);
		background: var(--primary);
		transform: scale(1.3);
	}

	.point-group.latest .dot {
		border-color: var(--accent);
	}

	.point-group.latest.selected .dot {
		border-color: var(--primary);
		background: var(--primary);
	}

	.point-group.anchor .dot {
		border-color: var(--accent);
		background: var(--accent);
		box-shadow: 0 0 6px var(--accent);
	}

	.point-group.in-range .dot {
		border-color: var(--accent);
	}

	.label {
		font-size: 8px;
		color: var(--text-dim);
		font-family: var(--font-display);
		letter-spacing: 0.5px;
	}

	.point-group.selected .label {
		color: var(--primary);
	}

	.point-group.anchor .label {
		color: var(--accent);
	}

	.point-group.dirty .label {
		color: var(--accent);
	}

	.dirty-dot {
		animation: pulse 1.5s ease-in-out infinite;
		border-color: var(--accent) !important;
		background: var(--accent) !important;
	}

	@keyframes pulse {
		0%,
		100% {
			opacity: 1;
		}
		50% {
			opacity: 0.3;
		}
	}

	.actions-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		min-height: 16px;
	}

	.diff-hint {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 10px;
		color: var(--accent);
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		padding: 0 4px;
	}

	.clear-diff {
		background: none;
		border: none;
		color: var(--text-dim);
		cursor: pointer;
		font-size: 11px;
		padding: 0 4px;
	}

	.clear-diff:hover {
		color: var(--text-muted);
	}

	.delete-version-btn {
		background: none;
		border: none;
		color: var(--text-dim);
		font-size: 9px;
		cursor: pointer;
		padding: 0 4px;
		margin-left: auto;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.delete-version-btn:hover {
		color: var(--score-bad);
	}

	.delete-confirm {
		display: flex;
		flex-direction: column;
		gap: 6px;
		padding: 8px 10px;
		background: var(--surface);
		border: 1px solid var(--score-bad);
		border-radius: 4px;
		font-size: 11px;
		color: var(--text-muted);
	}

	.delete-choices {
		display: flex;
		gap: 6px;
	}

	.choice {
		padding: 3px 10px;
		border-radius: 3px;
		font-size: 10px;
		cursor: pointer;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.choice.keep {
		background: none;
		border: 1px solid var(--accent);
		color: var(--accent);
	}

	.choice.keep:hover {
		background: var(--accent);
		color: #fff;
	}

	.choice.destroy {
		background: none;
		border: 1px solid var(--score-bad);
		color: var(--score-bad);
	}

	.choice.destroy:hover {
		background: var(--score-bad);
		color: #fff;
	}

	.choice.cancel {
		background: none;
		border: 1px solid var(--border);
		color: var(--text-dim);
	}

	.choice.cancel:hover {
		border-color: var(--text-muted);
		color: var(--text-muted);
	}
</style>
