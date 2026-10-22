// The legal texts live on the central site, one section per app; every page
// links them in this order.
const CENTRAL_LEGAL_ORIGIN = 'https://hallucinai.de';
const APP_LEGAL_ANCHOR = '#songmaker';

function centralLegalAddress(path: string): string {
	return `${CENTRAL_LEGAL_ORIGIN}/${path}${APP_LEGAL_ANCHOR}`;
}

export const LEGAL_SECTIONS = [
	{ label: 'Impressum', href: centralLegalAddress('impressum') },
	{ label: 'Datenschutz', href: centralLegalAddress('datenschutz') },
	{ label: 'Nutzungsbedingungen', href: centralLegalAddress('nutzungsbedingungen') }
] as const;
