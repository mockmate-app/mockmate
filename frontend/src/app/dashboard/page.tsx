"use client";

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useSession } from "@/lib/auth-client";
import { useQuery } from "@tanstack/react-query";
import AppHeader from "@/components/AppHeader";
import {
  Mic, FileText, BarChart2, ChevronRight,
  Calendar, Award, Clock, User, Briefcase, Loader2,
} from "lucide-react";import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

// ─── Types ────────────────────────────────────────────────────────────────────

interface SessionSummary {
  session_id: string;
  persona: string;
  job_role: string;
  interviewer_name: string;
  status: string;
  ended_by: string | null;
  created_at: string;
  ended_at: string | null;
  question_count: number;
  overall_score: number | null;
  feedback_ready: boolean;
}

interface ResumeExperience {
  title: string;
  company: string;
  duration: string;
  highlights?: string[];
}

interface ResumeData {
  name: string;
  email: string;
  phone?: string;
  summary?: string;
  skills?: string[];
  experience?: ResumeExperience[];
}

// ─── Persona helpers ───────────────────────────────────────────────────────────

const PERSONA_LABELS: Record<string, string> = {
  neutral:              "Neutral",
  startup_founder:      "Startup Founder",
  investment_banker:    "Investment Banker",
  tech_lead:            "Tech Lead",
  hr_manager:           "HR Manager",
  product_manager:      "Product Manager",
  vp_engineering:       "VP of Engineering",
  management_consultant:"Consultant",
  cto:                  "CTO",
  recruiter:            "Recruiter",
};

const PERSONA_COLORS: Record<string, string> = {
  neutral:              "bg-zinc-100 text-zinc-600",
  startup_founder:      "bg-purple-100 text-purple-700",
  investment_banker:    "bg-blue-100 text-blue-700",
  tech_lead:            "bg-green-100 text-green-700",
  hr_manager:           "bg-pink-100 text-pink-700",
  product_manager:      "bg-amber-100 text-amber-700",
  vp_engineering:       "bg-indigo-100 text-indigo-700",
  management_consultant:"bg-teal-100 text-teal-700",
  cto:                  "bg-red-100 text-red-700",
  recruiter:            "bg-lime-100 text-lime-700",
};

function personaLabel(p: string) { return PERSONA_LABELS[p] ?? p; }
function personaColor(p: string) { return PERSONA_COLORS[p] ?? "bg-zinc-100 text-zinc-600"; }

// ─── Score helpers ─────────────────────────────────────────────────────────────

function scoreTextColor(score: number | null) {
  if (score === null) return "text-muted";
  if (score >= 85) return "text-green-600";
  if (score >= 70) return "text-yellow-600";
  if (score >= 50) return "text-orange";
  return "text-red-500";
}

function scorePillClass(score: number | null) {
  if (score === null) return "bg-zinc-100 text-zinc-400";
  if (score >= 85) return "bg-green-100 text-green-700";
  if (score >= 70) return "bg-yellow-100 text-yellow-700";
  if (score >= 50) return "bg-orange/15 text-orange";
  return "bg-red-100 text-red-600";
}

// ─── Date helpers ──────────────────────────────────────────────────────────────

function fmtDate(iso: string) {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(iso));
}

function daysSince(iso: string) {
  return Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
}

// ─── Page shell ───────────────────────────────────────────────────────────────

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

// ─── Main content ─────────────────────────────────────────────────────────────

