"""Normal Windows profile paths and reversible integration into shared user files."""

import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path


def paths():
    user = Path(os.environ["USERPROFILE"]).resolve()
    return user / ".continue", user / ".vscode/extensions", Path(os.environ["APPDATA"]).resolve() / "Code"


def snapshot(root, extension, targets):
    """Keep the first pre-install version, never a patched repair as the original."""
    state_path = root / "normal-profile-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"files": {}}
    for target in targets:
        target = target.resolve()
        key = str(target)
        if key in state["files"]:
            continue
        backup = root / "backups/normal-profile-original" / hashlib.sha256(key.encode()).hexdigest()
        if target.exists():
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
        state["files"][key] = {"backup": str(backup) if target.exists() else None}
    state["extension"] = str(extension)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def record(root, targets, models, servers, disabled_updates_before):
    state_path = root / "normal-profile-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    for target in targets:
        state["files"][str(target.resolve())]["installed_sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    state["models"] = models
    state["servers"] = servers
    state.setdefault("disabled_updates_before", disabled_updates_before)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def detach(root):
    """Restore unedited installed files; merge only our exact model/server entries."""
    import yaml

    state_path = root / "normal-profile-state.json"
    if not state_path.exists():
        return
    manifest = json.loads((root / "installation.json").read_text(encoding="utf-8"))
    if manifest.get("profile_mode") != "normal":
        return
    state = json.loads(state_path.read_text(encoding="utf-8"))
    binding = Path(state["extension"]) / "out/web2api-installation.json"
    if not binding.exists() or Path(json.loads(binding.read_text(encoding="utf-8"))["root"]).resolve() != root.resolve():
        raise RuntimeError("The normal profile is now owned by another installation; no files changed.")
    continue_dir, extensions, data = paths()
    config_path = continue_dir / "config.yaml"
    allowed_roots = (continue_dir, extensions)
    for key, entry in state["files"].items():
        target = Path(key).resolve()
        if not any(target.is_relative_to(base) for base in allowed_roots):
            raise RuntimeError("Profile restoration outside known user directories refused")
        if target == config_path or not target.exists():
            continue
        if hashlib.sha256(target.read_bytes()).hexdigest() != entry.get("installed_sha256"):
            continue  # User edits made after installation are retained.
        if entry["backup"]:
            backup = Path(entry["backup"]).resolve()
            if not backup.is_relative_to(root.resolve() / "backups"):
                raise RuntimeError("Invalid backup location")
            shutil.copy2(backup, target)
        else:
            target.unlink()
    if config_path.exists():
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        original_entry = state["files"][str(config_path)]
        original = yaml.safe_load(Path(original_entry["backup"]).read_text(encoding="utf-8")) if original_entry["backup"] else {}
        original = original or {}
        for field, installed in (("models", state["models"]), ("mcpServers", state["servers"])):
            current = config.get(field, [])
            for item in installed:
                if item in current:
                    current.remove(item)
                    current.extend(old for old in original.get(field, []) if old.get("name") == item["name"] and old not in current)
            config[field] = current
        config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    db = data / "User/globalStorage/state.vscdb"
    if db.exists() and not state["disabled_updates_before"]:
        with sqlite3.connect(db) as conn:
            row = conn.execute("SELECT value FROM ItemTable WHERE key='extensions.donotAutoUpdate'").fetchone()
            values = json.loads(row[0]) if row else []
            values = [value for value in values if value != "continue.continue"]
            conn.execute("INSERT OR REPLACE INTO ItemTable(key,value) VALUES (?,?)", ("extensions.donotAutoUpdate", json.dumps(values)))
    print("Integration Web2API retiree du profil normal ; fichiers personnels conserves.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--detach", type=Path, required=True)
    detach(parser.parse_args().detach.resolve())
