"""Offline OpenCodex management contract tests; never use the user's config/proxy."""

from __future__ import annotations

import base64
import copy
import hmac
import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "codex_provider", Path(__file__).resolve().parents[1] / "installer/codex_provider.py"
)
cp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cp)


@pytest.fixture(autouse=True)
def forbid_real_commands_and_network(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail("A provider test attempted a real command or network request")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr("urllib.request.OpenerDirector.open", forbidden)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "user"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "user/.codex"))


class FakeOpenCodex:
    def __init__(self, tmp_path):
        self.root = tmp_path / "Web2API-Codex été"
        self.home = tmp_path / "OpenCodex home"
        self.home.mkdir(parents=True)
        self.codex_home = tmp_path / "user/.codex"
        self.codex_home.mkdir(parents=True)
        self.toml = self.codex_home / "config.toml"
        self.toml.write_text('model_context_window = 123456\nservice_tier = "fast"\napproval_policy = "on-request"\n', encoding="utf-8")
        self.path = self.home / "config.json"
        self.config = {
            "port": 10100,
            "defaultProvider": "existing",
            "providers": {
                "existing": {"adapter": "openai-chat", "baseUrl": "https://example.test/v1",
                             "apiKey": "OTHER-PROVIDER-SECRET", "defaultModel": "original"},
                "openai": {"adapter": "openai-responses", "authMode": "forward"},
            },
            "customModels": [{"id": "old", "provider": "existing", "modelId": "original"}],
            "combos": {"keep": {"targets": [{"provider": "existing", "model": "original"}]}},
            "disabledModels": ["existing/hidden"],
            "codexToolMode": "default",
            "userInstructions": "Preserve native tools and permissions",
            "nestedUnknown": {"keep": [1, "é"]},
        }
        self.initial = copy.deepcopy(self.config)
        self.calls = []
        self.commands = []
        self.catalog = {"gpt-native": {"native_tools": ["exec_command", "apply_patch"]}, "existing/original": {"custom": True}}
        self.original_catalog = copy.deepcopy(self.catalog)
        self.refresh = {"status": "committed", "degraded": False}
        self.sync = {"ok": True, "status": "synced", "catalogWritten": True}
        self.fail_before = None
        self.fail_after = None
        self.save()
        self.save_catalog()

    def save_catalog(self):
        (self.codex_home / "opencodex-catalog.json").write_text(json.dumps({"models": [
            {"slug": slug, **row} for slug, row in self.catalog.items()
        ]}), encoding="utf-8")

    def converge(self):
        if any(row.get("provider") == cp.PROVIDER for row in self.config["customModels"]):
            self.catalog[cp.PROVIDER + "/auto"] = {"display_name": cp.DISPLAY_NAME, "input_modalities": ["text", "image"], "supported_reasoning_levels": [], "context_window": cp.CONTEXT_WINDOW}
        else:
            self.catalog.pop(cp.PROVIDER + "/auto", None)
        self.save_catalog()

    def save(self):
        self.path.write_text(json.dumps(self.config, ensure_ascii=False), encoding="utf-8")

    def run(self, argv, **kwargs):
        self.commands.append((list(argv), kwargs))
        if argv[-1] == "sync":
            assert self.config["clientIntegrations"]["codex"] is False
            if self.sync.get("ok") and not self.sync.get("warning") and self.sync.get("status") == "catalog-only":
                self.converge()
            return SimpleNamespace(returncode=0 if self.sync.get("ok") and not self.sync.get("warning") else 1, stdout="Catalog sync", stderr="")
        assert argv[-4:] == ["config", "show", "--json", "--source"]
        assert kwargs["shell"] is False
        assert kwargs["capture_output"] is True
        assert kwargs["encoding"] == "utf-8"
        assert kwargs["env"]["OPENCODEX_HOME"] == str(self.home.resolve())
        return SimpleNamespace(returncode=0, stdout=json.dumps({"source": "file", "error": None, "config": {}}), stderr="")

    def request(self, method, path, body):
        self.calls.append((method, path, copy.deepcopy(body)))
        if path == self.fail_before:
            raise cp.IntegrationError("simulated management failure")
        if (method, path) == ("POST", "/api/providers"):
            assert body["name"] == cp.PROVIDER
            assert "setDefault" not in body
            assert cp.PROVIDER not in self.config["providers"]
            self.config["providers"][cp.PROVIDER] = copy.deepcopy(body["provider"])
            self.config["providers"][cp.PROVIDER]["initialModelSelection"] = {
                "version": 1, "registrationId": "generated-registration-id", "status": "ready", "modelCount": 1,
            }
            response = {"success": True, "name": cp.PROVIDER, "catalogRefresh": self.refresh}
        elif (method, path) == ("POST", "/api/custom-models"):
            row = {**copy.deepcopy(body), "id": "generated-model-id", "addedAt": "2026-09-21T00:00:00Z"}
            self.config.setdefault("customModels", []).append(row)
            response = {**row, "catalogRefresh": self.refresh}
        elif method == "PUT" and path == "/api/custom-models/generated-model-id":
            assert body == {}
            response = {"ok": True, "catalogRefresh": self.refresh}
        elif (method, path) == ("DELETE", "/api/providers?name=" + cp.PROVIDER):
            del self.config["providers"][cp.PROVIDER]
            self.config["customModels"] = [row for row in self.config["customModels"] if row["provider"] != cp.PROVIDER]
            response = {"success": True, "catalogRefresh": self.refresh}
        elif method == "DELETE" and path.startswith("/api/custom-models/"):
            self.config["customModels"] = [row for row in self.config["customModels"] if row["id"] != path.rsplit("/", 1)[1]]
            response = {"ok": True, "catalogRefresh": self.refresh}
        else:
            pytest.fail(f"Unexpected mutation: {method} {path}")
        self.save()
        if self.refresh.get("status") == "committed" and not self.refresh.get("degraded"):
            self.converge()
        if path == self.fail_after:
            raise cp.IntegrationError("simulated lost response after save")
        return response

    @property
    def options(self):
        return {"config_path": self.path, "runner": self.run, "request": self.request}

    def configure(self, port=8080, prefix=None):
        return cp.configure(self.root, prefix or ["ocx"], port, **self.options)

    def detach(self):
        return cp.detach(self.root, ["ocx"], **self.options)

    def journal(self):
        return json.loads((self.root / cp.STATE_FILE).read_text(encoding="utf-8"))


