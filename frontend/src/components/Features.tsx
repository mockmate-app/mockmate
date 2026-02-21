import {
  FileText,
  UserCircle,
  Zap,
  Eye,
  MailCheck,
  BarChart3,
} from "lucide-react";

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
    title: "Stress Injection Engine",
    description:
      "Mid-interview, MockMate deliberately interrupts, challenges your answers, or introduces surprise questions. Real interviews are unpredictable; your practice should be too.",
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
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f) => (
            <div
              key={f.title}
              className="group rounded-2xl border border-border bg-light p-8 transition-shadow hover:shadow-lg hover:shadow-dark/5"
            >
              <div className="mb-5 inline-flex h-11 w-11 items-center justify-center rounded-xl bg-orange/10 text-orange">
                {f.icon}
              </div>
              <h3 className="mb-3 text-base font-semibold text-dark">
                {f.title}
              </h3>
              <p className="text-sm leading-relaxed text-muted">
                {f.description}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
