<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { afterNavigate, goto } from '$app/navigation';
	import { navigating } from '$app/state';
	import { historyComesToRest, standingPageEntryId } from '#lib/history/historyController.ts';
	import Icon from '#lib/components/Icon.svelte';
	import { APP_NAME, RAIL_SETTINGS_LABEL, SETTINGS_NAV_LABEL } from '#lib/constants.ts';
	import { visibleSettingsSections } from '#lib/settingsSections.ts';
	import { isAdmin } from '#lib/stores/auth.ts';
	import { subscribeCompactLayout } from '#lib/utils/compact-layout.ts';

	let compact = $state<boolean | null>(null);

	const admin = $derived($isAdmin);
	const sections = $derived(visibleSettingsSections(admin));

	$effect(() =>
		subscribeCompactLayout((isCompact) => {
			compact = isCompact;
		})
	);

	const railListsSections = $derived(compact === false);

	// The redirect starts once this page's own navigation has landed and the
	// root layout has stamped it. The root layout holds this page back until the
	// session is known, so the page usually mounts after the router's start has
	// landed and `afterNavigate` never reports it: that start is landed when
	// nothing navigates and its entry has its id. A navigation still under way
	// reports through `afterNavigate`, in the run where the layout stamps it.
	let landed = $state(navigating.to === null && standingPageEntryId() !== null);
	afterNavigate(() => {
		landed = true;
	});

	$effect(() => {
		if (!railListsSections || !landed) return;
		const [firstVisible] = sections;
		let left = false;
		void historyComesToRest().then(() => {
			if (!left) goto(firstVisible.href, { replace: true });
		});
		return () => {
			left = true;
		};
	});
</script>

<svelte:head>
	<title>{RAIL_SETTINGS_LABEL} — {APP_NAME}</title>
</svelte:head>

{#if compact}
	<h1 class="settings-index-title">{RAIL_SETTINGS_LABEL}</h1>
	<nav aria-label={SETTINGS_NAV_LABEL}>
		<ul class="settings-list">
			{#each sections as section (section.href)}
				<li>
					<a href={section.href} class="settings-row">
						<Icon name={section.icon} size={20} class="settings-row-icon" />
						<span class="settings-row-label">{section.label}</span>
						<Icon name="chevron-right" class="settings-row-chevron" />
					</a>
				</li>
			{/each}
		</ul>
	</nav>
{/if}

<style>
	.settings-index-title {
		margin: 0 0 0.5rem;
		font-family: var(--font-display);
		font-size: 1.4rem;
		font-weight: 400;
		letter-spacing: 1px;
		text-transform: uppercase;
		color: var(--text);
	}

	.settings-list {
		list-style: none;
		margin: 0;
		padding: 0;
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		background: var(--surface);
		overflow: hidden;
	}

	.settings-list li + li {
		border-top: 1px solid var(--border);
	}

	.settings-row {
		display: flex;
		align-items: center;
		gap: 10px;
		min-height: 52px;
		padding: 0 12px 0 14px;
		color: var(--text);
		font-size: 0.93rem;
		text-decoration: none;
	}

	.settings-row:hover {
		background: var(--surface-hover);
	}

	.settings-row :global(.settings-row-icon),
	.settings-row :global(.settings-row-chevron) {
		flex: none;
		color: var(--text-muted);
	}

	.settings-row-label {
		flex: 1;
		min-width: 0;
	}
</style>
