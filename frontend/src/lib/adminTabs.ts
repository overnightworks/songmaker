export const ADMIN_TABS = [
	{ id: 'voices', labelKey: 'adminPage.tabVoices' },
	{ id: 'ratelimits', labelKey: 'adminPage.tabRateLimits' },
	{ id: 'generation', labelKey: 'adminPage.tabGeneration' },
	{ id: 'models', labelKey: 'adminPage.tabModels' },
	{ id: 'acestep', labelKey: 'adminPage.tabAcestep' },
	{ id: 'cleanup', labelKey: 'adminPage.tabCleanup' }
] as const;

export type AdminTab = (typeof ADMIN_TABS)[number]['id'];

export function parseAdminTab(value: string): AdminTab | null {
	return ADMIN_TABS.find((item) => item.id === value)?.id ?? null;
}
