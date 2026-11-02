// Presentation-only text helpers. Keep technical DB values from leaking into
// the normal UI without fabricating meaning that does not exist in the code.

// Human label for a stored status value. Unknown values are capitalized as-is
// rather than guessed. Keep the raw value available for the badge CSS class.
export function statusLabel(raw?: string | null): string {
  const map: Record<string, string> = {
    active: "Active",
    open: "Open",
    in_progress: "In progress",
    queued: "Queued",
    draft: "Draft",
    pending: "Awaiting review",
    approved: "Approved",
    rejected: "Needs revision",
    running: "Running",
    done: "Done",
    cancelled: "Cancelled",
  };
  if (!raw) return "—";
  if (map[raw]) return map[raw];
  return raw.charAt(0).toUpperCase() + raw.slice(1);
}

// Priority is a free integer in the schema (default 0), sorted descending
// (higher = more important). There is no documented Normal/High/Urgent scale in
// the code, so we do NOT invent one — we only render the numeric value where a
// detail view genuinely needs it and keep it out of the compact list rows.
export function priorityText(priority?: number | null): string {
  return (priority ?? 0).toString();
}

// Humanize a slug/database identifier only where there is no display_name.
export function humanize(name: string): string {
  return name
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}
