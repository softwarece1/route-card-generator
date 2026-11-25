import { useEffect, useRef, useState } from "react";
import SafeInputTextarea from "@/components/SafeInputTextarea";
import { annotateItemMentions } from "@/lib/itemLabels";
import { normalizeInstructionCase, sanitizeOperatorInstruction } from "@/lib/instructionCase";
import { renderInstructionWithViewInfo } from "@/lib/tableViewHints";
import "./instruction-click-edit.scss";

/**
 * Single surface: annotated preview by default; click to edit raw instruction text.
 * Item names/part numbers are display-only and never written into `value`.
 *
 * Editing uses a local draft so sanitize/normalize do not rewrite the controlled
 * value on every keystroke (that was jumping the caret and eating spaces).
 * Enter saves when `onSave` is provided; Shift+Enter inserts a newline.
 */
export default function InstructionClickEdit({
  value = "",
  onChange,
  onSave,
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
  const [draft, setDraft] = useState(() => String(value || ""));
  const wrapRef = useRef(null);
  const enteredEditRef = useRef(false);

  const displayNormalized = normalizeInstructionCase(
    sanitizeOperatorInstruction(value) || value,
  );
  const empty = !String(displayNormalized || "").trim();
  const previewSource = editing ? draft : displayNormalized;
  const previewForAnnot = normalizeInstructionCase(
    sanitizeOperatorInstruction(previewSource) || previewSource,
  );
  const previewNodes = renderInstructionWithViewInfo(previewForAnnot, {
    itemLookup,
    viewCrops,
    onOpenViewCrop,
    foundByCode,
    onOpenRefDoc,
  });
  const showLiveAnnot =
    editing &&
    (Boolean(annotateItemMentions(previewForAnnot, itemLookup)) ||
      (viewCrops || []).length > 0 ||
      (foundByCode && Object.keys(foundByCode).length > 0));

  useEffect(() => {
    const next = String(value || "");
    const cleaned = normalizeInstructionCase(sanitizeOperatorInstruction(next) || next);
    setDraft(cleaned || next);
    setEditing(!cleaned.trim());
    enteredEditRef.current = false;
  }, [resetKey]); // eslint-disable-line react-hooks/exhaustive-deps -- reopen resets mode

  useEffect(() => {
    if (!editing || disabled) return;
    if (enteredEditRef.current) return;
    enteredEditRef.current = true;
    const cleaned = normalizeInstructionCase(
      sanitizeOperatorInstruction(String(value || "")) || String(value || ""),
    );
    if (cleaned !== String(value || "") && onChange) {
      onChange({ target: { value: cleaned }, value: cleaned });
      setDraft(cleaned);
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
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only once when entering edit
  }, [editing, disabled]);

  const commitDraft = (raw) => {
    const next = String(raw ?? "");
    setDraft(next);
    onChange?.({ target: { value: next }, value: next });
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey && typeof onSave === "function") {
      e.preventDefault();
      e.stopPropagation();
      onSave();
      return;
    }
    if (e.key === "Enter" && e.shiftKey) {
      // Allow default newline; stop Dialog from treating Enter as Accept
      e.stopPropagation();
    }
  };

  if (editing && !disabled) {
    return (
      <div ref={wrapRef} className="instr-click-edit">
        <SafeInputTextarea
          profile="multiline"
          value={draft}
          onChange={(e) => commitDraft(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={rows}
          className="w-full oarc-instr-dialog__textarea instr-click-edit__textarea"
          autoResize
          placeholder={placeholder}
        />
        <p className="instr-click-edit__keys-hint">
          Shift+Enter for a new line
          {typeof onSave === "function" ? " · Enter to save" : ""}
        </p>
        {showLiveAnnot ? (
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
          enteredEditRef.current = false;
          setDraft(
            normalizeInstructionCase(
              sanitizeOperatorInstruction(String(value || "")) || String(value || ""),
            ),
          );
          setEditing(true);
        }}
        onKeyDown={(e) => {
          if (disabled) return;
          if (e.target?.closest?.(".instr-view-info-btn, .rca-refdoc-link")) return;
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            enteredEditRef.current = false;
            setDraft(
              normalizeInstructionCase(
                sanitizeOperatorInstruction(String(value || "")) || String(value || ""),
              ),
            );
            setEditing(true);
          }
        }}
      >
        {empty ? placeholder : previewNodes}
      </div>
    </div>
  );
}