@pytest.fixture
def ocx(tmp_path):
    return FakeOpenCodex(tmp_path)


def test_coexistence_exact_metadata_and_no_native_tool_changes(ocx, capsys):
    result = ocx.configure()
    assert result == {"provider": cp.PROVIDER, "model": "chatgpt-web2api/auto", "phase": "installed", "changed": True,
                      "catalog_status": "synced", "catalog_degraded": False, "catalog_notices": [], "picker_visibility": "not_verified", "restart_performed": False, "native_config_unchanged": True}
    provider = ocx.config["providers"][cp.PROVIDER]
    assert provider["baseUrl"] == "http://127.0.0.1:8080/codex/v1"
    assert provider["adapter"] == "openai-chat"
    assert provider["apiKey"] == "not-needed"
    assert provider["noReasoningModels"] == ["auto"]
    assert provider["modelInputModalities"] == {"auto": ["text", "image"]}
    assert provider["modelContextWindows"] == {"auto": 32768}
    model = ocx.config["customModels"][-1]
    assert model["reasoningEfforts"] == []
    assert "defaultReasoningEffort" not in model
    assert model["displayName"] == "ChatGPT Web2API"
    assert model["contextWindow"] == 32768
    assert model["inputModalities"] == ["text", "image"]
    without_ours = copy.deepcopy(ocx.config)
    del without_ours["providers"][cp.PROVIDER]
    without_ours["customModels"].pop()
    assert without_ours == ocx.initial
    for key, row in ocx.original_catalog.items():
        assert ocx.catalog[key] == row
    journal_text = json.dumps(ocx.journal())
    assert "OTHER-PROVIDER-SECRET" not in journal_text
    assert "nestedUnknown" not in journal_text
    assert "codexToolMode" not in json.dumps(ocx.calls)
    assert "userInstructions" not in json.dumps(ocx.calls)
    assert capsys.readouterr().out == ""


def test_idempotent_with_node_prefix_spaces_and_utf8(ocx):
    prefix = [r"C:\node with spaces\node.exe", r"C:\npm été\ocx.mjs"]
    ocx.configure(prefix=prefix)
    before = copy.deepcopy(ocx.config)
    calls = copy.deepcopy(ocx.calls)
    result = ocx.configure(prefix=prefix)
    assert result["changed"] is False
    assert ocx.config == before and ocx.calls == calls
    assert ocx.commands[-1][0][:2] == prefix
    assert ocx.journal()["command"] == prefix
    assert not (ocx.root / cp.STATE_FILE).read_bytes().startswith(b"\xef\xbb\xbf")


