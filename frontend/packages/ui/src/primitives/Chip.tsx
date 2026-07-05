export interface ChipProps {
  /** Optional leading emoji, matching the template's suggestion chips. */
  emoji?: string;
  label: string;
  onClick?: () => void;
  className?: string;
}

export function Chip({ emoji, label, onClick, className = "" }: ChipProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-2 rounded-full border border-cream bg-paper px-4 py-1.5 font-ui text-sm text-ink transition-colors cursor-pointer hover:bg-cream-soft ${className}`}
    >
      {emoji ? (
        <span aria-hidden="true" className="text-base leading-none">
          {emoji}
        </span>
      ) : null}
      <span>{label}</span>
    </button>
  );
}
