"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { Loading } from "@/components/ui";
import { useI18n } from "@/lib/i18n-client";
import { useSession } from "@/lib/session";
import { pathFor, type Locale } from "@/lib/text";

const LOCALE_COOKIE_SECONDS = 60 * 60 * 24 * 365;

function otherLocalePath(pathname: string, lang: Locale): { target: Locale; href: string } {
  const target: Locale = lang === "en" ? "hi" : "en";
  const rest = pathname.replace(/^\/(en|hi)(?=\/|$)/, "");
  return { target, href: `/${target}${rest}` };
}

export function Header() {
  const { lang, t } = useI18n();
  const { status, logout } = useSession();
  const pathname = usePathname();
  const router = useRouter();
  const switcher = otherLocalePath(pathname, lang);
  const signedIn = status === "signed_in";
  const links = signedIn
    ? [
        ["/dashboard", t.nav.home],
        ["/upload", t.nav.upload],
        ["/findings", t.nav.findings],
        ["/cases", t.nav.cases],
        ["/settings", t.nav.settings],
      ]
    : [
        ["/guide", t.nav.guide],
        ["/login", t.nav.login],
        ["/signup", t.nav.signup],
      ];

  function rememberLocale() {
    document.cookie = `vapas_locale=${switcher.target}; path=/; max-age=${LOCALE_COOKIE_SECONDS}; samesite=lax`;
  }

  async function signOut() {
    await logout();
    router.push(pathFor(lang, "/"));
  }

  return (
    <header className="border-b border-line bg-surface">
      <div className="mx-auto flex w-full max-w-3xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
        <Link href={pathFor(lang, signedIn ? "/dashboard" : "/")} className="text-xl font-bold text-brand">
          VAPAS
        </Link>
        <nav aria-label={t.nav.menu} className="flex flex-1 flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          {links.map(([href, label]) => (
            <Link
              key={href}
              href={pathFor(lang, href)}
              aria-current={pathname === pathFor(lang, href) ? "page" : undefined}
              className="py-2 underline-offset-4 hover:underline aria-[current=page]:font-semibold aria-[current=page]:underline"
            >
              {label}
            </Link>
          ))}
          {signedIn ? (
            <button type="button" onClick={signOut} className="py-2 underline-offset-4 hover:underline">
              {t.nav.logout}
            </button>
          ) : null}
        </nav>
        <Link href={switcher.href} onClick={rememberLocale} lang={switcher.target} className="rounded-md border border-line px-2 py-1 text-sm">
          {t.nav.switchLanguage}
        </Link>
      </div>
    </header>
  );
}

export function HeaderFallback() {
  return (
    <header className="border-b border-line bg-surface">
      <div className="mx-auto flex w-full max-w-3xl items-center px-4 py-3">
        <span className="text-xl font-bold text-brand">VAPAS</span>
      </div>
    </header>
  );
}

export function Footer() {
  const { lang, t } = useI18n();
  return (
    <footer className="mt-auto border-t border-line">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-2 px-4 py-6 text-sm text-muted">
        <p>{t.footer.notLegalAdvice}</p>
        <p>{t.footer.free}</p>
        <p className="flex gap-4">
          <Link href={pathFor(lang, "/privacy")} className="underline">
            {t.footer.privacy}
          </Link>
          <Link href={pathFor(lang, "/terms")} className="underline">
            {t.footer.terms}
          </Link>
        </p>
      </div>
    </footer>
  );
}

export function Protected({ children }: { children: ReactNode }) {
  const { status } = useSession();
  const { lang } = useI18n();
  const router = useRouter();
  useEffect(() => {
    if (status === "anonymous") router.replace(pathFor(lang, "/login"));
  }, [status, lang, router]);
  return status === "signed_in" ? <>{children}</> : <Loading />;
}

export function Page({ children }: { children: ReactNode }) {
  return <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-8">{children}</div>;
}
