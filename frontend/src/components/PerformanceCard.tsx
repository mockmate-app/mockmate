"use client";

import { useState, useCallback } from "react";
import Image from "next/image";
import { Download, Linkedin } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { API_BASE, personaLabel } from "@/constants/common";

/* ── Types ──────────────────────────────────────────────────────────── */

export interface PerformanceCardData {
  session_id: string;
  score: number;
  decision: "offer" | "rejection";
  job_role: string;
  persona: string;
  interviewer_name: string;
  motivational_line: string;
  has_background: boolean;
  image_url: string | null;
}

/* ── Score helpers ──────────────────────────────────────────────────── */

function scoreGradient(score: number) {
  if (score >= 85) return "from-amber-400 via-yellow-300 to-amber-500";
  if (score >= 70) return "from-emerald-400 via-green-300 to-emerald-500";
  if (score >= 50) return "from-orange via-amber-400 to-orange";
  return "from-red-400 via-rose-300 to-red-500";
}

function decisionLabel(d: string) {
  return d.toLowerCase() === "offer" ? "OFFER" : "REJECTED";
}

function decisionColor(d: string) {
  return d.toLowerCase() === "offer"
    ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/30"
    : "bg-rose-500/20 text-rose-300 border-rose-500/30";
}

/* ── Component ──────────────────────────────────────────────────────── */

