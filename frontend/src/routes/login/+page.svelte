<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { SIGN_IN_START_PATH } from '#lib/api/fetch.ts';
	import SignInCard from '#lib/components/SignInCard.svelte';
	import { SIGN_IN_ACTION_LABEL, SIGNED_OUT_HEADING } from '#lib/constants/auth.ts';
</script>

<SignInCard heading={SIGNED_OUT_HEADING}>
	{#snippet actions()}
		<!-- A full navigation: the server answers this address with the redirect. -->
		<a class="sign-in-action primary" href={SIGN_IN_START_PATH} data-sveltekit-reload>
			{SIGN_IN_ACTION_LABEL}
		</a>
	{/snippet}
</SignInCard>
