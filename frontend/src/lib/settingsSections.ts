type SettingsSectionId = 'generation' | 'voices' | 'admin';

interface SettingsSection {
	readonly id: SettingsSectionId;
	readonly href: string;
	readonly label: string;
	readonly icon: string;
	readonly adminOnly: boolean;
}

const SETTINGS_SECTIONS = [
	{
		id: 'generation',
		href: '/settings/generation',
		label: 'Generation',
		icon: 'audio-lines',
		adminOnly: false
	},
	{ id: 'voices', href: '/settings/voices', label: 'Voices', icon: 'mic', adminOnly: false },
	{ id: 'admin', href: '/settings/users', label: 'Admin', icon: 'shield', adminOnly: true }
] as const satisfies readonly SettingsSection[];

export type SettingsSectionRoute = (typeof SETTINGS_SECTIONS)[number]['href'];

export function visibleSettingsSections(
	admin: boolean
): readonly (typeof SETTINGS_SECTIONS)[number][] {
	return SETTINGS_SECTIONS.filter((section) => admin || !section.adminOnly);
}
