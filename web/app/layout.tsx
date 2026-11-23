import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import "./globals.css";
import { PwaUpdate } from "@/components/PwaUpdate";
import { fontVariables } from "./fonts";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "STEM Games",
  description: "Play games, earn points, and see how your school is doing this week.",
  applicationName: "STEM Games",
  // The installed app's identity lives in app/manifest.ts (P9-T01).
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, title: "STEM Games", statusBarStyle: "default" },
  icons: {
    icon: [{ url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" }],
    apple: [{ url: "/icons/apple-touch-icon.png", sizes: "180x180" }],
  },
  formatDetection: { telephone: false },
};

export const viewport: Viewport = {
  themeColor: "#f8fafd",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={fontVariables}>
      <body className="min-h-screen font-body">
        <Providers>{children}</Providers>
        <PwaUpdate />
      </body>
    </html>
  );
}
