"use client";

import Link from "next/link";
import Logo from "@/components/Logo";
import { useState } from "react";
import { Menu, X } from "lucide-react";
import { Button } from "@/components/ui/button";

const NAV_LINKS = [
  { label: "Features", href: "#features" },
  { label: "How it works", href: "#how-it-works" },
  { label: "Personas", href: "#personas" },
];

export default function Navbar() {
  const [open, setOpen] = useState(false);

  return (
    <header className="fixed top-0 inset-x-0 z-50 bg-background/90 backdrop-blur-md border-b border-border">
      <div className="mx-auto max-w-7xl px-6 flex items-center justify-between h-16">
        {/* Logo */}
        <Link href="/" className="flex items-center gap-2.5 shrink-0">
          <Logo />
          <span className="text-foreground font-semibold text-lg tracking-tight text-trim">
            Mock<span className="text-orange">Mate</span>
          </span>
        </Link>

        {/* Desktop nav */}
        <nav className="hidden md:flex items-center gap-8">
          {NAV_LINKS.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className="text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
            >
              {l.label}
            </Link>
          ))}
        </nav>

        {/* Desktop CTA */}
        <div className="hidden md:flex items-center gap-3">
          <Button variant="ghost" asChild className="text-foreground hover:text-orange hover:bg-transparent">
            <Link href="/login">Sign in</Link>
          </Button>
          <Button asChild className="rounded-full bg-orange text-light hover:opacity-90 hover:bg-orange transition-opacity">
            <Link href="/login">Start free</Link>
          </Button>
        </div>

        {/* Mobile menu toggle */}
        <Button
          variant="ghost"
          size="icon"
          className="md:hidden text-foreground hover:bg-transparent"
          onClick={() => setOpen((v) => !v)}
          aria-label="Toggle menu"
        >
          {open ? <X size={22} /> : <Menu size={22} />}
        </Button>
      </div>

      {/* Mobile dropdown */}
      {open && (
        <div className="md:hidden bg-background border-t border-border px-6 py-4 flex flex-col gap-4">
          {NAV_LINKS.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              onClick={() => setOpen(false)}
              className="text-sm font-medium text-foreground hover:text-orange transition-colors"
            >
              {l.label}
            </Link>
          ))}
          <Button
            asChild
            className="mt-2 rounded-full bg-orange text-light hover:opacity-90 hover:bg-orange"
            onClick={() => setOpen(false)}
          >
            <Link href="/login">Start free</Link>
          </Button>
        </div>
      )}
    </header>
  );
}
