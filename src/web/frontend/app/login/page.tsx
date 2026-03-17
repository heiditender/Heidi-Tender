"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { ActionButton, InlineNotice } from "@/components/ui";
import { buildAuthLoginUrl, getAuthOptions, requestMagicLink, type AuthProvidersResponse } from "@/lib/api";

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

        <div className="auth-login-actions">
          {providers?.google ? (
            <a href={buildAuthLoginUrl("google", nextPath)} className="btn btn-primary auth-provider-button">
              Continue with Google
            </a>
          ) : null}
          {providers?.microsoft ? (
            <a href={buildAuthLoginUrl("microsoft", nextPath)} className="btn btn-secondary auth-provider-button">
              Continue with Microsoft
            </a>
          ) : null}
        </div>

        {providers?.magic_link ? (
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
