"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { Page, Protected } from "@/components/shell";
import { Button, Card, ErrorMessage, errorCode, Field, Loading, Notice, PageTitle } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { day } from "@/lib/format";
import { useI18n } from "@/lib/i18n-client";
import { useSession } from "@/lib/session";
import { fill, pathFor } from "@/lib/text";
import type { FileKind, PresignOut, Statement } from "@/lib/types";
import { useLoad } from "@/lib/use-load";

const MAX_BYTES = 10 * 1024 * 1024;
const POLL_MS = 3000;
const BUSY_STATUSES = new Set(["queued", "parsing"]);
const KINDS: Record<string, FileKind> = { pdf: "pdf", csv: "csv", xls: "xls", xlsx: "xlsx" };

function kindOf(file: File): FileKind | null {
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  return KINDS[extension] ?? null;
}

async function sha256Hex(file: File): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function putFile(url: string, file: File, contentType: string): Promise<void> {
  const response = await fetch(url, { method: "PUT", headers: { "Content-Type": contentType }, body: file }).catch(() => null);
  if (!response?.ok) throw new ApiError(409, "upload_incomplete", "upload failed");
}

export function ProcessingGate({ children }: { children: React.ReactNode }) {
  const { me } = useSession();
  const { lang, t } = useI18n();
  if (me && !me.email_verified) return <Notice tone="warn">{t.errors.email_not_verified}</Notice>;
  if (me && !me.consent_active) {
    return (
      <Notice tone="warn">
        {t.errors.consent_withdrawn}{" "}
        <Link href={pathFor(lang, "/settings")} className="underline">
          {t.nav.settings}
        </Link>
      </Notice>
    );
  }
  return <>{children}</>;
}

function UploadForm() {
  const { lang, t } = useI18n();
  const router = useRouter();
  const [phase, setPhase] = useState<"idle" | "hashing" | "uploading">("idle");
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const file = form.get("file");
    const password = String(form.get("password") ?? "");
    setError(null);
    if (!(file instanceof File) || file.size === 0) return;
    const kind = kindOf(file);
    if (!kind) return setError("file_type");
    if (file.size > MAX_BYTES) return setError("file_too_large");
    try {
      setPhase("hashing");
      const sha256 = await sha256Hex(file);
      const presign = await api<PresignOut>("/statements/presign", {
        method: "POST",
        body: { sha256, size_bytes: file.size, file_kind: kind },
      });
      if (!presign.duplicate && presign.upload_url) {
        setPhase("uploading");
        await putFile(presign.upload_url, file, presign.content_type);
        await api(`/statements/${presign.statement_id}/confirm`, {
          method: "POST",
          body: { password: password || null },
        });
      }
      formElement.reset();
      router.push(pathFor(lang, presign.duplicate ? "/statements?duplicate=1" : "/statements"));
    } catch (problem) {
      setError(errorCode(problem));
    } finally {
      setPhase("idle");
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <Field label={t.upload.file} name="file" type="file" accept=".pdf,.csv,.xls,.xlsx" required />
      <Field label={t.upload.password} name="password" type="password" autoComplete="off" hint={t.upload.passwordNote} />
      <ErrorMessage code={error} />
      <Button type="submit" disabled={phase !== "idle"}>
        {phase === "hashing" ? t.upload.hashing : phase === "uploading" ? t.upload.uploading : t.upload.button}
      </Button>
    </form>
  );
}

export function Upload() {
  const { lang, t } = useI18n();
  return (
    <Page>
      <PageTitle>{t.upload.title}</PageTitle>
      <Protected>
        <ProcessingGate>
          <UploadForm />
        </ProcessingGate>
        <ul className="list-disc space-y-1 pl-5 text-sm text-muted">
          {t.upload.what.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
        <Link href={pathFor(lang, "/guide")} className="underline">
          {t.upload.guide}
        </Link>
      </Protected>
    </Page>
  );
}

function PasswordRetry({ statement, onDone }: { statement: Statement; onDone: () => Promise<void> }) {
  const { t } = useI18n();
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await api(`/statements/${statement.id}/password`, { method: "POST", body: { password: form.get("password") } });
      await onDone();
    } catch (problem) {
      setError(errorCode(problem));
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <Field label={t.upload.password} name="password" type="password" autoComplete="off" hint={t.upload.passwordNote} required />
      <ErrorMessage code={error} />
      <Button type="submit" tone="secondary">
        {t.statements.passwordButton}
      </Button>
    </form>
  );
}

function StatementCard({ statement, reload }: { statement: Statement; reload: () => Promise<void> }) {
  const { lang, t } = useI18n();
  const statuses = t.statements.status as Record<string, string>;
  return (
    <Card className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">
          {statement.bank_code ?? statement.file_kind.toUpperCase()} · {day(statement.created_at)}
        </h2>
        <span className="rounded-full bg-surface-strong px-3 py-1 text-sm" data-testid="statement-status">
          {statuses[statement.status] ?? statement.status}
        </span>
      </div>
      {statement.period_from && statement.period_to ? (
        <p className="text-sm">{fill(t.statements.period, { from: day(statement.period_from), to: day(statement.period_to) })}</p>
      ) : null}
      {statement.rows_parsed !== null ? <p className="text-sm">{fill(t.statements.rows, { rows: statement.rows_parsed })}</p> : null}
      {statement.reconciled ? <p className="text-sm text-brand">✓ {t.statements.reconciled}</p> : null}
      {statement.analysis_note ? (
        <Notice tone="warn">
          {statement.analysis_note}
          {lang === "hi" ? <span className="block text-xs">{t.common.englishOnly}</span> : null}
        </Notice>
      ) : null}
      {statement.status === "needs_password" ? <PasswordRetry statement={statement} onDone={reload} /> : null}
      {statement.status === "parsed" ? (
        <Link href={pathFor(lang, "/findings")} className="underline">
          {t.dashboard.findingsCta}
        </Link>
      ) : null}
    </Card>
  );
}

function StatementList() {
  const { lang, t } = useI18n();
  const load = useCallback(() => api<Statement[]>("/statements"), []);
  const statements = useLoad(load);
  const [duplicate] = useState(() => typeof window !== "undefined" && window.location.search.includes("duplicate=1"));
  const busy = statements.data?.some((item) => BUSY_STATUSES.has(item.status)) ?? false;
  const { reload } = statements;

  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(() => void reload(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [busy, reload]);

  if (statements.error) return <ErrorMessage code={statements.error} />;
  if (!statements.data) return <Loading />;
  return (
    <div className="flex flex-col gap-4">
      {duplicate ? <Notice>{t.upload.duplicate}</Notice> : null}
      {statements.data.length === 0 ? <p>{t.statements.empty}</p> : null}
      {statements.data.map((statement) => (
        <StatementCard key={statement.id} statement={statement} reload={reload} />
      ))}
      <Link href={pathFor(lang, "/upload")} className="self-start rounded-lg bg-brand px-4 py-2 font-medium text-on-brand">
        {t.dashboard.uploadCta}
      </Link>
    </div>
  );
}

export function Statements() {
  const { t } = useI18n();
  return (
    <Page>
      <PageTitle>{t.statements.title}</PageTitle>
      <Protected>
        <StatementList />
      </Protected>
    </Page>
  );
}
