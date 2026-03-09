import { betterAuth } from "better-auth";
import { Pool } from "pg";
import { polar, checkout, portal } from "@polar-sh/better-auth";
import { Polar } from "@polar-sh/sdk";

const polarClient = new Polar({
    accessToken: process.env.POLAR_ACCESS_TOKEN,
    // Use 'sandbox' if you're using the Polar Sandbox environment
    // Remember that access tokens, products, etc. are completely separated between environments.
    // Access tokens obtained in Production are for instance not usable in the Sandbox environment.
    server: process.env.POLAR_SERVER === "production" ? "production" : "sandbox",
});

const polarProMonthlyProductId = process.env.POLAR_PRO_MONTHLY_PRODUCT_ID?.trim();
const polarProYearlyProductId = process.env.POLAR_PRO_YEARLY_PRODUCT_ID?.trim();

const checkoutProducts = [
    polarProMonthlyProductId
        ? {
            productId: polarProMonthlyProductId,
            slug: "pro-monthly",
        }
        : null,
    polarProYearlyProductId
        ? {
            productId: polarProYearlyProductId,
            slug: "pro-yearly",
        }
        : null,
].filter((product): product is { productId: string; slug: string } => Boolean(product));

if (checkoutProducts.length === 0) {
    console.warn(
        "[auth] Polar checkout is enabled but no products are configured. " +
        "Set POLAR_PRO_MONTHLY_PRODUCT_ID and/or POLAR_PRO_YEARLY_PRODUCT_ID.",
    );
}

const pool = new Pool({
    host: process.env.PGHOST,
    port: Number(process.env.PGPORT ?? 5432),
    user: process.env.PGUSER,
    password: process.env.PGPASSWORD,
    database: process.env.PGDATABASE,
    ssl: {
        rejectUnauthorized: false, // For local dev with self-signed certs; adjust for production
    },
});

export const auth = betterAuth({
    database: pool,
    socialProviders: {
        google: {
            clientId: process.env.GOOGLE_CLIENT_ID as string,
            clientSecret: process.env.GOOGLE_CLIENT_SECRET as string,
        },
    },
    session: {
        cookieCache: {
            enabled: true,
            maxAge: 10 * 60, // 10 minutes
        },
    },
    plugins: [
        polar({
            client: polarClient,
            createCustomerOnSignUp: true,
            use: [
                checkout({
                    products: checkoutProducts,
                    successUrl: process.env.POLAR_SUCCESS_URL,
                    authenticatedUsersOnly: true
                }),
                portal()
            ],
        })
    ]
});