/** Sentence-case OCR ALL-CAPS shop instructions for display / edit. */

const KEEP_ACRONYMS = new Set([
  "GA",
  "PCB",
  "PCBA",
  "CTQ",
  "DC",
  "AC",
  "WL",
  "PL",
  "BOM",
  "OARC",
  "ISO",
  "DIN",
  "IEC",
  "EMI",
  "ESD",
  "SMT",
  "THT",
  "LED",
  "LCD",
  "USB",
  "RF",
  "NM",
  "MM",
  "IP",
  "QC",
  "QA",
  "SOP",
]);

const ACRONYM_RE = new RegExp(
  `\\b(?:${[...KEEP_ACRONYMS].sort((a, b) => b.length - a.length).join("|")})\\b`,
  "gi"
);
const CONNECTOR_RE = /\b[JPCX]\d{1,3}\b/gi;
const PART_GROUP_RE = /\b\d{3,}(?:\s+\d{2,}){1,4}\b/g;
const LIST_PREFIX_RE = /^(\s*(?:[a-z]\)|\d{1,3}\)|\([a-z]\)|[ivx]+\))\s+)(.*)$/i;

function capFirstAlpha(s) {
  const str = String(s || "");
  for (let i = 0; i < str.length; i += 1) {
    if (/[A-Za-z]/.test(str[i])) {
      return str.slice(0, i) + str[i].toUpperCase() + str.slice(i + 1);
    }
  }
  return str;
}

function capitalizeSentences(chunk) {
  const parts = String(chunk || "").split(/([.!?]\s+)/);
  let capNext = true;
  return parts
    .map((part) => {
      if (/^[.!?]\s+$/.test(part)) {
        capNext = true;
        return part;
      }
      if (capNext && part) {
        capNext = false;
        return capFirstAlpha(part);
      }
      return part;
    })
    .join("");
}

/**
 * Normalize mostly-uppercase instruction / description text to sentence case.
 * Leaves already-mixed text alone. Preserves acronyms, connectors, part-number groups.
 */
export function normalizeInstructionCase(text) {
  const raw = String(text || "");
  if (!raw) return "";
  const letters = [...raw].filter((c) => /[A-Za-z]/.test(c));
  if (!letters.length) return raw;
  const upperRatio = letters.filter((c) => c === c.toUpperCase()).length / letters.length;
  if (upperRatio < 0.65) return raw;

  const tokens = [];
  const protect = (match) => {
    tokens.push(match);
    return `\u0000${tokens.length - 1}\u0000`;
  };

  let out = raw;
  out = out.replace(PART_GROUP_RE, protect);
  out = out.replace(CONNECTOR_RE, protect);
  out = out.replace(ACRONYM_RE, protect);
  out = out.toLowerCase();

  out = out
    .split("\n")
    .map((line) => {
      const m = line.match(LIST_PREFIX_RE);
      if (m) return `${m[1].toLowerCase()}${capitalizeSentences(m[2])}`;
      return capitalizeSentences(line);
    })
    .join("\n");

  out = out.replace(
    /\bitem\s*(?:no\.?|nos\.?|number|#)?\s*-?\s*(\d{1,3})\b/gi,
    (_full, num) => `Item No. ${num}`
  );

  tokens.forEach((tok, i) => {
    let restored = tok;
    if (KEEP_ACRONYMS.has(String(tok || "").toUpperCase())) {
      restored = String(tok).toUpperCase();
    } else if (/^[JPCX]\d{1,3}$/i.test(tok || "")) {
      restored = tok[0].toUpperCase() + tok.slice(1);
    }
    out = out.split(`\u0000${i}\u0000`).join(restored);
  });
  return out;
}

const DOC_HEADER_RE =
  /Special\s+Assembly\s+Instructions\s+for\s+(?:\d{4}\s+\d{3}\s+\d{3}\s+\d{2}|\d{10,14})(?:\s+Page\s+\d+\s+of\s+\d+)?/gi;
const PAGE_OF_RE = /\bPage\s+\d+\s+of\s+\d+\b/gi;
const FROM_DRAWING_RE = /\s*\(\s*From\s+drawing\s*:\s*[^)]*\)\s*/gi;
const PARTS_APPENDIX_RE =
  /\s*Parts\s*:\s*.+?(?=(?:\s*(?:Torque|Connectors|Standard|Placement)\s*:)|$)/gi;
const PN_TOKEN_RE = /P\/?N\s*:\s*(?:\d{4}\s+\d{3}\s+\d{3}\s+\d{2}|\d{10,14})/gi;
// Imperatives only after a clause end — never mid-phrase (that cut part-number tails).
const ACTION_VERBS =
  "Carefully|Ensure|Further|Now|Engage|Refer|Place|Install|Assemble|Verify|Check|Peel|Stick|Paste|Apply|Mount|Secure|Fix|Bond|Glue|Torque|Tighten|Remove|Replace|Fit|Insert";
