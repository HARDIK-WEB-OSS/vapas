"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { Page } from "@/components/shell";
import { Button, Check, ErrorMessage, errorCode, Field, Loading, Notice, PageTitle } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useI18n } from "@/lib/i18n-client";
import { useSession } from "@/lib/session";
import { fill, pathFor } from "@/lib/text";
import type { ConsentNotice } from "@/lib/types";
import { clearHash, hashToken, useLoad } from "@/lib/use-load";

const loadNotice = () => api<ConsentNotice>("/consent/notice", { auth: false });

export function useNotice() {
  return useLoad(loadNotice);
}

export function NoticeText({ notice }: { notice: ConsentNotice }) {
  const { lang, t } = useI18n();
  return (
    <div className="flex flex-col gap-1">
      <div
        tabIndex={0}
        aria-label={t.consent.title}
        className="max-h-64 overflow-y-auto whitespace-pre-wrap rounded-lg border border-line bg-surface-strong p-3 text-sm"
      >
        {lang === "hi" ? notice.text_hi : notice.text_en}
      </div>
      <p className="text-xs text-muted">{fill(t.consent.version, { version: notice.version })}</p>
    </div>
  );
}

const INVITE_ONLY = process.env.NEXT_PUBLIC_INVITE_ONLY === "1";

export function Signup() {
  const { lang, t } = useI18n();
  const notice = useNotice();
  const [agreed, setAgreed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!notice.data) return;
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      await api("/auth/signup", {
        method: "POST",
        auth: false,
        body: {
          email: form.get("email"),
          password: form.get("password"),
          consent_notice_version: notice.data.version,
          locale: lang,
          invite_code: INVITE_ONLY ? form.get("invite_code") : null,
        },
      });
      setDone(true);
    } catch (problem) {
      const code = errorCode(problem);
      setError(code);
      if (code === "consent_notice_changed") {
        setAgreed(false);
        await notice.reload();
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Page>
      <PageTitle>{t.auth.signupTitle}</PageTitle>
      {done ? (
        <Notice tone="ok">{t.auth.checkEmail}</Notice>
      ) : (
        <form onSubmit={submit} className="flex flex-col gap-4">
          <Field label={t.auth.email} name="email" type="email" autoComplete="email" required />
          <Field
            label={t.auth.password}
            name="password"
            type="password"
            autoComplete="new-password"
            minLength={10}
            hint={t.auth.passwordHint}
            required
          />
          {INVITE_ONLY ? (
            <Field label={t.auth.inviteCode} name="invite_code" autoComplete="off" hint={t.auth.inviteHint} maxLength={40} required />
          ) : null}
          {notice.data ? <NoticeText notice={notice.data} /> : <Loading />}
          <ErrorMessage code={notice.error} />
          <Check label={t.auth.consentLabel} checked={agreed} onChange={(event) => setAgreed(event.target.checked)} required />
          <ErrorMessage code={error} />
          <Button type="submit" disabled={busy || !agreed || !notice.data}>
            {t.auth.signupButton}
          </Button>
        </form>
      )}
    </Page>
  );
}

export function Login() {
  const { lang, t } = useI18n();
  const { status, login } = useSession();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (status === "signed_in") router.replace(pathFor(lang, "/dashboard"));
  }, [status, lang, router]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      await login(String(form.get("email")), String(form.get("password")));
    } catch (problem) {
      setError(errorCode(problem));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Page>
      <PageTitle>{t.auth.loginTitle}</PageTitle>
      <form onSubmit={submit} className="flex flex-col gap-4">
        <Field label={t.auth.email} name="email" type="email" autoComplete="email" required />
        <Field label={t.auth.password} name="password" type="password" autoComplete="current-password" required />
        <ErrorMessage code={error} />
        <Button type="submit" disabled={busy}>
          {t.auth.loginButton}
        </Button>
      </form>
      <div className="flex flex-col gap-2">
        <Link href={pathFor(lang, "/forgot-password")} className="underline">
          {t.auth.forgot}
        </Link>
        <Link href={pathFor(lang, "/signup")} className="underline">
          {t.auth.noAccount}
        </Link>
      </div>
    </Page>
  );
}

const verifications = new Map<string, Promise<string>>();
let rememberedToken: string | null = null;

function verifyOutcome(problem: unknown): string {
  if (problem instanceof ApiError && (problem.status === 0 || problem.status >= 500)) return "unreachable";
  return errorCode(problem);
}

function verifyOnce(token: string): Promise<string> {
  const running = verifications.get(token);
  if (running) return running;
  const attempt = api("/auth/verify-email", { method: "POST", auth: false, body: { token } }).then(
    () => "verified",
    verifyOutcome,
  );
  verifications.set(token, attempt);
  void attempt.then((outcome) => {
    if (outcome === "unreachable") verifications.delete(token);
  });
  return attempt;
}