@pytest.mark.parametrize("collision", ["provider", "identical", "model", "disabled", "combo", "namespace", "discovery"])
def test_preexisting_namespace_is_never_adopted_or_overwritten(ocx, collision):
    if collision in {"provider", "identical"}:
        ocx.config["providers"][cp.PROVIDER] = cp.provider_entry(8080) if collision == "identical" else {"apiKey": "private"}
    elif collision == "model":
        ocx.config["customModels"].append({"provider": cp.PROVIDER, "modelId": "other", "id": "mine"})
    elif collision == "disabled":
        ocx.config["disabledModels"].append(cp.PROVIDER + "/auto")
    elif collision == "combo":
        ocx.config["combos"]["mine"] = {"targets": [{"provider": cp.PROVIDER}]}
    elif collision == "namespace":
        ocx.config["codexAccountNamespaces"] = {cp.PROVIDER: "mine"}
    else:
        ocx.config["modelDiscovery"] = {"knownModels": {cp.PROVIDER: ["auto"]}}
    ocx.save()
    before = ocx.path.read_bytes()
    with pytest.raises(cp.OwnershipConflict):
        ocx.configure()
    assert ocx.calls == [] and ocx.path.read_bytes() == before
    assert not (ocx.root / cp.STATE_FILE).exists()


def test_detach_preserves_unrelated_changes_and_is_idempotent(ocx):
    ocx.configure()
    ocx.config["providers"]["added-later"] = {"apiKey": "later-secret"}
    ocx.config["nestedUnknown"]["new"] = True
    ocx.save()
    expected = copy.deepcopy(ocx.config)
    del expected["providers"][cp.PROVIDER]
    expected["customModels"].pop()
    assert ocx.detach()["phase"] == "detached"
    assert ocx.config == expected
    assert ocx.catalog == ocx.original_catalog
    calls = copy.deepcopy(ocx.calls)
    assert ocx.detach()["changed"] is False
    assert ocx.calls == calls


@pytest.mark.parametrize("edit", ["key", "url", "tools", "selection", "registration", "model", "extra-model", "default", "combo", "default-model"])
def test_detach_refuses_user_edits_without_partial_deletion(ocx, edit):
    ocx.configure()
    provider = ocx.config["providers"][cp.PROVIDER]
    if edit == "key":
        provider["apiKey"] = "USER-REPLACEMENT-SECRET"
    elif edit == "url":
        provider["baseUrl"] = "http://127.0.0.1:9090/codex/v1"
    elif edit == "tools":
        provider["codexToolMode"] = "shell"
    elif edit == "selection":
        provider["selectedModels"] = []
    elif edit == "registration":
        provider["initialModelSelection"]["registrationId"] = "user-recreated"
    elif edit == "model":
        ocx.config["customModels"][-1]["reasoningEfforts"] = ["high"]
    elif edit == "extra-model":
        ocx.config["customModels"].append({"id": "user-model", "provider": cp.PROVIDER, "modelId": "mine"})
    elif edit == "default":
        ocx.config["defaultProvider"] = cp.PROVIDER
    elif edit == "combo":
        ocx.config["combos"]["added"] = {"targets": [{"provider": cp.PROVIDER, "model": "auto"}]}
    else:
        ocx.config["defaultModel"] = cp.PROVIDER + "/auto"
    ocx.save()
    before = ocx.path.read_bytes()
    calls = copy.deepcopy(ocx.calls)
    with pytest.raises(cp.OwnershipConflict):
        ocx.detach()
    assert ocx.path.read_bytes() == before and ocx.calls == calls
    assert "USER-REPLACEMENT-SECRET" not in json.dumps(ocx.journal())


def test_engine_discovery_progress_does_not_break_ownership(ocx):
    ocx.configure()
    ocx.config["providers"][cp.PROVIDER]["initialModelSelection"].update(status="ready", modelCount=2)
    ocx.config["modelDiscovery"] = {"knownModels": {cp.PROVIDER: ["auto"]}}
    ocx.save()
    assert ocx.configure()["changed"] is False
    assert ocx.detach()["phase"] == "detached"
    assert ocx.configure()["phase"] == "installed"


def test_missing_journal_detach_never_contacts_opencodex(ocx):
    assert ocx.detach()["phase"] == "unmanaged"
    assert ocx.commands == [] and ocx.calls == []


