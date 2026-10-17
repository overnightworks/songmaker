type RandomSource = () => number;

const playbackRandom: RandomSource = () => Math.random(); // NOSONAR(S2245) Playback ordering does not generate secrets or security tokens.

interface ShuffleOptions {
	keepFirst?: boolean;
	random?: RandomSource;
}

export function shuffled<T>(
	items: readonly T[],
	{ keepFirst = false, random = playbackRandom }: ShuffleOptions = {}
): T[] {
	const result = [...items];
	const firstShuffledIndex = keepFirst ? 1 : 0;
	for (let i = result.length - 1; i > firstShuffledIndex; i--) {
		const j = firstShuffledIndex + Math.floor(random() * (i - firstShuffledIndex + 1));
		[result[i], result[j]] = [result[j], result[i]];
	}
	return result;
}
