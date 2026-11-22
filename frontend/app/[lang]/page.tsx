import Link from "next/link";

import { messagesFor } from "@/lib/dictionaries";
import { isLocale, pathFor } from "@/lib/text";

export default async function Landing({ params }: PageProps<"/[lang]">) {
  const { lang: raw } = await params;
  const lang = isLocale(raw) ? raw : "en";
  const t = messagesFor(lang).landing;
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-4 py-10">
      <section className="flex flex-col gap-4">
        <h1 className="text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">{t.title}</h1>
        <p className="text-lg">{t.lead}</p>
        <div className="flex flex-col gap-3 sm:flex-row">
          <Link href={pathFor(lang, "/signup")} className="min-h-11 rounded-lg bg-brand px-5 py-3 text-center font-semibold text-on-brand">
            {t.cta}
          </Link>
          <Link href={pathFor(lang, "/login")} className="min-h-11 rounded-lg border border-line px-5 py-3 text-center">
            {t.login}
          </Link>
        </div>
      </section>
      <section className="rounded-xl border border-brand bg-brand-soft p-4">
        <h2 className="mb-2 text-xl font-semibold">{t.promisesTitle}</h2>
        <ul className="list-disc space-y-1 pl-5">
          {t.promises.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </section>
      <section>
        <h2 className="mb-2 text-xl font-semibold">{t.howTitle}</h2>
        <ol className="list-decimal space-y-1 pl-5">
          {t.steps.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ol>
      </section>
      <section>
        <h2 className="mb-2 text-xl font-semibold">{t.ruleTitle}</h2>
        <p>{t.rule}</p>
      </section>
      <p className="font-semibold">{t.notLegalAdvice}</p>
    </div>
  );
}
