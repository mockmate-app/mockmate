import { betterAuth } from "better-auth";
import { Pool } from "pg";

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
});