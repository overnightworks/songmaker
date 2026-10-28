import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { requiredAdminUsername } from './required-env';
import { requiredSeedId, seedJobState } from './seed';

const COVER_FIXTURE = path.join(
	path.dirname(fileURLToPath(import.meta.url)),
	'fixtures',
	'cover.png'
);

/**
 * A running cover suggestion job for `albumId`, seeded directly against the
 * database: CI's e2e stack mounts no image route, so no real run ever leaves
 * the failed state. `startedSecondsAgo` moves its start into the past, the
 * way a run that began a while before the page opened looks. Returns the job's id.
 */
export async function seedRunningCoverJob(
	albumId: string,
	options: { startedSecondsAgo?: number } = {}
): Promise<string> {
	const offsetArgs =
		options.startedSecondsAgo === undefined
			? []
			: ['--started-offset', String(options.startedSecondsAgo)];
	return requiredSeedId(
		await seedJobState('set-cover-running', [
			'--album-id',
			albumId,
			...offsetArgs,
			'--owner-username',
			requiredAdminUsername()
		])
	);
}

/**
 * Finishes a running cover job in place and publishes its one suggestion, the
 * way the web cover runner does when the image is ready.
 */
export async function completeCoverJob(jobId: string): Promise<void> {
	await seedJobState('set-cover-completed', ['--job-id', jobId], readFileSync(COVER_FIXTURE));
}
