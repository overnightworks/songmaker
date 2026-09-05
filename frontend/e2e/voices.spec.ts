import { mkdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';

import {
	deleteVoiceProofData,
	queueGenerateForVoiceProof,
	queueVoiceAdapterComparison,
	seedVoiceAdapterComparisonSong,
	seedVoiceDrafts,
	seedVoiceTake,
	setVoiceProofModelMode,
	VOICES_OCCUPANCY_PROMPT,
	type QueuedJob
} from './seed';

const SCREENSHOT_DIR =
	'/tmp/claude-1000/-home-felix-hummert-git-songmaker/b3634502-0150-4c8a-93e5-9818e2d499a2/scratchpad/issue-544';
const FAILED_TRAINING_CAPTION = 'e2e fake training failure';
const TAKE_FIXTURE = fileURLToPath(new URL('./fixtures/take.mp3', import.meta.url));

test.skip(
	process.env.E2E_VOICES_STACK !== '1',
	'Voices proof requires the docker-compose.e2e-voices.yml worker override.'
);

interface VoiceState {
	id: string;
	status: string;
	storage_path: string | null;
	training_job_id: string | null;
	error: string | null;
}

interface CreatedVoice {
	card: Locator;
	id: string;
}

interface GeneratedTake {
	id: string;
	wav_path: string | null;
}

interface GeneratedSong {
	generations: GeneratedTake[];
}

async function createVoice(page: Page, name: string): Promise<CreatedVoice> {
	await page.getByRole('button', { name: 'New Voice', exact: true }).click();
	await page.getByPlaceholder('Voice name (e.g. My Tenor)').fill(name);
	const createdResponse = page.waitForResponse(
		(response) =>
			response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/loras'
	);
	await page.getByRole('button', { name: 'Create', exact: true }).click();
	const response = await createdResponse;
	expect(response.ok(), `Create voice failed: ${await response.text()}`).toBeTruthy();
	const { id } = (await response.json()) as { id: string };
	const card = page.locator('.lora-card').filter({ hasText: name });
	await expect(card).toBeVisible();
	return { card, id };
}

async function addOwnTake(voice: Locator, sourceTitle: string): Promise<void> {
	const ownTakesResponse = voice
		.page()
		.waitForResponse(
			(response) =>
				response.request().method() === 'GET' &&
				new URL(response.url()).pathname === '/api/loras/own-takes'
		);
	await voice.getByRole('button', { name: 'Use a take', exact: true }).click();
	await expect((await ownTakesResponse).ok()).toBeTruthy();
	const ownTakes = voice.getByRole('region', { name: 'Your takes', exact: true });
	const sourceTake = ownTakes.locator('li').filter({ hasText: sourceTitle });
	await expect(sourceTake).toContainText('Take 1');
	await sourceTake.getByRole('button', { name: 'Use as sample', exact: true }).click();
	await expect(voice.locator('.sample-list li')).toHaveCount(1);
}

async function addUploadedSample(
	voice: Locator,
	caption: string,
	lyrics: string,
	expectedSampleCount: number
): Promise<void> {
	const upload = voice.getByRole('region', { name: 'Add sample', exact: true });
	const fileInput = upload.locator('input[type="file"]');
	await fileInput.setInputFiles({
		name: `${caption.replaceAll(' ', '-')}.mp3`,
		mimeType: 'audio/mpeg',
		buffer: readFileSync(TAKE_FIXTURE)
	});
	await upload.locator('textarea').nth(0).fill(caption);
	await upload.locator('textarea').nth(1).fill(lyrics);
	await upload.getByRole('button', { name: 'Add sample', exact: true }).click();
	await expect(voice.locator('.sample-list li')).toHaveCount(expectedSampleCount);
}

async function addThreeSamples(
	voice: Locator,
	sourceTitle: string,
	failed: boolean = false
): Promise<void> {
	await addOwnTake(voice, sourceTitle);
	await addUploadedSample(voice, 'uploaded e2e caption', 'uploaded e2e lyrics', 2);
	await addUploadedSample(
		voice,
		failed ? FAILED_TRAINING_CAPTION : 'second uploaded e2e caption',
		failed ? 'failed e2e lyrics' : 'second uploaded e2e lyrics',
		3
	);
}

async function readVoice(request: APIRequestContext, voiceId: string): Promise<VoiceState> {
	const response = await request.get(`/api/loras/${voiceId}`);
	expect(response.ok(), `GET voice failed: ${await response.text()}`).toBeTruthy();
	return (await response.json()) as VoiceState;
}

async function readJob(request: APIRequestContext, jobId: string): Promise<QueuedJob> {
	const response = await request.get(`/api/jobs/${jobId}`);
	expect(response.ok(), `GET job failed: ${await response.text()}`).toBeTruthy();
	return (await response.json()) as QueuedJob;
}

async function readGeneratedSong(
	request: APIRequestContext,
	songId: string
): Promise<GeneratedSong> {
	const response = await request.get(`/api/songs/${songId}`);
	expect(response.ok(), `GET song failed: ${await response.text()}`).toBeTruthy();
	return (await response.json()) as GeneratedSong;
}

async function waitForGeneratedTake(
	request: APIRequestContext,
	songId: string,
	jobId: string
): Promise<GeneratedTake> {
	await expect
		.poll(() => readJob(request, jobId).then((job) => job.status), { timeout: 40_000 })
		.toBe('completed');
	await expect
		.poll(() => readGeneratedSong(request, songId).then((song) => song.generations.at(0) ?? null))
		.not.toBeNull();
	const take = (await readGeneratedSong(request, songId)).generations.at(0);
	if (!take) throw new Error(`Generation job ${jobId} completed without a take`);
	return take;
}

async function readGeneratedWav(request: APIRequestContext, take: GeneratedTake): Promise<Buffer> {
	expect(take.wav_path).toBeTruthy();
	const response = await request.get(`/audio/${take.wav_path}`);
	expect(response.ok(), `GET generated WAV failed: ${await response.text()}`).toBeTruthy();
	return response.body();
}

function trainingJobId(voice: VoiceState): string {
	expect(voice.training_job_id).toBeTruthy();
	if (!voice.training_job_id) throw new Error(`Voice ${voice.id} has no training job`);
	return voice.training_job_id;
}

async function waitForReadyVoice(request: APIRequestContext, voiceId: string): Promise<void> {
	await expect
		.poll(() => readVoice(request, voiceId).then((voice) => voice.status), { timeout: 40_000 })
		.toBe('ready');
}

async function expandVoice(voice: Locator): Promise<void> {
	const row = voice.locator('.lora-row');
	if ((await row.getAttribute('aria-expanded')) === 'false') await row.click();
}

async function openAdminVoices(page: Page): Promise<Locator> {
	await page.goto('/settings/users');
	await expect(page.getByRole('heading', { name: 'Admin', exact: true })).toBeVisible();
	const tabs = page.getByRole('combobox', { name: /Admin (tabs|sections)/ });
	if (await tabs.count()) await tabs.selectOption('voices');
	else await page.getByRole('button', { name: 'Voices', exact: true }).click();
	const section = page
		.locator('section')
		.filter({ has: page.getByRole('heading', { name: 'Voice operations' }) });
	await expect(section).toBeVisible();
	return section;
}

test('the Voices override proves create, mode binding, adapter effect, deletion, waiting, progress, ready, failed, limits and admin visibility at desktop and 375px', async ({
	page,
	request,
	isMobile
}) => {
	test.setTimeout(180_000);
	if (isMobile) await page.setViewportSize({ width: 375, height: 844 });
	const source = await seedVoiceTake(request);
	const marker = Date.now().toString(36);
	const voiceName = `E2E Voice ${marker}`;
	const foreignVoiceName = `E2E Foreign Voice ${marker}`;
	const failedVoiceName = `E2E Failed Voice ${marker}`;
	const voiceIds: string[] = [];

	try {
		await page.goto('/settings/voices');
		const createdVoice = await createVoice(page, voiceName);
		voiceIds.push(createdVoice.id);
		const voice = createdVoice.card;
		await expect(voice.getByText('No samples yet. Add at least 3 to train.')).toBeVisible();
		const sampleFields = voice.locator('.sample-list textarea');
		await addThreeSamples(voice, source.songTitle);
		await expect(sampleFields.nth(0)).toHaveValue(source.caption);
		await expect(sampleFields.nth(1)).toHaveValue(source.lyrics);

		expect(source.caption).toBe(VOICES_OCCUPANCY_PROMPT);
		const generateJob = await queueGenerateForVoiceProof(request, source.songId, source.versionId);
		expect(generateJob.status).toBe('queued');
		await expect
			.poll(() => readJob(request, generateJob.id).then((job) => job.status))
			.toBe('running');
		await voice.getByRole('button', { name: 'Train voice', exact: true }).click();
		await expect(voice.getByText('Waiting', { exact: true })).toBeVisible({ timeout: 15_000 });
		await expect(voice).toContainText('Waiting for queued generations on this GPU.');
		await expect(voice).toContainText('Position 1 in the queue');
		await expect(voice.getByText(/^Epoch \d+ of \d+$/)).toBeVisible({ timeout: 35_000 });
		await expect(voice.getByText('ready', { exact: true })).toBeVisible({ timeout: 40_000 });
		await expect(voice.locator('.model-mode')).toHaveText('sft');

		const readyVoice = await readVoice(request, createdVoice.id);
		expect(readyVoice.status).toBe('ready');
		expect(readyVoice.storage_path).toBeTruthy();
		const readyJob = await readJob(request, trainingJobId(readyVoice));
		expect(readyJob.status).toBe('completed');

		const foreignVoice = await createVoice(page, foreignVoiceName);
		voiceIds.push(foreignVoice.id);
		await addThreeSamples(foreignVoice.card, source.songTitle);
		await foreignVoice.card.getByRole('button', { name: 'Train voice', exact: true }).click();
		await waitForReadyVoice(request, foreignVoice.id);
		await setVoiceProofModelMode(foreignVoice.id, 'turbo');
		await page.goto('/settings/voices');
		const foreignVoiceCard = page.locator('.lora-card').filter({ hasText: foreignVoiceName });
		await expect(foreignVoiceCard.getByText('ready', { exact: true })).toBeVisible();
		await expect(foreignVoiceCard.locator('.model-mode')).toHaveText('turbo');

		const adapterSong = await seedVoiceAdapterComparisonSong(request, createdVoice.id);
		const baselineSong = await seedVoiceAdapterComparisonSong(request, null);
		const adapterGeneration = await queueVoiceAdapterComparison(
			request,
			adapterSong.songId,
			adapterSong.versionId,
			4242
		);
		const adapterTake = await waitForGeneratedTake(
			request,
			adapterSong.songId,
			adapterGeneration.id
		);
		const baselineGeneration = await queueVoiceAdapterComparison(
			request,
			baselineSong.songId,
			baselineSong.versionId,
			4242
		);
		const baselineTake = await waitForGeneratedTake(
			request,
			baselineSong.songId,
			baselineGeneration.id
		);
		expect(await readGeneratedWav(request, adapterTake)).not.toEqual(
			await readGeneratedWav(request, baselineTake)
		);

		await page.goto(`/album/${adapterSong.albumId}/${adapterSong.songSlug}`);
		await expect(page.getByRole('heading', { name: /E2E With Voice/ })).toBeVisible();
		await page
			.getByRole('group', { name: 'Editor views', exact: true })
			.getByRole('button', { name: 'Recipe', exact: true })
			.click();
		const picker = page.locator('.voice-picker .picker');
		await picker.click();
		const options = page.getByRole('listbox', { name: 'Your Voice', exact: true });
		const matchingVoice = options.getByRole('option', { name: new RegExp(voiceName) });
		const foreignVoiceOption = options.getByRole('option', { name: new RegExp(foreignVoiceName) });
		await expect(matchingVoice).toContainText('sft');
		expect(await matchingVoice.isDisabled()).toBe(false);
		await expect(foreignVoiceOption).toContainText('turbo');
		await expect(foreignVoiceOption).toContainText('not available for this model');
		expect(await foreignVoiceOption.isDisabled()).toBe(true);

		await page.goto('/settings/voices');
		const readyVoiceCard = page.locator('.lora-card').filter({ hasText: voiceName });
		await readyVoiceCard.getByRole('button', { name: 'Delete', exact: true }).click();
		const deleteDialog = page.getByRole('dialog');
		await expect(
			deleteDialog.getByRole('heading', { name: 'Delete voice?', exact: true })
		).toBeVisible();
		await expect(deleteDialog).toContainText(
			`${voiceName} will be hidden from new generations. Existing takes keep their audio and remain playable; they will show “voice deleted”.`
		);
		await deleteDialog.getByRole('button', { name: 'Delete', exact: true }).click();

		await page.goto(`/album/${adapterSong.albumId}/${adapterSong.songSlug}`);
		await page
			.getByRole('group', { name: 'Editor views', exact: true })
			.getByRole('button', { name: 'Recipe', exact: true })
			.click();
		if (isMobile) {
			await expect(page.locator('.voice-picker .mobile-label')).toHaveText(
				'Your Voice · sft model'
			);
		}
		const deletedPicker = page.locator('.voice-picker .picker');
		await deletedPicker.click();
		const deletedVoiceOption = page
			.getByRole('listbox', { name: 'Your Voice', exact: true })
			.getByRole('option', { name: new RegExp(`${voiceName}.*voice deleted`) });
		await expect(deletedVoiceOption).toContainText(`${voiceName} — voice deleted`);
		expect(await deletedVoiceOption.isDisabled()).toBe(true);
		await deletedPicker.click();
		if (isMobile) {
			await page.getByRole('button', { name: 'Collapse ˄', exact: true }).click();
			const deletedVoiceTake = page.locator('.take-chip').filter({ hasText: 'v1 · take 1' });
			await expect(deletedVoiceTake).toBeVisible();
			await deletedVoiceTake.click();
			await expect(deletedVoiceTake).toHaveClass(/playing/);
		} else {
			const deletedVoiceTake = page.locator('.take-row').filter({ hasText: voiceName });
			await expect(deletedVoiceTake).toContainText(`Voice: ${voiceName} — voice deleted`);
			const deletedVoicePlayTarget = deletedVoiceTake.getByRole('button', {
				name: /v1.*take 1/
			});
			await expect(deletedVoicePlayTarget).toBeVisible();
		}

		await page.goto('/settings/voices');
		const failedVoice = await createVoice(page, failedVoiceName);
		voiceIds.push(failedVoice.id);
		await addThreeSamples(failedVoice.card, source.songTitle, true);
		await failedVoice.card.getByRole('button', { name: 'Train voice', exact: true }).click();
		await expect(failedVoice.card.getByText('Training failed', { exact: true })).toBeVisible({
			timeout: 15_000
		});
		await expect(failedVoice.card).toContainText('Worker training failed');
		const failedState = await readVoice(request, failedVoice.id);
		expect(failedState.status).toBe('failed');
		expect(failedState.error).toBe('Worker training failed');
		expect((await readJob(request, trainingJobId(failedState))).status).toBe('failed');

		const queuedVoiceOne = await createVoice(page, `E2E Queue One ${marker}`);
		voiceIds.push(queuedVoiceOne.id);
		await addThreeSamples(queuedVoiceOne.card, source.songTitle);
		const queuedVoiceTwo = await createVoice(page, `E2E Queue Two ${marker}`);
		voiceIds.push(queuedVoiceTwo.id);
		await addThreeSamples(queuedVoiceTwo.card, source.songTitle);
		const queueBlockingGenerate = await queueGenerateForVoiceProof(
			request,
			source.songId,
			source.versionId
		);
		expect(queueBlockingGenerate.status).toBe('queued');
		await expect
			.poll(() => readJob(request, queueBlockingGenerate.id).then((job) => job.status))
			.toBe('running');
		await expandVoice(queuedVoiceOne.card);
		await queuedVoiceOne.card.getByRole('button', { name: 'Train voice', exact: true }).click();
		await expandVoice(queuedVoiceTwo.card);
		await queuedVoiceTwo.card.getByRole('button', { name: 'Train voice', exact: true }).click();
		await expect(queuedVoiceTwo.card.getByText('Waiting', { exact: true })).toBeVisible({
			timeout: 15_000
		});
		await expandVoice(failedVoice.card);
		await failedVoice.card.getByRole('button', { name: 'Train again', exact: true }).click();
		await expect(failedVoice.card.locator('.training-error')).toContainText(
			'Training queue is full'
		);
		await expect
			.poll(() => readVoice(request, queuedVoiceOne.id).then((voice) => voice.status))
			.toBe('queued');
		await waitForReadyVoice(request, queuedVoiceOne.id);
		await waitForReadyVoice(request, queuedVoiceTwo.id);

		voiceIds.push(...(await seedVoiceDrafts(request, 6)));
		await page.getByRole('button', { name: 'New Voice', exact: true }).click();
		await page
			.getByPlaceholder('Voice name (e.g. My Tenor)')
			.fill(`E2E Voice Over Limit ${marker}`);
		await page.getByRole('button', { name: 'Create', exact: true }).click();
		await expect(page.locator('.create-error')).toContainText(
			'You have reached the limit of 10 voices.'
		);

		mkdirSync(SCREENSHOT_DIR, { recursive: true });
		await page.screenshot({
			path: `${SCREENSHOT_DIR}/live-s55-${isMobile ? '375' : 'desktop'}.png`,
			fullPage: true
		});

		const adminVoices = await openAdminVoices(page);
		await expect(adminVoices).toContainText(foreignVoiceName);
		await expect(adminVoices).toContainText(failedVoiceName);
		await expect(adminVoices.getByRole('button')).toHaveCount(0);

		if (isMobile) {
			await expect
				.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
				.toBe(true);
		}
	} finally {
		await deleteVoiceProofData(request, voiceIds);
	}
});
