declare const Deno: {
  env: { get(name: string): string | undefined };
  serve(handler: (request: Request) => Promise<Response>): void;
};

const ALLOWED_MODES = new Set(["scan", "global", "open", "close", "weekly"]);

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

export function createHandler(
  config: DispatcherConfig,
  githubFetch: typeof fetch = fetch,
): (request: Request) => Promise<Response> {
  const owner = config.owner ?? "kirandoddi1995-ux";
  const repository = config.repository ?? "Trading-Dashboard";
  const workflow = config.workflow ?? "scheduled-collector.yml";
  const ref = config.ref ?? "main";

  return async (request: Request): Promise<Response> => {
    if (request.method !== "POST") {
      return jsonResponse({ error: "METHOD_NOT_ALLOWED" }, 405);
    }

    if (!secretsMatch(request.headers.get("x-dispatch-secret"), config.sharedSecret)) {
      return jsonResponse({ error: "UNAUTHORIZED" }, 401);
    }

    let payload: DispatchRequest;
    try {
      payload = await request.json() as DispatchRequest;
    } catch {
      return jsonResponse({ error: "INVALID_JSON" }, 400);
    }

    if (typeof payload.mode !== "string" || !ALLOWED_MODES.has(payload.mode)) {
      return jsonResponse({ error: "INVALID_MODE" }, 400);
    }

    const endpoint =
      `https://api.github.com/repos/${owner}/${repository}/actions/workflows/${workflow}/dispatches`;
    const githubResponse = await githubFetch(endpoint, {
      method: "POST",
      headers: {
        accept: "application/vnd.github+json",
        authorization: `Bearer ${config.githubToken}`,
        "content-type": "application/json",
        "user-agent": "trading-dashboard-supabase-dispatcher",
        "x-github-api-version": "2026-03-10",
      },
      body: JSON.stringify({
        ref,
        inputs: {
          mode: payload.mode,
          apply_migrations: "false",
        },
      }),
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
        mode: payload.mode,
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
