"use client";

import { Suspense, useState, useRef, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useSession } from "@/lib/auth-client";
import { useInfiniteQuery } from "@tanstack/react-query";
import AppHeader from "@/components/AppHeader";
import {
  Mic, ChevronRight, Award, ArrowLeft,
  Search, BarChart2, Loader2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";
const PAGE_SIZE = 10;

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

interface SessionsPage {
  sessions: SessionSummary[];
  count: number;
  has_more: boolean;
  total: number;
  avg_score: number | null;
  this_month: number;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const PERSONA_LABELS: Record<string, string> = {
  neutral: "Neutral", startup_founder: "Startup Founder",
  investment_banker: "Investment Banker", tech_lead: "Tech Lead", hr_manager: "HR Manager",
  product_manager: "Product Manager", vp_engineering: "VP of Engineering",
  management_consultant: "Consultant", cto: "CTO", recruiter: "Recruiter",
};
const PERSONA_COLORS: Record<string, string> = {
  neutral: "bg-zinc-100 text-zinc-600", startup_founder: "bg-purple-100 text-purple-700",
  investment_banker: "bg-blue-100 text-blue-700", tech_lead: "bg-green-100 text-green-700",
  hr_manager: "bg-pink-100 text-pink-700", product_manager: "bg-amber-100 text-amber-700",
  vp_engineering: "bg-indigo-100 text-indigo-700", management_consultant: "bg-teal-100 text-teal-700",
  cto: "bg-red-100 text-red-700", recruiter: "bg-lime-100 text-lime-700",
};
function personaLabel(p: string) { return PERSONA_LABELS[p] ?? p; }
function personaColor(p: string) { return PERSONA_COLORS[p] ?? "bg-zinc-100 text-zinc-600"; }

function scorePillClass(score: number | null) {
  if (score === null) return "bg-zinc-100 text-zinc-400";
  if (score >= 85) return "bg-green-100 text-green-700";
  if (score >= 70) return "bg-yellow-100 text-yellow-700";
  if (score >= 50) return "bg-orange/15 text-orange";
  return "bg-red-100 text-red-600";
}

function fmtDate(iso: string) {
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" })
    .format(new Date(iso));
}

function fmtDuration(start: string, end: string | null) {
  if (!end) return "—";
  const mins = Math.round((new Date(end).getTime() - new Date(start).getTime()) / 60000);
  if (mins < 1) return "< 1 min";
  return `${mins} min${mins !== 1 ? "s" : ""}`;
}

// ─── Page shell ───────────────────────────────────────────────────────────────

export default function SessionsPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-surface flex items-center justify-center">
        <div className="w-6 h-6 border-2 border-orange border-t-transparent rounded-full animate-spin" />
      </div>
    }>
      <SessionsContent />
    </Suspense>
  );
}

