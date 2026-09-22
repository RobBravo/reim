import type { Metadata } from "next";
import "./globals.css";
import { Header } from "@/components/Header";
import { Providers } from "@/components/Providers";

export const metadata: Metadata = {
  title: "REIM — Monitor Económico Regional de Centroamérica",
  description: "Estadísticas macroeconómicas oficiales y comparables para América Central.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="es" className="dark">
      <body className="min-h-screen bg-reim-bg text-reim-text antialiased">
        <Providers>
          <Header />
          <main>{children}</main>
        </Providers>
      </body>
    </html>
  );
}