def test_partial_install_can_resume_without_readding_provider(ocx):
    ocx.fail_before = "/api/custom-models"
    with pytest.raises(cp.IntegrationError):
        ocx.configure()
    assert ocx.journal()["provider"] is not None and ocx.journal()["model"] is None
    ocx.fail_before = None
    assert ocx.configure()["phase"] == "installed"
    assert sum(path == "/api/providers" for _, path, _ in ocx.calls) == 1


def test_partial_install_can_detach(ocx):
    ocx.fail_before = "/api/custom-models"
    with pytest.raises(cp.IntegrationError):
        ocx.configure()
    ocx.fail_before = None
    assert ocx.detach()["phase"] == "detached"
    assert ocx.config == ocx.initial


@pytest.mark.parametrize("route", ["/api/providers", "/api/custom-models"])
def test_lost_mutation_response_never_claims_or_deletes_uncertain_entries(ocx, route):
    ocx.fail_after = route
    with pytest.raises(cp.IntegrationError):
        ocx.configure()
    ocx.fail_after = None
    calls = copy.deepcopy(ocx.calls)
    with pytest.raises(cp.OwnershipConflict):
        ocx.configure()
    with pytest.raises(cp.OwnershipConflict):
        ocx.detach()
    assert ocx.calls == calls


@pytest.mark.parametrize("refresh", [{"status": "failed"}, {"status": "skipped", "reason": "busy"}, {"status": "committed", "degraded": True}])
def test_pending_catalog_retries_supported_sync_without_restart(ocx, refresh):
    ocx.refresh = refresh
    assert ocx.configure()["catalog_status"] == "pending"
    ocx.refresh = {"status": "committed", "degraded": False}
    result = ocx.configure()
    assert result["changed"] is False and result["catalog_status"] == "synced"
    assert ocx.calls[-1] == ("PUT", "/api/custom-models/generated-model-id", {})
    assert len(ocx.config["customModels"]) == 2


@pytest.mark.parametrize("retry", [False, True])
def test_verified_owned_model_succeeds_despite_unrelated_provider_network_notices(ocx, retry):
    if retry:
        ocx.refresh = {"status": "skipped", "reason": "busy"}
        assert ocx.configure()["catalog_status"] == "pending"
    ocx.refresh = {"status": "committed", "changed": False, "degraded": True,
                   "notices": ["fallback", "provider-network"]}
    before = ocx.toml.read_bytes()

    def committed_catalog(method, path, body):
        result = ocx.request(method, path, body)
        ocx.converge()  # Existing providers used fallbacks; our row committed correctly.
        return result

    options = {**ocx.options, "request": committed_catalog}
    result = cp.configure(ocx.root, ["ocx"], 8080, **options)
    assert result["catalog_status"] == "synced"
    assert result["changed"] is not retry
    assert result["catalog_degraded"] is True
    assert result["catalog_notices"] == ["fallback", "provider-network"]
    assert ocx.journal()["catalog_notices"] == result["catalog_notices"]
    assert ocx.journal()["catalog_degraded"] is True
    assert ocx.toml.read_bytes() == before
    for name, provider in ocx.initial["providers"].items():
        assert ocx.config["providers"][name] == provider
    for slug, row in ocx.original_catalog.items():
        assert ocx.catalog[slug] == row
    if retry:
        assert ocx.calls[-1] == ("PUT", "/api/custom-models/generated-model-id", {})
    calls = copy.deepcopy(ocx.calls)
    assert cp.configure(ocx.root, ["ocx"], 8080, **options)["catalog_notices"] == result["catalog_notices"]
    assert ocx.calls == calls


def test_degraded_commit_with_wrong_owned_metadata_stays_pending_and_notices_are_bounded(ocx):
    ocx.refresh = {"status": "committed", "degraded": True,
                   "notices": ["fallback", "fallback", "provider-auth", "SECRET-FREEFORM-ERROR", {"error": "private"}]}

    def wrong_metadata(method, path, body):
        result = ocx.request(method, path, body)
        ocx.converge()
        if cp.PROVIDER + "/auto" in ocx.catalog:
            ocx.catalog[cp.PROVIDER + "/auto"]["supported_reasoning_levels"] = [{"effort": "high"}]
            ocx.save_catalog()
        return result

    result = cp.configure(ocx.root, ["ocx"], 8080, **{**ocx.options, "request": wrong_metadata})
    assert result["catalog_status"] == "pending"
    assert result["catalog_notices"] == ["fallback", "provider-auth"]
    assert "SECRET-FREEFORM-ERROR" not in json.dumps(ocx.journal())


