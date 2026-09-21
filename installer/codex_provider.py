"""Add one reversible OpenCodex provider using its local management API.

No Codex config, catalog, executable, or installed package is edited here. OpenCodex
2.59 owns persistence, live routing and catalog convergence. See codex-integration.md.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hmac
import json
import os
import re
import secrets
import subprocess
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

PROVIDER = "chatgpt-web2api"
MODEL = "auto"
DISPLAY_NAME = "ChatGPT Web2API"
CONTEXT_WINDOW = 32768
STATE_FILE = "codex-provider-state.json"
PRODUCT = "Web2API-Codex-provider"


class IntegrationError(RuntimeError):
    """An intentionally secret-free operator message."""


class OwnershipConflict(IntegrationError):
    """An existing or edited entry must be left to its owner."""


class NativeSettingsChanged(IntegrationError):
    """A concurrent writer or unsupported OpenCodex behavior changed native settings."""


class CoexistenceChanged(IntegrationError):
    """Unowned providers or protected routing changed during this operation."""


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (OSError, ValueError):
        raise IntegrationError("A required JSON object is missing or invalid.") from None


def _write(path: Path, value: dict) -> None:
    # Only our journal is ever written. Never snapshot/restore another application's file.
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


@contextmanager
def _locked(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    path = root / (STATE_FILE + ".lock")
    try:
        handle = path.open("x", encoding="utf-8")
    except FileExistsError:
        raise IntegrationError("Another installer owns the journal lock; inspect it before retrying.") from None
    try:
        with handle:
            handle.write(str(os.getpid()))
            handle.flush()
            yield
    finally:
        path.unlink()


def _port(value) -> int:
    if type(value) is not int or not 1 <= value <= 65535:
        raise IntegrationError("api_port must be an integer between 1 and 65535.")
    return value


def _api_port(root: Path, value: int | None) -> int:
    if value is not None:
        return _port(value)
    if (root / "config.json").exists():
        return _port(_read(root / "config.json").get("port"))
    return _port(_read(root / "installation.json").get("api_port"))


def provider_entry(api_port: int) -> dict:
    return {
        "adapter": "openai-chat",
        "baseUrl": f"http://127.0.0.1:{_port(api_port)}/codex/v1",
        "apiKey": "not-needed",
        "defaultModel": MODEL,
        "models": [MODEL],
        "selectedModels": [MODEL],
        "liveModels": False,
        "allowPrivateNetwork": True,
        "modelInputModalities": {MODEL: ["text", "image"]},
        "modelContextWindows": {MODEL: CONTEXT_WINDOW},
        "noReasoningModels": [MODEL],
    }


def model_entry() -> dict:
    return {
        "provider": PROVIDER,
        "modelId": MODEL,
        "displayName": DISPLAY_NAME,
        "contextWindow": CONTEXT_WINDOW,
        "inputModalities": ["text", "image"],
        "reasoningEfforts": [],
    }


def _provider_identity(value: dict | None) -> dict | None:
    result = copy.deepcopy(value)
    if result and isinstance(result.get("initialModelSelection"), dict):
        # OpenCodex changes these two discovery observations during convergence.
        # registrationId and every operator-controlled field remain protected.
        result["initialModelSelection"].pop("status", None)
        result["initialModelSelection"].pop("modelCount", None)
    return result


def _coexistence_snapshot(config: dict) -> dict:
    return {
        "providers": {name: _provider_identity(provider)
                      for name, provider in config.get("providers", {}).items() if name != PROVIDER},
        "routing": {key: copy.deepcopy(config[key])
                    for key in ("defaultProvider", "combos", "modelAliases") if key in config},
    }


def _check_coexistence(before: dict, after: dict) -> None:
    if before == after:
        return
    providers_before, providers_after = before["providers"], after["providers"]
    changed = sorted(name for name in providers_before.keys() | providers_after.keys()
                     if name not in providers_before or name not in providers_after
                     or providers_before[name] != providers_after[name])
    # Include only bounded provider identifiers, never credential/config/alias values.
    public_ids = [name if re.fullmatch(r"[A-Za-z0-9._-]{1,128}", name) else "<invalid-id>"
                  for name in changed[:20]]
    routing_changed = before["routing"] != after["routing"]
    raise CoexistenceChanged(
        f"OpenCodex coexistence changed during this operation; provider IDs: {json.dumps(public_ids)}; "
        f"protected routing changed: {str(routing_changed).lower()}. "
        "The owned-entry journal was retained. No global configuration was restored."
    ) from None


def _models(config: dict) -> list:
    return [row for row in config.get("customModels", []) if row.get("provider") == PROVIDER]


def _references(config: dict) -> bool:
    """Conservatively protect defaults, combos, aliases, context caps and stale selectors."""
    rest = {key: value for key, value in config.items() if key not in {"providers", "customModels"}}
    rest["providers"] = {key: value for key, value in config.get("providers", {}).items() if key != PROVIDER}
    rest["customModels"] = [row for row in config.get("customModels", []) if row.get("provider") != PROVIDER]
    # Discovery observations are engine-owned and routinely created for the new provider.
    discovery = copy.deepcopy(rest.get("modelDiscovery", {}))
    for key in ("knownModels", "recentArrivals"):
        if isinstance(discovery.get(key), dict):
            discovery[key].pop(PROVIDER, None)
    if "modelDiscovery" in rest:
        rest["modelDiscovery"] = discovery

    def contains(value):
        if isinstance(value, str):
            return value == PROVIDER or value.startswith(PROVIDER + "/")
        if isinstance(value, dict):
            return any(contains(key) or contains(item) for key, item in value.items())
        if isinstance(value, list):
            return any(contains(item) for item in value)
        return False

    return contains(rest)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class OpenCodex:
    """Read via the supported CLI; mutate via the authenticated loopback API.

    runner and request are injection points for offline tests. request has signature
    (method, path, body) -> decoded JSON and must raise IntegrationError on failure.
    """

    def __init__(self, command_prefix: Sequence[str], *, config_path=None, opencodex_home=None,
                 runner: Callable | None = None, request: Callable | None = None):
        if isinstance(command_prefix, (str, bytes)) or not command_prefix or not all(
            isinstance(part, str) and part and "\x00" not in part for part in command_prefix
        ):
            raise IntegrationError("command_prefix must be a non-empty list of argument strings.")
        self.command = list(command_prefix)
        names = [part.replace("\\", "/").rsplit("/", 1)[-1].lower() for part in self.command]
        if not (
            len(names) == 1 and names[0] in {"ocx", "ocx.exe", "ocx.cmd", "opencodex", "opencodex.exe", "opencodex.cmd"}
            or len(names) == 2 and names[0] in {"node", "node.exe"} and names[1] == "ocx.mjs"
        ):
            raise IntegrationError("Use an ocx executable or node plus ocx.mjs; command options and credentials are not accepted.")
        self.env = dict(os.environ)
        if config_path is not None:
            config_path = Path(config_path).expanduser().resolve()
            if config_path.name != "config.json" or (opencodex_home is not None and Path(opencodex_home).expanduser().resolve() != config_path.parent):
                raise IntegrationError("config_path must be the selected OpenCodex home's config.json.")
            opencodex_home = config_path.parent
        self.home = Path(opencodex_home or self.env.get("OPENCODEX_HOME") or Path.home() / ".opencodex").expanduser().resolve()
        codex_home = Path(self.env.get("CODEX_HOME") or Path.home() / ".codex").expanduser().resolve()
        self.scope = {"opencodex_home": str(self.home), "codex_home": str(codex_home)}
        self.env.update(OPENCODEX_HOME=str(self.home), CODEX_HOME=str(codex_home), PYTHONUTF8="1")
        self.runner = runner or subprocess.run
        self.injected_request = request
        self.opener = build_opener(ProxyHandler({}), _NoRedirect())
        self.base = None
        self.token = None
        self.sync_diagnostic = {"code": "not_attempted", "exit_code": None}

    def preflight(self) -> dict:
        try:
            result = self.runner(
                [*self.command, "config", "show", "--json", "--source"],
                capture_output=True, text=True, encoding="utf-8", errors="strict",
                shell=False, env=self.env, timeout=60,
            )
        except (OSError, subprocess.SubprocessError, UnicodeError):
            raise IntegrationError("OpenCodex CLI could not be read; no registration was attempted.") from None
        if result.returncode != 0:
            raise IntegrationError("OpenCodex config inspection failed; captured output was withheld.")
        try:
            diagnostic = json.loads(result.stdout.lstrip("\ufeff"))
        except (ValueError, AttributeError):
            raise IntegrationError("OpenCodex returned an invalid config diagnostic.") from None
        if not isinstance(diagnostic, dict) or diagnostic.get("source") != "file" or diagnostic.get("error"):
            raise IntegrationError("An existing valid OpenCodex configuration is required.")
        config = self.config()
        if config.get("runtimeRole") == "client" or diagnostic.get("config", {}).get("runtimeRole") == "client":
            raise IntegrationError("Connected-client mode is unsupported; register on the local OpenCodex host.")
        if not config.get("providers") or config.get("defaultProvider") not in config["providers"]:
            raise IntegrationError("An existing OpenCodex default provider is required.")
        return config

    def config(self) -> dict:
        # Raw reads let detach detect credential edits too; CLI/API mask them.
        # The object is neither logged nor saved wholesale nor returned to the caller.
        return _read(self.home / "config.json")

    def sync_catalog_only(self) -> bool:
        # Only this explicit CLI path sets catalogEvenWhenNotInjected. /api/sync
        # does not, and normal integration-ON sync runs the native TOML injector.
        if self.config().get("clientIntegrations", {}).get("codex") is not False:
            self.sync_diagnostic = {"code": "integration_not_off", "exit_code": None}
            return False
        try:
            result = self.runner(
                [*self.command, "sync"], capture_output=True, text=True,
                encoding="utf-8", errors="strict", shell=False, env=self.env, timeout=60,
            )
            self.sync_diagnostic = {
                "code": "cli_success" if result.returncode == 0 else "cli_nonzero",
                "exit_code": result.returncode,
            }
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            self.sync_diagnostic = {"code": "cli_timeout", "exit_code": None}
            return False
        except UnicodeError:
            self.sync_diagnostic = {"code": "cli_output_invalid", "exit_code": None}
            return False
        except (OSError, subprocess.SubprocessError):
            self.sync_diagnostic = {"code": "cli_launch_failed", "exit_code": None}
            return False

    def _http(self, method, path, body=None, headers=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = Request(self.base + path, data=data, method=method, headers=headers or {})
        try:
            with self.opener.open(req, timeout=60) as response:
                value = json.loads(response.read().decode("utf-8-sig"))
                return value, response.headers
        except HTTPError as error:
            code = error.code
            error.close()
            raise IntegrationError(f"OpenCodex management request failed (HTTP {code}); response withheld.") from None
        except (OSError, URLError, ValueError):
            raise IntegrationError("OpenCodex management request failed or returned invalid JSON.") from None

    def _connect(self):
        runtime = _read(self.home / "runtime-port.json")
        port = _port(runtime.get("port"))
        pid = runtime.get("pid")
        secret = runtime.get("attestationSecret")
        if type(pid) is not int or pid <= 0 or not isinstance(secret, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", secret):
            raise IntegrationError("OpenCodex 2.59 runtime attestation is unavailable; no process will be restarted.")
        hostname = runtime.get("hostname", "127.0.0.1")
        if hostname not in {"127.0.0.1", "localhost", "0.0.0.0", "::", "::1"}:
            raise IntegrationError("Only the existing local OpenCodex management endpoint is supported.")
        host = "[::1]" if hostname in {"::", "::1"} else "127.0.0.1"
        self.base = f"http://{host}:{port}"
        challenge = secrets.token_urlsafe(32)
        health, headers = self._http("GET", "/healthz", headers={"x-opencodex-attestation-challenge": challenge})
        payload = f"opencodex-local-management-v1\n{challenge}\n{pid}\n{port}"
        expected = base64.urlsafe_b64encode(hmac.digest(secret.encode(), payload.encode(), "sha256")).decode().rstrip("=")
        if not isinstance(health, dict) or health.get("service") != "opencodex" or health.get("pid") != pid or health.get("role") == "client" or not hmac.compare_digest(expected, headers.get("x-opencodex-attestation-proof", "")):
            raise IntegrationError("OpenCodex runtime identity could not be verified.")
        token = self.env.get("OPENCODEX_ADMIN_AUTH_TOKEN", "").strip()
        if not token:
            path = self.home / "admin-api-token"
            try:
                if path.is_symlink() or not path.is_file() or path.stat().st_size > 512:
                    raise ValueError
                token = path.read_text(encoding="utf-8").strip()
                if not re.fullmatch(r"ocx_admin_[A-Za-z0-9_-]{43}", token):
                    raise ValueError
            except (OSError, ValueError):
                raise IntegrationError("An existing OpenCodex admin token is required; none will be created.") from None
        self.token = token

    def request(self, method: str, path: str, body=None):
        if self.injected_request:
            return self.injected_request(method, path, body)
        if not self.token:
            self._connect()
        result, _ = self._http(method, path, body, {"Content-Type": "application/json", "X-OpenCodex-API-Key": self.token})
        return result


def _load_state(path: Path, client: OpenCodex) -> dict | None:
    if not path.exists():
        return None
    state = _read(path)
    if state.get("product") != PRODUCT or state.get("version") != 1 or state.get("scope") != client.scope:
        raise OwnershipConflict("The installer journal belongs to a different integration or OpenCodex home.")
    if state.get("phase") not in {"installing", "installed", "detaching", "detached"}:
        raise OwnershipConflict("The installer journal has an unknown phase.")
    if not {"desired_provider", "provider", "model", "catalog_status"} <= state.keys():
        raise OwnershipConflict("The installer journal is incomplete.")
    return state


def _assert_owned(config: dict, state: dict, *, missing_ok=False):
    provider = config.get("providers", {}).get(PROVIDER)
    expected = state.get("provider")
    if _provider_identity(provider) != _provider_identity(expected) and not (missing_ok and provider is None):
        raise OwnershipConflict("The provider is unowned, missing or user-edited; it was preserved.")
    models = _models(config)
    model = state.get("model")
    if models != ([model] if model else []) and not (missing_ok and not models):
        raise OwnershipConflict("Custom models are unowned, missing or user-edited; they were preserved.")
    if _references(config):
        raise OwnershipConflict("A default, combo, selector or other setting references this provider; it was preserved.")


def _catalog_status(response: dict, client: OpenCodex, state: dict, *, detached=False) -> str:
    refresh = response.get("catalogRefresh", {})
    refresh = refresh if isinstance(refresh, dict) else {}
    # Closed vocabularies from OpenCodex 2.59's CatalogDisposition/FailureCause.
    # Keep the API outcome when a later CLI retry supplies its own diagnostics.
    allowed = {
        "status": {"committed", "skipped", "failed"},
        "reason": {"not-requested", "catalog-unavailable", "busy", "stale", "refused",
                   "provider-auth", "provider-network", "disk", "request-invalid", "admission", "internal"},
        "phase": {"gather", "commit"},
    }
    public = {key: refresh[key] for key, values in allowed.items()
              if isinstance(refresh.get(key), str) and refresh[key] in values}
    cause = refresh.get("cause")
    if isinstance(cause, dict):
        allowed_cause = {
            "kind": {"invalid-request", "lock-busy", "io", "unknown"},
            "code": {"ENOSPC", "EACCES", "EPERM", "EROFS", "ENOENT", "SQLITE_BUSY"},
        }
        public_cause = {key: cause[key] for key, values in allowed_cause.items()
                        if isinstance(cause.get(key), str) and cause[key] in values}
        if public_cause:
            public["cause"] = public_cause
    state["catalog_diagnostic"] = {"catalog_refresh": public}
    # These are OpenCodex 2.59's complete, sanitized CatalogNotice codes. Never
    # persist free-form upstream errors or infer that unrelated providers are healthy.
    notices = refresh.get("notices", [])
    state["catalog_notices"] = list(dict.fromkeys(
        notice for notice in (notices if isinstance(notices, list) else [])
        if isinstance(notice, str) and notice in {"fallback", "provider-network", "provider-auth"}
    ))
    state["catalog_degraded"] = refresh.get("degraded") is True
    committed = refresh.get("status") == "committed"
    verified = not state["catalog_degraded"] or _catalog_matches(client, detached=detached)
    return "synced" if committed and verified else "pending"


def _catalog_matches(client: OpenCodex, *, detached=False) -> bool:
    path = Path(client.scope["codex_home"]) / "opencodex-catalog.json"
    if not path.is_file():
        return False
    try:
        rows = _read(path).get("models", [])
        ours = [row for row in rows if row.get("slug") == f"{PROVIDER}/{MODEL}"]
        if detached:
            return not ours
        return len(ours) == 1 and ours[0].get("display_name") == DISPLAY_NAME and set(
            ours[0].get("input_modalities", [])
        ) == {"text", "image"} and ours[0].get("supported_reasoning_levels") == []
    except (IntegrationError, AttributeError, TypeError):
        return False


@contextmanager
def _native_settings_guard(client: OpenCodex):
    # These snapshots remain in memory; never persist another application's settings.
    # Protect the native default home as well when a managed CODEX_HOME is selected.
    homes = {Path(client.scope["codex_home"]), Path.home() / ".codex"}
    paths = [home / "config.toml" for home in homes]
    before = {path: path.read_bytes() if path.exists() else None for path in paths}
    foreign_before = _coexistence_snapshot(client.config()) if (client.home / "config.json").is_file() else None
    catalog = Path(client.scope["codex_home"]) / "opencodex-catalog.json"
    previous_slugs = set()
    if catalog.is_file():
        previous_slugs = {row.get("slug") for row in _read(catalog).get("models", [])}
        previous_slugs.discard(f"{PROVIDER}/{MODEL}")
    try:
        yield
    finally:
        if foreign_before is not None:
            _check_coexistence(foreign_before, _coexistence_snapshot(client.config()))
        after = {path: path.read_bytes() if path.exists() else None for path in paths}
        if after != before:
            raise NativeSettingsChanged(
                "Codex config.toml changed during registration/detach; no success is claimed. "
                "The owned-entry journal was retained. No global settings were restored."
            ) from None
        if previous_slugs:
            current_slugs = {row.get("slug") for row in _read(catalog).get("models", [])} if catalog.is_file() else set()
            if not previous_slugs <= current_slugs:
                raise NativeSettingsChanged("Catalog refresh removed unrelated models; inspect OpenCodex's catalog backup. No global restore was attempted.") from None


def _sync(client: OpenCodex, state: dict, *, detached=False) -> str:
    if client.config().get("clientIntegrations", {}).get("codex") is False:
        succeeded = client.sync_catalog_only()
        verified = _catalog_matches(client, detached=detached)
        state["catalog_diagnostic"] = {
            **state.get("catalog_diagnostic", {}),
            **client.sync_diagnostic,
            "catalog_exists": (Path(client.scope["codex_home"]) / "opencodex-catalog.json").is_file(),
            "owned_catalog_verified": verified,
            "detached": detached,
        }
        if succeeded and verified:
            return "synced"
        return "pending"
    # Retry catalog convergence via the unchanged owned model only. This route
    # does not inject root TOML settings. With no model left, observe convergence;
    # do not call /api/sync (which also changes native settings).
    if not detached and state.get("model"):
        _assert_owned(client.config(), state)
        try:
            response = client.request("PUT", "/api/custom-models/" + quote(state["model"]["id"], safe=""), {})
            return _catalog_status(response, client, state)
        except IntegrationError:
            return "pending"
    return "synced" if _catalog_matches(client, detached=True) else "pending"


def _result(state: dict, changed: bool) -> dict:
    return {
        "provider": PROVIDER, "model": f"{PROVIDER}/{MODEL}",
        "phase": state["phase"], "changed": changed,
        "catalog_status": state["catalog_status"],
        "catalog_degraded": state.get("catalog_degraded", False),
        "catalog_notices": state.get("catalog_notices", []),
        "picker_visibility": "not_verified",
        "restart_performed": False,
        "native_config_unchanged": True,
        **({"catalog_diagnostic": copy.deepcopy(state["catalog_diagnostic"])}
           if "catalog_diagnostic" in state else {}),
    }


def _save_catalog_diagnostic(root: Path, state: dict) -> None:
    """Small CI artifact, containing codes/booleans only; no paths or CLI output."""
    if "catalog_diagnostic" in state:
        logs = root / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        _write(logs / "codex-provider-diagnostic.json", state["catalog_diagnostic"])


def install(root: Path, command_prefix: Sequence[str], api_port: int | None = None, **client_options) -> dict:
    """Register a provider and model; retry safely with the same root and endpoint.

    Existing entries are never adopted. On a partial failure, successful owned
    steps stay journalled; retry or detach them, without rolling back unrelated work.
    """
    root = Path(root).resolve()
    desired = provider_entry(_api_port(root, api_port))
    client = OpenCodex(command_prefix, **client_options)
    with _locked(root), _native_settings_guard(client):
        config = client.preflight()
        path = root / STATE_FILE
        state = _load_state(path, client)
        if state and state["phase"] == "detaching":
            raise OwnershipConflict("Finish the pending detach before registering again.")
        if state is None or state["phase"] == "detached":
            discovery = config.get("modelDiscovery", {})
            if PROVIDER in config.get("providers", {}) or _models(config) or _references(config) or (state is None and any(
                PROVIDER in discovery.get(key, {}) for key in ("knownModels", "recentArrivals")
            )):
                raise OwnershipConflict("The provider name or namespace already exists; nothing was overwritten.")
            state = {"product": PRODUCT, "version": 1, "scope": client.scope, "command": client.command,
                     "desired_provider": desired, "provider": None, "model": None,
                     "phase": "installing", "catalog_status": "pending"}
            _write(path, state)
        elif state["desired_provider"] != desired:
            raise OwnershipConflict("The endpoint differs from the owned installation; detach it before changing ports.")
        _assert_owned(config, state)
        changed = False
        if state["provider"] is None:
            # Recheck immediately before the API's upsert; it has no create-only/CAS flag.
            _assert_owned(client.config(), state)
            client.request("POST", "/api/providers", {"name": PROVIDER, "provider": desired})
            created = client.config().get("providers", {}).get(PROVIDER)
            public = copy.deepcopy(created)
            if isinstance(public, dict):
                public.pop("initialModelSelection", None)
            if public != desired:
                raise OwnershipConflict("Provider creation could not be verified; no entry was adopted.")
            state["provider"] = created
            _write(path, state)
            changed = True
        if state["model"] is None:
            _assert_owned(client.config(), state)
            response = client.request("POST", "/api/custom-models", model_entry())
            created = {key: value for key, value in response.items() if key != "catalogRefresh"}
            if {key: value for key, value in created.items() if key not in {"id", "addedAt"}} != model_entry() or not created.get("id") or not created.get("addedAt"):
                raise OwnershipConflict("Model creation could not be verified; no entry was adopted.")
            if _models(client.config()) != [created]:
                raise OwnershipConflict("Model changed during registration; it was preserved.")
            state["model"] = created
            state["catalog_status"] = _catalog_status(response, client, state)
            _write(path, state)
            changed = True
        _assert_owned(client.config(), state)
        if state["catalog_status"] != "synced" and (
            not changed or client.config().get("clientIntegrations", {}).get("codex") is False
        ):
            state["catalog_status"] = _sync(client, state)
        state["phase"] = "installed"
        _write(path, state)
        _save_catalog_diagnostic(root, state)
        return _result(state, changed)


def configure(root: Path, command_prefix: Sequence[str], api_port: int,
              config_path: Path | None = None, **client_options) -> dict:
    """Installer entry point; config_path selects an existing OpenCodex config.json."""
    return install(root, command_prefix, api_port, config_path=config_path, **client_options)


def detach(root: Path, command_prefix: Sequence[str], config_path: Path | None = None,
           **client_options) -> dict:
    """Remove only unchanged journalled entries; never reset defaults or user edits."""
    root = Path(root).resolve()
    client = OpenCodex(command_prefix, config_path=config_path, **client_options)
    with _locked(root), _native_settings_guard(client):
        path = root / STATE_FILE
        state = _load_state(path, client)
        if state is None:
            return {"provider": PROVIDER, "phase": "unmanaged", "changed": False}
        config = client.preflight()
        _assert_owned(config, state, missing_ok=True)
        changed = False
        if PROVIDER in config["providers"] or _models(config):
            state["phase"] = "detaching"
            state["catalog_status"] = "pending"
            _write(path, state)
            _assert_owned(client.config(), state, missing_ok=True)
            if PROVIDER in client.config()["providers"]:
                # This supported delete also removes its custom models; all were checked above.
                response = client.request("DELETE", f"/api/providers?name={PROVIDER}")
            else:
                response = client.request("DELETE", "/api/custom-models/" + quote(state["model"]["id"], safe=""))
            remaining = client.config()
            if PROVIDER in remaining["providers"] or _models(remaining):
                raise IntegrationError("Removal could not be verified; the ownership journal was retained.")
            state["catalog_status"] = _catalog_status(response, client, state, detached=True)
            changed = True
        if state["catalog_status"] != "synced" or (not changed and state["phase"] != "detached"):
            state["catalog_status"] = _sync(client, state, detached=True)
        state["phase"] = "detached"
        _write(path, state)
        _save_catalog_diagnostic(root, state)
        return _result(state, changed)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "detach"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--api-port", type=int)
    parser.add_argument("--opencodex-home", type=Path)
    parser.add_argument("--ocx-command", nargs="+", required=True, help="ocx executable, or node.exe and ocx.mjs (last option)")
    args = parser.parse_args(argv)
    try:
        options = {"opencodex_home": args.opencodex_home}
        if args.action == "install":
            result = install(args.root, args.ocx_command, args.api_port, **options)
        else:
            result = detach(args.root, args.ocx_command, **options)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("catalog_status") != "pending" else 2
    except IntegrationError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
