import { useEffect, useRef, useState } from "react";
import SafeInputTextarea from "@/components/SafeInputTextarea";
import { annotateItemMentions } from "@/lib/itemLabels";
import { normalizeInstructionCase } from "@/lib/instructionCase";
import "./instruction-click-edit.scss";

/**
 * Single surface: annotated preview by default; click to edit raw instruction text.
 * Item names/part numbers are display-only and never written into `value`.
 */
export default function InstructionClickEdit({
  value = "",
  onChange,
  itemLookup = {},
  rows = 6,
  placeholder = "Click to add instruction…",
  disabled = false,
  resetKey = null,
}) {
  const [editing, setEditing] = useState(!String(value || "").trim());
  const wrapRef = useRef(null);

  useEffect(() => {
    setEditing(!String(value || "").trim());
  }, [resetKey]); // eslint-disable-line react-hooks/exhaustive-deps -- reopen resets mode

  const normalized = normalizeInstructionCase(value);

  useEffect(() => {
    if (!editing || disabled) return;
    // Persist readable casing into parent state when entering edit mode.
    if (normalized !== String(value || "") && onChange) {
      onChange({ target: { value: normalized }, value: normalized });
    }
    const el = wrapRef.current?.querySelector?.("textarea");
    if (!el) return;
    const t = window.setTimeout(() => {
      el.focus();
      try {
        const len = String(el.value || "").length;
        el.setSelectionRange(len, len);
      } catch {
        /* ignore */
      }
    }, 0);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only when entering edit
  }, [editing]);

  if (editing && !disabled) {
    return (
      <div ref={wrapRef} className="instr-click-edit">
        <SafeInputTextarea
          profile="multiline"
          value={normalized}
          onChange={(e) => {
            // Keep editor on normalized text so Save persists readable casing.
            onChange?.(e);
          }}
          rows={rows}
          className="w-full oarc-instr-dialog__textarea instr-click-edit__textarea"
          autoResize
          placeholder={placeholder}
        />
      </div>
    );
  }

  const annotated = annotateItemMentions(normalized, itemLookup);
  const empty = !String(normalized || "").trim();

  return (
    <div ref={wrapRef} className="instr-click-edit">
      <div
        className={`instr-click-edit__preview${empty ? " instr-click-edit__preview--empty" : ""}${
          disabled ? " instr-click-edit__preview--disabled" : ""
        }`}
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-label={empty ? "Add instruction" : "Edit instruction"}
        onClick={() => {
          if (!disabled) setEditing(true);
        }}
        onKeyDown={(e) => {
          if (disabled) return;
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setEditing(true);
          }
        }}
      >
        {empty ? placeholder : annotated}
      </div>
    </div>
  );
}
