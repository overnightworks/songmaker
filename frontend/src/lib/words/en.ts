// Generated from the en catalog by design-catalogs. Do not edit.

export const language = "en";
// prettier-ignore
export type Words = {
    readonly "coverProblem.busy": string;
    readonly "coverProblem.budgetSpent": string;
    readonly "coverProblem.notEnabled": string;
    readonly "coverProblem.unavailable": string;
    readonly "coverProblem.signInAgain": string;
    readonly "cowriterProblem.busy": string;
    readonly "cowriterProblem.budgetSpent": string;
    readonly "cowriterProblem.notEnabled": string;
    readonly "cowriterProblem.signInAgain": string;
    readonly "cowriterProblem.unavailable": string;
    readonly "cowriterProblem.noAnswer": string;
    readonly "problemLine.logIn": string;
    readonly "problemLine.tryAgain": string;
    readonly "homeWrite.label": string;
    readonly "homeWrite.empty": string;
    readonly "homeWrite.loading": string;
    readonly "homeWrite.error": string;
    readonly "homeWrite.openSong": (gaps: { readonly title: string }) => string;
    readonly "homeWrite.workCreated": (gaps: { readonly time: string }) => string;
    readonly "homeWrite.workLyrics": (gaps: { readonly time: string }) => string;
    readonly "homeWrite.workStyle": (gaps: { readonly time: string }) => string;
    readonly "homeWrite.workRenamed": (gaps: { readonly time: string }) => string;
    readonly "homeWrite.workTake": (gaps: { readonly time: string }) => string;
    readonly "homeWrite.workCowriter": (gaps: { readonly time: string }) => string;
    readonly "homeWrite.workEdited": (gaps: { readonly time: string }) => string;
};
// prettier-ignore
export const words: Words = {
    "coverProblem.busy": "Cover suggestions are busy. Try again when Suggest opens.",
    "coverProblem.budgetSpent": "The budget for cover suggestions is used up. Try again later.",
    "coverProblem.notEnabled": "Cover suggestions are not enabled for your account. Ask an admin to enable them.",
    "coverProblem.unavailable": "Cover suggestions are unavailable right now. Try again later.",
    "coverProblem.signInAgain": "Log in again to get cover suggestions",
    "cowriterProblem.busy": "The co-writer is busy",
    "cowriterProblem.budgetSpent": "The co-writer's budget is used up. Try again later.",
    "cowriterProblem.notEnabled": "The co-writer is not enabled for your account",
    "cowriterProblem.signInAgain": "Log in again to use the co-writer",
    "cowriterProblem.unavailable": "The co-writer is unavailable",
    "cowriterProblem.noAnswer": "The co-writer did not answer. Try again.",
    "problemLine.logIn": "Log in",
    "problemLine.tryAgain": "Try again",
    "homeWrite.label": "Write",
    "homeWrite.empty": "Songs you work on will appear here.",
    "homeWrite.loading": "Loading Write…",
    "homeWrite.error": "Could not load Write.",
    "homeWrite.openSong": (gaps: { readonly title: string }) => "Open song " + gaps.title,
    "homeWrite.workCreated": (gaps: { readonly time: string }) => "new song · " + gaps.time,
    "homeWrite.workLyrics": (gaps: { readonly time: string }) => "lyrics edited · " + gaps.time,
    "homeWrite.workStyle": (gaps: { readonly time: string }) => "style edited · " + gaps.time,
    "homeWrite.workRenamed": (gaps: { readonly time: string }) => "renamed · " + gaps.time,
    "homeWrite.workTake": (gaps: { readonly time: string }) => "new take · " + gaps.time,
    "homeWrite.workCowriter": (gaps: { readonly time: string }) => "co-writer · " + gaps.time,
    "homeWrite.workEdited": (gaps: { readonly time: string }) => "edited · " + gaps.time,
};
export type Key = keyof Words;
