"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_LINKS = [
  { href: "/", label: "Inicio" },
  { href: "/map/", label: "Mapa" },
  { href: "/series/", label: "Series" },
  { href: "/catalog/", label: "Catálogo" },
  // The observability page remains under apps/web until its frontend rewrite.
  { href: "/legacy/runs", label: "Operaciones", interim: true },
];

export function Header() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-50 w-full border-b border-reim-border bg-reim-bg/90 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4 sm:px-6">
        <div className="flex items-center gap-3">
          <Link href="/" className="flex items-center gap-2 font-bold tracking-wider text-reim-text">
            <span className="flex h-7 w-7 items-center justify-center rounded bg-reim-gold/20 text-reim-gold font-mono text-xs border border-reim-gold/40">
              R
            </span>
            <span>REIM</span>
          </Link>
          <span className="hidden text-xs text-reim-subtle sm:inline-block border-l border-reim-border pl-3">
            Monitor Económico Regional
          </span>
        </div>

        <nav className="flex items-center gap-1 sm:gap-2">
          {NAV_LINKS.map((link) => {
            const isActive = pathname === link.href || (link.href !== "/" && pathname?.startsWith(link.href));
            const className = `rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
              isActive
                ? "bg-reim-surface text-reim-gold border border-reim-gold/30"
                : "text-reim-muted hover:bg-reim-surface hover:text-reim-text"
            }`;
            if (link.interim) {
              // Plain <a>, deliberately not next/link — see the comment on
              // NAV_LINKS above.
              return (
                <a key={link.href} href={link.href} className={className}>
                  {link.label}
                </a>
              );
            }
            return (
              <Link key={link.href} href={link.href} className={className}>
                {link.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
