import type en from "@/messages/en.json";

export type Messages = typeof en;

export const LOCALES = ["en", "hi"] as const;

export type Locale = (typeof LOCALES)[number];

export function isLocale(value: string): value is Locale {
  return (LOCALES as readonly string[]).includes(value);
}

export function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (match, key: string) => (key in values ? String(values[key]) : match));
}

export function pathFor(lang: Locale, path: string): string {
  return `/${lang}${path === "/" ? "" : path}`;
}
