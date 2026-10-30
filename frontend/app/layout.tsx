import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Lexio",
  description: "Ask questions about legal PDFs and get answers with page citations.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
