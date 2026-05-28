import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ChatScreen } from "./ChatScreen";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ChatScreen />
  </StrictMode>,
);
