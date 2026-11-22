"use client";

import { useState, type FormEvent } from "react";

import { NoticeText, useNotice } from "@/components/auth";
import { Page, Protected } from "@/components/shell";
import { Button, Card, ErrorMessage, errorCode, Field, Notice, PageTitle } from "@/components/ui";
import { api, apiBlob } from "@/lib/api";
import { useI18n } from "@/lib/i18n-client";
import { useSession } from "@/lib/session";
import { LOCALES, type Locale } from "@/lib/text";

const LANGUAGE_NAMES: Record<Locale, string> = { en: "English", hi: "हिन्दी" };

function LanguageChoice() {
  const { t } = useI18n();
  const { me, reload } = useSession();
  const [error, setError] = useState<string | null>(null);
  async function choose(locale: Locale) {
    try {
      await api("/account/locale", { method: "POST", body: { locale } });
      await reload();
    } catch (problem) {
      setError(errorCode(problem));
    }
  }
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1 font-medium">{t.settings.language}</legend>
      <div className="flex gap-4">
        {LOCALES.map((locale) => (
          <label key={locale} className="flex min-h-11 items-center gap-2" lang={locale}>
            <input type="radio" name="locale" className="size-5" checked={me?.locale === locale} onChange={() => choose(locale)} />
            {LANGUAGE_NAMES[locale]}
          </label>
        ))}
      </div>
      <ErrorMessage code={error} />
    </fieldset>
  );
}

function ExportData() {
  const { t } = useI18n();
  const [error, setError] = useState<string | null>(null);
  async function download() {
    try {
      const blob = await apiBlob("/account/export");
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "vapas-my-data.json";
      link.click();
      URL.revokeObjectURL(url);
    } catch (problem) {
      setError(errorCode(problem));
    }
  }
  return (
    <Card className="flex flex-col gap-3">
      <h2 className="text-lg font-semibold">{t.settings.exportTitle}</h2>
      <p className="text-sm">{t.settings.exportNote}</p>
      <ErrorMessage code={error} />
      <Button type="button" tone="secondary" onClick={download} className="self-start">
        {t.settings.exportButton}
      </Button>
    </Card>
  );
}

function Consent() {
  const { t } = useI18n();
  const { me, reload } = useSession();
  const notice = useNotice();
  const [error, setError] = useState<string | null>(null);
  const [given, setGiven] = useState(false);
  async function run(path: string, body?: unknown) {
    try {
      await api(path, { method: "POST", body });
      await reload();
      return true;
    } catch (problem) {
      setError(errorCode(problem));
      return false;
    }
  }
  return (
    <Card className="flex flex-col gap-3">
      <h2 className="text-lg font-semibold">{t.settings.consentTitle}</h2>
      {given ? <Notice tone="ok">{t.consent.given}</Notice> : null}
      {me?.consent_active ? (
        <>
          <p>{t.settings.consentActive}</p>
          <Button type="button" tone="secondary" className="self-start" onClick={() => run("/account/consent/withdraw")}>
            {t.settings.withdraw}
          </Button>
        </>
      ) : (
        <>
          <p>{t.settings.consentInactive}</p>
          {notice.data ? <NoticeText notice={notice.data} /> : null}
          <Button
            type="button"
            className="self-start"
            disabled={!notice.data}
            onClick={async () => setGiven(await run("/account/consent", { notice_version: notice.data?.version }))}
          >
            {t.consent.giveAgain}
          </Button>
        </>
      )}
      <ErrorMessage code={error ?? notice.error} />
    </Card>
  );
}

function DeleteAccount() {
  const { t } = useI18n();
  const { forget } = useSession();
  const [error, setError] = useState<string | null>(null);
  const [deleted, setDeleted] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await api("/account", { method: "DELETE", body: { password: form.get("password") }, withCookie: true });
      setDeleted(true);
      window.setTimeout(forget, 1500);
    } catch (problem) {
      setError(errorCode(problem));
    }
  }
  return (
    <Card className="flex flex-col gap-3 border-danger">
      <h2 className="text-lg font-semibold">{t.settings.deleteTitle}</h2>
      {deleted ? (
        <Notice tone="ok">{t.settings.deleted}</Notice>
      ) : (
        <form onSubmit={submit} className="flex flex-col gap-3">
          <p className="text-sm">{t.settings.deleteNote}</p>
          <Field label={t.auth.password} name="password" type="password" autoComplete="current-password" required />
          <ErrorMessage code={error} />
          <Button type="submit" tone="danger" className="self-start">
            {t.settings.deleteButton}
          </Button>
        </form>
      )}
    </Card>
  );
}

export function Settings() {
  const { t } = useI18n();
  const { me } = useSession();
  return (
    <Page>
      <PageTitle>{t.settings.title}</PageTitle>
      <Protected>
        <Card className="flex flex-col gap-3">
          <h2 className="text-lg font-semibold">{t.settings.account}</h2>
          <p className="break-all">{me?.email}</p>
          <LanguageChoice />
        </Card>
        <ExportData />
        <Consent />
        <DeleteAccount />
      </Protected>
    </Page>
  );
}
