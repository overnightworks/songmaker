<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { SIGN_IN_START_PATH } from '#lib/api/fetch.ts';
	import SignInCard from '#lib/components/SignInCard.svelte';
	import {
		SIGN_IN_FAILED_HEADING,
		SIGN_IN_FAILED_MESSAGE,
		SIGN_IN_RETRY_LABEL
	} from '#lib/constants/auth.ts';
</script>

<SignInCard heading={SIGN_IN_FAILED_HEADING} failure={SIGN_IN_FAILED_MESSAGE}>
	{#snippet actions()}
		<a class="sign-in-action primary" href={SIGN_IN_START_PATH} data-sveltekit-reload>
			{SIGN_IN_RETRY_LABEL}
		</a>
	{/snippet}
</SignInCard>
