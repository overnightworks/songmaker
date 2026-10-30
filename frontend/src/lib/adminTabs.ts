import { ADMIN_VOICES_TAB_LABEL } from '#lib/constants.ts';

export const ADMIN_TABS = [
	{ id: 'voices', label: ADMIN_VOICES_TAB_LABEL },
	{ id: 'ratelimits', label: 'Rate Limits' },
	{ id: 'generation', label: 'Generation' },
	{ id: 'agents', label: 'Agents' },
	{ id: 'acestep', label: 'ACE-Step' },
	{ id: 'cleanup', label: 'Cleanup' }
] as const;

export type AdminTab = (typeof ADMIN_TABS)[number]['id'];

export function parseAdminTab(value: string): AdminTab | null {
	return ADMIN_TABS.find((item) => item.id === value)?.id ?? null;
}
