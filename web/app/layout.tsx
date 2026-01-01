import type { Metadata } from "next";
import Script from "next/script";

export const metadata: Metadata = {
  title: "Transactoid - Personal Finance Agent",
  description: "AI-powered personal finance assistant",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <Script
          src="https://cdn.platform.openai.com/deployments/chatkit/chatkit.js"
          strategy="beforeInteractive"
        />
      </head>
      <body style={{ margin: 0, padding: 0, height: "100vh" }}>{children}</body>
    </html>
  );
}
