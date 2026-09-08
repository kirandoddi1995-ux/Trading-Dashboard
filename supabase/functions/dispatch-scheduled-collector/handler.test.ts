import assert from "node:assert/strict";
import test from "node:test";
import { createHandler } from "./index.ts";

const endpoint = "https://example.test/dispatch";

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
