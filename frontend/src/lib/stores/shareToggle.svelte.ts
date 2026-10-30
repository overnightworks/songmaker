import type { ShareResult } from '#lib/api/types.ts';
import { describeFailure } from '#lib/api/fetch.ts';
import {
	SHARE_BUTTON_COPIED_TOAST,
	SHARE_BUTTON_COPY_FAILED_TOAST,
	SHARE_BUTTON_FAILED_TOAST,
	SHARE_BUTTON_UNSHARED_TOAST
} from '#lib/constants.ts';
import { sharePagePath, type ShareKind } from '#lib/routes/addresses.ts';
import { addToast } from './toast';

interface ShareToggleSource {
	kind: ShareKind;
	isShared: boolean;
	shareSlug: string | null | undefined;
	onshare: () => Promise<ShareResult>;
	onunshare: () => Promise<void>;
}

/**
 * The one tap on a share control, whatever it looks like: unshares a shared
 * item, otherwise shares it and copies the link, telling the person which.
 * It also owns how the control shows its state: the icon, and the tooltip
 * that names the share page once shared.
 */
export function createShareToggle(source: () => ShareToggleSource) {
	let busy = $state(false);

	async function toggle(): Promise<void> {
		if (busy) return;
		busy = true;
		try {
			const { isShared, onshare, onunshare } = source();
			if (isShared) {
				await onunshare();
				addToast(SHARE_BUTTON_UNSHARED_TOAST, 'success');
			} else {
				const result = await onshare();
				try {
					await navigator.clipboard.writeText(result.share_url);
					addToast(SHARE_BUTTON_COPIED_TOAST, 'success');
				} catch {
					addToast(SHARE_BUTTON_COPY_FAILED_TOAST, 'success');
				}
			}
		} catch (e) {
			addToast(describeFailure(e, SHARE_BUTTON_FAILED_TOAST), 'error');
		} finally {
			busy = false;
		}
	}

	return {
		get busy() {
			return busy;
		},
		get iconName() {
			return source().isShared ? 'link' : 'share';
		},
		get sharedTooltip() {
			const { kind, isShared, shareSlug } = source();
			return isShared ? `Shared: ${sharePagePath(kind, shareSlug ?? '')}` : undefined;
		},
		toggle
	};
}
