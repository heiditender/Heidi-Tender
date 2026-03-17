"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cx } from "@/components/ui";
import { getModelSettings, setModelSettings, type ModelSettingsResponse } from "@/lib/api";
import { useTheme, type Theme } from "@/lib/use-theme";
import { useAuthSession } from "@/components/auth-session-provider";
import HeidiLogoLight from "../../../../assets/heidi_logo_bl.png";
import HeidiLogoDark from "../../../../assets/heidi_logo_ws.png";

const APP_NAV_ITEMS: Array<{ href: "/console" | "/rules" | "/stats"; label: string; match: (pathname: string) => boolean }> = [
  { href: "/console", label: "Task Console", match: (pathname: string) => pathname === "/console" || pathname.startsWith("/jobs/") },
  { href: "/rules", label: "Rules Workbench", match: (pathname: string) => pathname.startsWith("/rules") },
  { href: "/stats", label: "Analytics", match: (pathname: string) => pathname.startsWith("/stats") },
];

const MARKETING_NAV_ITEMS = [
  { href: "#problem", label: "Problem" },
  { href: "#workflow", label: "Workflow" },
  { href: "#economics", label: "Economics" },
];

function getPageHint(pathname: string) {
  if (pathname.startsWith("/stats")) {
    return "View job duration, step duration, extraction scale, and field frequency heatmap";
  }
  if (pathname.startsWith("/rules")) {
    return "Edit, validate, and publish field_rules versions";
  }
  if (pathname.startsWith("/jobs/")) {
    return "View the execution timeline, SSE events, and final results";
  }
  if (pathname === "/console") {
    return "Create jobs, upload tender files, and start the matching pipeline";
  }
  return "Traceable tender intelligence for lighting teams";
}

function ThemeToggle({ theme, setTheme }: { theme: Theme; setTheme: (nextTheme: Theme) => void }) {
  return (
    <div className="theme-toggle" role="group" aria-label="Theme">
      <button
        type="button"
        className="theme-toggle-option"
        data-theme-option="light"
        aria-pressed={theme === "light"}
        onClick={() => setTheme("light")}
      >
        Light
      </button>
      <button
        type="button"
        className="theme-toggle-option"
        data-theme-option="dark"
        aria-pressed={theme === "dark"}
        onClick={() => setTheme("dark")}
      >
        Dark
      </button>
    </div>
  );
}

function Brand({ href, subtitle }: { href: "/" | "/console"; subtitle: string }) {
  return (
    <div className="app-brand">
      <Link href={href} className="app-brand-link" aria-label="Heidi Tender home">
        <span className="app-brand-mark">
          <Image
            src={HeidiLogoLight}
            alt=""
            aria-hidden="true"
            className="app-brand-logo app-brand-logo-light"
            priority
            sizes="(max-width: 640px) 58px, 70px"
          />
          <Image
            src={HeidiLogoDark}
            alt=""
            aria-hidden="true"
            className="app-brand-logo app-brand-logo-dark"
            priority
            sizes="(max-width: 640px) 58px, 70px"
          />
        </span>
        <span className="app-brand-copy">
          <span className="app-brand-title">Heidi Tender</span>
          <span className="app-brand-subtitle">{subtitle}</span>
        </span>
      </Link>
    </div>
  );
}

function SessionControls() {
  const { status, user, logout } = useAuthSession();

  if (status === "authenticated" && user) {
    return (
      <>
        <span className="app-session-pill">{user.email}</span>
        <button type="button" className="btn btn-secondary app-session-logout" onClick={() => void logout()}>
          Log out
        </button>
      </>
    );
  }
  return (
    <Link href="/login" className="btn btn-secondary app-nav-cta">
      Log in
    </Link>
  );
}

