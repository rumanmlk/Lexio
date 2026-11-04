import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono, Newsreader } from "next/font/google";
import "./globals.css";

const display = Newsreader({ subsets: ["latin"], variable: "--font-display", axes: ["opsz"], display: "swap" });
const body = Geist({ subsets: ["latin"], variable: "--font-body", display: "swap" });
const mono = Geist_Mono({ subsets: ["latin"], variable: "--font-mono", display: "swap" });

const site = process.env.VERCEL_PROJECT_PRODUCTION_URL ? `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}` : "http://localhost:3000";

export const metadata: Metadata = {
  metadataBase: new URL(site),
  title: { default: "Lexio: ask legal PDFs, get the page it came from", template: "%s · Lexio" },
  description:
    "Ask questions about contracts and legal documents. Every answer cites the exact page, and Lexio says so when the documents don't contain the answer.",
  openGraph: { title: "Lexio", description: "Ask the contract. Get the page it came from.", type: "website" },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f3f5f4" },
    { media: "(prefers-color-scheme: dark)", color: "#0d1412" },
  ],
};

// Sets the saved theme before first paint so a dark-theme visitor never sees a white flash.
const THEME_INIT = `try{var t=localStorage.getItem("lexio-theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable} ${mono.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
