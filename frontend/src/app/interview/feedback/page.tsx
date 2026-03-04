"use client";

import Image from "next/image";
import { Suspense, useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { MessageSquareText, User } from "lucide-react";
import AppHeader from "@/components/AppHeader";
import { useSession } from "@/lib/auth-client";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

/* ── Data fetchers ─────────────────────────────────────────────────────── */

async function fetchSessionMeta(sessionId: string): Promise<SessionMeta> {
  const res = await fetch(`${API_BASE}/session/${sessionId}`);
  if (!res.ok) throw new Error("Session not found");
  return res.json();
}

async function fetchOrGenerateFeedback(sessionId: string): Promise<FeedbackReport> {
  // Try fetching previously generated feedback first
  const getRes = await fetch(`${API_BASE}/feedback/${sessionId}`);
  if (getRes.ok) return getRes.json();

  // Not found — generate it
  const res = await fetch(`${API_BASE}/feedback/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body?.detail ?? detail;
    } catch { /* ignore */ }
    throw new Error(detail);
  }
  return res.json();
}

async function fetchTranscript(sessionId: string): Promise<TranscriptData> {
  const res = await fetch(`${API_BASE}/transcript/${sessionId}`);
  if (!res.ok) throw new Error("Transcript not available");
  return res.json();
}

/* ── Types ─────────────────────────────────────────────────────────────── */

interface FeedbackReport {
  overall_score: number;
  dimension_scores: {
    communication: number;
    confidence: number;
    structure: number;
    technical_depth: number;
    domain_vocabulary: number;
    posture_presence: number;
  };
  strengths: string[];
  improvement_areas: string[];
  filler_words: { count: number; examples: string[] };
  vocabulary_calibration: string;
  tone_analysis: string;
  posture_summary: string;
  decision: "offer" | "rejection";
  decision_letter: string;
  session_id: string;
  compiled_at: string;
}

interface TranscriptTurn {
  speaker: "user" | "interviewer";
  text: string;
  ts?: string;
}

interface TranscriptData {
  session_id: string;
  turns: TranscriptTurn[];
  saved_at?: string;
}

interface SessionMeta {
  session_id: string;
  user_id?: string;
  persona: string;
  job_role: string;
  interviewer_name: string;
  interviewer_avatar_url?: string;
  status: string;
  ended_by: string | null;
  created_at: string;
  ended_at: string | null;
  question_count: number;
  overall_score: number | null;
  feedback_ready: boolean;
}

const PERSONA_LABELS: Record<string, string> = {
  neutral:              "Professional",
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

/* ── Small components ──────────────────────────────────────────────────── */

function ScoreRing({ score }: { score: number }) {
  const color =
    score >= 70 ? "text-emerald-400" : score >= 40 ? "text-amber-400" : "text-red-400";
  return (
    <span className={`text-4xl font-bold tabular-nums ${color}`}>
      {score}
      <span className="text-lg font-normal text-white/40">/100</span>
    </span>
  );
}

function DimensionBar({ label, value }: { label: string; value: number }) {
  const color =
    value >= 70 ? "bg-emerald-500" : value >= 40 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-3">
      <span className="w-36 shrink-0 text-xs text-white/60 capitalize">
        {label.replace(/_/g, " ")}
      </span>
      <div className="flex-1 h-2 rounded-full bg-white/10 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${color}`}
          style={{ width: `${value}%` }}
        />
      </div>
      <span className="w-8 text-right text-xs font-mono text-white/70">{value}</span>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card className="rounded-2xl border border-white/10 bg-white/5">
      <CardContent className="p-5">
        <h2 className="text-sm font-semibold text-white/50 uppercase tracking-widest mb-4">
          {title}
        </h2>
        {children}
      </CardContent>
    </Card>
  );
}
/* Stateful avatar component: shows the AI photo or falls back to initial. */
function InterviewerAvatarImg({
  src,
  label,
  initial,
}: {
  src?: string;
  label: string;
  initial: string;
}) {
  const [err, setErr] = useState(false);
  if (src && !err) {
    return (
      <Image
        src={src}
        alt={label}
        width={24}
        height={24}
        unoptimized
        onError={() => setErr(true)}
        className="h-6 w-6 rounded-full object-cover"
      />
    );
  }
  return (
    <div className="flex h-6 w-6 items-center justify-center rounded-full bg-white/10 text-white/70 text-[10px] font-bold">
      {initial}
    </div>
  );
}
/* ── Transcript list (shared between sidebar and sheet) ────────────────── */

