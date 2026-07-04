import type { KeyboardEvent } from "react";
import { Button } from "./Button";

export interface InputProps {
  value: string;
  onChange: (v: string) => void;
  onSubmit?: () => void;
  placeholder?: string;
  /** Label for the inset submit button. Defaults to "Ask Penny". */
  buttonLabel?: string;
}

/** Rounded search bar with an inset filled Button; Enter or the button fires
 *  onSubmit. Controlled: the caller owns `value` and updates it via `onChange`. */
export function Input({
  value,
  onChange,
  onSubmit,
  placeholder,
  buttonLabel = "Ask Penny",
}: InputProps) {
  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      e.preventDefault();
      onSubmit?.();
    }
  }

  return (
    <div className="flex items-center gap-2 rounded-full border border-cream bg-paper py-1.5 pl-5 pr-1.5">
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        className="min-w-0 flex-1 bg-transparent font-ui text-sm text-ink placeholder:text-steel focus:outline-none"
      />
      <Button variant="filled" onClick={() => onSubmit?.()}>
        {buttonLabel}
      </Button>
    </div>
  );
}
