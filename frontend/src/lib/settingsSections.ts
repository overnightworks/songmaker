import type { Pathname } from '$app/types';

type SettingsSectionId =
	'generation' | 'playback' | 'voices' | 'account' | 'admin' | 'cleanup' | 'legal';

interface SettingsSection {
	readonly id: SettingsSectionId;
	readonly href: Pathname;
	readonly label: string;
	readonly icon: string;
	readonly adminOnly: boolean;
}

const SETTINGS_SECTIONS: readonly SettingsSection[] = [
	{
		id: 'generation',
		href: '/settings/generation',
		label: 'Generation',
		icon: 'audio-lines',
		adminOnly: false
	},
	{ id: 'playback', href: '/settings/playback', label: 'Playback', icon: 'play', adminOnly: false },
	{ id: 'voices', href: '/settings/voices', label: 'Voices', icon: 'mic', adminOnly: false },
	{ id: 'account', href: '/settings/account', label: 'Account', icon: 'user', adminOnly: false },
	{ id: 'admin', href: '/settings/users', label: 'Admin', icon: 'shield', adminOnly: true },
	{ id: 'cleanup', href: '/settings/cleanup', label: 'Cleanup', icon: 'broom', adminOnly: true },
	{ id: 'legal', href: '/settings/legal', label: 'Legal', icon: 'file-text', adminOnly: false }
];

export function visibleSettingsSections(admin: boolean): SettingsSection[] {
	return SETTINGS_SECTIONS.filter((section) => admin || !section.adminOnly);
}
