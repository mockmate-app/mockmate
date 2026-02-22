import Link from "next/link";
import { ArrowRight } from "lucide-react";

const PERSONAS = [
  { name: "Startup Founder", tag: "Culture fit & ownership" },
  { name: "Investment Banker", tag: "Precision & numbers" },
  { name: "Tech Lead", tag: "Depth & trade-offs" },
  { name: "HR Manager", tag: "Behavioural & values" },
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
            Each persona has a distinct questioning style. The experience is
            fundamentally different depending on who you practise against.
          </p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {PERSONAS.map((p) => (
            <div
              key={p.name}
              className="cursor-pointer rounded-2xl border border-border bg-light p-6 text-center transition-all hover:border-orange hover:shadow-lg hover:shadow-orange/10"
            >
              {/* Avatar placeholder */}
              <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-dark text-2xl font-bold text-orange">
                {p.name.charAt(0)}
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
            Start your free session
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
