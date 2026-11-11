// Chooses, for each shard of one project or suite, the newest attempt among
// the artifact directories a job downloaded: a re-run of failed jobs uploads
// again under a higher attempt while the green shards keep their first one.
// Usage: node e2e/shard-artifacts.ts <artifact-prefix> <project> <total> <directory>
// Prints one directory per shard that has an artifact, in shard order, and
// fails when a shard has none or a directory is not an artifact of the project.

import { existsSync, readdirSync } from 'node:fs';
import path from 'node:path';

type Scope = { prefix: string; project: string; total: number };

export type ShardChoice = { chosen: string[]; problems: string[] };

const POSITIVE_INTEGER = '[1-9][0-9]*';

function escapeRegExp(text: string): string {
	return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// An artifact is named `<prefix>-<project>-<shard>-<attempt>`. Whatever else
// stands in the directory is refused instead of ignored, so a report of another
// project can never stand in for a shard's own.
export function chooseNewestAttempts(names: readonly string[], scope: Scope): ShardChoice {
	const { prefix, project, total } = scope;
	const form = new RegExp(
		`^${escapeRegExp(`${prefix}-${project}-`)}(${POSITIVE_INTEGER})-(${POSITIVE_INTEGER})$`
	);
	const problems: string[] = [];
	const newest = new Map<number, { attempt: number; name: string }>();
	for (const name of names) {
		const match = form.exec(name);
		const shard = match ? Number(match[1]) : 0;
		if (!match || shard > total) {
			problems.push(
				`${name} is not an artifact of a shard of ${project} (${prefix}-${project}-<shard from 1 to ${total}>-<attempt>)`
			);
			continue;
		}
		const attempt = Number(match[2]);
		if (attempt > (newest.get(shard)?.attempt ?? 0)) {
			newest.set(shard, { attempt, name });
		}
	}
	const chosen: string[] = [];
	for (let shard = 1; shard <= total; shard++) {
		const entry = newest.get(shard);
		if (entry) {
			chosen.push(entry.name);
		} else {
			problems.push(`shard ${shard}/${total} has no ${prefix} artifact`);
		}
	}
	return { chosen, problems };
}

function main(): void {
	const [prefix, project, totalText, directory] = process.argv.slice(2);
	const total = Number(totalText);
	if (!prefix || !project || !directory || !Number.isInteger(total) || total < 1) {
		console.error(
			'Usage: node e2e/shard-artifacts.ts <artifact-prefix> <project> <total> <directory>'
		);
		process.exit(2);
	}
	const names = existsSync(directory) ? readdirSync(directory) : [];
	const { chosen, problems } = chooseNewestAttempts(names, { prefix, project, total });
	for (const name of chosen) {
		console.log(path.join(directory, name));
	}
	for (const problem of problems) {
		console.error(problem);
	}
	if (problems.length > 0) {
		process.exit(1);
	}
}

if (import.meta.main) {
	main();
}
