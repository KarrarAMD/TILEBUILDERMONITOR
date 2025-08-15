#!/usr/bin/env python3.10
 
import subprocess
import json
from pathlib import Path
import os
import re
 
CURRENT_USERS_PATH = "/tool/aticad/1.0/flow/current_users.json"
 
FIELDS_TO_SAVE = [
    "basedir",
    "project",
    "nickname",
    "family",
    "personality",
    "when_measured",
    "tilename",
    "label",
]
 
def get_user_with_printenv():
    try:
        result = subprocess.run(["printenv", "USER"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
 
        user = result.stdout.strip()
        return user
    except subprocess.CalledProcessError as e:
        print("printenv command failed:", e.stderr.strip())
        return None
 
def extract_json_from_line(line: str):
    """Return a dict parsed from the first {...} JSON object found in the line, else None."""
    if not line:
        return None
    start = line.find("{")
    end = line.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    snippet = line[start : end + 1]
    try:
        return json.loads(snippet)
    except json.JSONDecodeError:
        return None
 
def print_user_runs_and_count(username: str, filepath: str = CURRENT_USERS_PATH) -> int:
    """Print basedir for each run matching username and return the count of runs."""
    count = 0
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue
                entry = extract_json_from_line(line)
                if not isinstance(entry, dict):
                    continue
                if entry.get("username") == username:
                    basedir = entry.get("basedir")
                    if basedir is not None:
                        print(basedir)
                    else:
                        print("<no basedir>")
                    count += 1
    except FileNotFoundError:
        print(f"File not found: {filepath}")
    except PermissionError:
        print(f"Permission denied reading: {filepath}")
    return count
 
# ---- Helpers to compute tech_node and flow_label (borrowed from /proj/constr16/apeterso/regression_scripts/regression_notification.py) ----
 
def _load_params(basedir: str) -> dict:
    if not basedir:
        return {}
    params_path = os.path.join(basedir, "params.json")
    try:
        with open(params_path, "r", encoding="utf-8", errors="ignore") as f:
            return json.load(f).get("params", {})
    except Exception:
        return {}
 
def _get_tech_node_from_params(params: dict) -> str:
    """Mimic Run.get_tech_node by parsing PDK_DIR and taking the segment after the one containing 'nm'."""
    pdk_dir = params.get("PDK_DIR", "")
    parts = pdk_dir.strip(os.sep).split(os.sep) if pdk_dir else []
    for i, part in enumerate(parts):
        if "nm" in part.lower():
            if i + 1 < len(parts):
                return parts[i + 1]
            break
    return ""
 
def _run_p4(tb_srv_dir: str, cwd_dir: str, args: list[str], timeout: int = 60) -> str:
    if not tb_srv_dir or not cwd_dir or not os.path.isdir(cwd_dir):
        return ""
    setenv = f"setenv TB_SRV_DIR {tb_srv_dir}; source $TB_SRV_DIR/.cshrc;"
    cmd = f"{setenv} p4 {' '.join(args)}"
    try:
        return subprocess.check_output(["/tool/aticad/1.0/bin/tcsh", "-c", cmd], text=True, errors="ignore", cwd=cwd_dir, timeout=timeout)
    except subprocess.CalledProcessError:
        return ""
    except subprocess.TimeoutExpired:
        return ""
 
def _compute_flow_label(params: dict, basedir: str) -> tuple[str | None, int | None]:
    """Mimic Run.get_synced_label: derive best label date and mismatch count using Perforce. Returns (label_str, mismatches)."""
    flow_dir = params.get("FLOW_DIR") or basedir
    tb_srv_dir = params.get("TB_SRV_DIR") or ""
 
    if not flow_dir or not os.path.isdir(flow_dir):
        return None, None
 
    test = _run_p4(tb_srv_dir, flow_dir, ["info"], timeout=15)
    if not test or "Connect to server failed" in test:
        return "P4 Unavailable", None
 
    out = _run_p4(tb_srv_dir, flow_dir, ["have", "//depot/tools/aticad/1.0/flow/TileBuilder/supra/templates/fc_shell/..."])
    have: dict[str, int] = {}
    for line in out.splitlines():
        if line.strip() and "#" in line:
            parts = line.split("#", 1)
            if len(parts) == 2:
                depot_file = parts[0]
                try:
                    rev = int(parts[1].split()[0])
                    have[depot_file] = rev
                except (ValueError, IndexError):
                    continue
    if not have:
        return None, None
 
    labels_out = _run_p4(tb_srv_dir, flow_dir, ["labels", "-e", "TileBuildersupraRelease202*0730"])
    labels = []
    for line in labels_out.splitlines():
        m = re.match(r"^Label\s+(\S+)", line)
        if m:
            labels.append(m.group(1))
    labels = labels[-20:] if labels else []
 
    best_label = None
    best_ratio = 0.0
    best_mismatches = None
    total = len(have)
 
    for label in labels:
        fstat_out = _run_p4(
            tb_srv_dir,
            flow_dir,
            [
                "-ztag",
                "fstat",
                "-m",
                "1000000",
                "-T",
                "depotFile,headRev",
                f"//depot/tools/aticad/1.0/flow/TileBuilder/supra/templates/fc_shell/...@{label}",
            ],
            timeout=90,
        )
        if not fstat_out:
            continue
        revs: dict[str, int] = {}
        cur: dict[str, int] = {}
        for ln in fstat_out.splitlines():
            ln = ln.strip()
            if ln.startswith("... depotFile"):
                cur["file"] = ln.split(" ", 2)[2]
            elif ln.startswith("... headRev") and "file" in cur:
                try:
                    cur_rev = int(ln.split(" ", 2)[2])
                except (ValueError, IndexError):
                    cur.clear()
                    continue
                revs[cur["file"]] = cur_rev
                cur.clear()
        if revs:
            matches = sum(1 for f, r in have.items() if revs.get(f) == r)
            mismatches = sum(1 for f, r in have.items() if revs.get(f) != r)
            ratio = matches / total if total else 0.0
            if ratio > best_ratio:
                best_label, best_ratio, best_mismatches = label, ratio, mismatches
 
    if best_label:
        match = re.search(r"-(\d{2})-(\d{2})_", best_label)
        if match:
            month, day = match.groups()
            year_match = re.search(r"(\d{4})", best_label)
            year = year_match.group(1) if year_match else "2024"
            label_str = f"{year}-{month}-{day}"
            return label_str, best_mismatches
    return None, None
 
def collect_user_entries(username: str, filepath: str = CURRENT_USERS_PATH) -> list:
    """Collect and return a list of dicts with selected fields for lines where username matches."""
    results = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue
                entry = extract_json_from_line(line)
                if not isinstance(entry, dict):
                    continue
                if entry.get("username") == username:
                    rec = {k: entry.get(k) for k in FIELDS_TO_SAVE}
 
                    basedir = entry.get("basedir", "")
                    params = _load_params(basedir)
                    tech_node = _get_tech_node_from_params(params)
                    flow_label, mismatches = _compute_flow_label(params, basedir)
 
                    # Fallbacks
                    if not flow_label:
                        flow_label = entry.get("label")  # fallback to provided label field
 
                    rec["tech_node"] = tech_node
                    rec["flow_label"] = flow_label

                    if mismatches is not None:
                        rec["flow_label_mismatches"] = mismatches
 
                    results.append(rec)
    except FileNotFoundError:
        print(f"File not found: {filepath}")
    except PermissionError:
        print(f"Permission denied reading: {filepath}")
    return results
 
def write_user_entries_json(username: str, entries: list, output_dir: Path | None = None) -> Path:
    """Write entries to a JSON file named '<username>_runs.json' in output_dir (or script dir)."""
    if output_dir is None:
        output_dir = Path(__file__).parent
    output_path = output_dir / f"{username}_runs.json"
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, sort_keys=True)
    except OSError as e:
        print(f"Failed to write JSON to {output_path}: {e}")
    return output_path
 
if __name__ == "__main__":
    user_from_cmd = get_user_with_printenv()
    if not user_from_cmd:
        print("Could not determine USER from environment.")
    else:

        entries = collect_user_entries(user_from_cmd)
        for obj in entries:
            basedir_val = obj.get("basedir")
            print(basedir_val if basedir_val is not None else "<no basedir>")

        print(f"Total runs for {user_from_cmd}: {len(entries)}")

        out_path = write_user_entries_json(user_from_cmd, entries)
        print(f"Wrote {len(entries)} records to {out_path}")