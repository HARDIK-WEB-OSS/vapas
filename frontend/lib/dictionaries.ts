import en from "@/messages/en.json";
import hi from "@/messages/hi.json";
import type { Locale, Messages } from "@/lib/text";

const DICTIONARIES: Record<Locale, Messages> = { en, hi };

export function messagesFor(lang: Locale): Messages {
  return DICTIONARIES[lang];
}
