import type { MemoryBundle, MemoryScopeItem } from '$lib/api/types';

export type MemoryScope = 'user' | 'song' | 'album';

export interface MemoryProposal {
	scope: MemoryScope;
	targetId: string | null;
	currentBody: string;
	proposedBody: string;
}

const PROPOSAL_RE =
	/<memory_proposal\s+scope="(user|song|album)"(?:\s+target_id="([^"]*)")?\s*>\s*<current>([\s\S]*?)<\/current>\s*<proposed>([\s\S]*?)<\/proposed>\s*<\/memory_proposal>/gi;

export function parseMemoryProposals(text: string): MemoryProposal[] {
	const out: MemoryProposal[] = [];
	for (const match of text.matchAll(PROPOSAL_RE)) {
		out.push({
			scope: match[1] as MemoryScope,
			targetId: match[2] ? match[2] : null,
			currentBody: match[3].trim(),
			proposedBody: match[4].trim()
		});
	}
	return out;
}

export function stripMemoryProposals(text: string): string {
	return text.replace(PROPOSAL_RE, '').trim();
}

export function proposalKey(proposal: MemoryProposal): string {
	return `${proposal.scope}:${proposal.targetId ?? ''}:${proposal.proposedBody}`;
}

export function collectPendingProposals(
	assistantTexts: string[],
	rejectedKeys: string[]
): MemoryProposal[] {
	const rejected = new Set(rejectedKeys);
	const found: MemoryProposal[] = [];
	const seen = new Set<string>();
	for (const text of assistantTexts) {
		for (const proposal of parseMemoryProposals(text)) {
			const key = proposalKey(proposal);
			if (rejected.has(key) || seen.has(key)) continue;
			seen.add(key);
			found.push(proposal);
		}
	}
	return found;
}

export function memoryItemForScope(
	bundle: MemoryBundle | null,
	scope: MemoryScope
): MemoryScopeItem | null {
	if (!bundle) return null;
	if (scope === 'user') return bundle.user;
	if (scope === 'song') return bundle.song ?? null;
	return bundle.album ?? null;
}

export function proposalTargetForMemory(
	proposal: MemoryProposal,
	bundle: MemoryBundle | null
): string | null {
	const item = memoryItemForScope(bundle, proposal.scope);
	if (!item) return null;
	if (proposal.targetId !== null && proposal.targetId !== item.target_id) return null;
	if (proposal.currentBody !== item.body.trim()) return null;
	return item.target_id;
}

export function shouldReplaceMemoryDraft(
	previousTargetId: string | null,
	previousBody: string,
	draft: string,
	nextTargetId: string | null
): boolean {
	return previousTargetId !== nextTargetId || draft === previousBody;
}
