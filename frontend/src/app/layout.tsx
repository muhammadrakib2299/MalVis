import type { Metadata } from "next";
import "./globals.css";

import { ThemeProvider } from "@/components/theme-provider";

export const metadata: Metadata = {
  title: "MalVis — Explainable Malware Detection",
  description:
    "Interactive dashboard for the MalVis explainable malware-detection paper. Upload a Windows PE, see per-model predictions and SHAP explanations.",
  // No favicon here yet — placeholder until Phase 5 (docs + polish).
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // suppressHydrationWarning is the documented pattern for next-themes:
    // the provider mutates <html class> on mount to reflect the active
    // theme, which is otherwise flagged as a server/client mismatch.
    <html lang="en" suppressHydrationWarning>
      <body>
        <ThemeProvider attribute="class" defaultTheme="dark" enableSystem={false}>
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
