"use client";

import Link from "next/link";
import Logo from "@/components/Logo";
import { useState, useEffect } from "react";
import { signIn, useSession } from "@/lib/auth-client";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const [loading, setLoading] = useState(false);
  const { data: session, isPending } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (!isPending && session) {
      router.replace("/dashboard");
    }
  }, [session, isPending, router]);

  const handleGoogleLogin = async () => {
    setLoading(true);
    await signIn.social({
      provider: "google",
      callbackURL: "/dashboard",
      newUserCallbackURL: "/dashboard?newuser=1",
    });
    // No need to setLoading(false) — browser will redirect
  };

  return (
    <div className="min-h-screen bg-surface flex flex-col">
      {/* Top bar */}
      <header className="bg-light border-b border-border px-6 h-16 flex items-center">
        <Link href="/" className="flex items-center gap-2.5">
          <Logo />
          <span className="text-dark font-semibold text-lg tracking-tight">
            Mock<span className="text-orange">Mate</span>
          </span>
        </Link>
      </header>

      {/* Centered card */}
      <main className="flex-1 flex items-center justify-center px-4 py-16">
        <div className="w-full max-w-sm bg-light rounded-xl border border-border shadow-sm p-8 flex flex-col items-center gap-6">
          {/* Heading */}
          <div className="text-center space-y-1.5">
            <h1 className="text-2xl font-bold text-dark tracking-tight">
              Welcome back
            </h1>
            <p className="text-sm text-muted">
              Sign in to continue your interview practice
            </p>
          </div>

          {/* Divider */}
          <div className="w-full border-t border-border" />

          {/* Google button */}
          <button
            onClick={handleGoogleLogin}
            disabled={loading}
            className="w-full flex items-center justify-center gap-3 bg-light border border-border rounded-lg px-4 py-3 text-sm font-medium text-dark hover:bg-surface active:scale-[0.98] transition-all duration-150 cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {/* Google logo SVG */}
            <svg
              width="18"
              height="18"
              viewBox="0 0 18 18"
              xmlns="http://www.w3.org/2000/svg"
              aria-hidden="true"
            >
              <path
                d="M17.64 9.204c0-.638-.057-1.252-.164-1.84H9v3.481h4.844a4.14 4.14 0 0 1-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.875 2.684-6.616Z"
                fill="#4285F4"
              />
              <path
                d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18Z"
                fill="#34A853"
              />
              <path
                d="M3.964 10.71A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.042l3.007-2.332Z"
                fill="#FBBC05"
              />
              <path
                d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58Z"
                fill="#EA4335"
              />
            </svg>
            {loading ? "Redirecting…" : "Continue with Google"}
          </button>

          {/* Terms */}
          <p className="text-xs text-muted text-center leading-relaxed">
            By continuing, you agree to our{" "}
            <Link href="/terms" className="underline underline-offset-2 hover:text-dark transition-colors">
              Terms of Service
            </Link>{" "}
            and{" "}
            <Link href="/privacy" className="underline underline-offset-2 hover:text-dark transition-colors">
              Privacy Policy
            </Link>
            .
          </p>
        </div>
      </main>

      {/* Footer note */}
      <footer className="py-6 text-center text-xs text-muted">
        © {new Date().getFullYear()} MockMate. All rights reserved.
      </footer>
    </div>
  );
}
