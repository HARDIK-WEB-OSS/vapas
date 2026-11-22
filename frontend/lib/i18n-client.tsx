"use client";

import { createContext, useContext, type ReactNode } from "react";

import type { Locale, Messages } from "@/lib/text";

type I18n = { lang: Locale; t: Messages };

const I18nContext = createContext<I18n | null>(null);

export function I18nProvider({ lang, messages, children }: { lang: Locale; messages: Messages; children: ReactNode }) {
  return <I18nContext.Provider value={{ lang, t: messages }}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18n {
  const value = useContext(I18nContext);
  if (!value) throw new Error("I18nProvider is missing");
  return value;
}
