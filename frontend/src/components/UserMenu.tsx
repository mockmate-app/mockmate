"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { CreditCard, LogOut } from "lucide-react";
import { openPolarPortal, signOut } from "@/lib/auth-client";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";

interface UserMenuProps {
  name?: string | null;
  email?: string | null;
  image?: string | null;
  variant?: "light" | "dark";
}

export default function UserMenu({ name, email, image, variant = "light" }: UserMenuProps) {
  const isDark = variant === "dark";
  const router = useRouter();
  const [openingPortal, setOpeningPortal] = useState(false);

  const initials = name
    ? name.split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase()
    : (email?.[0]?.toUpperCase() ?? "U");

  const handleSignOut = () => {
    signOut({ fetchOptions: { onSuccess: () => router.push("/login") } });
  };

  const handleManageSubscription = async () => {
    try {
      setOpeningPortal(true);
      await openPolarPortal();
    } catch {
      router.push("/pro");
    } finally {
      setOpeningPortal(false);
    }
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          className={`flex items-center gap-2 rounded-full border pl-1 pr-3 py-1 hover:border-orange/50 transition-colors outline-none ${
            isDark ? "border-white/10 bg-white/10" : "border-border bg-light"
          }`}
          aria-label="User menu"
        >
          <Avatar className="w-7 h-7">
            <AvatarImage src={image ?? undefined} alt={name ?? "User"} />
            <AvatarFallback className="bg-orange/10 text-orange text-xs font-semibold">
              {initials}
            </AvatarFallback>
          </Avatar>
          <svg
            width="10"
            height="6"
            viewBox="0 0 10 6"
            fill="none"
            className={isDark ? "text-white/60" : "text-muted"}
            aria-hidden="true"
          >
            <path d="M1 1l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end" className="min-w-52 rounded-xl border border-border bg-light shadow-lg">
        {/* User info */}
        <DropdownMenuLabel className="flex items-center gap-3 px-3 py-3">
          <Avatar className="w-9 h-9 shrink-0">
            <AvatarImage src={image ?? undefined} alt={name ?? "User"} />
            <AvatarFallback className="bg-orange/10 text-orange text-sm font-semibold">
              {initials}
            </AvatarFallback>
          </Avatar>
          <div className="min-w-0">
            {name && <p className="text-sm font-medium text-dark truncate">{name}</p>}
            {email && <p className="text-xs text-muted truncate font-normal">{email}</p>}
          </div>
        </DropdownMenuLabel>

        <DropdownMenuSeparator />

        <DropdownMenuItem
          onClick={() => void handleManageSubscription()}
          disabled={openingPortal}
          className="flex items-center gap-2.5 px-3 py-2.5 text-sm text-muted hover:text-dark cursor-pointer"
        >
          <CreditCard size={14} />
          {openingPortal ? "Opening billing portal..." : "Manage subscription"}
        </DropdownMenuItem>

        <DropdownMenuItem
          onClick={handleSignOut}
          className="flex items-center gap-2.5 px-3 py-2.5 text-sm text-muted hover:text-dark cursor-pointer"
        >
          <LogOut size={14} />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

