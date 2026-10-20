<!-- APP_NAME: if the app name changes, update the legal text below and the email addresses manually -->
<script lang="ts">
	import { onMount } from 'svelte';
	import type { LegalSection } from '$lib/components/LegalLinks.svelte';
	import { ensureCompactUiStyles } from '$lib/styles/compact-ui';
	import { subscribeCompactLayout } from '$lib/utils/compact-layout';

	interface Props {
		onback?: () => void;
		initialSection?: LegalSection;
	}

	let { onback, initialSection = 'impressum' }: Props = $props();
	let userOverride: LegalSection | null = $state(null);
	let section = $derived(userOverride ?? initialSection);
	let compact = $state(false);

	onMount(() => {
		ensureCompactUiStyles();
		return subscribeCompactLayout((value) => (compact = value));
	});

	function switchSection(s: LegalSection) {
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
		<section>
			<h1>Impressum</h1>
			<p>Angaben gemäß § 5 DDG und § 18 Abs. 1 MStV</p>

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
		<section>
			<h1>Datenschutzerklärung</h1>

			<h2>1. Verantwortlicher</h2>
			<p>
				Felix Hummert<br />
				Wöhrstr. 6a, 91054 Erlangen<br />
				E-Mail: legal@hallucinai.de
			</p>

			<h2>2. Welche Daten wir verarbeiten</h2>
			<p>Wir verarbeiten folgende personenbezogene Daten:</p>
			<ul>
				<li>
					<strong>Benutzerkonto:</strong> Benutzername und Passwort (nur als Argon2id-Hash gespeichert,
					nicht im Klartext). Konten legt der Betreiber auf Einladung an. Rechtsgrundlage: Art. 6 Abs.
					1 lit. b DSGVO (Vertragserfüllung).
				</li>
				<li>
					<strong>Inhalte, die Sie in songmaker anlegen:</strong> Alben, Songs, Liedtexte, Stilbeschreibungen,
					Versionen samt Generierungsparametern, Playlists, Bewertungen, Cover und Cover-Vorschläge, generierte
					Audiodateien sowie automatische Bewertungen samt Transkription des Gesungenen. Rechtsgrundlage:
					Art. 6 Abs. 1 lit. b DSGVO.
				</li>
				<li>
					<strong>Co-Writer:</strong> Ihre Nachrichten, automatisch erzeugte Gesprächszusammenfassungen
					sowie dauerhafte Notizen zu Ihnen, Ihren Songs und Alben, die Sie anlegen oder bestätigen. Rechtsgrundlage:
					Art. 6 Abs. 1 lit. b DSGVO.
				</li>
				<li>
					<strong>Hochgeladenes Audio:</strong> Referenzaufnahmen sowie Trainingsaufnahmen mit Beschreibung
					und Liedtext für eigene Stimmen und die daraus trainierten Modelle. Rechtsgrundlage: Art. 6
					Abs. 1 lit. b DSGVO.
				</li>
				<li>
					<strong>Anmeldung und Sicherheit:</strong> Sitzungskennung, IP-Adresse, Browserkennung und Zeitpunkt
					der Sitzung; Anmeldeversuche mit IP-Adresse, eingegebenem Benutzernamen, Zeitpunkt und Erfolg;
					kurzlebige Zähler zur Ratenbegrenzung; ein Audit-Log mit Anmelde- und Änderungsereignissen,
					der früheren und neuen IP-Adresse bei einem Wechsel und Verwaltungsaktionen. Rechtsgrundlage:
					Art. 6 Abs. 1 lit. f DSGVO (Schutz vor Missbrauch).
				</li>
				<li>
					<strong>Server-Logs:</strong> IP-Adresse, Zeitpunkt, aufgerufene Adresse, Statuscode und Dauer
					jeder Anfrage. Rechtsgrundlage: Art. 6 Abs. 1 lit. f DSGVO (Sicherheit und Fehlerbehebung).
				</li>
			</ul>
			<p>
				Für ein Konto sind Benutzername und Passwort erforderlich; alle weiteren Inhalte geben Sie
				freiwillig ein. Eine gesetzliche oder vertragliche Pflicht zur Bereitstellung besteht nicht.
				Eine automatisierte Entscheidungsfindung einschließlich Profiling im Sinne von Art. 22 DSGVO
				findet nicht statt; die automatischen Bewertungen von Songs dienen nur Ihrer Orientierung.
			</p>

			<h2>3. Verarbeitung auf unserem Server</h2>
			<p>
				Musikerzeugung (ACE-Step), Transkription des Gesungenen (Whisper), Audiobewertung und das
				Training eigener Stimmen laufen nur auf unserem Server in Deutschland.
			</p>
			<p>
				<strong>Eigene Stimmen und Referenzaufnahmen:</strong> Aus hochgeladenen Aufnahmen trainieren
				wir auf unserem Server ein Stimm- oder Stilmodell für Ihre Songs. Wir nutzen Aufnahmen und Modelle
				nicht, um Personen zu erkennen oder zu identifizieren, und geben sie nicht weiter.
			</p>
			<p>
				<strong>Daten über andere Personen:</strong> Gibt ein Nutzer Namen, Texte oder Aufnahmen über
				Sie ein, erhalten wir diese von ihm; für Zwecke, Empfänger, Speicherdauer und Ihre Rechte gelten
				diese Hinweise entsprechend. Bitte geben Sie keine Gesundheitsdaten, religiösen oder politischen
				Überzeugungen realer Personen ein.
			</p>

			<h2>4. KI-Funktionen mit externen Anbietern</h2>
			<p>
				Drei Funktionen senden Daten an externe KI-Anbieter. Jede davon stoßen Sie selbst an.
				Rechtsgrundlage: Art. 6 Abs. 1 lit. b DSGVO.
			</p>
			<ul>
				<li>
					<strong>Co-Writer:</strong> Wir senden Ihre Nachricht, den bisherigen Gesprächsverlauf (bei
					langen Gesprächen eine Zusammenfassung und die letzten Nachrichten), Ihre Co-Writer-Notizen
					sowie Titel, Liedtext, Stilbeschreibung und Parameter der Songs und Alben, die Sie geöffnet
					oder per @-Erwähnung genannt haben, an den von Ihnen gewählten Anbieter: Anthropic (Claude),
					xAI (Grok) oder OpenAI (Codex).
				</li>
				<li>
					<strong>Textprüfung:</strong> Ist sie eingeschaltet, senden wir nach einer Generierung den beabsichtigten
					Liedtext und die auf unserem Server erzeugte Transkription des Gesungenen an den vom Betreiber
					eingestellten Anbieter (Anthropic, xAI oder OpenAI).
				</li>
				<li>
					<strong>Cover-Vorschläge:</strong> Auf Ihre Anforderung senden wir Albumtitel, Künstlername
					sowie Auszüge aus Stilbeschreibungen und Liedtexten an OpenAI.
				</li>
			</ul>
			<p>
				<strong>Rolle der Anbieter:</strong> Der Betreiber stellt je Anbieter und Funktion ein, ob eine
				Anfrage über die Programmierschnittstelle (API) des Anbieters oder über ein Nutzerkonto des Betreibers
				beim Anbieter läuft; Cover-Vorschläge laufen stets über das Nutzerkonto des Betreibers bei OpenAI.
				Soweit eine Anfrage über ein Nutzerkonto des Betreibers läuft, verarbeitet der Anbieter die Daten
				als eigener Verantwortlicher nach seiner Datenschutzerklärung (Anthropic Ireland Ltd., Dublin;
				OpenAI Ireland Ltd., Dublin; xAI). Über die Programmierschnittstelle verarbeitet der Anbieter
				die Daten nach seinen Bedingungen für die API-Nutzung. Die Nutzung Ihrer Inhalte zum Training
				von KI-Modellen ist in den Konten des Betreibers bei Anthropic, OpenAI und xAI abgeschaltet.
			</p>
			<p>
				<strong>Übermittlung in die USA:</strong> Je nach genutzter Funktion verarbeiten Anthropic, OpenAI
				und xAI Daten auch in den USA. Anthropic und OpenAI stützen die Übermittlung nach ihren Datenschutzerklärungen
				auf Angemessenheitsbeschlüsse der EU-Kommission und auf deren Standardvertragsklauseln (Art. 45,
				Art. 46 Abs. 2 lit. c DSGVO). Für xAI konnten wir die Übermittlungsgrundlage bislang nicht feststellen.
				Eine Kopie der jeweils geltenden Garantien erhalten Sie auf Anfrage unter legal@hallucinai.de.
			</p>
			<p>
				<strong>Speicherung beim Betreiber:</strong> Läuft eine Anfrage an Anthropic über das Nutzerkonto
				des Betreibers, legt das dafür genutzte Programm (Claude-CLI) die Sitzung zusätzlich in seinem
				Profil auf unserem Server ab; eine feste Löschfrist besteht dafür derzeit nicht.
			</p>

			<h2>5. Cloudflare</h2>
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

			<h2>6. Freigaben</h2>
			<p>
				Wenn Sie ein Album, einen Song, eine Generierung oder eine Playlist freigeben, kann jede
				Person mit dem Link ohne Anmeldung Titel, Künstlername, Liedtext, Audio und Cover abrufen
				und den Link weitergeben. Sie können die Freigabe jederzeit beenden; bereits
				heruntergeladene Kopien lassen sich nicht zurückholen. Von Besuchern verarbeiten wir die
				IP-Adresse wie unter Server-Logs beschrieben und zur Ratenbegrenzung.
			</p>

			<h2>7. Speicherung auf Ihrem Gerät</h2>
			<p>
				songmaker speichert auf Ihrem Gerät nur, was für den von Ihnen gewünschten Dienst
				erforderlich ist (§ 25 Abs. 2 Nr. 2 TDDDG); eine Einwilligung ist dafür nicht erforderlich:
			</p>
			<ul>
				<li>
					ein Sitzungs-Cookie für die Anmeldung (HttpOnly) und ein Sicherheits-Cookie gegen
					Fremdanfragen (CSRF), beide nur für diese Domain, Laufzeit bis 30 Tage;
				</li>
				<li>
					im Browser-Speicher die von Ihnen gewählten Anzeige- und Wiedergabeeinstellungen, Ihre
					letzte Wiedergabeposition und den Navigationsverlauf des Tabs;
				</li>
				<li>
					im Browser-Cache die App selbst und Audiodateien, die Sie für die Offline-Wiedergabe
					gespeichert haben.
				</li>
			</ul>
			<p>
				Browser-Speicher und Browser-Cache verlassen Ihr Gerät nicht. Cloudflare kann eigene
				Sicherheits-Cookies setzen (siehe Cloudflare).
			</p>

			<h2>8. Speicherdauer</h2>
			<ul>
				<li>
					<strong>Benutzerkonten:</strong> bis zur Löschung. Konten löscht der Betreiber auf Ihre Anfrage
					an legal@hallucinai.de.
				</li>
				<li>
					<strong>Inhalte und Audiodateien:</strong> bis Sie sie löschen. Gelöschte Alben und Songs sind
					30 Tage wiederherstellbar und werden dann endgültig entfernt. Generierungen, die weder als Auswahl
					noch als behalten markiert sind, werden nach 7 Tagen archiviert und 30 Tage später samt Datei
					endgültig gelöscht, sofern keine andere Generierung auf sie als Ausgangspunkt verweist.
				</li>
				<li>
					<strong>Was die Löschung heute noch nicht entfernt:</strong> Eine gelöschte Stimme wird nur
					als gelöscht markiert; ihre Trainingsaufnahmen und das Modell bleiben gespeichert. Referenzaufnahmen
					lassen sich derzeit nicht in der App löschen. Bei der Löschung eines Kontos bleiben Referenzaufnahmen
					und Stimmdateien erhalten, und Einträge im Audit-Log bleiben mit Benutzername und IP-Adressen
					bestehen. Wenn Sie die Löschung dieser Daten wünschen, schreiben Sie an legal@hallucinai.de.
				</li>
				<li>
					<strong>Sitzungen:</strong> Das Anmelde-Cookie gilt bis zu 30 Tage ohne Nutzung; eine Anmeldung
					endet spätestens 90 Tage nach dem Einloggen. Der Sitzungseintrag mit IP-Adresse und Browserkennung
					bleibt bis zu etwa 120 Tage nach dem Einloggen gespeichert.
				</li>
				<li>
					<strong>Anmeldeversuche:</strong> Einträge älter als 90 Tage werden gelöscht; der Löschlauf
					findet derzeit nur beim Start des Servers statt, sodass Einträge auch länger liegen bleiben
					können.
				</li>
				<li><strong>Audit-Log:</strong> wird derzeit ohne feste Frist gespeichert.</li>
				<li>
					<strong>Server-Logs:</strong> werden nach Speichermenge rotiert (höchstens 50 MB je Dienst);
					eine feste Höchstdauer besteht derzeit nicht.
				</li>
				<li>
					<strong>Sicherungskopien:</strong> Sicherungskopien von Datenbank und Audiodateien werden wöchentlich
					verschlüsselt auf unserem Server erstellt und in der Regel höchstens etwa drei Monate aufbewahrt;
					gelöschte Daten können bis dahin in einer Sicherung enthalten sein. Vor Updates legt der Betreiber
					zusätzlich Sicherungen an, für die derzeit keine feste Löschfrist besteht.
				</li>
			</ul>

			<h2>9. Ihre Rechte</h2>
			<p>Sie haben gemäß DSGVO folgende Rechte:</p>
			<ul>
				<li>Auskunft über Ihre gespeicherten Daten (Art. 15)</li>
				<li>Berichtigung unrichtiger Daten (Art. 16)</li>
				<li>Löschung Ihrer Daten (Art. 17)</li>
				<li>Einschränkung der Verarbeitung (Art. 18)</li>
				<li>Datenübertragbarkeit (Art. 20)</li>
				<li>Beschwerde bei der zuständigen Aufsichtsbehörde</li>
			</ul>
			<p>Zur Ausübung Ihrer Rechte kontaktieren Sie uns per E-Mail: legal@hallucinai.de</p>

			<h2>10. Ihr Widerspruchsrecht</h2>
			<p>
				Soweit wir Daten auf Grundlage von Art. 6 Abs. 1 lit. f DSGVO verarbeiten (Server-Logs,
				Missbrauchsschutz, Audit-Log, Cloudflare), können Sie aus Gründen, die sich aus Ihrer
				besonderen Situation ergeben, jederzeit widersprechen (Art. 21 DSGVO). Wir verarbeiten die
				Daten dann nicht mehr, es sei denn, wir weisen zwingende schutzwürdige Gründe nach, die Ihre
				Interessen überwiegen, oder die Verarbeitung dient der Geltendmachung, Ausübung oder
				Verteidigung von Rechtsansprüchen. Kontakt: legal@hallucinai.de
			</p>

			<h2>11. Empfänger</h2>
			<p>
				Ihre Daten werden nicht verkauft und nicht zu Werbezwecken weitergegeben. Empfänger sind (a)
				Cloudflare für Transport und Schutz der Website, (b) die KI-Anbieter Anthropic, xAI und
				OpenAI, soweit Sie die oben beschriebenen KI-Funktionen nutzen, und (c) Personen, denen Sie
				einen Freigabelink geben.
			</p>

			<h2>12. Kein Tracking</h2>
			<p>
				Diese Website verwendet keine Analyse-Tools, keine Tracking-Cookies, keine Werbung und kein
				Social-Media-Tracking. Was auf Ihrem Gerät gespeichert wird, steht unter „Speicherung auf
				Ihrem Gerät“.
			</p>
		</section>

		<footer class="legal-footer">
			<p>Stand: 20. Oktober 2026</p>
		</footer>
	{/if}

	{#if section === 'nutzungsbedingungen'}
		<section>
			<h1>Nutzungsbedingungen</h1>

			<h2>1. Leistungsbeschreibung</h2>
			<p>
				songmaker (unter hallucinai.de) ist ein privat betriebener, kostenloser Dienst, der nur auf
				Einladung nutzbar ist. Er wandelt Liedtexte und Stilbeschreibungen auf dem Server des
				Betreibers mit ACE-Step in Musik um. Der Co-Writer, die Textprüfung und Cover-Vorschläge
				nutzen externe KI-Anbieter (siehe Datenschutzerklärung). Eine Verfügbarkeit wird nicht
				garantiert.
			</p>

			<h2>2. KI-generierte Inhalte</h2>
			<ul>
				<li>
					songmaker erzeugt Musik und Cover mithilfe künstlicher Intelligenz; Liedtexte,
					Referenzaufnahmen und Stilbeschreibungen können von Menschen stammen.
				</li>
				<li>
					Rein maschinell erzeugte Musik ist mangels menschlicher Schöpfung in der Regel kein
					urheberrechtlich geschütztes Werk (§ 2 Abs. 2 UrhG). Von Ihnen geschriebene Liedtexte und
					andere menschliche Beiträge bleiben geschützt; ob an generierten Aufnahmen
					Leistungsschutzrechte entstehen und ob Verwertungsgesellschaften wie die GEMA Ansprüche
					haben, ist nicht abschließend geklärt.
				</li>
				<li>
					Der Betreiber übernimmt keine Gewähr für die Originalität oder Qualität der generierten
					Inhalte und sichert nicht zu, dass Ergebnisse frei von Rechten Dritter sind.
				</li>
			</ul>

			<h2>3. Pflichten der Nutzer</h2>
			<ul>
				<li>
					Verwenden Sie nur Texte, Bilder und Aufnahmen, die Sie nutzen dürfen, auch für
					Bearbeitung, Stimmtraining und Veröffentlichung.
				</li>
				<li>Stimmen anderer Personen laden Sie nur mit deren ausdrücklicher Einwilligung hoch.</li>
				<li>
					Geben Sie synthetische Aufnahmen nicht als echte Äußerungen einer realen Person aus; wer
					Inhalte veröffentlicht, die einer realen Person ähneln, legt offen, dass sie KI-generiert
					sind (Art. 50 Abs. 4 KI-VO).
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
				Für Inhalte, die Nutzer eingeben oder speichern, ist der Betreiber nach § 7 DDG in
				Verbindung mit Art. 6 der Verordnung (EU) 2022/2065 erst ab Kenntnis einer Rechtsverletzung
				verantwortlich und entfernt sie dann zügig. KI-Ergebnisse können geschützten Werken ähneln;
				eine Gewähr für ihre rechtliche Verwertbarkeit übernimmt der Betreiber nicht. Im Übrigen
				gilt die Haftungsregelung in Absatz 1.
			</p>

			<h2>5. Löschung und Kündigung</h2>
			<p>
				Sie können die Nutzung jederzeit beenden und die Löschung Ihres Kontos per E-Mail an
				legal@hallucinai.de verlangen; Ihr Konto und Ihre Inhalte werden dann gelöscht. Was die
				Löschung heute noch nicht entfernt, steht in der Datenschutzerklärung. Der Betreiber kann
				Inhalte oder Konten bei Rechtsverletzungen, erheblichen Verstößen gegen diese Bedingungen
				oder Sicherheitsgefahren sperren. Eine Sperre ist keine Löschung.
			</p>

			<h2>6. Anwendbares Recht</h2>
			<p>Es gilt deutsches Recht.</p>
		</section>

		<footer class="legal-footer">
			<p>Stand: 20. Oktober 2026</p>
		</footer>
	{/if}
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
