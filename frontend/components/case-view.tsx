"use client";

import { useParams } from "next/navigation";
import { useCallback, useState, type FormEvent, type ReactNode } from "react";

import { bankName, Countdown } from "@/components/cases";
import { Page, Protected } from "@/components/shell";
import { Button, Card, Check, ErrorMessage, errorCode, Field, Loading, Notice, PageTitle, YesNo } from "@/components/ui";
import { api, apiBlob } from "@/lib/api";
import { day, money, rupeesToPaise, todayIst } from "@/lib/format";
import { useI18n } from "@/lib/i18n-client";
import { fill } from "@/lib/text";
import type { CaseDetail, CaseState, Letter } from "@/lib/types";
import { useLoad } from "@/lib/use-load";

type Act = (path: string, body: unknown) => Promise<boolean>;

const OPEN_TIMELINE: CaseState[] = ["awaiting_reply", "escalation_eligible"];
const FINAL: CaseState[] = ["closed", "expired"];

function saveFile(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card className="flex flex-col gap-3">
      <h2 className="text-lg font-semibold">{title}</h2>
      {children}
    </Card>
  );
}

function DateForm({ label, button, act, path, extra = {} }: { label: string; button: string; act: Act; path: string; extra?: Record<string, unknown> }) {
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await act(path, { on: form.get("on"), ...extra });
  }
  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <Field label={label} name="on" type="date" max={todayIst()} defaultValue={todayIst()} required />
      <Button type="submit">{button}</Button>
    </form>
  );
}

function LetterText({ letter }: { letter: Letter }) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  async function copy() {
    await navigator.clipboard.writeText(letter.text);
    setCopied(true);
  }
  return (
    <div className="flex flex-col gap-2">
      <pre className="max-h-96 overflow-y-auto whitespace-pre-wrap break-words rounded-lg border border-line bg-surface-strong p-3 font-sans text-sm" data-testid={`letter-${letter.kind}`}>
        {letter.text}
      </pre>
      {letter.approved_at ? (
        <div className="flex flex-wrap gap-3">
          <Button type="button" tone="secondary" onClick={copy}>
            {copied ? t.common.copied : t.common.copy}
          </Button>
          <Button type="button" tone="secondary" onClick={() => saveFile(new Blob([letter.text], { type: "text/plain" }), `vapas-${letter.kind}-letter.txt`)}>
            {t.common.download}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function ApproveForm({ letter, act, caseId }: { letter: Letter; act: Act; caseId: string }) {
  const { t } = useI18n();
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const bank = String(form.get("bank_name") ?? "").trim();
    await act(`/cases/${caseId}/letters/${letter.id}/approve`, {
      customer_name: form.get("customer_name"),
      account_hint: form.get("account_hint"),
      contact: form.get("contact"),
      bank_name: bank || null,
    });
  }
  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <h3 className="font-semibold">{t.cases.approveTitle}</h3>
      <p className="text-sm text-muted">{t.cases.approveNote}</p>
      <Field label={t.cases.name} name="customer_name" autoComplete="name" minLength={2} maxLength={120} required />
      <Field label={t.cases.last4} name="account_hint" inputMode="numeric" pattern="\d{4}" maxLength={4} required />
      <Field label={t.cases.contact} name="contact" minLength={5} maxLength={120} required />
      <Field label={t.cases.bankName} name="bank_name" maxLength={120} />
      <Button type="submit">{t.cases.approve}</Button>
    </form>
  );
}

function LetterSection({ detail, kind, act, editable }: { detail: CaseDetail; kind: "bank" | "cms"; act: Act; editable: boolean }) {
  const { t } = useI18n();
  const [polish, setPolish] = useState(false);
  const letter = detail.letters.find((item) => item.kind === kind && item.approved_at) ?? detail.letters.find((item) => item.kind === kind);
  return (
    <Section title={kind === "bank" ? t.cases.bankLetter : t.cases.cmsLetter}>
      {letter ? <LetterText letter={letter} /> : null}
      {letter && !letter.approved_at && editable ? <ApproveForm letter={letter} act={act} caseId={detail.id} /> : null}
      {editable && !letter?.approved_at ? (
        <div className="flex flex-col gap-3">
          <Check label={t.cases.polish} checked={polish} onChange={(event) => setPolish(event.target.checked)} />
          <Button type="button" tone={letter ? "secondary" : "primary"} onClick={() => act(`/cases/${detail.id}/letters`, { kind, polish })}>
            {t.cases.draftLetter}
          </Button>
        </div>
      ) : null}
      {letter?.approved_at && kind === "bank" ? <p className="text-sm">{t.cases.sendSteps}</p> : null}
    </Section>
  );
}

function EscalateForm({ detail, act }: { detail: CaseDetail; act: Act }) {
  const { t } = useI18n();
  const [ombudsman, setOmbudsman] = useState<boolean | null>(null);
  const [court, setCourt] = useState<boolean | null>(null);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await act(`/cases/${detail.id}/escalate`, {
      filed_on: form.get("filed_on"),
      already_with_ombudsman: ombudsman,
      in_court_or_other_forum: court,
    });
  }
  return (
    <Section title={t.cases.escalateTitle}>
      <ol className="list-decimal space-y-1 pl-5 text-sm">
        {t.cases.escalateSteps.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
      <form onSubmit={submit} className="flex flex-col gap-4">
        <YesNo legend={t.cases.withOmbudsman} name="with-ombudsman" value={ombudsman} onChange={setOmbudsman} />
        <YesNo legend={t.cases.inCourt} name="in-court" value={court} onChange={setCourt} />
        {ombudsman || court ? <Notice tone="error">{t.errors.blocked_clause_10}</Notice> : null}
        <Field label={t.cases.filedOn} name="filed_on" type="date" max={todayIst()} defaultValue={todayIst()} required />
        <Button type="submit" disabled={ombudsman !== false || court !== false}>
          {t.cases.markEscalated}
        </Button>
      </form>
    </Section>
  );
}

function ReplyForm({ detail, act }: { detail: CaseDetail; act: Act }) {
  const { t } = useI18n();
  const [resolved, setResolved] = useState<boolean | null>(null);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await act(`/cases/${detail.id}/reply`, { on: form.get("on"), resolved });
  }
  return (
    <Section title={t.cases.replyTitle}>
      <form onSubmit={submit} className="flex flex-col gap-3">
        <Field label={t.cases.replyOn} name="on" type="date" max={todayIst()} required />
        <YesNo legend={t.cases.resolvedQuestion} name="resolved" value={resolved} onChange={setResolved} />
        <Button type="submit" disabled={resolved === null}>
          {t.cases.saveReply}
        </Button>
      </form>
    </Section>
  );
}

