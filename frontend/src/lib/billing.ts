export type PlanTier = "free" | "pro";

export const BILLING_PLANS = {
  free: {
    id: "free" as const,
    label: "Free",
    monthlyPriceUsd: 0,
    yearlyPriceUsd: 0,
    interviewsPerMonth: 5,
    personaLimit: 3,
    postureAnalysis: false,
  },
  pro: {
    id: "pro" as const,
    label: "Pro",
    monthlyPriceUsd: 9,
    yearlyPriceUsd: 79,
    interviewsPerMonth: Number.POSITIVE_INFINITY,
    personaLimit: Number.POSITIVE_INFINITY,
    postureAnalysis: true,
  },
};

export const FREE_TIER_PERSONA_IDS = [
  "neutral",
  "startup_founder",
  "investment_banker",
] as const;

function toObject(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)
    : null;
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function hasActiveSubscription(subscription: unknown): boolean {
  const obj = toObject(subscription);
  if (!obj) return false;

  if (obj.active === true || obj.isActive === true) {
    return true;
  }

  const status = typeof obj.status === "string" ? obj.status.toLowerCase() : "";
  return status === "active" || status === "trialing";
}

export function resolvePlanFromCustomerState(customerState: unknown): PlanTier {
  const state = toObject(customerState);
  if (!state) return "free";

  const activeSubscriptions = asArray(
    state.activeSubscriptions ?? state.active_subscriptions,
  );
  if (activeSubscriptions.some((subscription) => hasActiveSubscription(subscription))) {
    return "pro";
  }

  const allSubscriptions = asArray(state.subscriptions);
  if (allSubscriptions.some((subscription) => hasActiveSubscription(subscription))) {
    return "pro";
  }

  return "free";
}
