import type { Metadata } from "next";
import { IBM_Plex_Mono, Manrope, Space_Grotesk } from "next/font/google";
import { AppHeader } from "@/components/app-header";
import { AuthSessionProvider, ProtectedRouteGate } from "@/components/auth-session-provider";
import "./globals.css";

const heading = Space_Grotesk({ subsets: ["latin"], variable: "--font-heading" });
const body = Manrope({ subsets: ["latin"], variable: "--font-body" });
const mono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-mono" });

export const metadata: Metadata = {
  title: {
    default: "Heidi Tender",
    template: "%s | Heidi Tender",
  },
  description: "Traceable tender intelligence for lighting engineering and bid teams.",
};

const themeInitScript = `
  (function() {
    var storageKey = "heidi-theme";
    var root = document.documentElement;
    var theme = "dark";
    try {
      var storedTheme = window.localStorage.getItem(storageKey);
      if (storedTheme === "light" || storedTheme === "dark") {
        theme = storedTheme;
      } else if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) {
        theme = "dark";
      } else {
        theme = "light";
      }
    } catch (error) {
      if (!(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches)) {
        theme = "light";
      }
    }
    root.dataset.theme = theme;
    root.style.colorScheme = theme;
  })();
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="dark" suppressHydrationWarning>
      <body className={`${heading.variable} ${body.variable} ${mono.variable} app-body`}>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
        <AuthSessionProvider>
          <AppHeader />
          <ProtectedRouteGate>
            <main className="app-main">{children}</main>
          </ProtectedRouteGate>
        </AuthSessionProvider>
      </body>
    </html>
  );
}
