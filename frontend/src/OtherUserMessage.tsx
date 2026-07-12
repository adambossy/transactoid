import { stripSystemReminders } from "@adambossy/agent-ui";
import type { UIMessage, UIMessagePart } from "@adambossy/agent-ui";
import { Avatar } from "@penny/ui";
import type { HouseholdMember } from "./useHouseholdMembers";

/**
 * A user message written by the *other* household member in a joint thread:
 * left-aligned green (steel) bubble with the sender's avatar at its foot —
 * the iMessage-style mirror of the viewer's own right-aligned grey bubble,
 * which stays with agent-ui's Message. Penny-local on purpose: the library's
 * message type has no sender concept, so the one authored-message case lives
 * here rather than pushing household semantics upstream.
 */
export function OtherUserMessage({
  message,
  member,
}: {
  message: UIMessage;
  member: HouseholdMember | undefined;
}) {
  const text = stripSystemReminders(
    message.parts
      .filter((p): p is Extract<UIMessagePart, { type: "text" }> => p.type === "text")
      .map((p) => p.text)
      .join(""),
  );
  return (
    <div className="my-3 flex items-end justify-start gap-1.5">
      <Avatar
        name={member?.display_name ?? "?"}
        imageUrl={member?.image_url}
        size="sm"
      />
      <div className="max-w-[78%] rounded-2xl bg-steel px-4 py-2.5 text-sm text-paper">
        {text}
      </div>
    </div>
  );
}
