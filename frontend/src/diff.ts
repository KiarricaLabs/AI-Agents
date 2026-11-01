export function diffLines(a: string, b: string): { added: string[]; removed: string[]; changed: string[] } {
  const al = a.split("\n");
  const bl = b.split("\n");
  const added = bl.filter((l) => !al.includes(l));
  const removed = al.filter((l) => !bl.includes(l));
  const changed = added.length || removed.length ? added.concat(removed).map((l) => `~ ${l}`) : [];
  return { added, removed, changed };
}