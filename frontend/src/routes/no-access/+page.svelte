<script lang="ts">
	import { SignInPage } from 'overnightworks-design';
	import { SIGN_OUT_FAILED_MESSAGE } from '#lib/constants/auth.ts';
	import { APP_NAME } from '#lib/constants/app.ts';
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
