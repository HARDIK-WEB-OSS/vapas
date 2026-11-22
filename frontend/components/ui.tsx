"use client";

import { useId, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode } from "react";

import { ApiError } from "@/lib/api";
import { useI18n } from "@/lib/i18n-client";

type Tone = "primary" | "secondary" | "danger";

const TONES: Record<Tone, string> = {
  primary: "bg-brand text-on-brand hover:bg-brand-strong",
  secondary: "border border-line bg-surface hover:bg-surface-strong",
  danger: "bg-danger text-on-brand hover:opacity-90",
};

export function Button({ tone = "primary", className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { tone?: Tone }) {
  return (
    <button
      className={`min-h-11 rounded-lg px-4 py-2 text-base font-medium disabled:cursor-not-allowed disabled:opacity-50 ${TONES[tone]} ${className}`}
      {...props}
    />
  );
}

export function Field({ label, hint, ...props }: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string }) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="font-medium">
        {label}
      </label>
      <input
        id={id}
        aria-describedby={hint ? `${id}-hint` : undefined}
        className="min-h-11 rounded-lg border border-line bg-surface px-3 py-2 text-base"
        {...props}
      />
      {hint ? (
        <p id={`${id}-hint`} className="text-sm text-muted">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export function Check({ label, ...props }: InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  const id = useId();
  return (
    <div className="flex items-start gap-3">
      <input id={id} type="checkbox" className="mt-1 size-5 shrink-0" {...props} />
      <label htmlFor={id}>{label}</label>
    </div>
  );
}

export function YesNo({ legend, name, value, onChange }: { legend: string; name: string; value: boolean | null; onChange: (value: boolean) => void }) {
  const { t } = useI18n();
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1 font-medium">{legend}</legend>
      <div className="flex gap-4">
        {[true, false].map((option) => (
          <label key={String(option)} className="flex min-h-11 items-center gap-2">
            <input type="radio" name={name} className="size-5" checked={value === option} onChange={() => onChange(option)} />
            {option ? t.common.yes : t.common.no}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-xl border border-line bg-surface p-4 ${className}`}>{children}</section>;
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warn" | "error" | "ok"; children: ReactNode }) {
  const styles = {
    info: "border-line bg-surface-strong",
    warn: "border-warn bg-warn-soft",
    error: "border-danger bg-danger-soft",
    ok: "border-brand bg-brand-soft",
  }[tone];
  return (
    <div role={tone === "error" ? "alert" : "status"} className={`rounded-lg border-l-4 p-3 ${styles}`}>
      {children}
    </div>
  );
}

export function errorCode(error: unknown): string {
  return error instanceof ApiError ? error.code : "generic";
}

export function ErrorMessage({ code }: { code: string | null }) {
  const { t } = useI18n();
  if (!code) return null;
  const messages = t.errors as Record<string, string>;
  return <Notice tone="error">{messages[code] ?? t.errors.generic}</Notice>;
}

export function PageTitle({ children }: { children: ReactNode }) {
  return <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{children}</h1>;
}

export function Loading() {
  const { t } = useI18n();
  return (
    <p role="status" className="text-muted">
      {t.common.loading}
    </p>
  );
}
