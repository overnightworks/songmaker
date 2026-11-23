<script lang="ts">
	import Icon from './Icon.svelte';

	interface Props {
		label: string;
		/** The word that confirms the state, already in the person's language. */
		hint: string;
		iconName: string;
		isShared: boolean;
		busy: boolean;
	}

	let { label, hint, iconName, isShared, busy }: Props = $props();
</script>

{#if busy}<span class="share-ring ring-turn" aria-hidden="true"></span>{:else}<Icon
		name={iconName}
		size={14}
	/>{/if}
{label}
<span class="menu-item-hint" aria-hidden="true">
	{#if isShared && !busy}<span class="shared-check">
			<Icon name="check" size={12} />
		</span>{/if}{hint}
</span>

<style>
	.share-ring {
		flex: none;
		box-sizing: border-box;
		width: 14px;
		height: 14px;
		border: 2px solid currentColor;
		border-right-color: transparent;
		border-radius: 50%;
		--ring-turn: 0.8s;
	}

	.shared-check {
		display: inline-flex;
		vertical-align: middle;
	}
</style>
