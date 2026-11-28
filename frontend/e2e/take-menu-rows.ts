import { words } from '../src/lib/words/en';

/**
 * The take menu's rows in order for a take with a seed, Delete (the editor's alone)
 * left out. A take with a version opens it first; an imported take goes to its song.
 */
export function takeMenuRows(opensVersion: boolean): string[] {
	return [
		opensVersion ? words['takeMenu.openVersion'] : words['takeMenu.goToSong'],
		words['takeMenu.repaint'],
		words['takeMenu.cover'],
		words['takeMenu.useSeed'],
		words['takeMenu.rescore'],
		words['takeMenu.addTo'],
		words['takeMenu.share']
	];
}
