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
        <link href="https://api.fontshare.com/v2/css?f[]=supreme@200,201,300,301,400,401,500,501,700,701&display=swap" rel="stylesheet"></link>
      </head>
      <body
        className="antialiased"
      >
        {children}
      </body>
    </html>
  );
}