function MarketingHeader({ theme, setTheme, isLoginPage }: { theme: Theme; setTheme: (nextTheme: Theme) => void; isLoginPage: boolean }) {
  return (
    <header className="app-header">
      <div className="page-wrap app-header-inner">
        <Brand href="/" subtitle="Traceable tender intelligence for lighting teams" />
        <nav className="app-nav" aria-label="Homepage sections">
          {!isLoginPage
            ? MARKETING_NAV_ITEMS.map((item) => (
                <a key={item.href} href={item.href} className="app-nav-link">
                  {item.label}
                </a>
              ))
            : (
              <Link href="/" className="app-nav-link">
                Home
              </Link>
            )}
          <ThemeToggle theme={theme} setTheme={setTheme} />
          <Link href="/console" className="btn btn-primary app-nav-cta">
            Open Console
          </Link>
          <SessionControls />
        </nav>
      </div>
    </header>
  );
}

function AppNavigationHeader({
  pathname,
  theme,
  setTheme,
  modelSettings,
  updatingModel,
  handleModelChange,
}: {
  pathname: string;
  theme: Theme;
  setTheme: (nextTheme: Theme) => void;
  modelSettings: ModelSettingsResponse | null;
  updatingModel: boolean;
  handleModelChange: (nextModel: "gpt-5.4" | "gpt-5-mini") => Promise<void>;
}) {
  return (
    <header className="app-header">
      <div className="page-wrap app-header-inner">
        <Brand href="/console" subtitle={getPageHint(pathname)} />
        <nav className="app-nav" aria-label="Main navigation">
          {APP_NAV_ITEMS.map((item) => {
            const active = item.match(pathname);
            return (
              <Link key={item.href} href={item.href} className={cx("app-nav-link", active && "app-nav-link-active")}>
                {item.label}
              </Link>
            );
          })}
          <ThemeToggle theme={theme} setTheme={setTheme} />
          <label className="app-model-control" htmlFor="global-model-select">
            <span className="app-model-label">Model</span>
            <select
              id="global-model-select"
              className="app-model-select"
              value={modelSettings?.current_model ?? "gpt-5-mini"}
              onChange={(event) => void handleModelChange(event.target.value as "gpt-5.4" | "gpt-5-mini")}
              disabled={updatingModel}
            >
              <option value="gpt-5.4">gpt-5.4</option>
              <option value="gpt-5-mini">gpt-5-mini</option>
            </select>
          </label>
          <span className={cx("app-key-state", modelSettings?.has_api_key ? "app-key-state-on" : "app-key-state-off")}>
            {modelSettings?.has_api_key ? "API key configured" : "API key missing"}
          </span>
          <SessionControls />
        </nav>
      </div>
    </header>
  );
}

export function AppHeader() {
  const pathname = usePathname();
  const isMarketingPage = pathname === "/" || pathname === "/login";
  const isLoginPage = pathname === "/login";
  const { theme, setTheme } = useTheme();
  const { status } = useAuthSession();
  const [modelSettings, setModelSettingsState] = useState<ModelSettingsResponse | null>(null);
  const [updatingModel, setUpdatingModel] = useState(false);

  useEffect(() => {
    if (isMarketingPage || status !== "authenticated") {
      return;
    }
    void getModelSettings()
      .then(setModelSettingsState)
      .catch(() => null);
  }, [isMarketingPage, status]);

  async function handleModelChange(nextModel: "gpt-5.4" | "gpt-5-mini") {
    setUpdatingModel(true);
    try {
      const payload = await setModelSettings(nextModel);
      setModelSettingsState(payload);
    } catch {
      // keep previous selection and let critical actions fail with explicit backend error
    } finally {
      setUpdatingModel(false);
    }
  }

  if (isMarketingPage) {
    return <MarketingHeader theme={theme} setTheme={setTheme} isLoginPage={isLoginPage} />;
  }

  return (
    <AppNavigationHeader
      pathname={pathname}
      theme={theme}
      setTheme={setTheme}
      modelSettings={modelSettings}
      updatingModel={updatingModel}
      handleModelChange={handleModelChange}
    />
  );
}
