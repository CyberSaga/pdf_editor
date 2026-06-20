# Gemini CLI Headless Diagnosis

## Symptom

Gemini CLI 0.46.0 hung for several minutes when invoked headlessly from the repository, even for a prompt requesting only `GEMINI_OK`.

## Evidence

- Provider API-key environment variables were absent.
- User settings selected `oauth-personal`.
- User settings configured a Revit MCP server.
- No orphaned Gemini or Node process remained after the bounded attempts.
- Supplying `--allowed-mcp-server-names __fusion_no_mcp__` reduced the run to about 27 seconds and exposed the underlying authentication error.
- The official npm registry reported 0.47.0 as the latest stable release; upgrading from 0.46.0 to 0.47.0 reduced the same failure to about five seconds.
- Version 0.47.0 still returned `IneligibleTierError` with reason `UNSUPPORTED_CLIENT`, and the service classified the cached login as `free-tier` / `Gemini Code Assist for individuals`.

## Root Cause

Two problems were stacked:

1. The globally configured Revit MCP server delayed headless startup and hid useful errors.
2. Google's service rejects the cached OAuth account as the discontinued free individual client. This is an account-entitlement response, not an executable, network, or prompt problem.

## Applied Correction

- Upgraded the official `@google/gemini-cli` package to 0.47.0.
- Established `--allowed-mcp-server-names __fusion_no_mcp__` as the minimal per-run isolation flag so fusion does not start unrelated MCP servers.

## Remaining User-Visible Authentication Step

The official installed documentation says Google AI Pro/Ultra subscription access requires signing in with the Google account associated with that subscription. Complete an interactive `/logout`, then sign in with the subscribed account. Credentials were not deleted or replaced automatically because account selection requires the user.

After sign-in, verify with:

```powershell
gemini --skip-trust --approval-mode plan `
  --allowed-mcp-server-names __fusion_no_mcp__ `
  --output-format json -p "Reply with exactly: GEMINI_OK"
```

The production fusion runner should retain the MCP isolation flag, classify `IneligibleTierError` as authentication/subscription failure, and enforce a process-tree timeout.
