import Link from "next/link";
import { ArrowRight } from "lucide-react";

const PERSONAS = [
  { name: "Startup Founder",        tag: "Culture fit & ownership",       emoji: "🚀" },
  { name: "Investment Banker",      tag: "Precision & numbers",           emoji: "📊" },
  { name: "Tech Lead",              tag: "Depth & trade-offs",            emoji: "⚙️" },
  { name: "HR Manager",             tag: "Behavioural & values",          emoji: "🤝" },
  { name: "Product Manager",        tag: "User empathy & data",           emoji: "🗺️" },
  { name: "VP of Engineering",      tag: "Leadership & scale",            emoji: "🏗️" },
  { name: "Management Consultant",  tag: "Structure & frameworks",        emoji: "🧩" },
  { name: "CTO",                    tag: "Tech strategy & vision",        emoji: "🔭" },
  { name: "Recruiter",              tag: "Career narrative & fit",        emoji: "🎯" },
];

export default function Personas() {
  return (
    <section id="personas" className="bg-light py-24">
      <div className="mx-auto max-w-7xl px-6">
        <div className="mb-16 text-center">
          <p className="text-xs font-semibold uppercase tracking-widest text-orange mb-3">
            Interviewer personas
          </p>
          <h2 className="text-4xl font-bold tracking-tight text-dark sm:text-5xl">
            Choose your challenge
          </h2>
          <p className="mx-auto mt-4 max-w-xl text-base leading-relaxed text-muted">
            Nine distinct interviewers. Each one pushes differently — from an
            aggressive investment banker to a visionary CTO. The experience
            changes entirely depending on who you practise against.
          </p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-3 xl:grid-cols-3 max-w-4xl mx-auto">
          {PERSONAS.map((p) => (
            <div
              key={p.name}
              className="cursor-pointer rounded-2xl border border-border bg-light p-6 text-center transition-all hover:border-orange hover:shadow-lg hover:shadow-orange/10"
            >
              <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-dark text-2xl">
                {p.emoji}
              </div>
              <h3 className="text-sm font-semibold text-dark">{p.name}</h3>
              <p className="mt-1 text-xs text-muted">{p.tag}</p>
            </div>
          ))}
        </div>

        {/* CTA band */}
        <div className="mt-20 rounded-3xl bg-dark px-8 py-14 text-center">
          <h2 className="text-3xl font-bold tracking-tight text-light sm:text-4xl">
            Ready to find out if you&apos;d get the job?
          </h2>
          <p className="mx-auto mt-4 max-w-lg text-base leading-relaxed text-light/60">
            Upload your résumé, pick a persona, and sit your first mock
            interview — free, no credit card required.
          </p>
          <Link
            href="/login"
            className="group mt-8 inline-flex items-center gap-2 rounded-full bg-orange px-8 py-3.5 text-sm font-semibold text-light hover:opacity-90 transition-opacity"
          >
            Start your mock interview
            <ArrowRight
              size={16}
              className="transition-transform group-hover:translate-x-1"
            />
          </Link>
        </div>
      </div>
    </section>
  );
}