def test_degraded_detach_accepts_verified_removal_and_keeps_notices(ocx):
    ocx.configure()
    ocx.refresh = {"status": "committed", "degraded": True, "notices": ["provider-network"]}

    def committed_removal(method, path, body):
        result = ocx.request(method, path, body)
        ocx.converge()
        return result

    result = cp.detach(ocx.root, ["ocx"], **{**ocx.options, "request": committed_removal})
    assert result["catalog_status"] == "synced"
    assert result["catalog_degraded"] is True
    assert result["catalog_notices"] == ["provider-network"]


@pytest.mark.parametrize("response", [{"ok": True, "status": "skipped"}, {"ok": False}, {"ok": True, "warning": "pending"}])
def test_off_sync_skips_and_warnings_are_not_reported_as_success(ocx, response):
    ocx.refresh = {"status": "failed"}
    ocx.config["clientIntegrations"] = {"codex": False}
    ocx.save()
    ocx.configure()
    ocx.sync = response
    assert ocx.configure()["catalog_status"] == "pending"


def test_failed_sync_keeps_successful_registration_and_journal(ocx):
    ocx.refresh = {"status": "failed"}
    ocx.configure()
    ocx.fail_before = "/api/custom-models/generated-model-id"
    assert ocx.configure()["catalog_status"] == "pending"
    assert ocx.journal()["phase"] == "installed"


def test_detach_pending_never_falls_back_to_full_sync(ocx):
    ocx.configure()
    ocx.refresh = {"status": "skipped"}
    assert ocx.detach()["catalog_status"] == "pending"
    assert ocx.detach()["catalog_status"] == "pending"
    ocx.converge()  # A later independent OpenCodex refresh completed.
    assert ocx.detach()["catalog_status"] == "synced"
    assert sum(method == "DELETE" for method, _, _ in ocx.calls) == 1
    assert all(path != "/api/sync" for _, path, _ in ocx.calls)
    assert all(argv[-1] != "sync" for argv, _ in ocx.commands)


def test_user_removed_provider_can_remove_unchanged_owned_orphan_model(ocx):
    ocx.configure()
    del ocx.config["providers"][cp.PROVIDER]
    ocx.save()
    assert ocx.detach()["phase"] == "detached"
    assert ocx.calls[-1][1] == "/api/custom-models/generated-model-id"


def test_endpoint_change_and_different_state_home_refused(ocx, tmp_path):
    ocx.configure()
    calls = copy.deepcopy(ocx.calls)
    with pytest.raises(cp.OwnershipConflict):
        ocx.configure(port=8081)
    other = FakeOpenCodex(tmp_path / "other")
    with pytest.raises(cp.OwnershipConflict):
        cp.configure(ocx.root, ["ocx"], 8080, **other.options)
    assert ocx.calls == calls and other.calls == []


@pytest.mark.parametrize("port", [True, 0, 65536, "8080", 1.5])
def test_invalid_ports_refused_before_commands(ocx, port):
    with pytest.raises(cp.IntegrationError):
        ocx.configure(port=port)
    assert ocx.commands == [] and ocx.calls == []


def test_install_resolves_existing_root_server_port(ocx):
    ocx.root.mkdir()
    (ocx.root / "config.json").write_text('{"port":8084}', encoding="utf-8")
    cp.install(ocx.root, ["ocx"], **ocx.options)
    assert ocx.config["providers"][cp.PROVIDER]["baseUrl"] == "http://127.0.0.1:8084/codex/v1"


def test_cli_error_does_not_echo_captured_secrets(ocx, capsys):
    def fail(argv, **kwargs):
        return SimpleNamespace(returncode=1, stdout="leaked-secret", stderr="leaked-secret")

    with pytest.raises(cp.IntegrationError) as error:
        cp.configure(ocx.root, ["ocx"], 8080, config_path=ocx.path, runner=fail, request=ocx.request)
    assert "leaked-secret" not in str(error.value)
    assert capsys.readouterr().out == "" and ocx.calls == []


@pytest.mark.parametrize("diagnostic", [{"source": "default"}, {"source": "fallback", "error": "invalid_json"}, []])
def test_cli_fallback_configuration_is_never_mutated(ocx, diagnostic):
    def run(argv, **kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps(diagnostic))

    with pytest.raises(cp.IntegrationError):
        cp.configure(ocx.root, ["ocx"], 8080, config_path=ocx.path, runner=run, request=ocx.request)
    assert ocx.calls == []


