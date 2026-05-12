import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "LibertAI Avatar",
  description: "Open-source avatar chat powered by LibertAI"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
