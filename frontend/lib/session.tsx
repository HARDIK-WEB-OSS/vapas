"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api, refreshSession, setAccessToken, setSignedOutHandler } from "@/lib/api";
import type { Me, TokenOut } from "@/lib/types";

type Status = "loading" | "anonymous" | "signed_in";

type Session = {
  status: Status;
  me: Me | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  reload: () => Promise<void>;
  forget: () => void;
};

const SessionContext = createContext<Session | null>(null);
const SIGNED_IN_HINT = "vapas-signed-in";

function rememberSignedIn(signedIn: boolean): void {
  try {
    if (signedIn) window.localStorage.setItem(SIGNED_IN_HINT, "1");
    else window.localStorage.removeItem(SIGNED_IN_HINT);
  } catch {}
}

function mightBeSignedIn(): boolean {
  try {
    return window.localStorage.getItem(SIGNED_IN_HINT) === "1";
  } catch {
    return true;
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [me, setMe] = useState<Me | null>(null);

  const forget = useCallback(() => {
    setAccessToken(null);
    rememberSignedIn(false);
    setMe(null);
    setStatus("anonymous");
  }, []);

  const reload = useCallback(async () => {
    setMe(await api<Me>("/account/me"));
    setStatus("signed_in");
  }, []);

  useEffect(() => {
    setSignedOutHandler(forget);
    let active = true;
    const attempt = mightBeSignedIn() ? refreshSession() : Promise.resolve(false);
    attempt
      .then(async (ok) => {
        if (!active) return;
        if (!ok) {
          forget();
          return;
        }
        await reload();
      })
      .catch(() => active && forget());
    return () => {
      active = false;
      setSignedOutHandler(null);
    };
  }, [forget, reload]);

  const login = useCallback(
    async (email: string, password: string) => {
      const grant = await api<TokenOut>("/auth/login", {
        method: "POST",
        body: { email, password },
        auth: false,
        withCookie: true,
      });
      setAccessToken(grant.access_token);
      rememberSignedIn(true);
      await reload();
    },
    [reload],
  );

  const logout = useCallback(async () => {
    await api("/auth/logout", { method: "POST", withCookie: true }).catch(() => undefined);
    forget();
  }, [forget]);

  const value = useMemo(() => ({ status, me, login, logout, reload, forget }), [status, me, login, logout, reload, forget]);
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const value = useContext(SessionContext);
  if (!value) throw new Error("SessionProvider is missing");
  return value;
}
