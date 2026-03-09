import { createAuthClient } from "better-auth/react"
import { polarClient } from "@polar-sh/better-auth/client";  

export const authClient = createAuthClient({
    /** The base URL of the server (optional if you're using the same domain) */
    baseURL: process.env.BETTER_AUTH_URL,
    plugins: [polarClient()], 
})

type PolarCustomerStateResponse = {
    data?: unknown;
};

type PolarAuthBridge = {
    checkout?: (input: { slug?: string; products?: string[] }) => Promise<unknown>;
    customer?: {
        state?: () => Promise<PolarCustomerStateResponse>;
        portal?: () => Promise<unknown>;
    };
};

function polarBridge(): PolarAuthBridge {
    return authClient as unknown as PolarAuthBridge;
}

export async function getPolarCustomerState(): Promise<unknown> {
    const response = await polarBridge().customer?.state?.();
    return response?.data ?? null;
}

export async function startPolarCheckout(slug: "pro-monthly" | "pro-yearly"): Promise<void> {
    const checkout = polarBridge().checkout;
    if (!checkout) {
        throw new Error("Polar checkout is not configured.");
    }

    try {
        await checkout({ slug });
        return;
    } catch {
        const monthlyProductId = process.env.POLAR_PRO_MONTHLY_PRODUCT_ID;
        const yearlyProductId = process.env.POLAR_PRO_YEARLY_PRODUCT_ID;
        const fallbackProductId = slug === "pro-monthly" ? monthlyProductId : yearlyProductId;

        if (!fallbackProductId) {
            throw new Error("Unable to start checkout. Product configuration is missing.");
        }

        await checkout({ products: [fallbackProductId] });
    }
}

export async function openPolarPortal(): Promise<void> {
    await polarBridge().customer?.portal?.();
}

export const { signIn, signUp, signOut, useSession } = authClient