"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { ActionButton, InlineNotice } from "@/components/ui";
import { buildAuthLoginUrl, getAuthOptions, requestMagicLink, type AuthProvidersResponse } from "@/lib/api";

type OAuthProvider = "google" | "microsoft";

function GoogleMark() {
  return (
    <svg viewBox="0 0 18 18" className="auth-provider-logo" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M17.64 9.2045c0-.6382-.0573-1.2518-.1636-1.8409H9v3.4818h4.8436c-.2086 1.125-.8427 2.0782-1.796 2.7164v2.2582h2.908c1.702-1.5673 2.684-3.8755 2.684-6.6155z"
      />
      <path
        fill="#34A853"
        d="M9 18c2.43 0 4.4673-.8055 5.9564-2.1791l-2.9082-2.2582c-.8054.54-1.8364.8591-3.0482.8591-2.3441 0-4.3282-1.5832-5.0364-3.7109H.9573v2.3291C2.4382 15.98 5.4818 18 9 18z"
      />
      <path
        fill="#FBBC05"
        d="M3.9636 10.7109C3.7832 10.1709 3.6818 9.5945 3.6818 9s.1014-1.1709.2818-1.7109V4.96H.9573C.3477 6.1732 0 7.5491 0 9s.3477 2.8268.9573 4.04l3.0063-2.3291z"
      />
      <path
        fill="#EA4335"
        d="M9 3.5782c1.3214 0 2.5077.4541 3.4418 1.3459l2.5818-2.5818C13.4636.8918 11.4264 0 9 0 5.4818 0 2.4382 2.02.9573 4.96l3.0063 2.3291C4.6718 5.1614 6.6559 3.5782 9 3.5782z"
      />
    </svg>
  );
}

function MicrosoftMark() {
  return (
    <svg viewBox="0 0 18 18" className="auth-provider-logo" aria-hidden="true">
      <rect x="1" y="1" width="7" height="7" fill="#F25022" />
      <rect x="10" y="1" width="7" height="7" fill="#7FBA00" />
      <rect x="1" y="10" width="7" height="7" fill="#00A4EF" />
      <rect x="10" y="10" width="7" height="7" fill="#FFB900" />
    </svg>
  );
}

function ProviderArrow() {
  return (
    <svg viewBox="0 0 16 16" className="auth-provider-arrow-icon" aria-hidden="true">
      <path
        d="M4.5 8h7m0 0-2.75-2.75M11.5 8l-2.75 2.75"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.4"
      />
    </svg>
  );
}

function AuthProviderButton({ provider, nextPath }: { provider: OAuthProvider; nextPath: string }) {
  const isGoogle = provider === "google";
  const label = isGoogle ? "Google account" : "Microsoft account";
  const title = isGoogle ? "Continue with Google" : "Continue with Microsoft";

  return (
    <a
      href={buildAuthLoginUrl(provider, nextPath)}
      className={`auth-provider-button auth-provider-button-${provider}`}
      aria-label={title}
    >
      <span className="auth-provider-logo-shell">{isGoogle ? <GoogleMark /> : <MicrosoftMark />}</span>
      <span className="auth-provider-copy">
        <span className="auth-provider-kicker">{label}</span>
        <span className="auth-provider-title">{title}</span>
      </span>
      <span className="auth-provider-arrow">
        <ProviderArrow />
      </span>
    </a>
  );
}

export default function LoginPage() {
  const [nextPath, setNextPath] = useState("/console");
  const [error, setError] = useState<string | null>(null);
  const [providers, setProviders] = useState<AuthProvidersResponse | null>(null);
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ tone: "info" | "success" | "warning" | "error"; message: string } | null>(
    null
  );

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const rawNext = params.get("next");
    setNextPath(rawNext && rawNext.startsWith("/") ? rawNext : "/console");
    const rawError = params.get("error");
    setError(rawError);
  }, []);

  useEffect(() => {
    void getAuthOptions()
      .then(setProviders)
      .catch(() =>
        setProviders({
          google: true,
          microsoft: true,
          magic_link: false,
        })
      );
  }, []);

  useEffect(() => {
    if (!error) {
      return;
    }
    setNotice({ tone: "error", message: error });
  }, [error]);

  async function handleMagicLink(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setNotice({ tone: "info", message: "Sending secure sign-in link..." });
    try {
      const payload = await requestMagicLink(email, nextPath);
      setNotice({ tone: "success", message: payload.detail });
    } catch (issue) {
      setNotice({
        tone: "error",
        message: issue instanceof Error ? issue.message : "Unable to send the sign-in link right now.",
      });
    } finally {
      setBusy(false);
    }
  }

  const hasOAuthProviders = Boolean(providers?.google || providers?.microsoft);
  const magicLinkEyebrow = hasOAuthProviders ? "Fallback sign-in" : "Email sign-in";

  return (
    <div className="page-wrap auth-page-shell">
      <section className="panel auth-login-panel">
        <div className="auth-login-copy">
          <span className="landing-eyebrow">Sign in to continue</span>
          <h1 className="section-title">Enter the Heidi Tender workspace.</h1>
          <p className="section-subtitle">
            {providers?.magic_link
              ? "Use your Google or Microsoft account, or request a one-time magic link by email."
              : "Use your Google or Microsoft account to enter the Heidi Tender workspace."}
          </p>
        </div>

        {notice ? <InlineNotice tone={notice.tone} message={notice.message} className="mt-4" /> : null}

        {hasOAuthProviders ? (
          <div className="auth-provider-section">
            <div className="auth-provider-section-head">
              <span className="auth-provider-section-label">Primary sign-in</span>
              <p className="auth-provider-section-title">Choose your provider</p>
            </div>

            <div className="auth-login-actions">
              {providers?.google ? <AuthProviderButton provider="google" nextPath={nextPath} /> : null}
              {providers?.microsoft ? <AuthProviderButton provider="microsoft" nextPath={nextPath} /> : null}
            </div>
          </div>
        ) : null}

        {providers?.magic_link ? (
          <div className="auth-magic-shell">
            {hasOAuthProviders ? (
              <div className="auth-login-divider" aria-hidden="true">
                <span>Or use a secure sign-in link</span>
              </div>
            ) : null}

            <div className="auth-magic-head">
              <span className="auth-provider-section-label">{magicLinkEyebrow}</span>
              <p className="auth-magic-title">Receive a one-time email link</p>
              <p className="auth-magic-copy">We will send a secure sign-in link to your inbox.</p>
            </div>

            <form className="auth-magic-form" onSubmit={(event) => void handleMagicLink(event)}>
              <label className="auth-field">
                <span className="auth-field-label">Email address</span>
                <input
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  className="auth-text-input"
                  placeholder="you@company.com"
                  required
                />
              </label>
              <ActionButton
                type="submit"
                disabled={busy || !email.trim()}
                variant="secondary"
                className="auth-magic-submit"
              >
                {busy ? "Sending link..." : "Send magic link"}
              </ActionButton>
            </form>
          </div>
        ) : null}

        {providers && !providers.google && !providers.microsoft && !providers.magic_link ? (
          <InlineNotice
            tone="warning"
            message="No sign-in provider is currently configured. Add Google or Microsoft credentials in production settings to enable access."
            className="mt-4"
          />
        ) : null}

        <p className="auth-login-footnote">
          After sign-in you will return to <code>{nextPath}</code>. Need to browse first? <Link href="/">Go back home</Link>.
        </p>
      </section>
    </div>
  );
}
