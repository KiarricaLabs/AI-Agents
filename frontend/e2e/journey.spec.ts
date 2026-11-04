import { test, expect } from "@playwright/test";
import { API } from "./env";

test("full workflow journey via backend", async ({ request }) => {
  // workspace
  const w = await request.post(`${API}/workspaces`, { data: { name: "J-W" } });
  expect(w.status()).toBe(200);
  const wid = (await w.json()).id;

  // project
  const p = await request.post(`${API}/workspaces/projects`, { data: { workspace_id: wid, name: "J-P" } });
  const pid = (await p.json()).id;

  // goal
  const g = await request.post(`${API}/workspaces/goals`, { data: { project_id: pid, title: "J-G", priority: 1 } });
  const gid = (await g.json()).id;

  // assignment
  const a = await request.post(`${API}/workspaces/assignments`, { data: { goal_id: gid, agent_id: "tutor" } });
  expect(a.status()).toBe(200);

  // deliverable
  const d = await request.post(`${API}/workspaces/deliverables`, { data: { project_id: pid, title: "J-D" } });
  const did = (await d.json()).id;

  // version 1 + approve
  const v1 = await request.post(`${API}/workspaces/deliverables/${did}/versions`, { data: { content: "hello world" } });
  const v1id = (await v1.json()).id;
  await request.post(`${API}/workspaces/versions/${v1id}/approve`);
  const v1list = await request.get(`${API}/workspaces/deliverables/${did}/versions`);
  const v1status = (await v1list.json()).items[0].status;
  expect(v1status).toBe("approved");

  // revision -> version 2 (reject then new version)
  const v2 = await request.post(`${API}/workspaces/deliverables/${did}/versions`, { data: { content: "hello world v2" } });
  const v2id = (await v2.json()).id;
  await request.post(`${API}/workspaces/versions/${v2id}/reject`, { data: { reason: "needs more" } });
  const v2list = await request.get(`${API}/workspaces/deliverables/${did}/versions`);
  const items = (await v2list.json()).items;
  expect(items.length).toBe(2);
  expect(items[0].status).toBe("approved");
  expect(items[1].status).toBe("rejected");

  // episode
  const ep = await request.post(`${API}/episodes`).catch(() => null); // no create endpoint; verify list
  const elist = await request.get(`${API}/episodes`);
  expect(elist.status()).toBe(200);
});