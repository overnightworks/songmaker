import { words } from '#lib/words/en.ts';

/** The name of a song row's pencil, which opens the song in the editor. */
export function songEditorOpenName(title: string): string {
	return words['songRow.openInEditor']({ title });
}
