import Link from "next/link";
import Logo from "@/components/Logo";
import UserMenu from "@/components/UserMenu";
import { Gem } from "lucide-react";

type AppHeaderProps = {
  homeHref?: string;
  sticky?: boolean;
  variant?: "light" | "dark";
  showUserMenu?: boolean;
  showProButton?: boolean;
  name?: string | null;
  email?: string | null;
  image?: string | null;
};

export default function AppHeader({
  homeHref = "/dashboard",
  variant = "light",
  showUserMenu = true,
  showProButton = true,
  name,
  email,
  image,
}: AppHeaderProps) {
  const isDark = variant === "dark";

  return (
    <header
      className={`sticky top-0 z-30 ${isDark ? "bg-dark border-white/10" : "bg-light border-border"} border-b h-16 px-4 sm:px-6 flex items-center justify-between shrink-0`}
    >
      <Link href={homeHref} className="flex items-center gap-2.5">
        <Logo color={isDark ? "#ffffff" : "#252525"} />
        <span className={`${isDark ? "text-white" : "text-dark"} font-semibold text-lg tracking-tight`}>
          Mock<span className="text-orange">Mate</span>
        </span>
      </Link>
      <div className="flex items-center gap-2 sm:gap-3">
        {showProButton && (
          <Link
            href="/pro"
            className="rounded-full border border-orange/30 bg-orange/10 h-9 px-3 flex items-center gap-1 justify-center text-xs font-semibold text-orange hover:bg-orange/15 transition-colors"
          >
            <Gem className="w-3 h-3" />
            Get PRO
          </Link>
        )}
        {showUserMenu ? (
          <UserMenu name={name} email={email} image={image} variant={variant} />
        ) : (
          <div aria-hidden className="w-8" />
        )}
      </div>
    </header>
  );
}
