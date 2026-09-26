import { describe, expect, it } from 'vitest';
import { normalizeLyricsToken } from './lyrics-normalize';

describe('normalizeLyricsToken', () => {
	it.each([
		['drops trailing punctuation', 'Rahmen,', 'rahmen'],
		['casefolds without altering an otherwise-equal word', 'Rahmen', 'rahmen'],
		['casefolds German eszett to ss, matching Python str.casefold()', 'Straße', 'strasse'],
		['casefolds capital eszett (ẞ) to ss as well', 'GROẞE', 'grosse'],
		['casefolds a Greek word-final sigma to the regular sigma, matching Python', 'λόγος', 'λόγοσ'],
		[
			'leaves Turkish İ as toLowerCase already agrees with Python casefold (i + combining dot)',
			'İstanbul',
			'i̇stanbul'
		],
		['keeps a straight word-internal apostrophe', "don't", "don't"],
		['unifies a curly right single quote to a straight apostrophe', 'don’t', "don't"],
		['unifies a curly reversed-9 quote to a straight apostrophe', 'don‛t', "don't"],
		['unifies a modifier-letter apostrophe to a straight apostrophe', 'donʼt', "don't"],
		["keeps a word-internal apostrophe before a trailing 's'", "café's", "café's"],
		['drops a leading punctuation-only apostrophe', "'tis", 'tis'],
		['collapses internal whitespace', 'foo   bar', 'foo bar'],
		['trims surrounding whitespace', '  foo  ', 'foo'],
		['reduces pure punctuation to an empty string', '—', ''],
		['spells out an umlaut the way typed German lyrics do', 'glüht', 'glueht'],
		['spells out a capital umlaut as well', 'ÖFFNET Übermut', 'oeffnet uebermut'],
		['spells a sung number out as its German word', '17', 'siebzehn'],
		['spells a two-digit number with its units first', '27', 'siebenundzwanzig'],
		['spells a one in a compound number as "ein"', '21', 'einundzwanzig'],
		['spells a round ten with its eszett folded', '30', 'dreissig'],
		['spells hundreds', '500', 'fuenfhundert'],
		['spells a hundred and one with its trailing "eins"', '101', 'einhunderteins'],
		['spells thousands', '2014', 'zweitausendvierzehn'],
		['leaves a number beyond the spelled range as digits', '12345', '12345'],
		['leaves digits inside a word alone', 'A1 bis B2', 'a1 bis b2']
	])('%s', (_name, input, expected) => {
		expect(normalizeLyricsToken(input)).toBe(expected);
	});

	it('treats differently-punctuated/cased tokens as equal keys', () => {
		expect(normalizeLyricsToken('Rahmen,')).toBe(normalizeLyricsToken('rahmen'));
		expect(normalizeLyricsToken('don’t')).toBe(normalizeLyricsToken("don't"));
		expect(normalizeLyricsToken('Straße')).toBe(normalizeLyricsToken('strasse'));
		expect(normalizeLyricsToken('glüht,')).toBe(normalizeLyricsToken('Glueht'));
		expect(normalizeLyricsToken('17')).toBe(normalizeLyricsToken('Siebzehn'));
	});
});