function DashboardContent() {
  const { data: session, isPending } = useSession();
  const router = useRouter();
  const searchParams = useSearchParams();

  const uid = session?.user?.id;

  const { data: sessionsData, isLoading: loadingSessions } = useQuery({
    queryKey: ["sessions", uid],
    queryFn: () =>
      fetch(`${API_BASE}/sessions/user/${uid}?limit=8`)
        .then(r => r.ok ? r.json() : null),
    enabled: !!uid,
  });

  const { data: resumeData, isLoading: loadingResume } = useQuery({
    queryKey: ["resume", uid],
    queryFn: () =>
      fetch(`${API_BASE}/resume/${uid}`)
        .then(r => r.ok ? r.json() : null),
    enabled: !!uid,
  });

  const sessions: SessionSummary[] = sessionsData?.sessions ?? [];
  const resume: ResumeData | null  = resumeData?.resume_data ?? null;

  // Use useEffect to avoid calling router.replace() during render
  useEffect(() => {
    if (!isPending && !session) {
      router.replace("/login");
    }
  }, [isPending, session, router]);

  if (isPending) {
    return (
      <div className="min-h-screen bg-surface flex items-center justify-center">
        <div className="w-6 h-6 border-2 border-orange border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!session) return null;

  const isNewUser = searchParams.get("newuser") === "1";
  const firstName = session.user.name?.split(" ")[0] ?? "there";

  // Derived stats
  const scoredSessions = sessions.filter(s => s.overall_score !== null);
  const avgScore = scoredSessions.length
    ? Math.round(scoredSessions.reduce((acc, s) => acc + (s.overall_score ?? 0), 0) / scoredSessions.length)
    : null;
  const lastSession = sessions[0] ?? null;
  const thisMonth   = sessions.filter(s => {
    const d = new Date(s.created_at);
    const n = new Date();
    return d.getMonth() === n.getMonth() && d.getFullYear() === n.getFullYear();
  }).length;

  return (
    <div className="min-h-screen bg-surface flex flex-col">
      <AppHeader
        homeHref="/"
        name={session.user.name}
        email={session.user.email}
        image={session.user.image}
      />

      {/* ── Main ── */}
      <main className="flex-1 mx-auto w-full max-w-6xl px-6 py-12">

        {/* New-user banner */}
        {isNewUser && (
          <Alert className="mb-6 border-orange/30 bg-orange/10 rounded-xl">
            <AlertDescription className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div>
                <p className="font-semibold text-dark">Welcome to MockMate! 🎉</p>
                <p className="text-sm text-muted mt-1">
                  Get started by uploading your résumé and running your first mock interview.
                </p>
              </div>
              <Button asChild className="shrink-0 rounded-full bg-orange text-light hover:opacity-90 hover:bg-orange">
                <Link href="/resume/upload?from=dashboard">Start onboarding</Link>
              </Button>
            </AlertDescription>
          </Alert>
        )}

        {/* Greeting + primary CTA */}
        <div className="flex items-center justify-between gap-4">
          <div>
            <h1 className="text-xl sm:text-2xl font-bold text-dark tracking-tight">Hi, {firstName} 👋</h1>
            <p className="mt-1.5 text-sm text-muted">Here&apos;s your interview practice overview.</p>
          </div>
          <Button
            asChild
            className="shrink-0 rounded-full bg-orange text-light hover:opacity-90 hover:bg-orange gap-2 hidden sm:inline-flex"
            disabled={loadingResume}
          >
            <Link href={!loadingResume && !resume ? "/resume/upload?from=dashboard" : "/interview/setup?from=dashboard"}>
              {!loadingResume && !resume ? <FileText size={15} /> : <Mic size={15} />}
              {!loadingResume && !resume ? "Upload résumé" : "Start interview"}
            </Link>
          </Button>
        </div>

        {/* ── Stats bar ── */}
        <div className="mt-8 grid grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard
            icon={<BarChart2 size={18} className="text-orange" />}
            label="Total sessions"
            value={sessions.length === 0 ? "—" : String(sessions.length)}
          />
          <StatCard
            icon={<Award size={18} className="text-orange" />}
            label="Avg. score"
            value={avgScore !== null ? String(avgScore) : "—"}
            unit={avgScore !== null ? "/ 100" : undefined}
            valueClass={avgScore !== null ? scoreTextColor(avgScore) : undefined}
          />
          <StatCard
            icon={<Calendar size={18} className="text-orange" />}
            label="This month"
            value={thisMonth === 0 ? "—" : String(thisMonth)}
            unit={thisMonth > 0 ? "session" + (thisMonth !== 1 ? "s" : "") : undefined}
          />
          <StatCard
            icon={<Clock size={18} className="text-orange" />}
            label="Last interview"
            value={
              lastSession
                ? daysSince(lastSession.created_at) === 0
                  ? "Today"
                  : `${daysSince(lastSession.created_at)}d ago`
                : "—"
            }
          />
        </div>

        {/* ── Mobile quick actions (shown only below lg) ── */}
        <div className="mt-6 flex flex-col gap-2 lg:hidden">
          <Button
            asChild
            className="w-full rounded-xl bg-orange text-light hover:opacity-90 hover:bg-orange gap-2"
          >
            <Link href={!loadingResume && !resume ? "/resume/upload?from=dashboard" : "/interview/setup?from=dashboard"}>
              {!loadingResume && !resume ? <FileText size={15} /> : <Mic size={15} />}
              {!loadingResume && !resume ? "Upload résumé to start" : "Start interview"}
            </Link>
          </Button>
          <QuickLink href="/resume/upload?from=dashboard" icon={<FileText size={15} className="text-orange" />} label="Upload / update résumé" />
          <QuickLink href="/sessions" icon={<BarChart2 size={15} className="text-orange" />} label="View all sessions" />
        </div>

        {/* ── Main grid ── */}
        <div className="mt-10 grid gap-6 lg:grid-cols-3">

          {/* Recent sessions — 2/3 width */}
          <div className="lg:col-span-2 flex flex-col gap-4">
            <SectionHeader title="Recent sessions" href="/sessions" />

            <Card className="rounded-xl border border-border overflow-hidden">
              {loadingSessions ? (
                <div className="p-6 flex flex-col gap-3">
                  {[...Array(3)].map((_, i) => (
                    <Skeleton key={i} className="h-12 w-full rounded-lg" />
                  ))}
                </div>
              ) : sessions.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 text-center gap-3 px-6">
                  <Mic size={32} className="text-muted opacity-40" />
                  <p className="text-sm text-muted">No sessions yet.</p>
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow className="bg-surface">
                      <TableHead className="text-xs font-medium text-muted">Persona / Role</TableHead>
                      <TableHead className="text-xs font-medium text-muted hidden sm:table-cell">Date</TableHead>
                      <TableHead className="text-xs font-medium text-muted text-center">Score</TableHead>
                      <TableHead className="text-xs font-medium text-muted text-right"></TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {sessions.map(s => (
                      <TableRow key={s.session_id} className="hover:bg-surface/60">
                        <TableCell className="py-3.5 max-w-32">
                          <Badge variant="secondary" className={`text-xs font-medium ${personaColor(s.persona)}`}>
                            {personaLabel(s.persona)}
                          </Badge>
                          <p className="mt-2 mx-0.5 text-xs text-muted truncate w-full">{s.job_role}</p>
                        </TableCell>
                        <TableCell className="text-xs text-muted hidden sm:table-cell whitespace-nowrap">
                          {fmtDate(s.created_at)}
                        </TableCell>
                        <TableCell className="text-center">
                          {s.overall_score !== null ? (
                            <Badge className={`text-xs font-semibold ${scorePillClass(s.overall_score)}`}>
                              {s.overall_score}
                            </Badge>
                          ) : s.status === "ended" ? (
                            <span className="text-xs text-muted italic">No report</span>
                          ) : (
                            <span className="text-xs text-muted italic">In progress</span>
                          )}
                        </TableCell>
                        <TableCell className="text-right">
                          {s.feedback_ready ? (
                            <Link
                              href={`/interview/feedback?session_id=${s.session_id}`}
                              className="text-xs text-orange hover:underline whitespace-nowrap inline-flex items-center gap-1"
                            >
                              View <ChevronRight size={12} />
                            </Link>
                          ) : (
                            <span className="text-xs text-muted/40">—</span>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </Card>

          </div>

          {/* Right sidebar */}
          <div className="flex flex-col gap-6">

            {/* Résumé card */}
            <div className="flex flex-col gap-3">
            <SectionHeader title="Your résumé" href="/resume" />
              <Card className="rounded-xl border border-border">
                <CardContent className="p-4">
                {loadingResume ? (
                  <div className="flex flex-col gap-3 py-3">
                    <div className="flex items-center gap-3">
                      <Skeleton className="h-9 w-9 rounded-full" />
                      <div className="flex flex-col gap-1.5 flex-1">
                        <Skeleton className="h-4 w-3/4 rounded" />
                        <Skeleton className="h-3 w-1/2 rounded" />
                      </div>
                    </div>
                    <Skeleton className="h-6 w-full rounded" />
                    <Skeleton className="h-6 w-full rounded" />
                  </div>
                ) : resume ? (
                  <div className="flex flex-col gap-4">
                    {/* Identity */}
                    <div className="flex items-start gap-3">
                      <div className="h-9 w-9 shrink-0 flex items-center justify-center rounded-full bg-orange/10">
                        <User size={16} className="text-orange" />
                      </div>
                      <div className="min-w-0">
                        <p className="font-semibold text-dark text-sm truncate">{resume.name}</p>
                        {resume.experience?.[0] && (
                          <p className="text-xs text-muted mt-0.5 truncate">
                            {resume.experience[0].title} · {resume.experience[0].company}
                          </p>
                        )}
                      </div>
                    </div>

                    {/* Skills */}
                    {resume.skills && resume.skills.length > 0 && (
                      <div>
                        <p className="text-xs font-medium text-muted mb-2">Top skills</p>
                        <div className="flex flex-wrap gap-1.5">
                          {resume.skills.slice(0, 8).map(skill => (
                            <Badge
                              key={skill}
                              variant="outline"
                              className="px-2 py-0.5 text-xs text-dark border-border bg-surface rounded-md"
                            >
                              {skill}
                            </Badge>
                          ))}
                          {resume.skills.length > 8 && (
                            <Badge variant="outline" className="px-2 py-0.5 text-xs text-muted border-border bg-surface rounded-md">
                              +{resume.skills.length - 8} more
                            </Badge>
                          )}
                        </div>
                      </div>
                    )}

                    {/* Experience */}
                    {resume.experience && resume.experience.length > 0 && (
                      <div>
                        <p className="text-xs font-medium text-muted mb-2">Experience</p>
                        <div className="flex flex-col gap-3">
                          {resume.experience.slice(0, 2).map((exp, i) => (
                            <div key={i} className="flex items-start gap-2.5">
                              <Briefcase size={12} className="text-muted mt-0.5 shrink-0" />
                              <div className="min-w-0">
                                <p className="text-xs font-medium text-dark truncate">{exp.title}</p>
                                <p className="text-xs text-muted truncate">{exp.company} · {exp.duration}</p>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    <Link
                      href="/resume"
                      className="text-xs text-orange hover:underline inline-flex items-center gap-1 w-fit"
                    >
                      View résumé <ChevronRight size={12} />
                    </Link>
                  </div>
                ) : (
                  <div className="flex flex-col items-center gap-3 py-6 text-center">
                    <FileText size={28} className="text-muted opacity-40" />
                    <p className="text-sm text-muted">No résumé uploaded yet.</p>
                  </div>
                )}
                </CardContent>
              </Card>
            </div>

            {/* Quick actions — desktop only */}
            <div className="hidden lg:flex flex-col gap-3">
              <p className="text-sm font-semibold text-dark">Quick actions</p>
              <div className="flex flex-col gap-2">
                <QuickLink href="/resume/upload?from=dashboard"   icon={<FileText size={15} className="text-orange" />} label="Upload / update résumé" />
                <QuickLink href="/sessions"        icon={<BarChart2 size={15} className="text-orange" />} label="View all sessions" />
              </div>
            </div>

          </div>
        </div>
      </main>
    </div>
  );
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatCard({
  icon,
  label,
  value,
  unit,
  valueClass,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  unit?: string;
  valueClass?: string;
}) {
  return (
    <Card className="rounded-xl border border-border">
      <CardContent className="p-4">
        <div className="flex items-center gap-2 text-muted mb-2">
          {icon}
          <span className="text-xs font-medium">{label}</span>
        </div>
        <div className="flex items-baseline gap-1.5 flex-wrap">
          <span className={`text-xl sm:text-2xl font-bold tracking-tight ${valueClass ?? "text-dark"}`}>
            {value}
          </span>
          {unit && <span className="text-xs text-muted">{unit}</span>}
        </div>
      </CardContent>
    </Card>
  );
}

function SectionHeader({ title, href }: { title: string; href: string }) {
  return (
    <div className="flex items-center justify-between">
      <p className="text-sm font-semibold text-dark">{title}</p>
      <Link href={href} className="text-xs text-orange hover:underline inline-flex items-center gap-0.5">
        View all <ChevronRight size={12} />
      </Link>
    </div>
  );
}

function QuickLink({ href, icon, label, disabled }: { href: string; icon: React.ReactNode; label: string; disabled?: boolean }) {
  if (disabled) {
    return (
      <Button
        asChild
        variant="outline"
        className="w-full justify-start gap-3 rounded-lg border-border opacity-50 hover:opacity-70 h-auto px-4 py-3"
        title="Upload your résumé first"
      >
        <Link href="/resume/upload?from=dashboard">
          <span className="flex h-7 w-7 items-center justify-center rounded-md bg-orange/10 shrink-0">
            {icon}
          </span>
          <span className="text-sm text-muted">{label}</span>
          <span className="ml-auto text-xs text-muted">Upload résumé first</span>
        </Link>
      </Button>
    );
  }
  return (
    <Button
      asChild
      variant="outline"
      className="w-full justify-start gap-3 rounded-lg border-border hover:border-orange/50 h-auto px-4 py-3 group"
    >
      <Link href={href}>
        <span className="flex h-7 w-7 items-center justify-center rounded-md bg-orange/10 shrink-0">
          {icon}
        </span>
        <span className="text-sm text-dark group-hover:text-orange transition-colors">{label}</span>
        <ChevronRight size={14} className="ml-auto text-muted group-hover:text-orange transition-colors" />
      </Link>
    </Button>
  );
}
