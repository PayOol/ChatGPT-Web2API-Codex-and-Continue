# ChatGPT Web2API 0.4.0 — Codex integration

The 0.4.0 installer adds `chatgpt-web2api/auto` through OpenCodex's supported local management API. It leaves model selection to the user. It does not patch Codex, replace installed packages, change the default provider, add a native alias/combo, or configure tools, permissions, approval policy, global guidance, Fast mode or `codexToolMode`.

## Two installer targets

The [0.4.0 release](https://github.com/PayOol/ChatGPT-Web2API-Continue/releases/tag/v0.4.0) offers **Codex** or **Continue**. Codex defaults to `%LOCALAPPDATA%/Programs/Web2API-Codex`; Continue defaults to `%LOCALAPPDATA%/Programs/Web2API-Continue`. The target is recorded in `installation.json`, and repair keeps that target. Do not reuse one target's root for the other.

The Codex branch uses Codex's native tool surface and existing permissions. It does not install the Continue Local, Browser, Computer, Vision or Connected MCP servers, Hostinger MCP, Continue extension patches, or a universal set of app connections. The native application is reused or installed through its official Microsoft Store package; its own tools, plugins, authentication and updates remain under Codex's control. These are installation contracts, not a claim of completed live validation.

`installer/configure_codex.py` coordinates the full Codex installation and chooses one of two OpenCodex modes:

- **Existing:** use the selected existing OpenCodex state and an identity-verified running proxy. The installer supplies its pinned CLI locally but does not overwrite global packages, start/restart an external proxy, or substitute a managed service when the existing state is invalid.
- **Managed fallback:** when no existing OpenCodex state is found, initialize a separate instance under `<root>/opencodex` with its dependencies under `<root>/apps/npm`. Keep `clientIntegrations.codex` explicitly OFF, use explicit catalog-only synchronization, then journal and merge only the top-level `openai_base_url` and `model_catalog_json` TOML keys. Existing route/catalog keys are refused rather than replaced. Other native settings and tool permissions stay untouched. This full installer can start its own managed proxy; the provider helper below never starts one.

`installer/codex_provider.py` is independent of browser installation and login. It can also add Codex to an existing Continue bridge using that bridge's root and API port, such as 8080, without another browser or ChatGPT login. Such an add-on keeps Continue as the maintenance target. A full new Codex installation does prepare its own browser profile and needs the user's own ChatGPT login; running the provider helper itself never creates a Chrome session.

## Maintenance by target

Run `Doctor.cmd`, `Repair.cmd` and `Uninstall.cmd` from the root being maintained. For Codex, Doctor checks the installation and desktop package, plus bridge health and OpenCodex identity unless `-Offline` is requested. Repair resumes the Codex target. Uninstall detaches the owned provider and, for a managed proxy, removes only unchanged journalled route keys and stops that verified process. It preserves an external OpenCodex service and the native Codex application.

For Continue, Doctor checks its patches and five MCP catalogs, Repair reapplies its integration, and Uninstall restores unchanged owned entries; VS Code must be closed for repair/removal. Continue uninstall also invokes provider detach when an add-on journal exists. Both targets preserve personal browser data, histories, media, configuration, logs and backups. User edits, ownership conflicts or pending catalog removal stop program deletion. Neither Doctor nor a model appearing in a catalog proves a successful live tool call. See [VALIDATION.md](VALIDATION.md) for evidence recorded separately by the validation owner.

## Installer interface

```python
import os
from pathlib import Path
from installer.codex_provider import configure, detach

root = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Web2API-Codex"
command_prefix = ["ocx"]
# Managed installation alternative, using its already-installed local dependencies:
# command_prefix = [str(root / "apps/node/node.exe"),
#                   str(root / "apps/npm/node_modules/@bitkyc08/opencodex/bin/ocx.mjs")]

result = configure(
    root=root,
    command_prefix=command_prefix,
    api_port=8080,
    config_path=None,
)
# Later, using the same root and OpenCodex home:
# result = detach(root, command_prefix, config_path=None)
```

`config_path` selects **OpenCodex's existing `config.json`**, not Web2API's server config or Codex's TOML. Its parent becomes `OPENCODEX_HOME` for child commands. When omitted, resolution uses `OPENCODEX_HOME` then `~/.opencodex`. `CODEX_HOME` is inherited, or defaults to `~/.codex`. Set the same homes when launching the proxy and installer. The provider helper does not initialize a home; the full installer prepares the managed fallback before calling it. The lower-level `install(root, command_prefix, api_port=None, ...)` can read `port` from the root's server `config.json`, falling back to `installation.json`'s `api_port` when the server config is absent.

The return value includes:

```json
{
  "provider": "chatgpt-web2api",
  "model": "chatgpt-web2api/auto",
  "phase": "installed",
  "changed": true,
  "catalog_status": "synced",
  "catalog_degraded": false,
  "catalog_notices": [],
  "picker_visibility": "not_verified",
  "restart_performed": false,
  "native_config_unchanged": true
}
```

`catalog_status: "pending"` means registration/removal persisted but catalog convergence is not yet confirmed. `changed` describes provider/model creation or removal, not a retry of catalog convergence. Repeating a completed installation makes no API mutation. Exceptions are `IntegrationError`, `OwnershipConflict` and `NativeSettingsChanged`; their messages omit captured command output, response bodies and secrets. Runner/request injection is available for offline tests.

The standalone CLI accepts `install` or `detach`, `--root`, optional `--api-port` and `--opencodex-home`, then `--ocx-command` followed by the executable argument list. Exit code 0 means completed, 2 means catalog pending, and 1 means a handled error. Use Python UTF-8 mode on Windows (`$env:PYTHONUTF8='1'`); JSON state is UTF-8 without BOM. Arguments are passed as a list with `shell=False`.

## Exact registration

| Setting | Value |
| --- | --- |
| Provider ID | `chatgpt-web2api` |
| Adapter | `openai-chat` |
| Base URL | `http://127.0.0.1:<api_port>/codex/v1` |
| API key | literal placeholder `not-needed` |
| Upstream model | `auto` |
| Display name | `ChatGPT Web2API` |
| Input modalities | `text`, `image` |
| Model context window | `32768` tokens |
| Reasoning ladder | explicit empty `reasoningEfforts: []` |

The conservative context cap belongs only to this model (`modelContextWindows.auto` and custom-model `contextWindow`). It avoids inheriting a large native model window; the bridge independently enforces its serialized prompt character budget. The web UI chooses reasoning automatically, so no Codex effort ladder/default is advertised. Provider `noReasoningModels: ["auto"]` suppresses an outgoing effort override. No native tool-mode or hosted-tool override is sent.

The adapter targets `/codex/v1/chat/completions`. Static `models: ["auto"]`, `selectedModels: ["auto"]`, and `liveModels: false` keep registration deterministic. Web2API's `/codex/v1/models` may still serve `auto` to other consumers. Only this loopback provider gets `allowPrivateNetwork: true`.

## Supported commands and catalog safety

Contracts were inspected in installed OpenCodex **2.59.0**, particularly `src/cli/provider.ts`, `src/cli/config-command.ts`, `src/cli/dispatch.ts`, `src/server/management/provider-routes.ts`, `model-routes.ts`, `src/codex/sync.ts`, and `src/lib/admin-secrets.ts`.

1. `ocx config show --json --source` validates the selected existing configuration. Default/fallback configuration and connected-client mode are refused. No `--force` or set-default command is used.
2. `POST /api/providers` creates the single provider and updates the live routing configuration. `POST /api/custom-models` declares its metadata. These routes converge the catalog without running the Codex TOML injector. The provider CLI alone does not provide this same live update contract.
3. A `catalogRefresh.status == "committed"` response counts as a successful implicit refresh when it is not degraded, or when the owned on-disk model row is independently verified despite degradation elsewhere (verified absence for detach). Thus unrelated provider/network fallbacks do not block a correctly registered Web2API model. The journal and result retain `catalog_degraded` and the deduplicated, allowlisted `catalog_notices` codes (`fallback`, `provider-network`, `provider-auth`); no raw error text is retained. `synced` describes this integration, not the health of every provider. When integration is ON, a pending installation retries through **`PUT /api/custom-models/{owned_id}` with `{}`**, after rechecking ownership. It never calls `/api/sync`, which runs the full native-settings injector.
4. When `clientIntegrations.codex` is explicitly **false**, implicit convergence is skipped. The explicit **`ocx sync` CLI** has a distinct supported `catalogEvenWhenNotInjected` path that writes only catalog/cache. It is invoked only after rechecking this OFF flag. Success additionally requires the owned catalog row to have the expected name, text/image modalities and empty reasoning ladder (or to be absent after detach). The integration toggle remains OFF; the calling installer owns any minimal TOML route/catalog merge.
5. Normal detach uses `DELETE /api/providers?name=chatgpt-web2api`, which also removes its custom models. If that catalog convergence remains pending with integration ON, no full-sync fallback is attempted. A later call may observe that an independent refresh removed the row. An unchanged owned orphan custom model can be removed through its own DELETE route.

Before each operation, native `config.toml` bytes are captured **in memory** for the selected and default Codex homes and compared on exit. Existing unrelated catalog slugs are also checked for loss. A change raises `NativeSettingsChanged` and retains the ownership journal; there is no unsafe restoration of the whole file. `native_config_unchanged: true` is returned only when this guard passes. Preserve an external baseline for a real deployment as well: this detects changes during the operation, not prior drift, and cannot identify which concurrent writer caused them.

The management client authenticates the loopback `/healthz` response against the selected home's `runtime-port.json` attestation before sending the existing admin token. It uses `OPENCODEX_ADMIN_AUTH_TOKEN` or `admin-api-token`, never creates a credential, never stores it in the journal, bypasses HTTP proxy environment variables, and refuses redirects. It requires an already-running local proxy; it does not start or restart it.

## Ownership, recovery and limits

The only installer state is `<root>/codex-provider-state.json`, with a same-root lock during operations. It records the desired provider and the exact provider/model entries successfully created, including generated registration/model IDs. Public executable arguments are stored as `command`, so uninstall can call `detach(root, state["command"], Path(state["scope"]["opencodex_home"]) / "config.json")` with the recorded `CODEX_HOME`. Only an ocx executable or node plus `ocx.mjs` is accepted; command options/credentials are rejected. It does not save other providers, their keys, native config, catalog contents or a global configuration backup. Raw OpenCodex config is read privately because redacted API/CLI output cannot detect a later credential edit.

A preexisting provider, even an identical one, is a collision. So are orphan custom models, account namespaces, combos and selectors occupying that namespace. Different installer roots cannot silently adopt each other's registration. A changed port requires detach first. Detach refuses changed credentials, metadata, selection or registration identity, added custom models, default-provider use and dependent settings. Unrelated changes survive because no whole-file restore is performed. OpenCodex's changing discovery `status`/`modelCount` fields are excluded from identity; its registration ID is still checked.

Successful steps are journalled individually. A model-add failure after provider creation can be retried or detached. If a request persisted but its response was lost, ownership cannot be proven: the entry is retained and automatic adoption/deletion is refused. Inspect that state manually before resolving the journal. A lock left by an interrupted process likewise requires inspection before removal.

OpenCodex's provider POST and DELETE do **not** provide conditional creation/deletion or an ETag/CAS contract. The installer rechecks immediately before mutation, but cannot atomically exclude a simultaneous GUI edit or another installer using a different root. Run registration/detach without concurrent edits to these entries. No package patch or unsupported persistence writer is used to bypass this limitation.

Catalog refresh may update OpenCodex-generated metadata for existing rows; the guard checks row preservation, not byte equality of the generated catalog. The existing proxy must have been launched with the same relevant home selection. An already-running Codex app-server may retain its in-memory model list even after the disk catalog changes. This module never restarts Codex and always returns `picker_visibility: "not_verified"`. Official Codex configuration documentation describes `model_catalog_json` as a startup-loaded override: [sample configuration](https://learn.chatgpt.com/docs/config-file/config-sample).

## Validation boundary

`tests/test_codex_provider.py` uses mocked CLI/API calls and temporary homes. It covers coexistence, exact metadata, no native-tool overrides, idempotency, collisions, user edits, detach, interrupted operations, pending convergence, integration-OFF explicit sync, UTF-8/argument handling, runtime attestation and native-config/catalog guards. It explicitly forbids real subprocess and network access. These tests establish installer behavior, not successful ChatGPT inference, tool execution, image upload or live Codex picker visibility. Verify those separately after authorized real registration.
