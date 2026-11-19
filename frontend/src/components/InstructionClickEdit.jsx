import { useEffect, useRef, useState } from "react";
import SafeInputTextarea from "@/components/SafeInputTextarea";
import { annotateItemMentions } from "@/lib/itemLabels";
import { normalizeInstructionCase, sanitizeOperatorInstruction } from "@/lib/instructionCase";
import "./instruction-click-edit.scss";

/**
 * Single surface: annotated preview by default; click to edit raw instruction text.
 * Item names/part numbers are display-only and never written into `value`.
 * While editing, a live annotated preview stays visible so PL labels do not "disappear".
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

  const normalized = normalizeInstructionCase(sanitizeOperatorInstruction(value) || value);
  const annotated = annotateItemMentions(normalized, itemLookup);
  const empty = !String(normalized || "").trim();
  const showAnnotPreview = Boolean(annotated && annotated !== normalized);

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
        {showAnnotPreview ? (
          <div className="instr-click-edit__live-annot" aria-live="polite">
            <span className="instr-click-edit__live-annot-label">Preview with Parts List names</span>
            <p className="instr-click-edit__live-annot-text">{annotated}</p>
          </div>
        ) : null}
      </div>
    );
  }

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
