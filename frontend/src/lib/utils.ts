import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge Tailwind classes safely. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Base URL for REST API calls. */
export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

/** Base URL for WebSocket connections. */
export const WS_BASE = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8080";
