"use client";

import { Suspense } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useSession } from "@/lib/auth-client";
import { useQuery } from "@tanstack/react-query";
import Logo from "@/components/Logo";
import UserMenu from "@/components/UserMenu";
import {
  ArrowLeft, User, Briefcase, GraduationCap, Star, Cpu,
  Upload, FileText, Mic, ExternalLink,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

// ─── Types ────────────────────────────────────────────────────────────────────

interface ResumeData {
  name: string;
  email: string;
  phone?: string;
  summary?: string;
  skills?: string[];
  experience?: { title: string; company: string; duration: string; highlights?: string[] }[];
  education?: { degree: string; institution: string; year: string }[];
  certifications?: string[];
  bold_claims?: string[];
  filename?: string;
  parsed_at?: string;
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function ResumesPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-surface flex items-center justify-center">
        <div className="w-6 h-6 border-2 border-orange border-t-transparent rounded-full animate-spin" />
      </div>
    }>
      <ResumesContent />
    </Suspense>
  );
}

function ResumesContent() {
  const { data: session, isPending } = useSession();
  const router = useRouter();

  const uid = session?.user?.id;

  const { data: resumeData, isLoading: loading } = useQuery({
    // Share the same cache key as the dashboard so navigating between pages
    // reuses the already-fetched data without a second network request.
    queryKey: ["resume", uid],
    queryFn: () =>
      fetch(`${API_BASE}/resume/${uid}`)
        .then(r => r.ok ? r.json() : null),
    enabled: !!uid,
    staleTime: 10 * 60 * 1000,
  });

  const resume: ResumeData | null = resumeData?.resume_data ?? null;
  const pdfUrl = uid && resume ? `${API_BASE}/resume/${uid}/file` : null;

  if (isPending || (!session && !loading)) {
    return (
      <div className="min-h-screen bg-surface flex items-center justify-center">
        <div className="w-6 h-6 border-2 border-orange border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }
  if (!session) { router.replace("/login"); return null; }

  return (
    <div className="min-h-screen bg-surface flex flex-col">
      {/* Header */}
      <header className="bg-light border-b border-border h-16 px-6 flex items-center justify-between shrink-0">
        <Link href="/dashboard" className="flex items-center gap-2.5">
          <Logo />
          <span className="text-dark font-semibold text-lg tracking-tight">
            Mock<span className="text-orange">Mate</span>
          </span>
        </Link>
        <UserMenu name={session.user.name} email={session.user.email} image={session.user.image} />
      </header>

      <main className="flex-1 mx-auto w-full max-w-7xl px-6 py-10 flex flex-col gap-8">
        {/* Breadcrumb + actions */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <Link href="/dashboard" className="flex items-center gap-1.5 text-sm text-muted hover:text-dark transition-colors w-fit">
            <ArrowLeft size={14} /> Back to dashboard
          </Link>
          {resume && (
            <div className="flex items-center gap-3">
              <Button asChild className="rounded-full bg-orange text-light hover:opacity-90 hover:bg-orange gap-2">
                <Link href="/interview/setup?from=resumes">
                  <Mic size={14} /> Start interview
                </Link>
              </Button>
              <Button asChild variant="outline" className="rounded-full border-border text-dark hover:border-orange/50 gap-2">
                <Link href="/resume">
                  <Upload size={14} /> Upload new version
                </Link>
              </Button>
            </div>
          )}
        </div>

        {/* Title */}
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-dark tracking-tight">My résumé</h1>
          {resume?.filename && (
            <p className="mt-1 text-sm text-muted">
              {resume.filename}
              {resume.parsed_at && (
                <> · Uploaded {new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" }).format(new Date(resume.parsed_at))}</>
              )}
            </p>
          )}
        </div>

        {loading ? (
          <div className="flex flex-col gap-4 py-6">
            <Skeleton className="h-24 w-full rounded-xl" />
            <Skeleton className="h-32 w-full rounded-xl" />
            <Skeleton className="h-20 w-full rounded-xl" />
          </div>
        ) : !resume ? (
          /* No resume uploaded yet */
          <div className="flex flex-col items-center justify-center py-24 text-center gap-5">
            <FileText size={48} className="text-muted opacity-30" />
            <div>
              <p className="font-semibold text-dark">No résumé uploaded yet</p>
              <p className="text-sm text-muted mt-1">Upload your résumé to get personalised interview questions.</p>
            </div>
            <Button asChild className="rounded-full bg-orange text-light hover:opacity-90 hover:bg-orange">
              <Link href="/resume">Upload résumé</Link>
            </Button>
          </div>
        ) : (
          /* Two-column layout: parsed data + PDF viewer */
          <div className="grid gap-6 lg:grid-cols-5">

            {/* ── Left: parsed data ── */}
            <div className="lg:col-span-2 flex flex-col gap-5">

              {/* Identity */}
              <Section>
                <div className="flex items-start gap-3.5">
                  <div className="h-10 w-10 shrink-0 flex items-center justify-center rounded-full bg-orange/10">
                    <User size={18} className="text-orange" />
                  </div>
                  <div className="min-w-0">
                    <p className="font-bold text-dark text-base">{resume.name}</p>
                    {resume.email && <p className="text-xs text-muted mt-0.5">{resume.email}</p>}
                    {resume.phone && <p className="text-xs text-muted">{resume.phone}</p>}
                  </div>
                </div>
                {resume.summary && (
                  <p className="text-sm text-muted leading-relaxed mt-3">{resume.summary}</p>
                )}
              </Section>

              {/* Skills */}
              {resume.skills && resume.skills.length > 0 && (
                <Section title="Skills" icon={<Cpu size={14} className="text-orange" />}>
                  <div className="flex flex-wrap gap-1.5 mt-3">
                    {resume.skills.map(skill => (
                      <Badge key={skill} variant="outline" className="rounded-md border-border text-dark text-xs px-2.5 py-1">
                        {skill}
                      </Badge>
                    ))}
                  </div>
                </Section>
              )}

              {/* Bold claims */}
              {resume.bold_claims && resume.bold_claims.length > 0 && (
                <Section title="Key achievements" icon={<Star size={14} className="text-orange" />}>
                  <ul className="mt-3 flex flex-col gap-1.5">
                    {resume.bold_claims.map((claim, i) => (
                      <li key={i} className="text-xs text-dark flex items-start gap-2">
                        <span className="text-orange mt-0.5 shrink-0">•</span>
                        {claim}
                      </li>
                    ))}
                  </ul>
                </Section>
              )}

              {/* Experience */}
              {resume.experience && resume.experience.length > 0 && (
                <Section title="Experience" icon={<Briefcase size={14} className="text-orange" />}>
                  <div className="mt-3 flex flex-col gap-4">
                    {resume.experience.map((exp, i) => (
                      <div key={i}>
                        <p className="text-sm font-semibold text-dark">{exp.title}</p>
                        <p className="text-xs text-muted mt-0.5">{exp.company} · {exp.duration}</p>
                        {exp.highlights && exp.highlights.length > 0 && (
                          <ul className="mt-1.5 flex flex-col gap-1">
                            {exp.highlights.map((h, j) => (
                              <li key={j} className="text-xs text-muted flex items-start gap-1.5">
                                <span className="text-orange mt-0.5 shrink-0">–</span>
                                {h}
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    ))}
                  </div>
                </Section>
              )}

              {/* Education */}
              {resume.education && resume.education.length > 0 && (
                <Section title="Education" icon={<GraduationCap size={14} className="text-orange" />}>
                  <div className="mt-3 flex flex-col gap-3">
                    {resume.education.map((edu, i) => (
                      <div key={i}>
                        <p className="text-sm font-semibold text-dark">{edu.degree}</p>
                        <p className="text-xs text-muted mt-0.5">{edu.institution} · {edu.year}</p>
                      </div>
                    ))}
                  </div>
                </Section>
              )}

              {/* Certifications */}
              {resume.certifications && resume.certifications.length > 0 && (
                <Section title="Certifications" icon={<Star size={14} className="text-orange" />}>
                  <ul className="mt-3 flex flex-col gap-1.5">
                    {resume.certifications.map((cert, i) => (
                      <li key={i} className="text-xs text-dark flex items-start gap-2">
                        <span className="text-orange mt-0.5 shrink-0">•</span>
                        {cert}
                      </li>
                    ))}
                  </ul>
                </Section>
              )}
            </div>

            {/* ── Right: PDF viewer ── */}
            <div className="lg:col-span-3">
              <Card className="rounded-xl border border-border overflow-hidden flex flex-col">
                <div className="flex items-center justify-between px-4 py-3 border-b border-border">
                  <p className="text-sm font-medium text-dark">Document preview</p>
                  {pdfUrl && (
                    <a
                      href={pdfUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-1.5 text-xs text-orange hover:underline"
                    >
                      Open in new tab <ExternalLink size={11} />
                    </a>
                  )}
                </div>
                {pdfUrl ? (
                  <iframe
                    src={pdfUrl}
                    className="w-full"
                    style={{ height: "calc(100vh - 220px)", minHeight: 500 }}
                    title="Résumé preview"
                  />
                ) : (
                  <div className="flex items-center justify-center py-24 text-muted text-sm">
                    Preview unavailable
                  </div>
                )}
              </Card>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

// ─── Section card ─────────────────────────────────────────────────────────────

function Section({
  title,
  icon,
  children,
}: {
  title?: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Card className="rounded-xl border border-border">
      <CardContent className="p-4">
        {title && (
          <div className="flex items-center gap-1.5 mb-1">
            {icon}
            <p className="text-xs font-semibold text-dark uppercase tracking-wide">{title}</p>
          </div>
        )}
        {children}
      </CardContent>
    </Card>
  );
}
