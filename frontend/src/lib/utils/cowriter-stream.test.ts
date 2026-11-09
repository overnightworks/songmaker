import { describe, expect, it } from 'vitest';
import type { CoWriterStreamEvent } from '#lib/api/client.ts';
import { applyStreamEvent, type CoWriterMessage } from './cowriter-stream.ts';

const bubble = (over: Partial<CoWriterMessage> = {}): CoWriterMessage => ({
	role: 'assistant',
	text: '',
	toolCalls: [],
	...over
});

const piece = (text: string): CoWriterStreamEvent => ({ type: 'assistant_text', text });
const call = (name: string): CoWriterStreamEvent => ({
	type: 'tool_call',
	tool_use_id: 'c',
	name,
	input: {}
});
const final = (content: string): CoWriterStreamEvent =>
	({
		type: 'final',
		conversation_id: 'c1',
		user_message: { id: 'u1' },
		assistant_message: { id: 'a1', content }
	}) as CoWriterStreamEvent;

const shownAfter = (events: CoWriterStreamEvent[]): CoWriterMessage =>
	events.reduce((message, event) => applyStreamEvent(message, event), bubble());

describe('applyStreamEvent', () => {
	it.each([
		['pieces append', [piece('Hel'), piece('lo')], 'Hello'],
		['a tool call keeps the words', [piece('Let me look'), call('get_song')], 'Let me look'],
		[
			'the next piece after a tool call starts fresh text',
			[piece('Let me look'), call('get_song'), piece('It has')],
			'It has'
		],
		[
			'pieces after the reset append again',
			[piece('Let me look'), call('get_song'), piece('It '), piece('has')],
			'It has'
		],
		[
			'a second tool round resets again',
			[piece('a'), call('x'), piece('b'), call('y'), piece('c')],
			'c'
		]
	])('%s', (_name, events, text) => {
		expect(shownAfter(events).text).toBe(text);
	});

	it('records each tool call', () => {
		const message = shownAfter([call('a'), call('b')]);
		expect(message.toolCalls?.map((entry) => entry.name)).toEqual(['a', 'b']);
	});

	it('final sets the stored text and id, equal to the text shown after a streamed final round', () => {
		const streamed = shownAfter([
			piece('Let me look'),
			call('get_song'),
			piece('It '),
			piece('has one verse')
		]);
		const done = applyStreamEvent(streamed, final('It has one verse'));
		expect(done.text).toBe(streamed.text);
		expect(done.persistedId).toBe('a1');
	});

	it('a failure frame leaves the words shown', () => {
		const shown = shownAfter([piece('partial')]);
		expect(applyStreamEvent(shown, { type: 'error' } as CoWriterStreamEvent)).toEqual(shown);
	});
});
