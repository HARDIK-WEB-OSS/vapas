import { messagesFor } from "@/lib/dictionaries";
import { isLocale } from "@/lib/text";

export default async function Terms({ params }: PageProps<"/[lang]/terms">) {
  const { lang } = await params;
  const t = messagesFor(isLocale(lang) ? lang : "en").terms;
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-5 px-4 py-8">
      <h1 className="text-2xl font-semibold sm:text-3xl">{t.title}</h1>
      <p className="rounded-lg border-l-4 border-warn bg-warn-soft p-3">{t.draft}</p>
      <ol className="list-decimal space-y-2 pl-5">
        {t.items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ol>
    </div>
  );
}
