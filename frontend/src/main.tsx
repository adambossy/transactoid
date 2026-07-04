import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Gallery } from "@penny/ui";
import { ChatScreen } from "./ChatScreen";
import "./index.css";

// Dev-only design-system preview: `/ui` renders the @penny/ui Gallery. Guarded by
// import.meta.env.DEV so the route never exists in a production build.
const showGallery = import.meta.env.DEV && window.location.pathname.startsWith("/ui");

createRoot(document.getElementById("root")!).render(
  <StrictMode>{showGallery ? <Gallery /> : <ChatScreen />}</StrictMode>,
);