const ACTION_SPLIT_RE = new RegExp(
  `(?<=[.!?;)])\\s+(?=(?:${ACTION_VERBS})\\b)|(?<=\\d[Ll])\\s+(?=(?:Now|Further|Carefully|Ensure)\\b)`,
  "g"
);
const SENTENCE_SPLIT_RE = /(?<=[.!?])\s+(?=[A-Z(])/g;
const MULTI_SENTENCE_IN_LINE_RE = new RegExp(
  `(?<=[.!?])\\s+(?=[A-Z(])|(?<=[.!?;)])\\s+(?=(?:${ACTION_VERBS})\\b)`,
  "g"
);
/** Mid-paragraph bullet glyphs glued into one line (… Item 4. • Assemble …). */
const INLINE_BULLET_SPLIT_RE = /(?<!\n)\s*[•·●▪‣⁃]\s+/g;
const KEEP_PN_CONTEXT_RE = /(?:tool|engage|using|fastener|part\s*no|item)\s*$/i;

function stripChromePartNumbers(text) {
  return String(text || "").replace(PN_TOKEN_RE, (match, offset, full) => {
    const before = full.slice(Math.max(0, offset - 24), offset);
    if (KEEP_PN_CONTEXT_RE.test(before)) return match;
    return " ";
  });
}

// Revision-history table cells OCR often merges into NOTES beside them.
const REV_DATE_FRAG =
  String.raw`\d{1,2}\s*[./]\s*\d{1,2}(?:\s*[./]\s*\d{2,4}|\s*[./]\s*)`;
const REV_DELETED_PHRASE =
  String.raw`(?:NOTE\s+\d+\s*&\s*\d+\s+DELETED|(?:[A-Za-z]{1,4}(?:\s*[_\-.•]+\s*[A-Za-z0-9]{0,4}){0,5}\s+)?\d{1,2}\s+DELETED)(?:\s+\d+\s+one)?`;
const REV_BLEED_BLOCK = new RegExp(
  String.raw`(?:\s+|,|;)+(?:[-•*]\s*)?(?:${REV_DATE_FRAG}\s*)?(?:${REV_DELETED_PHRASE})`,
  "gi"
);
const REV_DATE_BEFORE_WORD = new RegExp(
  String.raw`\s+${REV_DATE_FRAG}(?:[\s•*.|-]*)(?=(?:indicated|shown|per|figure|as|in|on|to|the)\b)`,
  "gi"
);
const REV_DATE_TRAILING = new RegExp(String.raw`\s+${REV_DATE_FRAG}\s*$`, "im");
const REV_BULLET_ONLY = new RegExp(
  String.raw`^(?:[-•*]\s*)?(?:${REV_DATE_FRAG}\s*)?(?:${REV_DELETED_PHRASE})\s*$`,
  "i"
);
const REV_OCR_NOISE_BULLET = new RegExp(
  String.raw`^(?:[-•*]\s*)?(?:[A-Za-z]{1,3}(?:\s*[_\-.•]+\s*[A-Za-z0-9]{0,3}){1,6})\s*(?:\d{1,2}\s+)?(?:deleted|one)\b.*$`,
  "i"
);

/** Remove revision-table OCR bleed glued onto assembly instructions. */
export function stripRevisionTableBleed(text) {
  let s = String(text || "");
  if (!s) return "";
  s = s.replace(REV_BLEED_BLOCK, " ");
  s = s.replace(REV_DATE_BEFORE_WORD, " ");
  s = s.replace(REV_DATE_TRAILING, "");
  s = s.replace(
    new RegExp(String.raw`(?:\s+|,|;)+(?:${REV_DELETED_PHRASE})`, "gi"),
    " "
  );
  s = s.replace(/\s{2,}/g, " ").replace(/\s+([.,;:])/g, "$1");
  return s.replace(/^[\s;:|\n\t]+|[\s;:|\n\t]+$/g, "");
}

function isRevisionJunkBullet(body) {
  const b = String(body || "").trim();
  if (!b) return true;
  if (REV_BULLET_ONLY.test(b) || REV_OCR_NOISE_BULLET.test(b)) return true;
  if (/^\d+\s+deleted(?:\s+\d+\s+one)?$/i.test(b)) return true;
  return false;
}

function expandCrowdedBulletLines(lines) {
  const out = [];
  for (const ln of lines) {
    const body = String(ln || "")
      .replace(/^[-•*·●]\s+/, "")
      .trim();
    if (!body) continue;
    if (!MULTI_SENTENCE_IN_LINE_RE.test(body)) {
      MULTI_SENTENCE_IN_LINE_RE.lastIndex = 0;
      out.push(`• ${body}`);
      continue;
    }
    MULTI_SENTENCE_IN_LINE_RE.lastIndex = 0;
    for (const part of body.replace(MULTI_SENTENCE_IN_LINE_RE, "\n").split("\n")) {
      const p = part.replace(/\s+/g, " ").replace(/^[\s;:|]+|[\s;:|]+$/g, "");
      if (p) out.push(`• ${p}`);
    }
  }
  return out;
}

function toOperatorBullets(lines) {
  const deduped = [];
  for (const line of lines) {
    const cleaned = String(line || "").replace(/\s+/g, " ").replace(/^[\s;:|]+|[\s;:|]+$/g, "");
    if (!cleaned) continue;
    const key = cleaned.toLowerCase();
    if (deduped.length && deduped[deduped.length - 1].toLowerCase() === key) continue;
    deduped.push(cleaned);
  }
  if (!deduped.length) return "";

  // Rejoin orphaned "32) on the …" onto previous unclosed "(" line.
  const joined = [];
  for (const line of deduped) {
    if (
      joined.length &&
      /^\d{1,3}\)\s+\S/.test(line) &&
      (joined[joined.length - 1].match(/\(/g) || []).length >
        (joined[joined.length - 1].match(/\)/g) || []).length
    ) {
      joined[joined.length - 1] = `${joined[joined.length - 1]} ${line}`;
      continue;
    }
    joined.push(line);
  }

  const stepStart = new RegExp(
    `^(?:${ACTION_VERBS}|Open|Use|Follow|Torque)\\b`,
    "i"
  );
  // Always point-wise — one bullet per line for editor + OARC print.
  return joined
    .map((line) => {
      if (/^(?:->|→)\s/.test(line)) return line.startsWith("• ") ? line : `• ${line}`;
      const m = line.match(/^(?:([-•*])|(\d+[.)])|([a-z]\)))\s+(.*)$/i);
      if (m) {
        const rest = (m[4] || "").trim();
        // Digits like "32) on the face…" are broken paren tails — keep intact.
        if (m[2] && rest && !stepStart.test(rest)) {
          return line.startsWith("• ") ? line : `• ${line}`;
        }
        return rest ? `• ${rest}` : line;
      }
      return `• ${line}`;
    })
    .join("\n");
}

