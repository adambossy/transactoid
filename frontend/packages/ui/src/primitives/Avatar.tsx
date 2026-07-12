import { useState } from "react";

/** A person as the avatar primitives see one: presentation data only. */
export interface AvatarPerson {
  name: string;
  imageUrl?: string | null;
}

export type AvatarSize = "xs" | "sm" | "md";

const SIZE_CLASSES: Record<AvatarSize, string> = {
  xs: "h-5 w-5 text-[10px]",
  sm: "h-6 w-6 text-xs",
  md: "h-8 w-8 text-sm",
};

export interface AvatarProps extends AvatarPerson {
  size?: AvatarSize;
  className?: string;
}

/**
 * A member's profile picture as a circle, falling back to their initial on a
 * navy disc when there is no picture (or the URL dies — `onError` swaps to the
 * fallback, so a dead image degrades identically to a missing one). Presentation
 * only: no fetching, no knowledge of where pictures come from.
 * `referrerPolicy="no-referrer"` because Google-hosted images can 403 with one.
 */
export function Avatar({ name, imageUrl, size = "sm", className = "" }: AvatarProps) {
  const [broken, setBroken] = useState(false);
  const base = `inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full ${SIZE_CLASSES[size]} ${className}`;
  if (imageUrl && !broken) {
    return (
      <img
        src={imageUrl}
        alt={name}
        referrerPolicy="no-referrer"
        onError={() => setBroken(true)}
        className={`${base} object-cover`}
      />
    );
  }
  return (
    <span
      role="img"
      aria-label={name}
      title={name}
      className={`${base} bg-navy font-ui font-medium text-paper uppercase select-none`}
    >
      {name.trim().charAt(0) || "?"}
    </span>
  );
}

export interface AvatarStackProps {
  people: AvatarPerson[];
  size?: Extract<AvatarSize, "xs" | "sm">;
  className?: string;
}

/**
 * Up to two overlapping avatars — the compact "these people" mark for list
 * rows. Each disc gets a paper ring so the overlap reads as two distinct
 * circles. Entries past the second are ignored (two-person households are the
 * product reality; add a "+N" chip when a third member becomes real).
 */
export function AvatarStack({ people, size = "xs", className = "" }: AvatarStackProps) {
  return (
    <span className={`flex shrink-0 items-center ${className}`}>
      {people.slice(0, 2).map((person, i) => (
        <Avatar
          key={`${person.name}-${i}`}
          {...person}
          size={size}
          className={`ring-2 ring-paper ${i > 0 ? "-ml-2" : ""}`}
        />
      ))}
    </span>
  );
}