function TranscriptList({
  turns,
  interviewerName,
  interviewerAvatarUrl,
}: {
  turns: TranscriptTurn[];
  interviewerName?: string;
  interviewerAvatarUrl?: string;
}) {
  if (turns.length === 0) {
    return <p className="text-xs text-white/30 italic px-1">No transcript turns recorded.</p>;
  }

  const interviewerInitial = (interviewerName ?? "I").trim()[0].toUpperCase();
  const interviewerLabel = interviewerName ?? "Interviewer";

  return (
    <div className="flex flex-col gap-3">
      {turns.map((turn, i) => {
        const isUser = turn.speaker === "user";
        return (
          <div key={i} className={`flex gap-2.5 ${isUser ? "" : ""}` }>
            <div
              className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${
                isUser ? "bg-orange/20 text-orange" : ""
              }`}
            >
              {isUser ? (
                <User className="h-3.5 w-3.5" />
              ) : (
                <InterviewerAvatarImg
                  src={interviewerAvatarUrl}
                  label={interviewerLabel}
                  initial={interviewerInitial}
                />
              )}
            </div>
            <div className="min-w-0">
              <p className="text-[11px] font-medium text-white/40 mb-0.5">
                {isUser ? "You" : interviewerLabel}
              </p>
              <p className="text-sm leading-relaxed text-white/80">{turn.text}</p>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ── Main content ──────────────────────────────────────────────────────── */

function FeedbackContent() {
  const params = useSearchParams();
  const router = useRouter();
  const { data: session, isPending: sessionPending } = useSession();
  const sessionId = params.get("session_id") ?? "";
  const [sheetOpen, setSheetOpen] = useState(false);

  // ── Auth guard ────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!sessionPending && !session) {
      router.replace(`/login?next=/interview/feedback?session_id=${sessionId}`);
    }
  }, [session, sessionPending, router, sessionId]);

  // ── Ownership guard — runs once sessionMeta loads ─────────────────────────
  const { data: sessionMeta } = useQuery({
    queryKey: ["session-meta", sessionId],
    queryFn: () => fetchSessionMeta(sessionId),
    enabled: !!sessionId,
    retry: false,
  });

  useEffect(() => {
    if (sessionMeta?.user_id && session?.user?.id && sessionMeta.user_id !== session.user.id) {
      router.replace("/dashboard");
    }
  }, [sessionMeta, session, router]);

  const { data: report, isLoading: loading, error: queryError } = useQuery({
    queryKey: ["feedback", sessionId],
    queryFn: () => fetchOrGenerateFeedback(sessionId),
    enabled: !!sessionId,
    staleTime: Infinity,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    retry: 3,
    retryDelay: (attempt) => Math.min(2000 * 2 ** attempt, 10000),
  });

  const { data: transcript, isLoading: transcriptLoading } = useQuery({
    queryKey: ["transcript", sessionId],
    queryFn: () => fetchTranscript(sessionId),
    enabled: !!sessionId,
    retry: 2,
    retryDelay: 2000,
  });

  // sessionMeta already declared above for the ownership guard

  const turns = transcript?.turns ?? [];
  // Build the interviewer avatar URL from the stored path (backend-relative)
  const interviewerAvatarUrl = sessionMeta?.interviewer_avatar_url
    ? `${API_BASE}${sessionMeta.interviewer_avatar_url}`
    : undefined;

  const error = !sessionId
    ? "Missing session_id. Please start a new interview."
    : queryError instanceof Error ? queryError.message : queryError ? "Failed to generate feedback." : null;

  return (
    <div className="min-h-screen bg-dark text-white pb-12 lg:pb-0">
      <AppHeader
        homeHref="/dashboard"
        variant="dark"
        name={session?.user?.name}
        email={session?.user?.email}
        image={session?.user?.image}
      />

      {/* Desktop: side-by-side | Mobile: stacked with sheet */}
      <div className="mx-auto max-w-7xl flex gap-6 px-4 sm:px-6 py-10">
        {/* ── Feedback column ──────────────────────────────────────────── */}
        <div className="flex-1 min-w-0 max-w-3xl flex flex-col gap-5">
          <div>
            <h1 className="text-xl sm:text-2xl font-semibold">Interview Feedback</h1>
            {sessionMeta ? (
              <p className="text-white/40 text-xs md:text-sm mt-1">
                <span className="text-primary">Job role </span>{sessionMeta.job_role}
                {" · "}
                <span className="text-primary">Persona </span>{PERSONA_LABELS[sessionMeta.persona] ?? sessionMeta.persona}
                {" · "}
                <span className="text-primary">Interviewer </span>{sessionMeta.interviewer_name}
              </p>
            ) : (
              <p className="text-white/40 text-xs mt-1">Loading interview info…</p>
            )}
          </div>

          {loading && (
            <>
              <Skeleton className="h-28 w-full rounded-2xl bg-white/10" />
              <Skeleton className="h-40 w-full rounded-2xl bg-white/10" />
              <Skeleton className="h-32 w-full rounded-2xl bg-white/10" />
              <Skeleton className="h-24 w-full rounded-2xl bg-white/10" />
            </>
          )}

          {!loading && error && (
            <Alert variant="destructive" className="rounded-xl border-red-500/25 bg-red-500/10 text-red-300">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {!loading && !error && report && (
            <>
              {/* Overall score + decision */}
              <Section title="Overall">
                <div className="flex items-center justify-between flex-wrap gap-4">
                  <ScoreRing score={report.overall_score} />
                  <Badge
                    className={`text-sm px-4 py-1 rounded-full font-semibold ${
                      report.decision === "offer"
                        ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
                        : "bg-red-500/20 text-red-400 border border-red-500/30"
                    }`}
                  >
                    {report.decision === "offer" ? "✓ Would Hire" : "✗ Rejection"}
                  </Badge>
                </div>
              </Section>

              {/* Dimension scores */}
              <Section title="Score Breakdown">
                <div className="flex flex-col gap-3">
                  {Object.entries(report.dimension_scores).map(([key, val]) => (
                    <DimensionBar key={key} label={key} value={val} />
                  ))}
                </div>
              </Section>

              {/* Tone & vocabulary */}
              <Section title="Tone & Communication">
                <div className="flex flex-col gap-4">
                  <div>
                    <p className="text-xs text-white/40 mb-1">Tone Analysis</p>
                    <p className="text-sm text-white/85 leading-relaxed">{report.tone_analysis}</p>
                  </div>
                  <div>
                    <p className="text-xs text-white/40 mb-1">Vocabulary Calibration</p>
                    <p className="text-sm text-white/85 leading-relaxed">{report.vocabulary_calibration}</p>
                  </div>
                  {report.filler_words.count > 0 && (
                    <div>
                      <p className="text-xs text-white/40 mb-1">
                        Filler Words — <span className="text-amber-400">{report.filler_words.count} detected</span>
                      </p>
                      <div className="flex flex-wrap gap-2 mt-1">
                        {report.filler_words.examples.map((w) => (
                          <span key={w} className="text-xs bg-white/10 px-2 py-0.5 rounded-full text-white/60">
                            {w}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </Section>

              {/* Strengths & improvements */}
              <div className="grid sm:grid-cols-2 gap-5">
                <Section title="Strengths">
                  <ul className="flex flex-col gap-2">
                    {report.strengths.map((s, i) => (
                      <li key={i} className="flex gap-2 text-sm text-white/80">
                        <span className="text-emerald-400 mt-0.5">✓</span> {s}
                      </li>
                    ))}
                  </ul>
                </Section>
                <Section title="Areas to Improve">
                  <ul className="flex flex-col gap-2">
                    {report.improvement_areas.map((s, i) => (
                      <li key={i} className="flex gap-2 text-sm text-white/80">
                        <span className="text-amber-400 mt-0.5">→</span> {s}
                      </li>
                    ))}
                  </ul>
                </Section>
              </div>

              {/* Posture */}
              <Section title="Posture & Presence">
                <p className="text-sm text-white/80 leading-relaxed">{report.posture_summary}</p>
              </Section>

              {/* Decision letter */}
              <Section title={report.decision === "offer" ? "Offer Letter" : "Rejection Letter"}>
                <p className="text-sm text-white/75 leading-relaxed whitespace-pre-wrap">
                  {report.decision_letter}
                </p>
              </Section>
            </>
          )}

          <Button
            onClick={() => router.push("/dashboard")}
            className="self-start rounded-full bg-orange text-white hover:opacity-90 hover:bg-orange px-5"
          >
            Back to Dashboard
          </Button>
        </div>

        {/* ── Desktop transcript sidebar (hidden on <lg) ───────────────── */}
        <aside className="hidden lg:flex w-85 xl:w-95 shrink-0 flex-col sticky top-20 max-h-[calc(100vh-6rem)]">
          <div className="flex items-center gap-2 mb-3">
            <MessageSquareText className="h-4 w-4 text-white/40" />
            <h2 className="text-sm font-semibold text-white/50 uppercase tracking-widest">
              Transcript
            </h2>
            {turns.length > 0 && (
              <span className="text-sm text-white/30 ml-auto">{turns.length} turns</span>
            )}
          </div>
          <Card className="flex-1 overflow-hidden rounded-2xl border border-white/10 bg-white/5">
            <ScrollArea className="h-full">
              <div className="p-4">
                {transcriptLoading ? (
                  <div className="flex flex-col gap-3">
                    <Skeleton className="h-10 w-full rounded-lg bg-white/10" />
                    <Skeleton className="h-14 w-full rounded-lg bg-white/10" />
                    <Skeleton className="h-10 w-full rounded-lg bg-white/10" />
                  </div>
                ) : (
                  <TranscriptList
                    turns={turns}
                    interviewerName={sessionMeta?.interviewer_name}
                    interviewerAvatarUrl={interviewerAvatarUrl}
                  />
                )}
              </div>
            </ScrollArea>
          </Card>
        </aside>
      </div>

      {/* ── Mobile transcript bottom button + sheet (visible on <lg) ───── */}
      <div className="lg:hidden fixed bottom-6 left-0 right-0 flex justify-center z-50 pointer-events-none">
        <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
          <SheetTrigger asChild>
            <Button
              className="pointer-events-auto rounded-full bg-white/10 backdrop-blur-md border border-white/15 text-white shadow-lg hover:bg-white/20 gap-2 px-5"
            >
              <MessageSquareText className="h-4 w-4" />
              Transcript
              {turns.length > 0 && (
                <Badge variant="secondary" className="ml-1 bg-white/15 text-white/70 text-[10px] px-1.5 py-0">
                  {turns.length}
                </Badge>
              )}
            </Button>
          </SheetTrigger>
          <SheetContent
            side="bottom"
            className="bg-dark border-white/10 text-white rounded-t-2xl max-h-[75vh] flex flex-col overflow-auto p-0"
          >
            <SheetHeader className="shrink-0 border-b border-white/10">
              <SheetTitle className="text-white flex items-center gap-2 pr-8">
                <MessageSquareText className="h-4 w-4 text-white/40" />
                Transcript
                {/* {turns.length > 0 && (
                  <span className="text-[10px] text-white/30 font-normal ml-auto">
                    {turns.length} turns
                  </span>
                )} */}
              </SheetTitle>
            </SheetHeader>
            <ScrollArea className="flex-1 min-h-0">
              <div className="px-4 pb-6">
                {transcriptLoading ? (
                  <div className="flex flex-col gap-3">
                    <Skeleton className="h-10 w-full rounded-lg bg-white/10" />
                    <Skeleton className="h-14 w-full rounded-lg bg-white/10" />
                    <Skeleton className="h-10 w-full rounded-lg bg-white/10" />
                  </div>
                ) : (
                  <TranscriptList
                    turns={turns}
                    interviewerName={sessionMeta?.interviewer_name}
                    interviewerAvatarUrl={interviewerAvatarUrl}
                  />
                )}
              </div>
            </ScrollArea>
          </SheetContent>
        </Sheet>
      </div>
    </div>
  );
}

export default function FeedbackPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-dark text-white flex items-center justify-center">
          Loading feedback…
        </div>
      }
    >
      <FeedbackContent />
    </Suspense>
  );
}
