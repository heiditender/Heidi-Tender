"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { getAuthSession, logout as apiLogout, type AuthUser, UnauthorizedError } from "@/lib/api";

type SessionStatus = "loading" | "authenticated" | "unauthenticated" | "error";

interface AuthSessionContextValue {
  status: SessionStatus;
  user: AuthUser | null;
  errorMessage: string | null;
  refreshSession: () => Promise<void>;
  logout: () => Promise<void>;
}

const AuthSessionContext = createContext<AuthSessionContextValue | null>(null);
const PUBLIC_PATHS = new Set(["/", "/login"]);

function currentNextPath(pathname: string, searchParams: { toString(): string }): string {
  const query = searchParams.toString();
  return query ? `${pathname}?${query}` : pathname;
}

export function AuthSessionProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [status, setStatus] = useState<SessionStatus>("loading");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const refreshSession = useCallback(async () => {
    try {
      const payload = await getAuthSession();
      setUser(payload.user);
      setStatus("authenticated");
      setErrorMessage(null);
    } catch (error) {
      if (error instanceof UnauthorizedError) {
        setUser(null);
        setStatus("unauthenticated");
        setErrorMessage(null);
        return;
      }
      setStatus("error");
      setErrorMessage(error instanceof Error ? error.message : "Unable to verify session");
    }
  }, []);

  useEffect(() => {
    void refreshSession();
  }, [refreshSession]);

  useEffect(() => {
    const handler = () => {
      setUser(null);
      setStatus("unauthenticated");
      setErrorMessage(null);
    };
    window.addEventListener("heidi:auth-required", handler as EventListener);
    return () => window.removeEventListener("heidi:auth-required", handler as EventListener);
  }, []);

  useEffect(() => {
    const isPublic = PUBLIC_PATHS.has(pathname);
    const replaceTarget = (target: string) =>
      router.replace(target as Parameters<typeof router.replace>[0]);
    const browserSearchParams =
      typeof window === "undefined" ? new URLSearchParams() : new URLSearchParams(window.location.search);
    if (status === "loading") {
      return;
    }
    if (pathname === "/login" && status === "authenticated") {
      const next = browserSearchParams.get("next");
      replaceTarget(next && next.startsWith("/") ? next : "/console");
      return;
    }
    if (!isPublic && status === "unauthenticated") {
      const next = currentNextPath(pathname, browserSearchParams);
      replaceTarget(`/login?next=${encodeURIComponent(next)}`);
    }
  }, [pathname, router, status]);

  const logout = useCallback(async () => {
    await apiLogout();
    setUser(null);
    setStatus("unauthenticated");
    setErrorMessage(null);
    router.push("/");
  }, [router]);

  const value = useMemo<AuthSessionContextValue>(
    () => ({
      status,
      user,
      errorMessage,
      refreshSession,
      logout,
    }),
    [errorMessage, logout, refreshSession, status, user]
  );

  return <AuthSessionContext.Provider value={value}>{children}</AuthSessionContext.Provider>;
}

export function useAuthSession() {
  const value = useContext(AuthSessionContext);
  if (!value) {
    throw new Error("useAuthSession must be used inside AuthSessionProvider");
  }
  return value;
}

export function ProtectedRouteGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { status, errorMessage } = useAuthSession();
  const isPublic = PUBLIC_PATHS.has(pathname);

  if (isPublic) {
    return <>{children}</>;
  }
  if (status === "loading") {
    return (
      <div className="page-wrap">
        <section className="panel auth-gate-panel">
          <p className="auth-gate-title">Checking session...</p>
          <p className="auth-gate-copy">Verifying your Heidi Tender login before loading the workspace.</p>
        </section>
      </div>
    );
  }
  if (status === "error") {
    return (
      <div className="page-wrap">
        <section className="panel auth-gate-panel">
          <p className="auth-gate-title">Session check failed</p>
          <p className="auth-gate-copy">{errorMessage ?? "Please refresh and try again."}</p>
        </section>
      </div>
    );
  }
  if (status !== "authenticated") {
    return null;
  }
  return <>{children}</>;
}
