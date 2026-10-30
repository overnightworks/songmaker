<script lang="ts">
	import { SignInPage } from 'overnightworks-appkit';
	import { APP_NAME, SIGN_OUT_FAILED_MESSAGE } from '#lib/constants.ts';
	import { LEGAL_SECTIONS } from '#lib/constants/legal.ts';
	import { logout, signOutFailed } from '#lib/stores/auth.ts';
</script>

<SignInPage
	appName={APP_NAME}
	state={{
		page: 'no-access',
		onLogOut: () => void logout(),
		logOutFailure: $signOutFailed ? SIGN_OUT_FAILED_MESSAGE : undefined
	}}
	legalLinks={LEGAL_SECTIONS}
/>