function RecoveredForm({ detail, act }: { detail: CaseDetail; act: Act }) {
  const { lang, t } = useI18n();
  const [invalid, setInvalid] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const paise = rupeesToPaise(String(form.get("amount") ?? ""));
    setInvalid(paise === null || paise <= 0);
    if (paise === null || paise <= 0) return;
    await act(`/cases/${detail.id}/recovered`, { amount_paise: paise, on: form.get("on") });
  }
  return (
    <Section title={t.cases.recoveredTitle}>
      {detail.recovered_paise && detail.recovered_on ? (
        <p className="font-semibold text-brand">
          {fill(t.cases.recoveredShown, { amount: money(detail.recovered_paise, lang), date: day(detail.recovered_on) })}
        </p>
      ) : null}
      <form onSubmit={submit} className="flex flex-col gap-3">
        <Field label={t.common.rupees} name="amount" inputMode="decimal" required aria-invalid={invalid} />
        <Field label={t.cases.recoveredOn} name="on" type="date" max={todayIst()} defaultValue={todayIst()} required />
        <Button type="submit" tone="secondary">
          {t.cases.saveRecovered}
        </Button>
      </form>
    </Section>
  );
}

function CloseForm({ detail, act }: { detail: CaseDetail; act: Act }) {
  const { t } = useI18n();
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await act(`/cases/${detail.id}/close`, { reason: form.get("reason") });
  }
  return (
    <Section title={t.cases.closeTitle}>
      <form onSubmit={submit} className="flex flex-col gap-3">
        <Field label={t.cases.closeReason} name="reason" minLength={2} maxLength={300} required />
        <Button type="submit" tone="secondary">
          {t.cases.close}
        </Button>
      </form>
    </Section>
  );
}

