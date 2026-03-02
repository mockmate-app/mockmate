"use client";

import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import AppHeader from "@/components/AppHeader";
import { useSession } from "@/lib/auth-client";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

async function generateFeedback(sessionId: string): Promise<FeedbackReport> {
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

function FeedbackContent() {
  const params = useSearchParams();
  const router = useRouter();
  const { data: session } = useSession();
  const sessionId = params.get("session_id") ?? "";

  const { data: report, isLoading: loading, error: queryError } = useQuery({
    queryKey: ["feedback", sessionId],
    queryFn: () => generateFeedback(sessionId),
    enabled: !!sessionId,
    refetchOnMount: true,
    refetchOnWindowFocus: true,
  });

  const error = !sessionId
    ? "Missing session_id. Please start a new interview."
    : queryError instanceof Error ? queryError.message : queryError ? "Failed to generate feedback." : null;

  return (
    <div className="min-h-screen bg-dark text-white">
      <AppHeader
        homeHref="/dashboard"
        variant="dark"
        name={session?.user?.name}
        email={session?.user?.email}
        image={session?.user?.image}
      />

      <div className="mx-auto max-w-3xl flex flex-col gap-5 px-4 sm:px-6 py-10">
        <div>
          <h1 className="text-xl sm:text-2xl font-semibold">Interview Feedback</h1>
          <p className="text-white/40 text-xs mt-1">Session: {sessionId || "N/A"}</p>
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
