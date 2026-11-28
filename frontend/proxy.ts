import { NextResponse, type NextRequest } from "next/server";

import { isLocale, type Locale } from "@/lib/text";

const API_PREFIX = "/api";
const PROXY_SECRET_HEADER = "x-vapas-proxy-secret";
const CLIENT_IP_HEADER = "x-vapas-client-ip";

function preferredLocale(request: NextRequest): Locale {
  const saved = request.cookies.get("vapas_locale")?.value;
  if (saved && isLocale(saved)) return saved;
  const accepted = request.headers.get("accept-language") ?? "";
  return /^\s*hi\b/i.test(accepted) ? "hi" : "en";
}

function clientIp(request: NextRequest): string | null {
  const real = request.headers.get("x-real-ip")?.trim();
  if (real) return real;
  const forwarded = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim();
  return forwarded || null;
}

function isApiPath(pathname: string): boolean {
  return pathname === API_PREFIX || pathname.startsWith(`${API_PREFIX}/`);
}

function proxyToApi(request: NextRequest): NextResponse {
  const origin = process.env.VAPAS_API_ORIGIN;
  const secret = process.env.VAPAS_PROXY_SECRET;
  if (!origin || !secret) return NextResponse.json({ error: "not_found" }, { status: 404 });
  const { pathname, search } = request.nextUrl;
  const target = new URL(`${pathname.slice(API_PREFIX.length) || "/"}${search}`, origin);
  const ip = clientIp(request);
  const headers = new Headers(request.headers);
  headers.delete(CLIENT_IP_HEADER);
  headers.set(PROXY_SECRET_HEADER, secret);
  if (ip) headers.set(CLIENT_IP_HEADER, ip);
  return NextResponse.rewrite(target, { request: { headers } });
}

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (isApiPath(pathname)) return proxyToApi(request);
  const first = pathname.split("/")[1] ?? "";
  if (isLocale(first)) return NextResponse.next();
  const url = request.nextUrl.clone();
  url.pathname = `/${preferredLocale(request)}${pathname === "/" ? "" : pathname}`;
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ["/((?!_next|favicon.ico|robots.txt).*)"],
};
