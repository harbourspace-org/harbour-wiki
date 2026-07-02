import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Harbour.Wiki",
  description: "The living encyclopedia of everything taught — built on Knottra.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
