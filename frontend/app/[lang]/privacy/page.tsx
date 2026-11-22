import { messagesFor } from "@/lib/dictionaries";
import { isLocale } from "@/lib/text";

export default async function Privacy({ params }: PageProps<"/[lang]/privacy">) {
  const { lang } = await params;
  const t = messagesFor(isLocale(lang) ? lang : "en").privacy;
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-5 px-4 py-8">
      <h1 className="text-2xl font-semibold sm:text-3xl">{t.title}</h1>
      <p className="rounded-lg border-l-4 border-warn bg-warn-soft p-3">{t.draft}</p>
      {t.sections.map((section) => (
        <section key={section.h}>
          <h2 className="mb-1 text-lg font-semibold">{section.h}</h2>
          <p>{section.p}</p>
        </section>
      ))}
    </div>
  );
}
