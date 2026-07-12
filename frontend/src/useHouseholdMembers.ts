import { useEffect, useState } from "react";
import { authHeaders } from "./authFetch";

/** Injected token source: Clerk's getToken in clerk mode, a null no-op in dev. */
type GetToken = () => Promise<string | null>;

/** One household member as `GET /api/household/members` returns them. */
export interface HouseholdMember {
  user_id: string;
  email: string;
  display_name: string;
  image_url: string | null;
  is_you: boolean;
}

// One fetch per app session: the list changes only when someone joins the
// household, and every consumer (drawer, chat screen) shares this cache.
let cached: HouseholdMember[] | null = null;

/**
 * The household's members with their live Clerk (Google) avatars.
 *
 * Returns an empty list until loaded — and stays empty if the fetch fails,
 * which every consumer treats as "no avatars": the stacks and sender icons
 * are decoration, and their absence must never block chat.
 */
export function useHouseholdMembers(getToken: GetToken): {
  members: HouseholdMember[];
  me: HouseholdMember | null;
} {
  const [members, setMembers] = useState<HouseholdMember[]>(cached ?? []);

  useEffect(() => {
    if (cached !== null) return;
    let cancelled = false;
    authHeaders(getToken)
      .then((headers) => fetch("/api/household/members", { headers }))
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => {
        cached = (data.members ?? []) as HouseholdMember[];
        if (!cancelled) setMembers(cached);
      })
      .catch(() => {
        // Decoration only — render without avatars; a reload retries.
      });
    return () => {
      cancelled = true;
    };
  }, [getToken]);

  return { members, me: members.find((m) => m.is_you) ?? null };
}
