import Link from "next/link";
import { ArrowRight, Mic, Eye, FileText } from "lucide-react";

export default function Hero() {
  return (
    <section className="relative bg-dark overflow-hidden">
      {/* Subtle radial glow behind headline */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 flex items-center justify-center"
      >
        <div
          className="h-[600px] w-[600px] rounded-full opacity-10"
          style={{
            background:
              "radial-gradient(circle, #FF7518 0%, transparent 70%)",
          }}
        />
      </div>

      <div className="relative mx-auto max-w-7xl px-6 pt-36 pb-28 text-center">
        {/* Eyebrow pill */}
        <div className="inline-flex items-center gap-2 rounded-full border border-orange/30 bg-orange/10 px-4 py-1.5 text-xs font-semibold uppercase tracking-widest text-orange mb-8">
          <span className="h-1.5 w-1.5 rounded-full bg-orange animate-pulse" />
          AI-Powered Mock Interviews
        </div>

        {/* Main headline */}
        <h1 className="mx-auto max-w-4xl text-5xl font-bold leading-tight tracking-tight text-light sm:text-6xl lg:text-7xl">
          Interview practice,{" "}
          <span className="text-gradient">without the nerves.</span>
        </h1>

        {/* Subtext */}
        <p className="mx-auto mt-6 max-w-2xl text-lg leading-relaxed text-light/60">
          MockMate conducts live, voice-based mock interviews personalised to
          your résumé — scoring your tone, posture, vocabulary, and confidence
          in real time. Walk into every real interview already knowing how it
          ends.
        </p>

        {/* CTAs */}
        <div className="mt-10 flex flex-col items-center justify-center gap-4 sm:flex-row">
          <Link
            href="#"
            className="group inline-flex items-center gap-2 rounded-full bg-orange px-8 py-3.5 text-sm font-semibold text-light hover:opacity-90 transition-opacity"
          >
            Start your mock interview
            <ArrowRight size={16} className="transition-transform group-hover:translate-x-1" />
          </Link>
          <Link
            href="#how-it-works"
            className="inline-flex items-center gap-2 rounded-full border border-light/20 px-8 py-3.5 text-sm font-semibold text-light hover:border-light/50 transition-colors"
          >
            See how it works
          </Link>
        </div>

        {/* Trust line */}
        <p className="mt-8 text-xs text-light/30 tracking-wide">
          No credit card required &nbsp;·&nbsp; Free mock session to start
        </p>

        {/* Feature pill strip */}
        <div className="mt-16 flex flex-wrap items-center justify-center gap-3">
          {[
            { icon: <Mic size={14} />, label: "Live voice interview" },
            { icon: <Eye size={14} />, label: "Real-time vision analysis" },
            { icon: <FileText size={14} />, label: "Résumé-personalised questions" },
          ].map((item) => (
            <div
              key={item.label}
              className="flex items-center gap-2 rounded-full border border-light/10 bg-light/5 px-4 py-2 text-xs font-medium text-light/60"
            >
              <span className="text-orange">{item.icon}</span>
              {item.label}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
