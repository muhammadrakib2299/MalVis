import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MalVis — Explainable Malware Detection",
  description:
    "Interactive dashboard for the MalVis explainable malware-detection paper. Upload a Windows PE, see per-model predictions and SHAP explanations.",
  // No favicon here yet — placeholder until Phase 5 (docs + polish).
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