function tokenFromPage(): string | null {
  const fromLink = hashToken();
  if (fromLink) {
    rememberedToken = fromLink;
    clearHash();
  }
  return rememberedToken;
}

export function VerifyEmail() {
  const { lang, t } = useI18n();
  const { status, reload } = useSession();
  const [result, setResult] = useState("pending");

  useEffect(() => {
    const token = tokenFromPage();
    let active = true;
    const outcome = token ? verifyOnce(token) : Promise.resolve("missing");
    void outcome.then((value) => {
      if (active) setResult(value);
    });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (result === "verified" && status === "signed_in") reload().catch(() => undefined);
  }, [result, status, reload]);

  async function retry() {
    const token = rememberedToken;
    if (!token) return;
    setResult("pending");
    const outcome = await verifyOnce(token);
    setResult(outcome === "invalid_token" ? "maybe_verified" : outcome);
  }

  const signedIn = status === "signed_in";
  return (
    <Page>
      <PageTitle>{t.auth.verifyTitle}</PageTitle>
      {result === "pending" ? <Loading /> : null}
      {result === "verified" ? (
        <>
          <Notice tone="ok">{t.auth.verified}</Notice>
          <Link href={pathFor(lang, signedIn ? "/dashboard" : "/login")} className="underline">
            {signedIn ? t.nav.home : t.nav.login}
          </Link>
        </>
      ) : null}
      {result === "unreachable" ? (
        <div className="flex flex-col gap-3">
          <Notice tone="error">{t.auth.verifyUnreachable}</Notice>
          <Button type="button" onClick={retry}>
            {t.auth.tryAgain}
          </Button>
        </div>
      ) : null}
      {result === "maybe_verified" ? (
        <>
          <Notice tone="warn">{t.auth.maybeVerified}</Notice>
          <Link href={pathFor(lang, "/login")} className="underline">
            {t.nav.login}
          </Link>
        </>
      ) : null}
      {result === "missing" ? <Notice tone="error">{t.auth.missingToken}</Notice> : null}
      {!["pending", "verified", "missing", "unreachable", "maybe_verified"].includes(result) ? <ErrorMessage code={result} /> : null}
    </Page>
  );
}

export function ForgotPassword() {
  const { t } = useI18n();
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await api("/auth/password-reset/request", { method: "POST", auth: false, body: { email: form.get("email") } });
      setSent(true);
    } catch (problem) {
      setError(errorCode(problem));
    }
  }

  return (
    <Page>
      <PageTitle>{t.auth.forgotTitle}</PageTitle>
      {sent ? (
        <Notice tone="ok">{t.auth.resetSent}</Notice>
      ) : (
        <form onSubmit={submit} className="flex flex-col gap-4">
          <Field label={t.auth.email} name="email" type="email" autoComplete="email" required />
          <ErrorMessage code={error} />
          <Button type="submit">{t.auth.forgotButton}</Button>
        </form>
      )}
    </Page>
  );
}

export function ResetPassword() {
  const { lang, t } = useI18n();
  const token = useRef<string | null>(null);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    token.current = hashToken();
    clearHash();
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token.current) {
      setError("invalid_token");
      return;
    }
    const form = new FormData(event.currentTarget);
    try {
      await api("/auth/password-reset/confirm", {
        method: "POST",
        auth: false,
        body: { token: token.current, new_password: form.get("password") },
      });
      setDone(true);
    } catch (problem) {
      setError(errorCode(problem));
    }
  }

  return (
    <Page>
      <PageTitle>{t.auth.resetTitle}</PageTitle>
      {done ? (
        <>
          <Notice tone="ok">{t.auth.resetDone}</Notice>
          <Link href={pathFor(lang, "/login")} className="underline">
            {t.nav.login}
          </Link>
        </>
      ) : (
        <form onSubmit={submit} className="flex flex-col gap-4">
          <Field
            label={t.auth.newPassword}
            name="password"
            type="password"
            autoComplete="new-password"
            minLength={10}
            hint={t.auth.passwordHint}
            required
          />
          <ErrorMessage code={error} />
          <Button type="submit">{t.auth.resetButton}</Button>
        </form>
      )}
    </Page>
  );
}

export function ConsentPage() {
  const { t } = useI18n();
  const notice = useNotice();
  return (
    <Page>
      <PageTitle>{t.consent.title}</PageTitle>
      {notice.data ? <NoticeText notice={notice.data} /> : <Loading />}
      <ErrorMessage code={notice.error} />
    </Page>
  );
}
