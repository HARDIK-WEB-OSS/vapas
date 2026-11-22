"use client";

import Link from "next/link";
import { useState } from "react";

import { Page, Protected } from "@/components/shell";
import { Card, ErrorMessage, errorCode, Loading, Notice, PageTitle } from "@/components/ui";
import { api } from "@/lib/api";
import { money } from "@/lib/format";
import { useI18n } from "@/lib/i18n-client";
import { useSession } from "@/lib/session";
import { fill, pathFor } from "@/lib/text";
import type { CaseSummary, Finding, Notification } from "@/lib/types";
import { useLoad } from "@/lib/use-load";

type Summary = { findings: Finding[]; cases: CaseSummary[]; notifications: Notification[] };

async function loadSummary(): Promise<Summary> {
  const [findings, cases, notifications] = await Promise.all([
    api<Finding[]>("/findings"),
    api<CaseSummary[]>("/cases"),
    api<Notification[]>("/notifications?unread_only=true"),
  ]);
  return { findings, cases, notifications };
}

export function impact(findings: Finding[], cases: CaseSummary[]) {
  const claims = findings.filter((item) => item.level === "claim" && item.status !== "dismissed");
  const owed = new Map(claims.map((item) => [item.id, item.amount_owed_paise ?? 0]));
  const sent = cases.filter((item) => item.state !== "draft");
  return {
    found: claims.reduce((sum, item) => sum + (item.amount_owed_paise ?? 0), 0),
    claimed: sent.flatMap((item) => item.finding_ids).reduce((sum, id) => sum + (owed.get(id) ?? 0), 0),
    recovered: cases.reduce((sum, item) => sum + (item.recovered_paise ?? 0), 0),
  };
}

function Counter({ label, hint, paise }: { label: string; hint: string; paise: number }) {
  const { lang } = useI18n();
  return (
    <Card className="flex flex-col gap-1">
      <p className="text-sm text-muted">{label}</p>
      <p className="text-2xl font-bold text-brand">{money(paise, lang)}</p>
      <p className="text-xs text-muted">{hint}</p>
    </Card>
  );
}

function ResendVerification({ email }: { email: string }) {
  const { t } = useI18n();
  const [state, setState] = useState<string | null>(null);
  async function resend() {
    try {
      await api("/auth/resend-verification", { method: "POST", auth: false, body: { email } });
      setState("sent");
    } catch (problem) {
      setState(errorCode(problem));
    }
  }
  return (
    <Notice tone="warn">
      <p>{fill(t.dashboard.verifyBanner, { email })}</p>
      {state === "sent" ? (
        <p className="mt-2">{t.auth.resent}</p>
      ) : (
        <button type="button" className="mt-2 underline" onClick={resend}>
          {t.auth.resend}
        </button>
      )}
      {state && state !== "sent" ? <ErrorMessage code={state} /> : null}
    </Notice>
  );
}

function DashboardBody() {
  const { lang, t } = useI18n();
  const { me } = useSession();
  const summary = useLoad(loadSummary);

  async function dismiss(id: string) {
    await api(`/notifications/${id}/read`, { method: "POST" }).catch(() => undefined);
    await summary.reload();
  }

  if (summary.error) return <ErrorMessage code={summary.error} />;
  if (!summary.data || !me) return <Loading />;
  const totals = impact(summary.data.findings, summary.data.cases);
  return (
    <div className="flex flex-col gap-6">
      {!me.email_verified ? <ResendVerification email={me.email} /> : null}
      {!me.consent_active ? <Notice tone="warn">{t.dashboard.consentBanner}</Notice> : null}
      {summary.data.notifications.length > 0 ? (
        <section className="flex flex-col gap-2" aria-labelledby="updates">
          <h2 id="updates" className="text-lg font-semibold">
            {t.dashboard.notifications}
          </h2>
          {summary.data.notifications.map((item) => (
            <Notice key={item.id} tone="warn">
              <p>{item.message}</p>
              <div className="mt-2 flex gap-4">
                {item.case_id ? (
                  <Link href={pathFor(lang, `/cases/${item.case_id}`)} className="underline">
                    {t.cases.open}
                  </Link>
                ) : null}
                <button type="button" className="underline" onClick={() => dismiss(item.id)}>
                  {t.dashboard.dismiss}
                </button>
              </div>
            </Notice>
          ))}
        </section>
      ) : null}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3" data-testid="impact">
        <Counter label={t.dashboard.found} hint={t.dashboard.foundHint} paise={totals.found} />
        <Counter label={t.dashboard.claimed} hint={t.dashboard.claimedHint} paise={totals.claimed} />
        <Counter label={t.dashboard.recovered} hint={t.dashboard.recoveredHint} paise={totals.recovered} />
      </div>
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">{t.dashboard.next}</h2>
        <div className="flex flex-col gap-3 sm:flex-row">
          <Link href={pathFor(lang, "/upload")} className="rounded-lg bg-brand px-4 py-3 text-center font-medium text-on-brand">
            {t.dashboard.uploadCta}
          </Link>
          <Link href={pathFor(lang, "/findings")} className="rounded-lg border border-line px-4 py-3 text-center">
            {t.dashboard.findingsCta}
          </Link>
          <Link href={pathFor(lang, "/cases")} className="rounded-lg border border-line px-4 py-3 text-center">
            {t.dashboard.casesCta}
          </Link>
          <Link href={pathFor(lang, "/statements")} className="rounded-lg border border-line px-4 py-3 text-center">
            {t.nav.statements}
          </Link>
        </div>
      </section>
    </div>
  );
}

export function Dashboard() {
  const { t } = useI18n();
  return (
    <Page>
      <PageTitle>{t.dashboard.title}</PageTitle>
      <Protected>
        <DashboardBody />
      </Protected>
    </Page>
  );
}
