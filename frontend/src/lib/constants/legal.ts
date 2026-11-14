// The legal texts live on the central site, one section per app; every page
// links them in this order. A label is a catalog key; the pages are the binding German ones.
const CENTRAL_LEGAL_ORIGIN = 'https://hallucinai.de';
const APP_LEGAL_ANCHOR = '#songmaker';

function centralLegalAddress(path: string): string {
	return `${CENTRAL_LEGAL_ORIGIN}/${path}${APP_LEGAL_ANCHOR}`;
}

export const LEGAL_SECTIONS = [
	{ labelKey: 'legal.imprint', href: centralLegalAddress('impressum') },
	{ labelKey: 'legal.privacy', href: centralLegalAddress('datenschutz') },
	{ labelKey: 'legal.terms', href: centralLegalAddress('nutzungsbedingungen') }
] as const;
