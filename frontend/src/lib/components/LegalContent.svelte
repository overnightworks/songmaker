<!-- APP_NAME: if the app name changes, update the legal text below and the email addresses manually -->
<script lang="ts">
	import { onMount } from 'svelte';
	import { ensureCompactUiStyles } from '$lib/styles/compact-ui';
	import { subscribeCompactLayout } from '$lib/utils/compact-layout';

	interface Props {
		onback?: () => void;
		initialSection?: string;
	}

	let { onback, initialSection = 'impressum' }: Props = $props();
	let userOverride: string | null = $state(null);
	let section = $derived(userOverride ?? initialSection);
	let compact = $state(false);

	onMount(() => {
		ensureCompactUiStyles();
		return subscribeCompactLayout((value) => (compact = value));
	});

	function switchSection(s: string) {
		userOverride = s;
	}
</script>

<div class="legal-content" class:compact>
	<div class="legal-tabs">
		{#if onback}
			<button class="back-arrow" onclick={onback} aria-label="Back">←</button>
		{/if}
		<button class:active={section === 'impressum'} onclick={() => switchSection('impressum')}
			>Impressum</button
		>
		<button class:active={section === 'datenschutz'} onclick={() => switchSection('datenschutz')}
			>Datenschutz</button
		>
		<button
			class:active={section === 'nutzungsbedingungen'}
			onclick={() => switchSection('nutzungsbedingungen')}>Nutzungsbedingungen</button
		>
	</div>

	{#if section === 'impressum'}
		<section id="impressum">
			<h1>Impressum</h1>
			<p>Angaben gemäß §5 DDG</p>

			<h2>Verantwortlich</h2>
			<p>
				Felix Hummert<br />
				Wöhrstr. 6a<br />
				91054 Erlangen<br />
				Deutschland
			</p>

			<h2>Kontakt</h2>
			<p>E-Mail: legal@hallucinai.de</p>
		</section>
	{/if}

	{#if section === 'datenschutz'}
		<section id="datenschutz">
			<h1>Datenschutzerklärung</h1>

			<h2>1. Verantwortlicher</h2>
			<p>
				Felix Hummert<br />
				Wöhrstr. 6a, 91054 Erlangen<br />
				E-Mail: legal@hallucinai.de
			</p>

			<h2>2. Erhobene Daten</h2>
			<p>Wir verarbeiten folgende personenbezogene Daten:</p>
			<ul>
				<li>
					<strong>Benutzerkonto:</strong> Benutzername, Passwort (verschlüsselt gespeichert mit bcrypt).
					Rechtsgrundlage: Art. 6 Abs. 1 lit. b DSGVO (Vertragserfüllung).
				</li>
				<li>
					<strong>IP-Adressen:</strong> In Server-Logs und zur Missbrauchserkennung. Rechtsgrundlage:
					Art. 6 Abs. 1 lit. f DSGVO (berechtigtes Interesse an Sicherheit).
				</li>
				<li>
					<strong>Session-Cookies:</strong> Technisch notwendig für die Anmeldung (HttpOnly, kein Tracking).
					Rechtsgrundlage: Art. 6 Abs. 1 lit. b DSGVO. Keine Einwilligung erforderlich gemäß §25 Abs.
					2 TDDDG.
				</li>
				<li>
					<strong>Audiodateien:</strong> KI-generierte Songs, die Sie erstellen. Rechtsgrundlage: Art.
					6 Abs. 1 lit. b DSGVO.
				</li>
				<li>
					<strong>Audit-Log:</strong> Anmeldevorgänge, IP-Änderungen, Admin-Aktionen. Rechtsgrundlage:
					Art. 6 Abs. 1 lit. f DSGVO (berechtigtes Interesse an Sicherheit).
				</li>
			</ul>

			<h2>3. Cloudflare</h2>
			<p>
				Diese Website nutzt Cloudflare, Inc. (101 Townsend St, San Francisco, CA 94107, USA) als
				Infrastrukturanbieter für DDoS-Schutz und verschlüsselte Datenübertragung (TLS). Cloudflare
				verarbeitet dabei IP-Adressen und HTTP-Header der Besucher.
			</p>
			<p>
				Cloudflare ist unter dem EU-U.S. Data Privacy Framework zertifiziert. Die Datenverarbeitung
				erfolgt auf Grundlage eines Auftragsverarbeitungsvertrags (Art. 28 DSGVO) und Art. 6 Abs. 1
				lit. f DSGVO (berechtigtes Interesse an Sicherheit und Verfügbarkeit).
			</p>
			<p>
				Cloudflare kann technisch notwendige Cookies setzen (z.B. <code>__cf_bm</code> für Bot-Erkennung).
				Diese dienen ausschließlich der Sicherheit.
			</p>

			<h2>4. Speicherdauer</h2>
			<ul>
				<li>
					<strong>Benutzerkonten:</strong> Bis zur Löschung durch den Nutzer oder Administrator.
				</li>
				<li><strong>Session-Daten:</strong> Maximal 90 Tage.</li>
				<li><strong>Server-Logs / IP-Adressen:</strong> Maximal 30 Tage.</li>
				<li><strong>Audiodateien:</strong> Bis zur Löschung durch den Nutzer.</li>
				<li><strong>Audit-Log:</strong> Maximal 90 Tage.</li>
			</ul>

			<h2>5. Ihre Rechte</h2>
			<p>Sie haben gemäß DSGVO folgende Rechte:</p>
			<ul>
				<li>Auskunft über Ihre gespeicherten Daten (Art. 15)</li>
				<li>Berichtigung unrichtiger Daten (Art. 16)</li>
				<li>Löschung Ihrer Daten (Art. 17)</li>
				<li>Einschränkung der Verarbeitung (Art. 18)</li>
				<li>Datenübertragbarkeit (Art. 20)</li>
				<li>Widerspruch gegen die Verarbeitung (Art. 21)</li>
				<li>Beschwerde bei der zuständigen Aufsichtsbehörde</li>
			</ul>
			<p>Zur Ausübung Ihrer Rechte kontaktieren Sie uns per E-Mail: legal@hallucinai.de</p>

			<h2>6. Keine Weitergabe an Dritte</h2>
			<p>
				Ihre Daten werden nicht an Dritte verkauft oder zu Werbezwecken weitergegeben. Eine
				Weitergabe erfolgt nur an Cloudflare als Auftragsverarbeiter (siehe oben).
			</p>

			<h2>7. Kein Tracking</h2>
			<p>
				Diese Website verwendet keine Analyse-Tools, keine Tracking-Cookies, keine Werbung und kein
				Social-Media-Tracking. Es werden ausschließlich technisch notwendige Cookies für die
				Anmeldefunktion verwendet.
			</p>
		</section>
	{/if}

	{#if section === 'nutzungsbedingungen'}
		<section id="nutzungsbedingungen">
			<h1>Nutzungsbedingungen</h1>

			<h2>1. Leistungsbeschreibung</h2>
			<p>
				Hallucinai ist eine Plattform zur KI-gestützten Musikerzeugung. Nutzer erstellen Liedtexte
				und Stilbeschreibungen, die von einem KI-Modell (ACE-Step) in Audiodateien umgewandelt
				werden. Der Dienst wird kostenlos und ohne Verfügbarkeitsgarantie bereitgestellt.
			</p>

			<h2>2. KI-generierte Inhalte</h2>
			<ul>
				<li>
					Alle generierten Songs werden vollständig durch künstliche Intelligenz erzeugt und als
					solche gekennzeichnet.
				</li>
				<li>
					KI-generierte Werke genießen nach deutschem Recht keinen urheberrechtlichen Schutz (§2
					Abs. 2 UrhG erfordert eine persönliche geistige Schöpfung eines Menschen).
				</li>
				<li>
					Der Betreiber übernimmt keine Gewähr für die Originalität, Qualität oder rechtliche
					Verwertbarkeit der generierten Inhalte.
				</li>
				<li>
					KI-generierte Musik kann zufällig bestehenden urheberrechtlich geschützten Werken ähneln.
					Der Betreiber haftet nicht für unbeabsichtigte Ähnlichkeiten.
				</li>
			</ul>

			<h2>3. Pflichten der Nutzer</h2>
			<ul>
				<li>
					Nutzer dürfen keine urheberrechtlich geschützten Texte Dritter als Eingabe verwenden.
				</li>
				<li>
					Nutzer dürfen keine rechtswidrigen, beleidigenden oder diskriminierenden Inhalte
					erstellen.
				</li>
				<li>Nutzer sind für die Sicherheit ihres Kontos (Passwort) selbst verantwortlich.</li>
				<li>Die Nutzung ist ausschließlich für private, nicht-kommerzielle Zwecke gestattet.</li>
			</ul>

			<h2>4. Haftung</h2>
			<p>
				Der Betreiber haftet unbeschränkt für Vorsatz und grobe Fahrlässigkeit sowie für Schäden an
				Leben, Körper und Gesundheit. Für einfache Fahrlässigkeit haftet der Betreiber nur bei
				Verletzung wesentlicher Vertragspflichten, begrenzt auf den vorhersehbaren,
				vertragstypischen Schaden. Dies gilt nicht für Ansprüche nach dem Produkthaftungsgesetz.
			</p>
			<p>
				Für Inhalte, die durch Nutzer eingegeben oder durch KI generiert werden, übernimmt der
				Betreiber keine Haftung (§§7, 8, 10 DDG).
			</p>

			<h2>5. GEMA</h2>
			<p>
				Vollständig KI-generierte Musik unterliegt nach aktuellem Rechtsstand keiner GEMA-Pflicht,
				da kein menschlicher Urheber existiert. Der Betreiber übernimmt keine Garantie für den
				GEMA-freien Status der generierten Werke. Nutzer sind selbst dafür verantwortlich, die
				rechtliche Zulässigkeit einer kommerziellen Verwertung zu prüfen.
			</p>

			<h2>6. Löschung und Kündigung</h2>
			<p>
				Der Betreiber behält sich vor, Inhalte zu entfernen und Konten zu sperren, insbesondere bei
				Verstößen gegen diese Nutzungsbedingungen.
			</p>

			<h2>7. Anwendbares Recht</h2>
			<p>Es gilt deutsches Recht.</p>
		</section>
	{/if}

	<footer class="legal-footer">
		<p>Stand: März 2026</p>
	</footer>
</div>

<style>
	.legal-content {
		max-width: 640px;
		width: 100%;
		min-width: 0;
		box-sizing: border-box;
		padding: 2rem;
		color: var(--text, #e0e0e0);
		font-family: var(--font-body, 'Open Sans', sans-serif);
		line-height: 1.6;
		overflow-y: auto;
	}

	.legal-content.compact {
		padding: 1rem;
	}

	.legal-tabs {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem 1rem;
		margin-bottom: 2rem;
		border-bottom: 1px solid var(--border, #333);
		padding-bottom: 0.75rem;
	}

	.back-arrow {
		background: none;
		border: none;
		color: var(--text-muted, #888);
		font-size: 16px;
		cursor: pointer;
		padding: 0.4rem 0.4rem 0.4rem 0;
	}

	.back-arrow:hover {
		color: var(--primary, #ff3220);
	}

	.legal-tabs button:not(.back-arrow) {
		background: none;
		border: none;
		border-bottom: 2px solid transparent;
		color: var(--text-muted, #888);
		font-size: 0.75rem;
		font-family: var(--font-display, 'Oswald', sans-serif);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		padding: 0.4rem 0;
		cursor: pointer;
	}

	.legal-tabs button:hover {
		color: var(--text, #e0e0e0);
	}

	.legal-tabs button.active {
		color: var(--primary, #ff3220);
		border-image: linear-gradient(90deg, var(--primary, #ff3220), var(--accent, #a020f0)) 1;
	}

	section {
		margin-bottom: 2rem;
	}

	h1 {
		font-family: var(--font-display, 'Oswald', sans-serif);
		font-size: 1.1rem;
		text-transform: uppercase;
		letter-spacing: 1px;
		background: linear-gradient(90deg, var(--primary, #ff3220), var(--accent, #a020f0));
		-webkit-background-clip: text;
		-webkit-text-fill-color: transparent;
		background-clip: text;
		margin: 0 0 0.75rem;
	}

	h2 {
		font-family: var(--font-display, 'Oswald', sans-serif);
		font-size: 0.8rem;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		color: var(--text-muted, #888);
		margin: 1.2rem 0 0.4rem;
	}

	p {
		margin: 0.4rem 0;
		font-size: 0.78rem;
	}

	ul {
		margin: 0.5rem 0;
		padding-left: 1.5rem;
	}

	li {
		margin: 0.2rem 0;
		font-size: 0.78rem;
	}

	code {
		background: var(--surface, #111);
		padding: 1px 4px;
		border-radius: 3px;
		font-size: 0.85rem;
	}

	.legal-footer {
		margin-top: 3rem;
		padding-top: 1rem;
		border-top: 1px solid var(--border, #333);
		font-size: 0.75rem;
		color: var(--text-subtle, #888);
	}
</style>
