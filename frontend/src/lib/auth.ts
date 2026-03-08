import { betterAuth } from "better-auth";
import { Pool } from "pg";
import { polar, checkout, portal, usage, webhooks } from "@polar-sh/better-auth"; 
import { Polar } from "@polar-sh/sdk";

const polarClient = new Polar({ 
    accessToken: process.env.POLAR_ACCESS_TOKEN, 
    // Use 'sandbox' if you're using the Polar Sandbox environment
    // Remember that access tokens, products, etc. are completely separated between environments.
    // Access tokens obtained in Production are for instance not usable in the Sandbox environment.
    server: 'sandbox'
}); 

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
                    products: [
                        {
                            productId: "221cd4df-10f9-4035-9dab-9c441619068d",
                            slug: "Pro" // Custom slug for easy reference in Checkout URL, e.g. /checkout/Pro
                        },
                        {
                            productId: "f4d27ae1-06bf-45bf-acd2-5b8cc96648ee",
                            slug: "Pro" // Custom slug for easy reference in Checkout URL, e.g. /checkout/Pro
                        },
                        {
                            productId: "5acc849d-c821-4f7c-ae17-46264e9633f0",
                            slug: "Free" // Custom slug for easy reference in Checkout URL, e.g. /checkout/Free
                        }
                    ],
                    successUrl: process.env.POLAR_SUCCESS_URL,
                    authenticatedUsersOnly: true
                }),
                portal()
            ],
        })
    ]
});