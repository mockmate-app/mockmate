const STEPS = [
  {
    step: "01",
    title: "Upload your résumé",
    description:
      "Drop in your PDF or DOCX. MockMate parses every claim, transition, and quantified achievement so questions are personal — not generic.",
  },
  {
    step: "02",
    title: "Choose your interviewer",
    description:
      "Pick a persona and difficulty level. An aggressive investment banker hits different from a supportive startup founder — your choice, your challenge.",
  },
  {
    step: "03",
    title: "Sit the interview live",
    description:
      "Speak naturally. MockMate listens, responds, follows up, and injects curveballs in real time. Your webcam tracks posture and presence throughout.",
  },
  {
    step: "04",
    title: "Receive your decision",
    description:
      "Get a full multimodal feedback report — tone, posture, vocabulary, confidence — and a mock offer or rejection letter with specific reasoning.",
  },
];

export default function HowItWorks() {
  return (
    <section id="how-it-works" className="bg-surface py-24">
      <div className="mx-auto max-w-7xl px-6">
        {/* Header */}
        <div className="mb-16 text-center">
          <p className="text-xs font-semibold uppercase tracking-widest text-orange mb-3">
            How it works
          </p>
          <h2 className="text-4xl font-bold tracking-tight text-dark sm:text-5xl">
            From résumé to decision in one session
          </h2>
        </div>

        {/* Steps */}
        <div className="grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((s) => (
            <div key={s.step} className="relative">
              {/* Step number */}
              <div className="mb-5 inline-flex h-14 w-14 items-center justify-center rounded-2xl bg-dark text-light">
                <span className="font-mono text-sm font-semibold text-orange">
                  {s.step}
                </span>
              </div>

              <h3 className="mb-3 text-base font-semibold text-dark">
                {s.title}
              </h3>
              <p className="text-sm leading-relaxed text-muted">
                {s.description}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
