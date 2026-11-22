import Link from "next/link";

import { messagesFor } from "@/lib/dictionaries";
import { isLocale, pathFor } from "@/lib/text";

const BANKS = ["State Bank of India", "HDFC Bank", "ICICI Bank", "Axis Bank", "Kotak Mahindra Bank"];

export default async function Guide({ params }: PageProps<"/[lang]/guide">) {
  const { lang: raw } = await params;
  const lang = isLocale(raw) ? raw : "en";
  const t = messagesFor(lang).guide;
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-8">
      <h1 className="text-2xl font-semibold sm:text-3xl">{t.title}</h1>
      <p>{t.lead}</p>
      <ol className="list-decimal space-y-2 pl-5">
        {t.general.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ol>
      <section>
        <h2 className="mb-2 text-xl font-semibold">{t.banksTitle}</h2>
        <ul className="list-disc space-y-1 pl-5">
          {BANKS.map((bank) => (
            <li key={bank}>{bank}</li>
          ))}
        </ul>
        <p className="mt-3 text-muted">{t.bankNote}</p>
        <p className="mt-2 text-muted">{t.otherBanks}</p>
      </section>
      <Link href={pathFor(lang, "/upload")} className="self-start rounded-lg bg-brand px-5 py-3 font-semibold text-on-brand">
        {t.start}
      </Link>
    </div>
  );
}
