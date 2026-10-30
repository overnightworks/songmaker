<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { SIGN_IN_PATH } from '#lib/api/fetch.ts';
	import Icon from '#lib/components/Icon.svelte';
	import SignInCard from '#lib/components/SignInCard.svelte';
	import {
		NO_ACCESS_BACK_LABEL,
		NO_ACCESS_HEADING,
		NO_ACCESS_MESSAGE
	} from '#lib/constants/auth.ts';
	import { ACCOUNT_MENU_LOGOUT_LABEL, SIGN_OUT_FAILED_MESSAGE } from '#lib/constants.ts';
	import { logout, signOutFailed } from '#lib/stores/auth.ts';
</script>

<SignInCard heading={NO_ACCESS_HEADING} failure={NO_ACCESS_MESSAGE}>
	{#snippet actions()}
		<button type="button" class="sign-in-action primary" onclick={() => void logout()}>
			<Icon name="log-out" size={16} />{ACCOUNT_MENU_LOGOUT_LABEL}
		</button>
		<a class="sign-in-action" href={SIGN_IN_PATH}>{NO_ACCESS_BACK_LABEL}</a>
		{#if $signOutFailed}
			<p class="sign-out-failed" role="alert">{SIGN_OUT_FAILED_MESSAGE}</p>
		{/if}
	{/snippet}
</SignInCard>

<style>
	.sign-out-failed {
		width: 100%;
		margin: 0;
		font-size: 0.8rem;
		color: var(--score-bad);
	}
</style>
