"use client";

import { ChatKit, useChatKit } from "@openai/chatkit-react";

export default function Home() {
  const chatkit = useChatKit({
    api: {
      url: "http://localhost:8000/chatkit",
      domainKey: "local-dev",
    },
    theme: "dark",
    composer: {
      placeholder: "Ask about your finances...",
    },
    startScreen: {
      greeting: "What can I help you with today?",
      prompts: [
        { label: "Monthly spending", prompt: "How much did I spend last month?" },
        { label: "Top categories", prompt: "Show me my top spending categories" },
        { label: "Sync transactions", prompt: "Sync my latest transactions" },
      ],
    },
  });

  return (
    <main
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        backgroundColor: "#1a1a2e",
      }}
    >
      <header
        style={{
          padding: "1rem 2rem",
          borderBottom: "1px solid #333",
          backgroundColor: "#16213e",
        }}
      >
        <h1
          style={{
            margin: 0,
            color: "#e94560",
            fontSize: "1.5rem",
            fontFamily: "system-ui, sans-serif",
          }}
        >
          Transactoid
        </h1>
        <p
          style={{
            margin: "0.25rem 0 0 0",
            color: "#888",
            fontSize: "0.875rem",
            fontFamily: "system-ui, sans-serif",
          }}
        >
          Personal Finance Agent
        </p>
      </header>

      <div style={{ flex: 1, display: "flex" }}>
        <ChatKit control={chatkit.control} style={{ flex: 1 }} />
      </div>
    </main>
  );
}