export default function PerformanceCard({
  card,
  compact = false,
  onCardClick,
}: {
  card: PerformanceCardData;
  userName?: string;
  compact?: boolean;
  onCardClick?: () => void;
}) {
  const [downloading, setDownloading] = useState(false);

  const handleCardClick = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      if (!onCardClick) return;
      const target = event.target as HTMLElement;
      if (target.closest("button") || target.closest("a")) return;
      onCardClick();
    },
    [onCardClick],
  );

  const handleCardKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (!onCardClick) return;
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      onCardClick();
    },
    [onCardClick],
  );

  /* ── Download image reliably ──────────────────────────────────────── */
  const handleDownload = useCallback(async () => {
    setDownloading(true);
    try {
      const imageUrl = card.has_background && card.image_url
        ? `${API_BASE}${card.image_url}`
        : null;

      if (!imageUrl) return;

      const resp = await fetch(imageUrl, { cache: "no-store" });
      if (!resp.ok) throw new Error(`Image download failed: ${resp.status}`);
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `mockmate-performance-card-${card.session_id}.jpg`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error("Download failed:", err);
    } finally {
      setDownloading(false);
    }
  }, [card]);

  /* ── Share to LinkedIn ───────────────────────────────────────────── */
  const handleLinkedInShare = useCallback(() => {
    const shareText = [
      `I scored ${card.score}/100 in a MockMate ${card.job_role} interview.`,
      `"${card.motivational_line}"`,
      `Interviewer persona: ${personaLabel(card.persona)}.`,
      `Attend your first mock interview for free at https://getmockmate.com!`,
      "#MockMate #InterviewPrep #CareerGrowth",
    ].join("\n\n");

    window.open(
      `https://www.linkedin.com/feed/?shareActive=true&text=${encodeURIComponent(shareText)}`,
      "_blank",
      "noopener,noreferrer",
    );
  }, [card]);

  const bgImageUrl = card.has_background
    ? `${API_BASE}${card.image_url}`
    : null;

  return (
    <Card
      className={`group relative w-full overflow-hidden rounded-2xl border-0 shadow-2xl ${onCardClick ? "cursor-pointer" : ""}`}
      onClick={handleCardClick}
      onKeyDown={handleCardKeyDown}
      role={onCardClick ? "button" : undefined}
      tabIndex={onCardClick ? 0 : undefined}
    >
      {/* AI background image */}
      <div className="relative w-full aspect-video">
        {bgImageUrl ? (
          <Image
            src={bgImageUrl}
            alt="Performance card background"
            fill
            className="object-cover"
            unoptimized
          />
        ) : (
          <div className="absolute inset-0 bg-linear-to-br from-[#1a1a2e] via-[#16213e] to-[#0f3460]" />
        )}

        {/* Overlay for text legibility */}
        <div className="absolute inset-0 bg-linear-to-r from-black/90 via-black/70 to-transparent" />
        <div className="absolute inset-0 bg-linear-to-t from-black/60 to-transparent" />

        {/* Content overlay */}
        <div className={`absolute inset-0 flex flex-col justify-between ${compact ? "p-3" : "p-5 sm:p-8"}`}>
          {/* Top row: branding + decision */}
          <div className="flex items-center justify-between">
            <span className={`${compact ? "text-[9px]" : "text-xs sm:text-sm"} font-bold tracking-wider text-orange uppercase`}>
              MockMate
            </span>
            <Badge
              variant="outline"
              className={`${compact ? "text-[8px] px-1.5 py-0 h-5" : "text-[10px] sm:text-xs"} font-bold uppercase tracking-wide border ${decisionColor(card.decision)}`}
            >
              {decisionLabel(card.decision)}
            </Badge>
          </div>

          {/* Center: score + details */}
          <div className={`flex flex-col ${compact ? "gap-0.5" : "gap-1.5 sm:gap-3"}`}>
            <div className={`flex items-end ${compact ? "gap-1" : "gap-2 sm:gap-3"}`}>
              {/* <div className="self-center -mt-0.5">{scoreIcon(card.score)}</div> */}
              <span
                className={`${compact ? "text-5xl leading-none" : "text-5xl sm:text-7xl"} font-extrabold tracking-tight bg-linear-to-r ${scoreGradient(card.score)} bg-clip-text text-transparent`}
              >
                {card.score}
              </span>
              <span className={`${compact ? "text-4xl mb-0.5" : "text-lg sm:text-2xl mb-1 sm:mb-2"} font-light text-white/30 self-end`}>
                /100
              </span>
            </div>
            <p className={`${compact ? "text-[12px]" : "text-sm sm:text-xl"} font-semibold text-white/95 truncate`}>
              {card.job_role}
            </p>
            <p className={`${compact ? "text-[10px]" : "text-[10px] sm:text-sm"} text-white/50 truncate`}>
              Interviewed by {card.interviewer_name} &bull;{" "}
              {personaLabel(card.persona)}
            </p>
          </div>

          {/* Bottom: motivational line + actions */}
          <div className={`flex ${compact ? "justify-end" : "flex-col sm:flex-row sm:items-end justify-between"} gap-2`}>
            {!compact && (
              <p className="text-xs sm:text-base italic text-white/60 max-w-md leading-relaxed line-clamp-2">
                &ldquo;{card.motivational_line}&rdquo;
              </p>
            )}

            {/* Action buttons */}
            <div className={`flex items-center gap-2 shrink-0 ${compact ? "ml-auto" : ""}`}>
              <Button
                size="sm"
                variant="outline"
                className={`${compact ? "h-8 px-3 text-[11px]" : "text-xs"} rounded-full border-white/20 bg-white/10 text-white hover:bg-white/20 hover:text-white gap-1.5 backdrop-blur-sm`}
                onClick={handleDownload}
                disabled={downloading}
              >
                <Download size={14} />
                <span className={`${compact ? "hidden" : "hidden sm:inline"}`}>
                  {downloading ? "Saving…" : "Download"}
                </span>
              </Button>
              <Button
                size="sm"
                variant="outline"
                className={`${compact ? "h-8 px-3 text-[11px]" : "text-xs"} rounded-full border-white/20 bg-white/10 text-white hover:bg-[#0077b5]/80 hover:border-[#0077b5]/50 hover:text-white gap-1.5 backdrop-blur-sm`}
                onClick={handleLinkedInShare}
              >
                <Linkedin size={14} />
                <span className={`${compact ? "hidden" : "hidden sm:inline"}`}>Share</span>
              </Button>
            </div>
          </div>
        </div>
      </div>
    </Card>
  );
}

/* ── Loading skeleton ──────────────────────────────────────────────── */

export function PerformanceCardSkeleton() {
  return (
    <Card className="w-full overflow-hidden rounded-2xl border-0 shadow-2xl">
      <Skeleton className="aspect-video w-full rounded-none" />
    </Card>
  );
}
