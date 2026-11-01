import { diffLines } from "./diff";

test("diffLines detects added and removed lines", () => {
  const r = diffLines("hello\nworld", "hello\nworld\nnew");
  expect(r.added).toContain("new");
  expect(r.removed).toEqual([]);
});