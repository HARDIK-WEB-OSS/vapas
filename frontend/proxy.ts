import { NextResponse, type NextRequest } from "next/server";

import { isLocale, type Locale } from "@/lib/text";

function preferredLocale(request: NextRequest): Locale {
  const saved = request.cookies.get("vapas_locale")?.value;
  if (saved && isLocale(saved)) return saved;
  const accepted = request.headers.get("accept-language") ?? "";
  return /^\s*hi\b/i.test(accepted) ? "hi" : "en";
}

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const first = pathname.split("/")[1] ?? "";
  if (isLocale(first)) return NextResponse.next();
  const url = request.nextUrl.clone();
  url.pathname = `/${preferredLocale(request)}${pathname === "/" ? "" : pathname}`;
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ["/((?!_next|favicon.ico|robots.txt).*)"],
};