function SessionsContent() {
  const { data: session, isPending } = useSession();
  const router = useRouter();
  const [query, setQuery] = useState("");

  const uid = session?.user?.id;

  const {
    data,
    isLoading: loading,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery<SessionsPage>({
    queryKey: ["sessions-all", uid],
    queryFn: ({ pageParam }) =>
      fetch(`${API_BASE}/sessions/user/${uid}?limit=${PAGE_SIZE}&offset=${pageParam}`)
        .then(r => {
          if (!r.ok) throw new Error("Failed to load sessions");
          return r.json();
        }),
    initialPageParam: 0,
    getNextPageParam: (lastPage, _allPages, lastPageParam) =>
      lastPage.has_more ? (lastPageParam as number) + PAGE_SIZE : undefined,
    enabled: !!uid,
    staleTime: 5 * 60 * 1000,
  });

  // Flatten all pages into a single array
  const sessions: SessionSummary[] = data?.pages.flatMap(p => p.sessions) ?? [];
  const firstPage = data?.pages[0];

  // ── IntersectionObserver sentinel ──
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  const handleObserver = useCallback(
    (entries: IntersectionObserverEntry[]) => {
      const [entry] = entries;
      if (entry.isIntersecting && hasNextPage && !isFetchingNextPage) {
        fetchNextPage();
      }
    },
    [fetchNextPage, hasNextPage, isFetchingNextPage],
  );

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(handleObserver, {
      root: null,
      rootMargin: "200px",
      threshold: 0,
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [handleObserver]);

  if (isPending || (!session && !loading)) {
    return (
      <div className="min-h-screen bg-surface flex items-center justify-center">
        <div className="w-6 h-6 border-2 border-orange border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }
  if (!session) { router.replace("/login"); return null; }

  const filtered = sessions.filter(s => {
    if (!query) return true;
    const q = query.toLowerCase();
    return (
      s.job_role?.toLowerCase().includes(q) ||
      s.persona?.toLowerCase().includes(q) ||
      s.interviewer_name?.toLowerCase().includes(q)
    );
  });

  const totalSessionCount = firstPage?.total ?? sessions.length;
  const avgScore: number | null = firstPage?.avg_score ?? null;

  return (
    <div className="min-h-screen bg-surface flex flex-col">
      <AppHeader
        homeHref="/dashboard"
        name={session.user.name}
        email={session.user.email}
        image={session.user.image}
      />

      <main className="flex-1 mx-auto w-full max-w-6xl px-4 sm:px-6 py-10 flex flex-col gap-8">
        {/* Breadcrumb */}
        <Link href="/dashboard" className="flex items-center gap-1.5 text-sm text-muted hover:text-dark transition-colors w-fit">
          <ArrowLeft size={14} /> Back to dashboard
        </Link>

        {/* Title + stats */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="text-xl sm:text-2xl font-bold text-dark tracking-tight">All sessions</h1>
            <p className="mt-1 text-sm text-muted">{totalSessionCount} total interviews recorded</p>
          </div>
          <div className="flex gap-3">
            {totalSessionCount > 0 && (
              <Card className="rounded-xl border border-border">
                <CardContent className="py-3 px-4 flex items-center gap-2.5">
                  <Award size={16} className="text-orange" />
                  <div>
                    <p className="text-xs text-muted">Avg score</p>
                    <p className="text-lg font-bold text-dark leading-tight">
                      {avgScore !== null ? avgScore : "—"}
                    </p>
                  </div>
                </CardContent>
              </Card>
            )}
            {/* <Button asChild className="rounded-xl bg-orange text-light hover:opacity-90 hover:bg-orange gap-2">
              <Link href="/interview/setup?from=sessions">
                <Mic size={15} /> New interview
              </Link>
            </Button> */}
          </div>
        </div>

        {/* Search */}
        {sessions.length > 0 && (
          <div className="relative max-w-sm">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted pointer-events-none" />
            <Input
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Search by role, persona, interviewer…"
              className="pl-9 rounded-xl border-border bg-light focus:ring-orange/40 focus:border-orange"
            />
          </div>
        )}

        {/* Table */}
        <Card className="rounded-xl border border-border overflow-hidden">
          {loading ? (
            <div className="p-6 flex flex-col gap-3">
              {[...Array(4)].map((_, i) => (
                <Skeleton key={i} className="h-12 w-full rounded-lg" />
              ))}
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-center gap-4 px-6">
              {sessions.length === 0 ? (
                <>
                  <BarChart2 size={36} className="text-muted opacity-30" />
                  <p className="text-sm text-muted">No interviews yet. Start your first one!</p>
                </>
              ) : (
                <p className="text-sm text-muted">No sessions match your search.</p>
              )}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="bg-surface">
                    <TableHead className="text-xs font-medium text-muted">Persona / Role</TableHead>
                    <TableHead className="text-xs font-medium text-muted hidden md:table-cell">Interviewer</TableHead>
                    <TableHead className="text-xs font-medium text-muted hidden sm:table-cell">Date</TableHead>
                    <TableHead className="text-xs font-medium text-muted hidden lg:table-cell">Duration</TableHead>
                    <TableHead className="text-xs font-medium text-muted text-center hidden sm:table-cell">Questions</TableHead>
                    <TableHead className="text-xs font-medium text-muted text-center">Score</TableHead>
                    <TableHead className="text-xs font-medium text-muted">Status</TableHead>
                    <TableHead className="text-xs font-medium text-muted text-right"></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map(s => (
                    <TableRow key={s.session_id} className="hover:bg-surface/60">
                      <TableCell className="py-3.5 max-w-32">
                        <Badge variant="secondary" className={`text-xs font-medium ${personaColor(s.persona)}`}>
                          {personaLabel(s.persona)}
                        </Badge>
                        <p className="mt-2 mx-0.5 text-xs text-muted truncate w-full">{s.job_role}</p>
                      </TableCell>
                      <TableCell className="text-xs text-muted hidden md:table-cell">
                        {s.interviewer_name ?? "—"}
                      </TableCell>
                      <TableCell className="text-xs text-muted hidden sm:table-cell whitespace-nowrap">
                        {fmtDate(s.created_at)}
                      </TableCell>
                      <TableCell className="text-xs text-muted hidden lg:table-cell whitespace-nowrap">
                        {fmtDuration(s.created_at, s.ended_at)}
                      </TableCell>
                      <TableCell className="text-xs text-center text-muted hidden sm:table-cell">
                        {s.question_count > 0 ? s.question_count : "—"}
                      </TableCell>
                      <TableCell className="text-center">
                        {s.overall_score !== null ? (
                          <Badge className={`text-xs font-semibold ${scorePillClass(s.overall_score)}`}>
                            {s.overall_score}
                          </Badge>
                        ) : (
                          <span className="text-xs text-muted/40">—</span>
                        )}
                      </TableCell>
                      <TableCell>
                        {!s.feedback_ready && s.status !== "active" ? (
                          <Badge variant="secondary" className="text-xs font-medium rounded-full bg-red-100 text-red-600">
                            Abandoned
                          </Badge>
                        ) : (
                          <Badge variant="secondary" className={`text-xs font-medium rounded-full ${s.status === "ended" ? "bg-zinc-100 text-zinc-500"
                              : s.status === "active" ? "bg-green-100 text-green-600"
                                : "bg-yellow-100 text-yellow-600"
                            }`}>
                            {s.status === "ended" ? "Completed" : s.status}
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        {s.feedback_ready ? (
                          <Link
                            href={`/interview/feedback?session_id=${s.session_id}`}
                            className="text-xs text-orange hover:underline whitespace-nowrap inline-flex items-center gap-1"
                          >
                            Feedback <ChevronRight size={12} />
                          </Link>
                        ) : (
                          <span className="text-xs text-muted/40">—</span>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </Card>

        {/* Infinite-scroll sentinel */}
        <div ref={sentinelRef} className="h-1" />
        {isFetchingNextPage && (
          <div className="flex justify-center py-4">
            <Loader2 size={20} className="animate-spin text-orange" />
          </div>
        )}
      </main>
    </div>
  );
}
