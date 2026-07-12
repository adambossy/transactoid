import { useEffect, useState } from "react";
import { authHeaders } from "./authFetch";
import type { TokenGetter } from "./authFetch";

/** One household member as `GET /api/household/members` returns them. */
export interface HouseholdMember {
  user_id: string;
  email: string;
  display_name: string;
  image_url: string | null;
  is_you: boolean;
}

// One fetch per app session: the list changes only when someone joins the
// household, and every consumer (drawer, chat screen) shares this cache. The
// in-flight promise is cached (not just the result) so consumers that mount
// while the first fetch is still pending await it instead of duplicating it.
let membersPromise: Promise<HouseholdMember[]> | null = null;

function loadMembers(getToken: TokenGetter): Promise<HouseholdMember[]> {
  membersPromise ??= authHeaders(getToken)
    .then((headers) => fetch("/api/household/members", { headers }))
    .then((res) => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    })
    .then((data) => (data.members ?? []) as HouseholdMember[])
    .catch(() => {
      // Decoration only — render without avatars; a reload retries.
      membersPromise = null;
      return [];
    });
  return membersPromise;
}

/**
 * The household's members with their live Clerk (Google) avatars.
 *
 * Returns an empty list until loaded — and stays empty if the fetch fails,
 * which every consumer treats as "no avatars": the stacks and sender icons
 * are decoration, and their absence must never block chat.
 */
export function useHouseholdMembers(getToken: TokenGetter): {
  members: HouseholdMember[];
  me: HouseholdMember | null;
} {
  const [members, setMembers] = useState<HouseholdMember[]>([]);

  useEffect(() => {
    let cancelled = false;
    void loadMembers(getToken).then((loaded) => {
      if (!cancelled && loaded.length > 0) setMembers(loaded);
    });
    return () => {
      cancelled = true;
    };
  }, [getToken]);

  return { members, me: members.find((m) => m.is_you) ?? null };
}
