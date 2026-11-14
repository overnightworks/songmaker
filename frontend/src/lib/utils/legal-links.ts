import { LEGAL_SECTIONS } from '#lib/constants/legal.ts';
import { pageText } from '#lib/utils/page-words.ts';

/** The legal links the kit's account menu, sign-in pages and footer take: each label in the page's language, each address the binding German page. */
export function legalLinks(): { label: string; href: string }[] {
	return LEGAL_SECTIONS.map(({ labelKey, href }) => ({ label: pageText(labelKey), href }));
}