def test_client_role_rejected(ocx):
    ocx.config["runtimeRole"] = "client"
    ocx.save()
    with pytest.raises(cp.IntegrationError, match="Connected-client"):
        ocx.configure()
    assert ocx.calls == []


def test_existing_lock_does_not_get_removed(ocx):
    ocx.root.mkdir()
    lock = ocx.root / (cp.STATE_FILE + ".lock")
    lock.write_text("other-process", encoding="utf-8")
    with pytest.raises(cp.IntegrationError, match="journal lock"):
        ocx.configure()
    assert lock.read_text() == "other-process" and not ocx.commands


@pytest.mark.parametrize("valid_proof", [True, False])
def test_transport_attests_runtime_before_sending_admin_token(ocx, monkeypatch, valid_proof):
    secret = "S" * 43
    (ocx.home / "runtime-port.json").write_text(json.dumps({"pid": 123, "port": 10200, "attestationSecret": secret}), encoding="utf-8")
    token = "ocx_admin_" + "T" * 43
    (ocx.home / "admin-api-token").write_text(token, encoding="utf-8")
    monkeypatch.delenv("OPENCODEX_ADMIN_AUTH_TOKEN", raising=False)
    client = cp.OpenCodex(["node", "ocx.mjs"], config_path=ocx.path)
    calls = []

    def http(method, path, body=None, headers=None):
        calls.append((method, path, headers))
        if path == "/healthz":
            assert "X-OpenCodex-API-Key" not in headers
            challenge = headers["x-opencodex-attestation-challenge"]
            payload = f"opencodex-local-management-v1\n{challenge}\n123\n10200"
            proof = base64.urlsafe_b64encode(hmac.digest(secret.encode(), payload.encode(), "sha256")).decode().rstrip("=")
            return {"service": "opencodex", "pid": 123}, {"x-opencodex-attestation-proof": proof if valid_proof else "bad"}
        assert headers["X-OpenCodex-API-Key"] == token
        return {"ok": True}, {}

    monkeypatch.setattr(client, "_http", http)
    if valid_proof:
        assert client.request("POST", "/api/sync", {}) == {"ok": True}
        assert client.base == "http://127.0.0.1:10200"
    else:
        with pytest.raises(cp.IntegrationError, match="identity"):
            client.request("POST", "/api/sync", {})
        assert len(calls) == 1
        assert client.token is None


def test_integration_off_uses_explicit_catalog_only_cli_and_preserves_toml(ocx):
    ocx.config["clientIntegrations"] = {"codex": False}
    ocx.save()
    ocx.refresh = {"status": "skipped", "reason": "desired-disabled"}
    ocx.sync = {"ok": True, "status": "catalog-only"}
    before = ocx.toml.read_bytes()
    result = ocx.configure()
    assert result["catalog_status"] == "synced"
    assert result["native_config_unchanged"] is True
    assert ocx.commands[-1][0] == ["ocx", "sync"]
    assert ocx.toml.read_bytes() == before
    assert ocx.config["clientIntegrations"] == {"codex": False}
    assert not any(path == "/api/sync" for _, path, _ in ocx.calls)
    assert ocx.detach()["catalog_status"] == "synced"
    assert ocx.toml.read_bytes() == before


def test_native_settings_change_is_detected_without_automatic_global_restore(ocx):
    def changed(method, path, body):
        result = ocx.request(method, path, body)
        ocx.toml.write_text('model_context_window = 999\napproval_policy = "never"\n', encoding="utf-8")
        return result

    with pytest.raises(cp.NativeSettingsChanged, match="config.toml changed"):
        cp.configure(ocx.root, ["ocx"], 8080, config_path=ocx.path, runner=ocx.run, request=changed)
    assert ocx.journal()["provider"] is not None
    assert 'approval_policy = "never"' in ocx.toml.read_text()


def test_catalog_loss_is_detected(ocx):
    def lost_row(method, path, body):
        result = ocx.request(method, path, body)
        ocx.catalog.pop("gpt-native", None)
        ocx.save_catalog()
        return result

    with pytest.raises(cp.NativeSettingsChanged, match="unrelated models"):
        cp.configure(ocx.root, ["ocx"], 8080, config_path=ocx.path, runner=ocx.run, request=lost_row)
    assert ocx.journal()["model"] is not None


def test_command_prefix_rejects_credentials_before_persisting_state(ocx):
    with pytest.raises(cp.IntegrationError):
        ocx.configure(prefix=["ocx", "--api-key", "secret"])
    assert not (ocx.root / cp.STATE_FILE).exists()
