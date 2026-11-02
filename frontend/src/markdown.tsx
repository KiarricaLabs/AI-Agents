import type { ReactNode } from "react";

/**
 * Minimal, dependency-free Markdown renderer for agent output.
 *
 * Safety model: this renderer NEVER uses `dangerouslySetInnerHTML`. Every
 * fragment of the (untrusted) agent response is emitted as either a plain text
 * node (which React escapes) or an explicitly constructed element. Any raw
 * HTML, `<script>`, or inline event handler in the source therefore stays inert
 * — it is rendered as literal text, never executed.
 */

// Only allow link protocols that are safe to open. `javascript:` and `data:`
// are blocked to prevent script/data-URL execution.
function safeHref(raw: string): string {
  const url = raw.trim();
  if (/^(https?:|mailto:|tel:)/i.test(url)) return url;
  if (/^javascript:/i.test(url) || /^data:/i.test(url) || /^vbscript:/i.test(url)) return "#";
  if (url.startsWith("/") || url.startsWith("#") || url.startsWith("./") || url.startsWith("../")) {
    return url;
  }
  // Unknown scheme (e.g. "foo:...") -> treat as inert relative text.
  return "#";
}

const INLINE_RE =
  /(\*\*([^*]+)\*\*|\*([^*\s][^*]*)\*|`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)\))/g;

/** Convert inline markdown (bold, italic, code, links) into safe React nodes. */
export function renderInline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let key = 0;
  let m: RegExpExecArray | null;
  INLINE_RE.lastIndex = 0;
  while ((m = INLINE_RE.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[2] !== undefined) {
      out.push(<strong key={key++}>{m[2]}</strong>);
    } else if (m[3] !== undefined) {
      out.push(<em key={key++}>{m[3]}</em>);
    } else if (m[4] !== undefined) {
      out.push(<code key={key++} className="md-inline-code">{m[4]}</code>);
    } else if (m[5] !== undefined) {
      out.push(
        <a key={key++} href={safeHref(m[6])} target="_blank" rel="noopener noreferrer">
          {m[5]}
        </a>
      );
    }
    last = INLINE_RE.lastIndex;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function splitRow(line: string): string[] {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|")) s = s.slice(0, -1);
  return s.split("|").map((c) => c.trim());
}

function isTableSeparator(line: string): boolean {
  const s = line.trim();
  if (!s.includes("|") || !s.includes("-")) return false;
  const cells = splitRow(s);
  return cells.length > 0 && cells.every((c) => /^:?-+:?$/.test(c));
}

function alignOf(cell: string): "left" | "center" | "right" {
  const c = cell.trim();
  if (c.startsWith(":") && c.endsWith(":")) return "center";
  if (c.startsWith(":")) return "left";
  if (c.endsWith(":")) return "right";
  return "left";
}

function isBlockStart(line: string): boolean {
  const t = line.trim();
  if (t === "") return true;
  if (/^```/.test(t)) return true;
  if (/^#{1,6}\s/.test(t)) return true;
  if (/^>\s?/.test(t)) return true;
  if (/^([-*+]|\d+\.)\s/.test(t)) return true;
  return false;
}

/** Render a Markdown string to safe React nodes (block-level). */
export function Markdown({ source }: { source: string }): ReactNode {
  const lines = (source ?? "").replace(/\r\n?/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (line.trim() === "") {
      i++;
      continue;
    }

    // Fenced code block
    const fence = /^```([^\s`]*)\s*$/.exec(line);
    if (fence) {
      const lang = (fence[1] || "").trim();
      const code: string[] = [];
      i++;
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) {
        code.push(lines[i]);
        i++;
      }
      if (i < lines.length) i++; // consume closing fence
      blocks.push(
        <div key={key++} className="md-codeblock-wrap">
          {lang ? <div className="md-codeblock-lang">{lang}</div> : null}
          <pre className="md-pre">
            <code>{code.join("\n")}</code>
          </pre>
        </div>
      );
      continue;
    }

    // Heading
    const heading = /^(#{1,6})\s+(.*?)\s*$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      const text = heading[2];
      const Tag = (`h${level}` as unknown) as "h1" | "h2" | "h3" | "h4" | "h5" | "h6";
      blocks.push(<Tag key={key++}>{renderInline(text)}</Tag>);
      i++;
      continue;
    }

    // Blockquote (consecutive `>` lines)
    if (/^>\s?/.test(line)) {
      const quoteLines: string[] = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) {
        quoteLines.push(lines[i].replace(/^>\s?/, ""));
        i++;
      }
      blocks.push(
        <blockquote key={key++} className="md-quote">
          {quoteLines.map((ql, idx) => (
            <p key={idx} className="md-quote-p">{renderInline(ql)}</p>
          ))}
        </blockquote>
      );
      continue;
    }

    // GFM table: header line followed by a `| --- |` separator
    if (line.includes("|") && i + 1 < lines.length && isTableSeparator(lines[i + 1])) {
      const headers = splitRow(line);
      const aligns = splitRow(lines[i + 1]).map(alignOf);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim() !== "" && lines[i].includes("|")) {
        rows.push(splitRow(lines[i]));
        i++;
      }
      blocks.push(
        <div key={key++} className="md-table-scroll">
          <table className="md-table">
            <thead>
              <tr>
                {headers.map((h, idx) => (
                  <th key={idx} style={{ textAlign: aligns[idx] ?? "left" }}>
                    {renderInline(h)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, r) => (
                <tr key={r}>
                  {row.map((cell, idx) => (
                    <td key={idx} style={{ textAlign: aligns[idx] ?? "left" }}>
                      {renderInline(cell)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      continue;
    }

    // List item
    const listItem = /^([-*+]|\d+\.)\s+(.*)$/.exec(line);
    if (listItem) {
      const ordered = /^\d+\./.test(listItem[1]);
      const items: string[] = [];
      while (i < lines.length) {
        const lm = /^([-*+]|\d+\.)\s+(.*)$/.exec(lines[i]);
        if (!lm) break;
        items.push(lm[2]);
        i++;
      }
      const children = items.map((it, idx) => <li key={idx}>{renderInline(it)}</li>);
      blocks.push(
        ordered ? (
          <ol key={key++} className="md-ol">{children}</ol>
        ) : (
          <ul key={key++} className="md-ul">{children}</ul>
        )
      );
      continue;
    }

    // Paragraph: accumulate until blank line or next block.
    const paraLines: string[] = [line];
    i++;
    while (i < lines.length && lines[i].trim() !== "" && !isBlockStart(lines[i])) {
      paraLines.push(lines[i]);
      i++;
    }
    blocks.push(
      <p key={key++} className="md-p">{renderInline(paraLines.join(" "))}</p>
    );
  }

  return <div className="markdown">{blocks}</div>;
}

export default Markdown;
