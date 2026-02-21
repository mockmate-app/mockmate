import Link from "next/link";
import Logo from "@/components/Logo";

const LINKS = {
  Product: ["Features", "Personas", "How it works", "Pricing"],
  Company: ["About", "Blog", "Careers", "Press"],
  Legal: ["Privacy policy", "Terms of service", "Cookie policy"],
};

export default function Footer() {
  return (
    <footer className="bg-dark text-light/60">
      <div className="mx-auto max-w-7xl px-6 py-16">
        {/* Top row */}
        <div className="flex flex-col gap-10 lg:flex-row lg:justify-between">
          {/* Brand */}
          <div className="max-w-xs">
            <Link href="/" className="flex items-center gap-2.5 mb-4">
              <Logo color="#ffffff" size={28} />
              <span className="text-light font-semibold text-lg tracking-tight">
                Mock<span className="text-orange">Mate</span>
              </span>
            </Link>
            <p className="text-sm leading-relaxed">
              Interview practice, without the nerves. Real-time AI mock
              interviews powered by voice, vision, and your résumé.
            </p>
          </div>

          {/* Link columns */}
          <div className="grid grid-cols-2 gap-10 sm:grid-cols-3">
            {Object.entries(LINKS).map(([heading, items]) => (
              <div key={heading}>
                <p className="mb-4 text-xs font-semibold uppercase tracking-widest text-light">
                  {heading}
                </p>
                <ul className="space-y-2.5">
                  {items.map((item) => (
                    <li key={item}>
                      <Link
                        href="#"
                        className="text-sm hover:text-orange transition-colors"
                      >
                        {item}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>

        {/* Bottom row */}
        <div className="mt-12 border-t border-light/10 pt-8 flex flex-col items-center justify-between gap-4 sm:flex-row">
          <p className="text-xs">
            © {new Date().getFullYear()} MockMate. All rights reserved.
          </p>
          <p className="text-xs">
            Built with{" "}
            <span className="text-orange">Google Gemini Live API</span> &amp;{" "}
            <span className="text-orange">Google ADK</span>
          </p>
        </div>
      </div>
    </footer>
  );
}
