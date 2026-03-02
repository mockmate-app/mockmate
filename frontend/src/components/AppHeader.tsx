import Link from "next/link";
import Logo from "@/components/Logo";
import UserMenu from "@/components/UserMenu";

type AppHeaderProps = {
  homeHref?: string;
  sticky?: boolean;
  variant?: "light" | "dark";
  showUserMenu?: boolean;
  name?: string | null;
  email?: string | null;
  image?: string | null;
};

export default function AppHeader({
  homeHref = "/dashboard",
  sticky = true,
  variant = "light",
  showUserMenu = true,
  name,
  email,
  image,
}: AppHeaderProps) {
  const isDark = variant === "dark";

  return (
    <header
      className={`${sticky ? "sticky top-0 z-30" : ""} ${isDark ? "bg-dark border-white/10" : "bg-light border-border"} border-b h-16 px-6 flex items-center justify-between shrink-0`}
    >
      <Link href={homeHref} className="flex items-center gap-2.5">
        <Logo color={isDark ? "#ffffff" : "#252525"} />
        <span className={`${isDark ? "text-white" : "text-dark"} font-semibold text-lg tracking-tight`}>
          Mock<span className="text-orange">Mate</span>
        </span>
      </Link>
      {showUserMenu ? (
        <UserMenu name={name} email={email} image={image} variant={variant} />
      ) : (
        <div aria-hidden className="w-8" />
      )}
    </header>
  );
}
