import { useEffect, useRef, useState } from "react";
import SafeInputTextarea from "@/components/SafeInputTextarea";
import { annotateItemMentions } from "@/lib/itemLabels";
import { normalizeInstructionCase, sanitizeOperatorInstruction } from "@/lib/instructionCase";
import { renderInstructionWithViewInfo } from "@/lib/tableViewHints";
import "./instruction-click-edit.scss";

/**
 * Single surface: annotated preview by default; click to edit raw instruction text.
 * Item names/part numbers are display-only and never written into `value`.
 * Gated view-ref (i) buttons open drawing snapshots when crops are available.
 * Found reference sheets (PS200, …) become links when `foundByCode` is provided.
 */
export default function InstructionClickEdit({
  value = "",
  onChange,
  itemLookup = {},
  viewCrops = [],
  onOpenViewCrop,
  foundByCode = {},
  onOpenRefDoc,
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
  const previewNodes = renderInstructionWithViewInfo(normalized, {
    itemLookup,
    viewCrops,
    onOpenViewCrop,
    foundByCode,
    onOpenRefDoc,
  });

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
            onChange?.(e);
          }}
          rows={rows}
          className="w-full oarc-instr-dialog__textarea instr-click-edit__textarea"
          autoResize
          placeholder={placeholder}
        />
        {showAnnotPreview ||
        (viewCrops || []).length > 0 ||
        (foundByCode && Object.keys(foundByCode).length > 0) ? (
          <div className="instr-click-edit__live-annot" aria-live="polite">
            <span className="instr-click-edit__live-annot-label">Preview</span>
            <p className="instr-click-edit__live-annot-text">{previewNodes}</p>
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
        onClick={(e) => {
          if (disabled) return;
          if (e.target?.closest?.(".instr-view-info-btn, .rca-refdoc-link")) return;
          setEditing(true);
        }}
        onKeyDown={(e) => {
          if (disabled) return;
          if (e.target?.closest?.(".instr-view-info-btn, .rca-refdoc-link")) return;
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setEditing(true);
          }
        }}
      >
        {empty ? placeholder : previewNodes}
      </div>
    </div>
  );
}
