"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { Page, Protected } from "@/components/shell";
import { Button, Card, Check, ErrorMessage, errorCode, Field, Loading, Notice, PageTitle } from "@/components/ui";
import { api } from "@/lib/api";
import { day, money, todayIst } from "@/lib/format";
import { useI18n } from "@/lib/i18n-client";
import { fill, pathFor } from "@/lib/text";
import type { CaseSummary, Finding, Question, Verdict } from "@/lib/types";
import { useLoad } from "@/lib/use-load";

const POLL_MS = 3000;
const POLL_LIMIT = 10;
const GROUPS = ["claim", "worth_checking", "needs_user_input", "other"] as const;
type Group = (typeof GROUPS)[number];
const CASE_LEVELS = new Set(["claim", "worth_checking"]);

type Data = { findings: Finding[]; inCase: Set<string> };

async function loadAll(): Promise<Data> {
  const [findings, cases] = await Promise.all([api<Finding[]>("/findings"), api<CaseSummary[]>("/cases")]);
  return { findings, inCase: new Set(cases.flatMap((item) => item.finding_ids)) };
}

function groupOf(finding: Finding): Group {
  if (finding.level === "claim" || finding.level === "worth_checking" || finding.level === "needs_user_input") return finding.level;
  return "other";
}

function YesNoQuestion({ finding, onAnswered }: { finding: Finding; onAnswered: () => void }) {
  const { t } = useI18n();
  const [error, setError] = useState<string | null>(null);
  const question = finding.question as Exclude<Question, "mandate_revoked">;

  async function answer(value: boolean) {
    try {
      await api(`/findings/${finding.id}/answer`, { method: "POST", body: { value } });
      onAnswered();
    } catch (problem) {
      setError(errorCode(problem));
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <p className="font-medium">{t.findings.questions[question]}</p>
      <div className="flex gap-3">
        <Button type="button" tone="secondary" onClick={() => answer(true)}>
          {t.common.yes}
        </Button>
        <Button type="button" tone="secondary" onClick={() => answer(false)}>
          {t.common.no}
        </Button>
      </div>
      <ErrorMessage code={error} />
    </div>
  );
}

function MandateQuestion({ finding, onAnswered }: { finding: Finding; onAnswered: () => void }) {
  const { t } = useI18n();
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await api(`/findings/${finding.id}/answer`, {
        method: "POST",
        body: { revoked_on: form.get("revoked_on"), proof: form.get("proof") === "on" },
      });
      onAnswered();
    } catch (problem) {
      setError(errorCode(problem));
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <p className="font-medium">{t.findings.questions.mandate_revoked}</p>
      <Field label={t.findings.revokedOn} name="revoked_on" type="date" max={todayIst()} required />
      <Check label={t.findings.proof} name="proof" />
      <ErrorMessage code={error} />
      <Button type="submit" tone="secondary">
        {t.findings.send}
      </Button>
    </form>
  );
}

type CardProps = {
  finding: Finding;
  inCase: boolean;
  selected: boolean;
  onSelect: (selected: boolean) => void;
  onChanged: () => void;
  onAnswered: () => void;
};

