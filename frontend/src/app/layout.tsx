import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MockMate — Interview practice, without the nerves.",
  description:
    "AI-powered mock interview platform that conducts real, adaptive interview sessions using voice, vision, and personalised question generation.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <link href="https://api.fontshare.com/v2/css?f[]=supreme@200,201,300,301,400,401,500,501,700,701&display=swap" rel="stylesheet" />
        <link rel="icon" type="image/png" href="/favicons/favicon-96x96.png" sizes="96x96" />
        <link rel="icon" type="image/svg+xml" href="/favicons/favicon.svg" />
        <link rel="apple-touch-icon" sizes="180x180" href="/favicons/apple-touch-icon.png" />
        <meta name="apple-mobile-web-app-title" content="MockMate" />
        <link rel="manifest" href="/favicons/site.webmanifest" />
      </head>
      <body
        className="antialiased"
      >
        {children}
      </body>
    </html>
  );
}
