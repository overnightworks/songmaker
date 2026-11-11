export const COWRITER_TURN_TIMEOUT_MS = 600_000;
export const COWRITER_RUNNING_TURN_POLL_MS = 2_000;
export const COWRITER_RUNNING_TURN_POLL_FAILURE_LIMIT = 3;
export const COWRITER_BUSY_WAIT_CEILING_SECONDS = 300;
export const COWRITER_CONVERSATION_MENU_LABEL = 'Conversation menu';
export const COWRITER_COMPOSER_PLACEHOLDER = 'Ask for a rewrite…';
export const COWRITER_SEND_LABEL = 'Send';
export const COWRITER_NEW_CONVERSATION_LABEL = 'New conversation';
export const COWRITER_MEMORY_LABEL = 'Memory';
export const COWRITER_MEMORY_PROPOSAL_WAITING_LABEL = 'Memory proposal waiting';
export const COWRITER_DELETE_CONVERSATION_TITLE = 'Delete conversation?';
export const COWRITER_DELETE_CONVERSATION_WARNING = "This can't be undone.";
export const COWRITER_NEW_CONVERSATION_LINE = 'new conversation';
export const COWRITER_CONVERSATION_SINCE_TEMPLATE = 'conversation since {day}';
export const COWRITER_ARCHIVED_CONVERSATION_TEMPLATE = 'archived conversation from {day}';
export const COWRITER_CONVERSATION_ROW_TEMPLATE = 'Conversation since {day} {time}';
export const COWRITER_ARCHIVED_CONVERSATION_ROW_TEMPLATE = 'Archived · {day} {time}';
export const COWRITER_MESSAGE_COUNT_TEMPLATE = '{count} msgs';
export const COWRITER_SINGLE_MESSAGE_COUNT = '1 msg';
export const COWRITER_CONVERSATION_CONFIRM_TEMPLATE = '{name} · {count}';
// The co-writer is one global conversation (REQ-COWRITER-01): a proposal
// streamed while song X is open can target song Y. Every tool-call badge
// that attributes a proposal to its target song shares this copy.
export const COWRITER_TOOL_CALL_TARGET_PREFIX = 'for:';
export const COWRITER_TOOL_CALL_FOREIGN_TARGET_TITLE =
	'This proposal applies to a different song than the one you have open';
export const COWRITER_TURN_PATH = '/api/chat/turn';
