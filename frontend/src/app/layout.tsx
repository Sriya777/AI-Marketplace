import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import Providers from "@/components/Providers";
import { SessionProvider } from "@/lib/session";
import Shell from "@/components/Shell";

const geistSans = localFont({ src: "./fonts/GeistVF.woff", variable: "--font-geist-sans", weight: "100 900" });
const geistMono = localFont({ src: "./fonts/GeistMonoVF.woff", variable: "--font-geist-mono", weight: "100 900" });

export const metadata: Metadata = {
  title: "AI Model Marketplace",
  description: "Decentralized AI Model Marketplace with Cryptographic Verification",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased`}>
        <Providers>
          <SessionProvider>
            <Shell>{children}</Shell>
          </SessionProvider>
        </Providers>
      </body>
    </html>
  );
}
