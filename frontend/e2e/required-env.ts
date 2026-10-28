export const PROBE_STACK_TARGET =
	'a probe stack (frontend/e2e/README.md, "Running it locally"), never the live stack on 8080';

export function requiredEnv(name: string, target: string): string {
	const value = process.env[name];
	if (!value) throw new Error(`${name} must be set to ${target}`);
	return value;
}

export function requiredAdminUsername(): string {
	return requiredEnv('E2E_ADMIN_USERNAME', "the e2e admin's username");
}
