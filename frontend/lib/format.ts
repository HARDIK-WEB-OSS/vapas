import type { Locale } from "@/lib/text";

const IST_DAY = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" });

export function money(paise: number, lang: Locale): string {
  const whole = paise % 100 === 0;
  return new Intl.NumberFormat(lang === "hi" ? "hi-IN" : "en-IN", {
    style: "currency",
    currency: "INR",
    minimumFractionDigits: whole ? 0 : 2,
    maximumFractionDigits: whole ? 0 : 2,
  }).format(paise / 100);
}

export function day(iso: string | null | undefined): string {
  if (!iso) return "-";
  const [year, month, date] = iso.slice(0, 10).split("-");
  return `${date}/${month}/${year}`;
}

export function todayIst(): string {
  return IST_DAY.format(new Date());
}

export function rupeesToPaise(value: string): number | null {
  const cleaned = value.replace(/[,\s₹]/g, "");
  if (!/^\d+(\.\d{1,2})?$/.test(cleaned)) return null;
  const [rupees, fraction = ""] = cleaned.split(".");
  return Number(rupees) * 100 + Number(fraction.padEnd(2, "0"));
}
