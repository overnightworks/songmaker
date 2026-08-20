import { describe, expect, it } from 'vitest';
import { playerTakeIdForSong } from './cowriter-take';

describe('player take selector', () => {
	it('sends the playing take only when it belongs to the open song', () => {
		expect(playerTakeIdForSong('s1', { songId: 's1', generationId: 'gB' })).toBe('gB');
		expect(playerTakeIdForSong('s1', { songId: 's2', generationId: 'gOther' })).toBeNull();
		expect(playerTakeIdForSong('s1', null)).toBeNull();
	});
});
