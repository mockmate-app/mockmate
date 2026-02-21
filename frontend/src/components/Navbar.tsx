"use client";

import Link from "next/link";
import Logo from "@/components/Logo";
import { useState } from "react";
import { Menu, X } from "lucide-react";

const NAV_LINKS = [
  { label: "Features", href: "#features" },
  { label: "How it works", href: "#how-it-works" },
  { label: "Personas", href: "#personas" },
];

export default function Navbar() {
  const [open, setOpen] = useState(false);

  return (
    <header className="fixed top-0 inset-x-0 z-50 bg-light/90 backdrop-blur-md border-b border-border">
      <div className="mx-auto max-w-7xl px-6 flex items-center justify-between h-16">
        {/* Logo */}
        <Link href="/" className="flex items-center gap-2.5 shrink-0">
          <Logo />
          <span className="text-dark font-semibold text-lg tracking-tight">
            Mock<span className="text-orange">Mate</span>
          </span>
        </Link>

        {/* Desktop nav */}
        <nav className="hidden md:flex items-center gap-8">
          {NAV_LINKS.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className="text-sm font-medium text-muted hover:text-dark transition-colors"
            >
              {l.label}
            </Link>
          ))}
        </nav>

        {/* Desktop CTA */}
        <div className="hidden md:flex items-center gap-3">
          <Link href="#" className="text-sm font-medium text-dark hover:text-orange transition-colors">
            Sign in
          </Link>
          <Link
            href="#"
            className="rounded-full bg-orange px-5 py-2 text-sm font-semibold text-light hover:opacity-90 transition-opacity"
          >
            Start free
          </Link>
        </div>

        {/* Mobile menu toggle */}
        <button
          className="md:hidden p-1 text-dark"
          onClick={() => setOpen((v) => !v)}
          aria-label="Toggle menu"
        >
          {open ? <X size={22} /> : <Menu size={22} />}
        </button>
      </div>

      {/* Mobile dropdown */}
      {open && (
        <div className="md:hidden bg-light border-t border-border px-6 py-4 flex flex-col gap-4">
          {NAV_LINKS.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              onClick={() => setOpen(false)}
              className="text-sm font-medium text-dark hover:text-orange transition-colors"
            >
              {l.label}
            </Link>
          ))}
          <Link
            href="#"
            onClick={() => setOpen(false)}
            className="mt-2 rounded-full bg-orange px-5 py-2.5 text-center text-sm font-semibold text-light hover:opacity-90 transition-opacity"
          >
            Start free
          </Link>
        </div>
      )}
    </header>
  );
}
