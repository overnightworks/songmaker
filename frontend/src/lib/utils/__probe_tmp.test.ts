import { describe, expect, it } from 'vitest';
import type { WhisperCue } from '$lib/api/types';
import { alignLyricsToCues } from './lyrics-align';

const RIVER = 'the river carries every promise home';
const HOOK = 'hold the line until the morning';
const COUNT = 'we count the fading city lights';

function sungCue(start: number, perWord: number, text: string): WhisperCue {
	const words = text.split(' ').map((word, index) => ({
		start: start + index * perWord,
		end: start + (index + 1) * perWord,
		text: word
	}));
	return { start: words[0].start, end: words[words.length - 1].end, text, words };
}

describe('probe', () => {
	it('repeat pattern', () => {
		const lines = [RIVER, RIVER, HOOK, HOOK, RIVER, COUNT, HOOK, HOOK];
		const aligned = alignLyricsToCues(lines.join('\n'), [sungCue(0, 0.5, lines.join(' '))]);
		console.log(JSON.stringify(aligned.map((l) => l.interval)));
		expect(aligned.length).toBe(8);
	}, 60000);
});
