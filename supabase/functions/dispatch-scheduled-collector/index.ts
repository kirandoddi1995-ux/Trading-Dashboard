declare const Deno: {
  env: { get(name: string): string | undefined };
  serve(handler: (request: Request) => Promise<Response>): void;
};

const ALLOWED_MODES = new Set(["scan", "global", "open", "close", "weekly"]);

type FixedTarget = Readonly<{ workflow: string; inputs: Readonly<Record<string, string>> }>;

// Fixed, server-side targets other than the collector. The caller picks a name;
// the workflow and every input are decided here, never taken from the request.
// "archive-nightly" = drive-archive.yml mode=nightly: the restore-proven nightly
// retention run, still gated in the workflow by ARCHIVE_ENABLED and
// ARCHIVE_NIGHTLY_DELETE. It can never request preview/export/delete/prune inputs.
// Frozen and exported so the tests pin the exact set of targets.
export const FIXED_TARGETS: Readonly<Record<string, FixedTarget>> = Object.freeze({
  "archive-nightly": Object.freeze({ workflow: "drive-archive.yml", inputs: Object.freeze({ mode: "nightly" }) }),
});

export type DispatcherConfig = {
  githubToken: string;
  sharedSecret: string;
  owner?: string;
  repository?: string;
  workflow?: string;
  ref?: string;
};

type DispatchRequest = {
  mode?: unknown;
  target?: unknown;
  schedule?: unknown;
};

function jsonResponse(body: Record<string, unknown>, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function secretsMatch(received: string | null, expected: string): boolean {
  if (!received || !expected) return false;

  const encoder = new TextEncoder();
  const left = encoder.encode(received);
  const right = encoder.encode(expected);
  if (left.length !== right.length) return false;

  let difference = 0;
  for (let index = 0; index < left.length; index += 1) {
    difference |= left[index] ^ right[index];
  }
  return difference === 0;
}

type ResolvedDispatch =
  | { error: string }
  | { workflow: string; inputs: Record<string, string>; dispatched: Record<string, unknown> };

/**
 * Map a validated request body to the workflow, inputs and echo fields to dispatch.
 * A `target` picks one FIXED_TARGETS entry (and must come without `mode`); otherwise
 * `mode` must be an allowed collector mode. Nothing else from the body is used.
 */
function resolveDispatch(payload: DispatchRequest, collectorWorkflow: string): ResolvedDispatch {
  if (payload.target !== undefined) {
    const fixed = typeof payload.target === "string" && Object.hasOwn(FIXED_TARGETS, payload.target)
      ? FIXED_TARGETS[payload.target]
      : undefined;
    if (!fixed || payload.mode !== undefined) return { error: "INVALID_TARGET" };
    return { workflow: fixed.workflow, inputs: { ...fixed.inputs }, dispatched: { target: payload.target } };
  }
  if (typeof payload.mode !== "string" || !ALLOWED_MODES.has(payload.mode)) {
    return { error: "INVALID_MODE" };
  }
  return {
    workflow: collectorWorkflow,
    inputs: { mode: payload.mode, apply_migrations: "false" },
    dispatched: { mode: payload.mode },
  };
}

/**
 * Build the Edge Function handler: authenticate the Cron caller with the shared
 * secret, resolve the request to one allowlisted workflow dispatch, call GitHub
 * with the token (never echoed), and report the outcome as JSON.
 */
export function createHandler(
  config: DispatcherConfig,
  githubFetch: typeof fetch = fetch,
): (request: Request) => Promise<Response> {
  const owner = config.owner ?? "kirandoddi1995-ux";
  const repository = config.repository ?? "Trading-Dashboard";
  const workflow = config.workflow ?? "scheduled-collector.yml";
  const ref = config.ref ?? "main";

  /**
   * Handle one Cron request: method, then caller secret, then body, then one
   * allowlisted dispatch. Every refusal happens before GitHub is contacted.
   */
  return async (request: Request): Promise<Response> => {
    if (request.method !== "POST") {
      return jsonResponse({ error: "METHOD_NOT_ALLOWED" }, 405);
    }

    if (!secretsMatch(request.headers.get("x-dispatch-secret"), config.sharedSecret)) {
      return jsonResponse({ error: "UNAUTHORIZED" }, 401);
    }

    let payload: DispatchRequest | null;
    try {
      payload = await request.json() as DispatchRequest | null;
    } catch {
      return jsonResponse({ error: "INVALID_JSON" }, 400);
    }

    if (payload === null) {
      return jsonResponse({ error: "INVALID_BODY" }, 400);
    }

    const resolved = resolveDispatch(payload, workflow);
    if ("error" in resolved) {
      return jsonResponse({ error: resolved.error }, 400);
    }
    const { inputs, dispatched } = resolved;

    const endpoint =
      `https://api.github.com/repos/${owner}/${repository}/actions/workflows/${resolved.workflow}/dispatches`;
    const githubResponse = await githubFetch(endpoint, {
      method: "POST",
      headers: {
        accept: "application/vnd.github+json",
        authorization: `Bearer ${config.githubToken}`,
        "content-type": "application/json",
        "user-agent": "trading-dashboard-supabase-dispatcher",
        "x-github-api-version": "2026-03-10",
      },
      body: JSON.stringify({ ref, inputs }),
    });

    if (githubResponse.status !== 200 && githubResponse.status !== 204) {
      const githubMessage = (await githubResponse.text()).slice(0, 500);
      return jsonResponse(
        {
          error: "GITHUB_DISPATCH_REJECTED",
          github_status: githubResponse.status,
          github_message: githubMessage,
        },
        502,
      );
    }

    let run: Record<string, unknown> = {};
    if (githubResponse.status === 200) {
      try {
        run = await githubResponse.json() as Record<string, unknown>;
      } catch {
        // A successful dispatch may legitimately return no response body.
      }
    }

    return jsonResponse(
      {
        status: "DISPATCHED",
        ...dispatched,
        schedule: typeof payload.schedule === "string" ? payload.schedule : null,
        workflow_run_id: run.workflow_run_id ?? null,
        html_url: run.html_url ?? null,
      },
      202,
    );
  };
}

if (typeof Deno !== "undefined") {
  const githubToken = Deno.env.get("GITHUB_ACTIONS_TOKEN") ?? "";
  const sharedSecret = Deno.env.get("DISPATCH_SHARED_SECRET") ?? "";

  if (!githubToken || !sharedSecret) {
    throw new Error("Required dispatcher secrets are not configured");
  }

  Deno.serve(createHandler({ githubToken, sharedSecret }));
}