function FindingCard({ finding, inCase, selected, onSelect, onChanged, onAnswered }: CardProps) {
  const { lang, t } = useI18n();
  const [error, setError] = useState<string | null>(null);
  const claim = finding.level === "claim" && finding.amount_owed_paise !== null;
  const selectable = CASE_LEVELS.has(finding.level) && finding.status !== "dismissed" && !inCase;

  async function mark(status: "confirmed" | "dismissed" | "open") {
    try {
      await api(`/findings/${finding.id}/status`, { method: "POST", body: { status } });
      if (status !== "open") await sendFeedback(status === "confirmed" ? "correct" : "wrong");
      onChanged();
    } catch (problem) {
      setError(errorCode(problem));
    }
  }

  async function sendFeedback(verdict: Verdict) {
    await api(`/findings/${finding.id}/feedback`, { method: "POST", body: { verdict } });
  }

  async function notSure() {
    try {
      await sendFeedback("not_sure");
      onChanged();
    } catch (problem) {
      setError(errorCode(problem));
    }
  }

  return (
    <Card className={`flex flex-col gap-3 ${finding.status === "dismissed" ? "opacity-60" : ""}`}>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="rounded-full bg-surface-strong px-3 py-1">{t.findings.level[finding.level]}</span>
        <span className="text-muted">{t.findings.confidence[finding.confidence]}</span>
        {inCase ? <span className="rounded-full bg-brand-soft px-3 py-1">{t.findings.inCase}</span> : null}
      </div>
      {claim ? (
        <div>
          <p className="text-sm text-muted">{t.findings.owed}</p>
          <p className="text-3xl font-bold text-brand" data-testid="amount-owed">
            {money(finding.amount_owed_paise ?? 0, lang)}
          </p>
          {finding.delay_days ? <p className="text-sm">{fill(t.findings.delay, { days: finding.delay_days })}</p> : null}
          {finding.already_paid_paise > 0 ? (
            <p className="text-sm">{fill(t.findings.alreadyPaid, { amount: money(finding.already_paid_paise, lang) })}</p>
          ) : null}
          {finding.accruing ? <p className="text-sm">{t.findings.accruing}</p> : null}
        </div>
      ) : null}
      <p>
        {finding.why}
        {lang === "hi" ? <span className="block text-xs text-muted">{t.common.englishOnly}</span> : null}
      </p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
        {finding.t_date ? (
          <>
            <dt className="text-muted">{t.findings.txnDate}</dt>
            <dd>{day(finding.t_date)}</dd>
          </>
        ) : null}
        {finding.r_date ? (
          <>
            <dt className="text-muted">{t.findings.reversalDate}</dt>
            <dd>{day(finding.r_date)}</dd>
          </>
        ) : null}
        {finding.rule_id ? (
          <>
            <dt className="text-muted">{t.findings.rule}</dt>
            <dd className="break-all">{finding.rule_id}</dd>
          </>
        ) : null}
      </dl>
      {finding.question === "mandate_revoked" ? <MandateQuestion finding={finding} onAnswered={onAnswered} /> : null}
      {finding.question && finding.question !== "mandate_revoked" ? <YesNoQuestion finding={finding} onAnswered={onAnswered} /> : null}
      {finding.status === "dismissed" ? (
        <p className="text-sm">
          {t.findings.markedWrong}{" "}
          <button type="button" className="underline" onClick={() => mark("open")}>
            {t.findings.undo}
          </button>
        </p>
      ) : finding.status === "confirmed" ? (
        <p className="text-sm">{t.findings.markedRight}</p>
      ) : (
        <div className="flex flex-col gap-2">
          {finding.feedback === "not_sure" ? <p className="text-sm">{t.findings.markedNotSure}</p> : null}
          <div className="flex flex-wrap gap-3">
            <Button type="button" tone="secondary" onClick={() => mark("confirmed")}>
              {t.findings.right}
            </Button>
            <Button type="button" tone="secondary" onClick={() => mark("dismissed")}>
              {t.findings.wrong}
            </Button>
            {finding.feedback === "not_sure" ? null : (
              <Button type="button" tone="secondary" onClick={notSure}>
                {t.findings.notSure}
              </Button>
            )}
          </div>
          <p className="text-xs text-muted">{t.findings.feedbackHelp}</p>
        </div>
      )}
      {selectable ? <Check label={t.findings.select} checked={selected} onChange={(event) => onSelect(event.target.checked)} /> : null}
      <ErrorMessage code={error} />
    </Card>
  );
}

function FindingList() {
  const { lang, t } = useI18n();
  const router = useRouter();
  const data = useLoad(loadAll);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [polls, setPolls] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const { reload } = data;

  useEffect(() => {
    if (polls === 0) return;
    const timer = window.setTimeout(() => {
      void reload();
      setPolls((count) => (count >= POLL_LIMIT ? 0 : count + 1));
    }, POLL_MS);
    return () => window.clearTimeout(timer);
  }, [polls, reload]);

  function toggle(id: string, on: boolean) {
    setSelected((current) => {
      const next = new Set(current);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  async function createCase() {
    try {
      const created = await api<CaseSummary>("/cases", { method: "POST", body: { finding_ids: [...selected], language: lang } });
      router.push(pathFor(lang, `/cases/${created.id}`));
    } catch (problem) {
      setError(errorCode(problem));
    }
  }

  if (data.error) return <ErrorMessage code={data.error} />;
  if (!data.data) return <Loading />;
  const { findings, inCase } = data.data;
  if (findings.length === 0) return <p>{t.findings.empty}</p>;
  return (
    <div className="flex flex-col gap-8 pb-24">
      {polls > 0 ? <Notice>{t.findings.recomputing}</Notice> : null}
      {GROUPS.map((group) => {
        const items = findings.filter((finding) => groupOf(finding) === group);
        if (items.length === 0) return null;
        return (
          <section key={group} className="flex flex-col gap-3" aria-labelledby={`group-${group}`}>
            <h2 id={`group-${group}`} className="text-xl font-semibold">
              {t.findings.groups[group]} ({items.length})
            </h2>
            <p className="text-sm text-muted">{t.findings.groupHints[group]}</p>
            {items.map((finding) => (
              <FindingCard
                key={finding.id}
                finding={finding}
                inCase={inCase.has(finding.id)}
                selected={selected.has(finding.id)}
                onSelect={(on) => toggle(finding.id, on)}
                onChanged={() => void reload()}
                onAnswered={() => setPolls(1)}
              />
            ))}
          </section>
        );
      })}
      {selected.size > 0 ? (
        <div className="fixed inset-x-0 bottom-0 border-t border-line bg-surface p-3">
          <div className="mx-auto flex max-w-3xl flex-col gap-2">
            <ErrorMessage code={error} />
            <Button type="button" onClick={createCase}>
              {fill(t.findings.createCase, { count: selected.size })}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function Findings() {
  const { t } = useI18n();
  return (
    <Page>
      <PageTitle>{t.findings.title}</PageTitle>
      <Protected>
        <FindingList />
      </Protected>
    </Page>
  );
}
