import { pageText } from '#lib/utils/page-words.ts';
import type { Key } from '#lib/words/en.ts';

type SettingsSectionId = 'generation' | 'voices' | 'references' | 'admin' | 'about';

interface SettingsSection {
	readonly id: SettingsSectionId;
	readonly href: string;
	readonly labelKey: Key;
	readonly icon: string;
	readonly adminOnly: boolean;
}

const SETTINGS_SECTIONS = [
	{
		id: 'generation',
		href: '/settings/generation',
		labelKey: 'settingsSections.generation',
		icon: 'audio-lines',
		adminOnly: false
	},
	{
		id: 'voices',
		href: '/settings/voices',
		labelKey: 'settingsSections.voices',
		icon: 'mic',
		adminOnly: false
	},
	{
		id: 'references',
		href: '/settings/references',
		labelKey: 'settingsSections.references',
		icon: 'file-music',
		adminOnly: false
	},
	{
		id: 'admin',
		href: '/settings/users',
		labelKey: 'settingsSections.admin',
		icon: 'shield',
		adminOnly: true
	},
	{
		id: 'about',
		href: '/settings/about',
		labelKey: 'settingsSections.about',
		icon: 'info',
		adminOnly: false
	}
] as const satisfies readonly SettingsSection[];

type SettingsSectionEntry = (typeof SETTINGS_SECTIONS)[number];

export type SettingsSectionRoute = SettingsSectionEntry['href'];

export function visibleSettingsSections(
	admin: boolean
): readonly (Omit<SettingsSectionEntry, 'labelKey'> & { readonly label: string })[] {
	return SETTINGS_SECTIONS.filter((section) => admin || !section.adminOnly).map(
		({ labelKey, ...section }) => ({ ...section, label: pageText(labelKey) })
	);
}
