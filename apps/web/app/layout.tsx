import type { Metadata } from "next";
import { DM_Mono, Host_Grotesk } from "next/font/google";
import { BRAND, LEGAL } from "@/lib/brand";
import "./globals.css";

// Host Grotesk for every word and number; DM Mono only for small caps labels.
const hostGrotesk = Host_Grotesk({
  variable: "--font-host-grotesk",
  subsets: ["latin"],
});

const dmMono = DM_Mono({
  variable: "--font-dm-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: `${BRAND.name} — ${BRAND.tagline}`,
  description: BRAND.description,
  applicationName: BRAND.name,
  authors: [{ name: LEGAL.owner }],
  creator: LEGAL.owner,
  publisher: LEGAL.owner,
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${hostGrotesk.variable} ${dmMono.variable} h-full antialiased`}>
      <body className="min-h-full bg-page text-white">
        {/* Vercel Web Analytics is off on this project, so its script 404s; Sentry covers us. */}
        {children}
      </body>
    </html>
  );
}
