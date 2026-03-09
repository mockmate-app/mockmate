"use client";

import { Suspense, useEffect, useMemo } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import AppHeader from "@/components/AppHeader";
import {
    useSession,
    getPolarCustomerState,
    startPolarCheckout,
    openPolarPortal,
} from "@/lib/auth-client";
import { resolvePlanFromCustomerState } from "@/lib/billing";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { CheckCircle2, Sparkles } from "lucide-react";

export default function ProPage() {
    return (
        <Suspense fallback={<Spinner />}>
            <ProPageInner />
        </Suspense>
    );
}

function ProPageInner() {
    const { data: session, isPending } = useSession();
    const router = useRouter();

    const { data: customerState } = useQuery({
        queryKey: ["polar-customer-state", session?.user?.id],
        queryFn: getPolarCustomerState,
        enabled: !!session?.user?.id,
    });

    const currentPlan = useMemo(
        () => resolvePlanFromCustomerState(customerState),
        [customerState],
    );

    useEffect(() => {
        if (!isPending && !session) {
            router.replace("/login");
        }
    }, [isPending, router, session]);

    if (isPending) return <Spinner />;
    if (!session) return null;

    const checkout = async (slug: "pro-monthly" | "pro-yearly") => {
        await startPolarCheckout(slug);
    };

    const openPortal = async () => {
        await openPolarPortal();
    };

    return (
        <div className="min-h-screen bg-surface flex flex-col">
            <AppHeader
                homeHref="/dashboard"
                name={session.user.name}
                email={session.user.email}
                image={session.user.image}
                showProButton={false}
            />

            <main className="flex-1 mx-auto w-full max-w-5xl px-4 sm:px-6 py-12">
                <div className="rounded-2xl border shadow-lg bg-light p-6 sm:p-8 mb-6">
                    <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
                        <div>
                            {/* <p className="inline-flex items-center gap-1.5 text-xs font-medium text-orange bg-orange/10 border border-orange/25 rounded-full px-2.5 py-1 mb-3">
                <Sparkles size={12} /> MockMate Pro
              </p> */}
                            <h1 className="text-2xl sm:text-3xl font-bold text-dark tracking-tight">Upgrade to Pro</h1>
                            <p className="text-sm text-muted mt-2">Unlimited interviews, all personas, and posture coaching to level up faster.</p>
                        </div>
                        {currentPlan === "pro" ? (
                            <Badge className="bg-orange/5 text-orange border border-orange/30 w-fit">Current plan: Pro</Badge>
                        ) : (
                            <Badge variant="secondary" className="w-fit">Current plan: Free</Badge>
                        )}
                    </div>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                    <Card className="rounded-2xl shadow-lg">
                        <CardContent className="p-6 flex flex-col gap-6 h-full">
                            <div className="flex flex-col gap-2">
                                <p className="text-xl font-bold text-dark">🆓 Free</p>
                                <p className="text-sm text-muted">$0 / forever</p>
                            </div>
                            <ul className="text-sm text-dark space-y-2.5">
                                <li className="flex items-center gap-2"><CheckCircle2 size={15} className="text-muted" />5 mock interviews per month</li>
                                <li className="flex items-center gap-2"><CheckCircle2 size={15} className="text-muted" />3 interviewer personas</li>
                            </ul>
                            {currentPlan !== "pro" && (<Button asChild variant="outline" className="rounded-full mt-auto">
                                <Link href="/dashboard">Continue on Free</Link>
                            </Button>)}
                        </CardContent>
                    </Card>

                    <Card className="rounded-2xl shadow-lg">
                        <CardContent className="p-6 flex flex-col gap-6 h-full">
                            <div className="flex flex-col gap-2">
                                <p className="text-xl font-bold text-dark">⚡ Pro</p>
                                <p className="text-sm text-muted">$9 / month</p>
                                <p className="text-sm text-muted flex gap-1.5 items-center">$79 / year <span className="text-orange font-medium">(save 26%)</span><Badge className="bg-orange/5 text-orange border border-orange">Best value</Badge></p>
                            </div>

                            <ul className="text-sm text-dark space-y-2.5">
                                <li className="flex items-center gap-2"><CheckCircle2 size={15} className="text-orange" />Unlimited mock interviews</li>
                                <li className="flex items-center gap-2"><CheckCircle2 size={15} className="text-orange" />All interviewer personas</li>
                                <li className="flex items-center gap-2"><CheckCircle2 size={15} className="text-orange" />Posture &amp; presence analysis</li>
                            </ul>

                            {currentPlan !== "pro" && (<div className="flex flex-col sm:flex-row gap-2 mt-auto">
                                <Button
                                    onClick={() => void checkout("pro-monthly")}
                                    className="rounded-full bg-orange text-light hover:opacity-90 hover:bg-orange"
                                >
                                    Start Pro Monthly
                                </Button>
                                <Button
                                    onClick={() => void checkout("pro-yearly")}
                                    variant="outline"
                                    className="rounded-full"
                                >
                                    Start Pro Yearly
                                </Button>
                            </div>)}

                            {currentPlan === "pro" && (
                                <Button
                                    onClick={() => void openPortal()}
                                    variant="outline"
                                    className="rounded-full"
                                >
                                    Manage subscription
                                </Button>
                            )}
                        </CardContent>
                    </Card>
                </div>
            </main>
        </div>
    );
}

function Spinner() {
    return (
        <div className="min-h-screen bg-surface flex items-center justify-center">
            <div className="w-6 h-6 border-2 border-orange border-t-transparent rounded-full animate-spin" />
        </div>
    );
}
