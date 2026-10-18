import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { BRAND, LEGAL } from "@/lib/brand";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
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
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="min-h-full bg-black text-white">
        {/* Vercel Web Analytics is off on this project, so its script 404s; Sentry covers us. */}
        {children}
      </body>
    </html>
  );
}
