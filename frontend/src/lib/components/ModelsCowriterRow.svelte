<script lang="ts">
	import type { Snippet } from 'svelte';
	import { onMount } from 'svelte';
	import { fetchCowriterOffer } from '$lib/api/client';
	import { signInAddress } from '$lib/api/fetch';
	import type { CowriterOfferResponse } from '$lib/api/types';
	import {
		COWRITER_PROVIDER_LABEL,
		MODELS_STATUS_CHECKING_LABEL,
		MODELS_TASK_COWRITER_LABEL
	} from '$lib/constants';
	import ModelsServiceRow from './ModelsServiceRow.svelte';

	type OfferState = CowriterOfferResponse['state'];
	type Status = {
		text: string;
		tone: 'ok' | 'plain' | 'off' | 'warn';
		signIn?: boolean;
		warning?: string;
	};

	const MODELS_TAB_ADDRESS = '/settings/users?tab=models';
	const CHECKING: Status = { text: MODELS_STATUS_CHECKING_LABEL, tone: 'off' };
	const STATUS_OF_STATE: Record<OfferState, Status> = {
		ready: { text: 'Ready', tone: 'ok' },
		not_built: { text: 'Not set up in the service', tone: 'off' },
		no_longer_offered: {
			text: '',
			tone: 'plain',
			warning: 'No longer offered by the agent service'
		},
		not_reachable: { text: "The agent service's offer is not reachable", tone: 'plain' },
		not_available: { text: 'Not available for you', tone: 'off' },
		sign_in_again: { text: 'Sign in again to check the offer', tone: 'warn', signIn: true }
	};

	interface Props {
		model: string;
		advanced: Snippet;
	}

	let { model, advanced }: Props = $props();

	let offer = $state<CowriterOfferResponse | null>(null);
	let unreachable = $state(false);

	onMount(async () => {
		try {
			offer = await fetchCowriterOffer();
		} catch {
			unreachable = true;
		}
	});

	const status = $derived(
		offer ? STATUS_OF_STATE[offer.state] : unreachable ? STATUS_OF_STATE.not_reachable : CHECKING
	);
</script>

<ModelsServiceRow
	task={MODELS_TASK_COWRITER_LABEL}
	provider={COWRITER_PROVIDER_LABEL}
	route="Agent service"
	model={offer?.model ?? model}
	status={status.text}
	statusTone={status.tone}
	statusLink={status.signIn
		? { href: signInAddress(MODELS_TAB_ADDRESS), text: 'Sign in' }
		: undefined}
	modelWarning={status.warning}
	note="Grok, Codex: not selectable yet"
	{advanced}
/>
