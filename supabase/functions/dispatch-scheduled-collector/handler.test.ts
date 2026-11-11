import assert from "node:assert/strict";
import test from "node:test";
import { createHandler, FIXED_TARGETS } from "./index.ts";

const endpoint = "https://example.test/dispatch";

test("rejects literal JSON null with 400 before contacting GitHub", async () => {
  let calls = 0;
  const handler = createHandler(
    { githubToken: "github-secret", sharedSecret: "shared-test-secret" },
    async () => {
      calls += 1;
      return new Response(null, { status: 204 });
    },
  );
  const incoming = request(null);
  assert.equal(await incoming.clone().text(), "null");
  const response = await handler(incoming);
  assert.equal(response.status, 400);
  assert.deepEqual(await response.json(), { error: "INVALID_BODY" });
  assert.equal(calls, 0);
});

function request(body: unknown, secret = "shared-test-secret"): Request {
  return new Request(endpoint, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-dispatch-secret": secret,
    },
    body: JSON.stringify(body),
  });
}

test("dispatches only the requested collector mode without exposing the token", async () => {
  let capturedUrl = "";
  let capturedInit: RequestInit | undefined;
  const githubFetch: typeof fetch = async (url, init) => {
    capturedUrl = String(url);
    capturedInit = init;
    return new Response(JSON.stringify({ workflow_run_id: 42, html_url: "https://github.test/run/42" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  const handler = createHandler(
    { githubToken: "github-secret", sharedSecret: "shared-test-secret" },
    githubFetch,
  );

  const response = await handler(request({ mode: "scan", schedule: "equity-scan-1007-ist" }));
  const responseBody = await response.json();
  const githubBody = JSON.parse(String(capturedInit?.body));

  assert.equal(response.status, 202);
  assert.match(capturedUrl, /scheduled-collector\.yml\/dispatches$/);
  assert.equal(new Headers(capturedInit?.headers).get("authorization"), "Bearer github-secret");
  assert.deepEqual(githubBody, {
    ref: "main",
    inputs: { mode: "scan", apply_migrations: "false" },
  });
  assert.equal(responseBody.workflow_run_id, 42);
  assert.doesNotMatch(JSON.stringify(responseBody), /github-secret/);
});

test("rejects an invalid caller secret before contacting GitHub", async () => {
  let calls = 0;
  const handler = createHandler(
    { githubToken: "github-secret", sharedSecret: "shared-test-secret" },
    async () => {
      calls += 1;
      return new Response(null, { status: 204 });
    },
  );

  const response = await handler(request({ mode: "open" }, "wrong-secret"));

  assert.equal(response.status, 401);
  assert.equal(calls, 0);
});

test("rejects unknown modes before contacting GitHub", async () => {
  let calls = 0;
  const handler = createHandler(
    { githubToken: "github-secret", sharedSecret: "shared-test-secret" },
    async () => {
      calls += 1;
      return new Response(null, { status: 204 });
    },
  );

  const response = await handler(request({ mode: "all" }));

  assert.equal(response.status, 400);
  assert.equal(calls, 0);
});

test("reports GitHub rejection without retrying", async () => {
  let calls = 0;
  const handler = createHandler(
    { githubToken: "github-secret", sharedSecret: "shared-test-secret" },
    async () => {
      calls += 1;
      return new Response("bad credentials", { status: 401 });
    },
  );

  const response = await handler(request({ mode: "close" }));
  const body = await response.json();

  assert.equal(response.status, 502);
  assert.equal(body.github_status, 401);
  assert.equal(calls, 1);
});

/** A fake GitHub fetch that records every dispatch call it receives. */
function capture(): { calls: { url: string; body: Record<string, unknown> }[]; githubFetch: typeof fetch } {
  const calls: { url: string; body: Record<string, unknown> }[] = [];
  /** Record each GitHub dispatch call and answer 204 like GitHub does. */
  const githubFetch: typeof fetch = async (url, init) => {
    calls.push({ url: String(url), body: JSON.parse(String(init?.body)) });
    return new Response(null, { status: 204 });
  };
  return { calls, githubFetch };
}

test("archive-nightly target dispatches drive-archive.yml with only the fixed nightly input", async () => {
  const { calls, githubFetch } = capture();
  const handler = createHandler({ githubToken: "github-secret", sharedSecret: "shared-test-secret" }, githubFetch);

  // Extra caller fields can never widen the run: inputs come only from the fixed target.
  const response = await handler(request({
    target: "archive-nightly", schedule: "01:45 IST daily",
    inputs: { mode: "prune-preserved", table: "evidence_ledger_events" }, ref: "evil",
  }));
  const body = await response.json();

  assert.equal(response.status, 202);
  assert.equal(calls.length, 1);
  assert.match(calls[0].url, /\/actions\/workflows\/drive-archive\.yml\/dispatches$/);
  assert.deepEqual(calls[0].body, { ref: "main", inputs: { mode: "nightly" } });
  assert.equal(body.target, "archive-nightly");
  assert.equal(body.mode, undefined);
  assert.equal(body.schedule, "01:45 IST daily");
});

const REJECTED_TARGETS: Record<string, unknown>[] = [
  { target: "archive-delete" },
  { target: "__proto__" },
  { target: "toString" },
  { target: 7 },
  { target: null },
  { target: ["archive-nightly"] },
  { target: { "archive-nightly": true } },
  { target: "archive-nightly", mode: "scan" },
];

/** Assert one body is refused with 400 INVALID_TARGET and GitHub is never called. */
async function assertTargetRejected(payload: Record<string, unknown>): Promise<void> {
  const { calls, githubFetch } = capture();
  const handler = createHandler({ githubToken: "github-secret", sharedSecret: "shared-test-secret" }, githubFetch);
  const response = await handler(request(payload));
  assert.equal(response.status, 400, JSON.stringify(payload));
  assert.deepEqual(await response.json(), { error: "INVALID_TARGET" });
  assert.equal(calls.length, 0);
}

test("rejects unknown, inherited, non-string or mixed targets before contacting GitHub", async () => {
  await Promise.all(REJECTED_TARGETS.map(assertTargetRejected));
});

test("collector requests are unchanged by the archive target", async () => {
  const { calls, githubFetch } = capture();
  const handler = createHandler({ githubToken: "github-secret", sharedSecret: "shared-test-secret" }, githubFetch);
  const response = await handler(request({ mode: "scan", schedule: "10:07 IST Monday-Friday" }));
  assert.equal(response.status, 202);
  assert.match(calls[0].url, /\/actions\/workflows\/scheduled-collector\.yml\/dispatches$/);
  assert.deepEqual(calls[0].body, { ref: "main", inputs: { mode: "scan", apply_migrations: "false" } });
  assert.equal((await response.json()).mode, "scan");
});

test("an archive target with a wrong caller secret is refused before contacting GitHub", async () => {
  const { calls, githubFetch } = capture();
  const handler = createHandler({ githubToken: "github-secret", sharedSecret: "shared-test-secret" }, githubFetch);
  const response = await handler(request({ target: "archive-nightly" }, "wrong-secret"));
  assert.equal(response.status, 401);
  assert.equal(calls.length, 0);
});

test("the only fixed target is archive-nightly = drive-archive.yml mode=nightly, frozen", () => {
  assert.deepEqual(Object.keys(FIXED_TARGETS), ["archive-nightly"]);
  assert.deepEqual(FIXED_TARGETS["archive-nightly"], { workflow: "drive-archive.yml", inputs: { mode: "nightly" } });
  assert.ok(Object.isFrozen(FIXED_TARGETS));
  assert.ok(Object.isFrozen(FIXED_TARGETS["archive-nightly"]));
  assert.ok(Object.isFrozen(FIXED_TARGETS["archive-nightly"].inputs));
});