/**
 * Strip drawing-chrome junk and format as operator-friendly bullets.
 * Mirrors backend sanitize_operator_instruction for already-saved ops.
 */
export function sanitizeOperatorInstruction(text) {
  let s = String(text || "")
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n");
  if (!s.trim()) return "";
  s = s.replace(FROM_DRAWING_RE, " ");
  s = s.replace(PARTS_APPENDIX_RE, " ");
  s = s.replace(DOC_HEADER_RE, " ");
  s = s.replace(PAGE_OF_RE, " ");
  s = stripChromePartNumbers(s);
  s = stripRevisionTableBleed(s);
  // Break mid-line bullets onto their own lines before any other splits.
  s = s.replace(INLINE_BULLET_SPLIT_RE, "\n• ");
  s = s.replace(/[ \t]+/g, " ").replace(/ *\n */g, "\n").replace(/\n{3,}/g, "\n\n").trim();
  if (!s) return "";

  const rawLines = s.split("\n").map((ln) => ln.trim()).filter(Boolean);
  const bulletish = rawLines.filter((ln) => /^[-•*·●]/.test(ln)).length;
  if (rawLines.length >= 2 && bulletish >= Math.max(2, Math.floor(rawLines.length * 0.5))) {
    const cleaned = [];
    for (const ln of rawLines) {
      let body = ln.replace(/^[-•*·●]\s+/, "").trim();
      body = stripRevisionTableBleed(body);
      if (!body || /^P\/?N\s*:\s*[\d\s]+$/i.test(body) || isRevisionJunkBullet(body)) {
        continue;
      }
      cleaned.push(`• ${body}`);
    }
    return toOperatorBullets(expandCrowdedBulletLines(cleaned));
  }

  s = s.replace(/\s*(->|→)\s*/g, "\n$1 ");
  s = s.replace(ACTION_SPLIT_RE, "\n");
  s = s.replace(SENTENCE_SPLIT_RE, "\n");
  s = normalizeInstructionCase(s);

  const lines = [];
  for (const rawLine of s.split("\n")) {
    const line = rawLine.replace(/\s+/g, " ").replace(/^[\s;:|]+|[\s;:|]+$/g, "");
    if (!line) continue;
    if (/^P\/?N\s*:\s*[\d\s]+$/i.test(line)) continue;
    if (/^Page\s+\d+\s+of\s+\d+$/i.test(line)) continue;
    const body = line.replace(/^[-•*]\s+/, "").trim();
    if (isRevisionJunkBullet(body)) continue;
    // Rejoin "32) on the …" onto previous unclosed parenthesis
    if (lines.length && /^\d{1,3}\)\s+\S/.test(line)) {
      const prev = lines[lines.length - 1];
      if ((prev.match(/\(/g) || []).length > (prev.match(/\)/g) || []).length) {
        lines[lines.length - 1] = `${prev} ${line}`;
        continue;
      }
    }
    lines.push(line);
  }

  return toOperatorBullets(lines);
}
