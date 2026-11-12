// Generated from the catalogs by design-catalogs. Do not edit.

import type { Words } from "./en.js";

export const languages = ["en"] as const;
export type Language = (typeof languages)[number];
export const sourceLanguage: Language = "en";
// prettier-ignore
const modules: Record<Language, () => Promise<{ readonly words: Words }>> = {
    "en": () => import("./en.js"),
};
export const loadWords = async (language: Language): Promise<Words> => (await modules[language]()).words;
