import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Button } from "primereact/button";
import "./PmfAnalyzeLoader.scss";

/** Single document glyph — fill/stroke via CSS variables. */
function DocSvg() {
  return (
    <svg
      className="pmf-analyze-loader__doc-svg"
      viewBox="0 0 40 52"
      width="40"
      height="52"
      aria-hidden
      focusable="false"
    >
      <path
        className="pmf-analyze-loader__doc-body"
        d="M6 2h20l10 10v36a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z"
      />
      <path className="pmf-analyze-loader__doc-fold" d="M26 2v10h10" />
      <path
        className="pmf-analyze-loader__doc-lines"
        d="M10 22h20M10 28h16M10 34h18M10 40h12"
        fill="none"
        strokeLinecap="round"
      />
    </svg>
  );
}

/** Stationary magnifying glass over the stage center. */
function MagnifierSvg() {
  return (
    <svg
      className="pmf-analyze-loader__glass-svg"
      viewBox="0 0 72 72"
      width="72"
      height="72"
      aria-hidden
      focusable="false"
    >
      <circle
        className="pmf-analyze-loader__glass-rim"
        cx="30"
        cy="30"
        r="18"
        fill="none"
      />
      <circle
        className="pmf-analyze-loader__glass-lens"
        cx="30"
        cy="30"
        r="14.5"
      />
      <line
        className="pmf-analyze-loader__glass-handle"
        x1="43"
        y1="43"
        x2="60"
        y2="60"
        strokeLinecap="round"
      />
    </svg>
  );
}

/**
 * Fixed viewport-centered analyze overlay over the main content pane only
 * (sidebar + topbar stay clear). Three docs travel RTL under a fixed magnifier.
 */
export default function PmfAnalyzeLoader({
  visible = false,
  onCancel,
  message = "Analyzing",
}) {
  const [box, setBox] = useState(null);

  useEffect(() => {
    if (!visible) {
      setBox(null);
      return undefined;
    }

    const update = () => {
      const main = document.querySelector(".rca-main");
      const topbar = document.querySelector(".rca-topbar");
      const topbarBottom = topbar
        ? Math.max(0, topbar.getBoundingClientRect().bottom)
        : 0;
      if (!main) {
        setBox({
          top: topbarBottom,
          left: 0,
          width: window.innerWidth,
          height: Math.max(0, window.innerHeight - topbarBottom),
        });
        return;
      }
      const mr = main.getBoundingClientRect();
      const top = Math.max(topbarBottom, Math.max(0, mr.top));
      const left = Math.max(0, mr.left);
      const width = Math.max(0, Math.min(window.innerWidth, mr.right) - left);
      const height = Math.max(0, window.innerHeight - top);
      setBox({ top, left, width, height });
    };

    update();
    window.addEventListener("resize", update);
    const t = window.setInterval(update, 200);
    const stop = window.setTimeout(() => window.clearInterval(t), 800);
    return () => {
      window.removeEventListener("resize", update);
      window.clearInterval(t);
      window.clearTimeout(stop);
    };
  }, [visible]);

  if (!visible || !box) return null;

  const node = (
    <div
      className="pmf-analyze-loader-overlay"
      role="dialog"
      aria-modal="true"
      aria-busy="true"
      style={{
        top: box.top,
        left: box.left,
        width: box.width,
        height: box.height,
      }}
    >
      <div className="pmf-analyze-loader" role="status" aria-live="polite">
        <div className="pmf-analyze-loader__stage">
          <div className="pmf-analyze-loader__docs" aria-hidden>
            <div className="pmf-analyze-loader__doc pmf-analyze-loader__doc--1">
              <DocSvg />
            </div>
            <div className="pmf-analyze-loader__doc pmf-analyze-loader__doc--2">
              <DocSvg />
            </div>
            <div className="pmf-analyze-loader__doc pmf-analyze-loader__doc--3">
              <DocSvg />
            </div>
          </div>
          <div className="pmf-analyze-loader__glass" aria-hidden>
            <MagnifierSvg />
          </div>
        </div>
        <p className="pmf-analyze-loader__caption">{message}</p>
        {typeof onCancel === "function" ? (
          <Button
            type="button"
            label="Stop"
            icon="pi pi-stop"
            size="small"
            outlined
            severity="danger"
            className="pmf-analyze-loader__stop"
            onClick={onCancel}
          />
        ) : null}
      </div>
    </div>
  );

  return createPortal(node, document.body);
}
