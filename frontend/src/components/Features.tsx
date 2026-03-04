import {
  FileText,
  UserCircle,
  Zap,
  Eye,
  MailCheck,
  BarChart3,
} from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

const FEATURES = [
  {
    icon: <FileText size={22} />,
    title: "Résumé-Aware Questions",
    description:
      "MockMate reads your actual résumé and generates hyper-personalised questions. If you claim to have led a team of 30, expect to be asked exactly how you handled underperformance.",
  },
  {
    icon: <UserCircle size={22} />,
    title: "Live Interviewer Personas",
    description:
      "Choose from multiple archetypes — startup founder, investment banker, tech lead, HR manager — each with distinct questioning styles, pressure levels, and follow-up behaviours.",
  },
  {
    icon: <Zap size={22} />,
    title: "Adaptive Follow-ups",
    description:
      "The interviewer probes deeper, challenges weak answers, and asks tough follow-ups based on what you actually say — just like a real interviewer would.",
  },
  {
    icon: <Eye size={22} />,
    title: "Posture & Presence Vision",
    description:
      "Using your webcam, MockMate scores your non-verbal communication in real time — posture, eye contact, facial confidence — and delivers a split report after the session.",
  },
  {
    icon: <MailCheck size={22} />,
    title: "Mock Hiring Decision Letter",
    description:
      "At the end of every session you receive a simulated offer or rejection letter with specific, personalised reasoning — making feedback feel consequential, not academic.",
  },
  {
    icon: <BarChart3 size={22} />,
    title: "Skill Progression Dashboard",
    description:
      "Every session feeds a longitudinal skill graph tracking your growth across communication, confidence, structure, technical depth, and domain vocabulary over time.",
  },
];

export default function Features() {
  return (
    <section id="features" className="bg-light py-24">
      <div className="mx-auto max-w-7xl px-6">
        {/* Header */}
        <div className="mb-16 text-center">
          <p className="text-xs font-semibold uppercase tracking-widest text-orange mb-3">
            Features
          </p>
          <h2 className="text-4xl font-bold tracking-tight text-dark sm:text-5xl">
            Everything real interviews throw at you
          </h2>
          <p className="mx-auto mt-4 max-w-xl text-base leading-relaxed text-muted">
            Most platforms evaluate what you say. MockMate evaluates who you
            are under pressure.
          </p>
        </div>

        {/* Grid */}
        <div className="grid gap-4 lg:gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f) => (
            <Card
              key={f.title}
              className="group rounded-2xl border border-border bg-light transition-shadow hover:shadow-lg hover:shadow-dark/5 overflow-hidden"
            >
              <CardHeader className="pt-6 gap-4">
                <div className="inline-flex h-11 w-11 items-center justify-center rounded-xl bg-orange/10 text-orange">
                  {f.icon}
                </div>
                <h3 className="text-base font-semibold text-dark">{f.title}</h3>
              </CardHeader>
              <CardContent className="px-6 pt-2 pb-6">
                <p className="text-sm leading-relaxed text-muted">{f.description}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </section>
  );
}
