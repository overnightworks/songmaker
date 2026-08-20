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
