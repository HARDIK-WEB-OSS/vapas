"use client";

import Link from "next/link";
import { useCallback } from "react";

import { Page, Protected } from "@/components/shell";
import { Card, ErrorMessage, Loading, PageTitle } from "@/components/ui";
import { api } from "@/lib/api";
import { day } from "@/lib/format";
import { useI18n } from "@/lib/i18n-client";
import { fill, pathFor } from "@/lib/text";
import type { CaseSummary } from "@/lib/types";
import { useLoad } from "@/lib/use-load";

const BANKS: Record<string, string> = {
  SBI: "State Bank of India",
  HDFC: "HDFC Bank",
  ICICI: "ICICI Bank",
  AXIS: "Axis Bank",
  KOTAK: "Kotak Mahindra Bank",
};

export function bankName(code: string): string {
  return BANKS[code] ?? code;
}

export function Countdown({ summary }: { summary: CaseSummary }) {
  const { t } = useI18n();
  if (summary.days_left === null || !summary.filing_deadline_on) return null;
  const urgent = summary.days_left <= 7;
  return (
    <div
      className={`rounded-lg border-l-4 p-3 ${urgent ? "border-danger bg-danger-soft" : "border-brand bg-brand-soft"}`}
      data-testid="countdown"
    >
      <p className="text-lg font-semibold">{fill(t.cases.daysLeft, { days: summary.days_left })}</p>
      <p className="text-sm">{fill(t.cases.lastDate, { date: day(summary.filing_deadline_on) })}</p>
    </div>
  );
}

function CaseCard({ summary }: { summary: CaseSummary }) {
  const { lang, t } = useI18n();
  return (
    <Card className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">{bankName(summary.bank_code)}</h2>
        <span className="rounded-full bg-surface-strong px-3 py-1 text-sm">{t.cases.state[summary.state]}</span>
      </div>
      <p className="text-sm text-muted">
        {fill(t.cases.findingsCount, { count: summary.finding_ids.length })} · {day(summary.created_at)}
      </p>
      <Countdown summary={summary} />
      <Link href={pathFor(lang, `/cases/${summary.id}`)} className="self-start underline">
        {t.cases.open}
      </Link>
    </Card>
  );
}

function CaseList() {
  const { t } = useI18n();
  const cases = useLoad(useCallback(() => api<CaseSummary[]>("/cases"), []));
  if (cases.error) return <ErrorMessage code={cases.error} />;
  if (!cases.data) return <Loading />;
  if (cases.data.length === 0) return <p>{t.cases.empty}</p>;
  return (
    <div className="flex flex-col gap-4">
      {cases.data.map((summary) => (
        <CaseCard key={summary.id} summary={summary} />
      ))}
    </div>
  );
}

export function Cases() {
  const { t } = useI18n();
  return (
    <Page>
      <PageTitle>{t.cases.title}</PageTitle>
      <Protected>
        <CaseList />
      </Protected>
    </Page>
  );
}