function Timeline({ detail }: { detail: CaseDetail }) {
  const { t } = useI18n();
  const labels = t.events as Record<string, string>;
  return (
    <Section title={t.cases.timeline}>
      <ol className="flex flex-col gap-2 border-l-2 border-line pl-4" data-testid="timeline">
        {detail.events.map((event) => (
          <li key={event.seq}>
            <span className="font-medium">{labels[event.type] ?? event.type}</span>{" "}
            <span className="text-sm text-muted">{day(event.at)}</span>
          </li>
        ))}
      </ol>
    </Section>
  );
}

function CaseBody({ id }: { id: string }) {
  const { t } = useI18n();
  const detail = useLoad(useCallback(() => api<CaseDetail>(`/cases/${id}`), [id]));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const act: Act = async (path, body) => {
    setBusy(true);
    setError(null);
    try {
      await api(path, { method: "POST", body });
      await detail.reload();
      return true;
    } catch (problem) {
      setError(errorCode(problem));
      return false;
    } finally {
      setBusy(false);
    }
  };

  async function evidence() {
    try {
      saveFile(await apiBlob(`/cases/${id}/evidence.pdf`), "vapas-evidence.pdf");
    } catch (problem) {
      setError(errorCode(problem));
    }
  }

  if (detail.error) return <ErrorMessage code={detail.error} />;
  const data = detail.data;
  if (!data) return <Loading />;
  const state = data.state;
  const bankApproved = data.letters.some((letter) => letter.kind === "bank" && letter.approved_at);
  const cmsApproved = data.letters.some((letter) => letter.kind === "cms" && letter.approved_at);
  return (
    <div className="flex flex-col gap-4" aria-busy={busy}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-surface-strong px-3 py-1 text-sm font-medium" data-testid="case-state">
          {t.cases.state[state]}
        </span>
        <span className="text-sm text-muted">{bankName(data.bank_code)}</span>
      </div>
      <Countdown summary={data} />
      {state === "awaiting_reply" && data.escalation_eligible_on ? <p>{fill(t.cases.eligibleOn, { date: day(data.escalation_eligible_on) })}</p> : null}
      {OPEN_TIMELINE.includes(state) && !data.filing_deadline_on ? <Notice tone="warn">{t.cases.noDeadline}</Notice> : null}
      {state === "expired" ? <Notice tone="error">{t.cases.expiredNote}</Notice> : null}
      <ErrorMessage code={error} />
      <LetterSection detail={data} kind="bank" act={act} editable={state === "draft"} />
      {state === "draft" && bankApproved ? (
        <Section title={t.cases.markSent}>
          <DateForm label={t.cases.sentOn} button={t.cases.markSent} act={act} path={`/cases/${id}/sent`} />
        </Section>
      ) : null}
      {state === "sent_to_bank" ? (
        <Section title={t.cases.markReceived}>
          <DateForm label={t.cases.receivedOn} button={t.cases.markReceived} act={act} path={`/cases/${id}/received`} />
        </Section>
      ) : null}
      {OPEN_TIMELINE.includes(state) ? <ReplyForm detail={data} act={act} /> : null}
      {OPEN_TIMELINE.includes(state) ? (
        <Section title={t.cases.communicationTitle}>
          <DateForm label={t.cases.communicationOn} button={t.cases.saveCommunication} act={act} path={`/cases/${id}/communication`} />
        </Section>
      ) : null}
      {state === "escalation_eligible" || cmsApproved ? <LetterSection detail={data} kind="cms" act={act} editable={state === "escalation_eligible"} /> : null}
      {state === "escalation_eligible" && cmsApproved ? <EscalateForm detail={data} act={act} /> : null}
      {state !== "draft" ? <RecoveredForm detail={data} act={act} /> : null}
      {!FINAL.includes(state) ? <CloseForm detail={data} act={act} /> : null}
      <Button type="button" tone="secondary" onClick={evidence}>
        {t.cases.evidence}
      </Button>
      <Timeline detail={data} />
    </div>
  );
}

export function CaseView() {
  const { t } = useI18n();
  const params = useParams<{ id: string }>();
  return (
    <Page>
      <PageTitle>{t.cases.title}</PageTitle>
      <Protected>
        <CaseBody id={params.id} />
      </Protected>
    </Page>
  );
}
