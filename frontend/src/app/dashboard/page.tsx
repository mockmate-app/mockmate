"use client";

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import Image from "next/image";
import { useSession, signOut } from "@/lib/auth-client";
import Logo from "@/components/Logo";
import { Mic, FileText, BarChart2, LogOut } from "lucide-react";

export default function DashboardPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-surface flex items-center justify-center">
          <div className="w-6 h-6 border-2 border-orange border-t-transparent rounded-full animate-spin" />
        </div>
      }
    >
      <DashboardContent />
    </Suspense>
  );
}

function DashboardContent() {
  const { data: session, isPending } = useSession();
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    if (isPending) return;

    // Not authenticated → go to login
    if (!session) {
      router.replace("/login");
    }
  }, [session, isPending, router]);

  if (isPending) {
    return (
      <div className="min-h-screen bg-surface flex items-center justify-center">
        <div className="w-6 h-6 border-2 border-orange border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!session) return null;

  const isNewUser = searchParams.get("newuser") === "1";

  return (
    <div className="min-h-screen bg-surface flex flex-col">
      {/* Header */}
      <header className="bg-light border-b border-border h-16 px-6 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2.5">
          <Logo />
          <span className="text-dark font-semibold text-lg tracking-tight">
            Mock<span className="text-orange">Mate</span>
          </span>
        </Link>

        <div className="flex items-center gap-4">
          <span className="text-sm text-muted hidden sm:block">
            {session.user.email}
          </span>
          {session.user.image && (
            <Image
              src={session.user.image}
              alt={session.user.name ?? "User"}
              width={32}
              height={32}
              className="w-8 h-8 rounded-full border border-border"
            />
          )}
          <button
            onClick={() => signOut({ fetchOptions: { onSuccess: () => router.push("/login") } })}
            className="text-sm text-muted hover:text-dark transition-colors flex items-center gap-1.5"
          >
            <LogOut size={14} />
            Sign out
          </button>
        </div>
      </header>

      <main className="flex-1 mx-auto w-full max-w-5xl px-6 py-12">
        {/* Onboarding banner for new users */}
        {isNewUser && (
          <div className="mb-8 rounded-xl border border-orange/30 bg-orange/10 px-6 py-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <p className="font-semibold text-dark">
                Welcome to MockMate! 🎉
              </p>
              <p className="text-sm text-muted mt-1">
                Get started by uploading your résumé and running your first mock interview.
              </p>
            </div>
            <button className="shrink-0 rounded-full bg-orange px-5 py-2.5 text-sm font-semibold text-light hover:opacity-90 transition-opacity">
              Start onboarding
            </button>
          </div>
        )}

        {/* Greeting */}
        <h1 className="text-2xl font-bold text-dark tracking-tight">
          Hi, {session.user.name?.split(" ")[0] ?? "there"} 👋
        </h1>
        <p className="mt-1 text-sm text-muted">
          Ready to sharpen your interview skills?
        </p>

        {/* Quick-action cards */}
        <div className="mt-8 grid gap-4 sm:grid-cols-3">
          <QuickCard
            icon={<Mic size={20} className="text-orange" />}
            title="Start a mock interview"
            description="Jump into a live, voice-based session tailored to your résumé."
            cta="Start now"
          />
          <QuickCard
            icon={<FileText size={20} className="text-orange" />}
            title="Upload your résumé"
            description="Personalise questions to your experience and target role."
            cta="Upload"
          />
          <QuickCard
            icon={<BarChart2 size={20} className="text-orange" />}
            title="View past sessions"
            description="Review scores, feedback, and improvement trends over time."
            cta="View history"
          />
        </div>
      </main>
    </div>
  );
}

function QuickCard({
  icon,
  title,
  description,
  cta,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  cta: string;
}) {
  return (
    <div className="flex flex-col gap-4 rounded-xl border border-border bg-light p-6">
      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-orange/10">
        {icon}
      </div>
      <div className="flex-1">
        <p className="font-semibold text-dark text-sm">{title}</p>
        <p className="mt-1 text-xs text-muted leading-relaxed">{description}</p>
      </div>
      <button className="self-start rounded-full border border-border px-4 py-2 text-xs font-medium text-dark hover:border-orange hover:text-orange transition-colors">
        {cta}
      </button>
    </div>
  );
}
