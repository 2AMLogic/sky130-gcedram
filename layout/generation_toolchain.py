#!/usr/bin/env python3
"""generation_toolchain.py -- pinned klt toolchains for the array layout
generation paths (issue #91).

`layout/generate_array.sh` and the scaling builds in
`layout/extract_array_parasitics.sh` used whatever `klt` was on PATH. The
committed 4x4 array then stopped reproducing once klt moved on. This helper
is the one place the generation pin lives (data in
`layout/generation-toolchain.json`), and both scripts call it before they
write anything.

Two toolchains, kept separate on purpose:

  generation  `klt gen mos_array` + `klt gen-compose`. The revision that
              reproduces the committed GDS byte-for-byte.
  check       `klt drc` / `klt lvs` / `klt erc` status gates. The revision
              that produced the committed DRC/LVS/ERC reports (the same one
              `.github/workflows/signoff.yml` pins).

Parasitic extraction is NOT pinned here: it has its own documented toolchain
(see layout/README.md), and the generation revision predates extraction
features that the committed extraction uses.

A toolchain is identified by a Python interpreter whose environment has
klayout-tools installed. Default location (gitignored):

    <repo>/.toolchains/klt-<role>-<commit12>-klayout-<version>/bin/python

overridable per role with GCEDRAM_KLT_GENERATION_PYTHON /
GCEDRAM_KLT_CHECK_PYTHON, or for the whole directory with
GCEDRAM_TOOLCHAIN_DIR. The helper never installs implicitly; a missing or
mismatched toolchain fails with the exact install command.

Subcommands:

  install   --role R        create the default venv for R with uv (explicit)
  preflight --role R ...    verify each role (and, with --pdk, the PDK pin);
                            on success print `KLT_<ROLE>=<path to klt>` shell
                            assignments; on failure print expected/actual
                            diagnostics to stderr and exit 2
  identity  --role R        print the probed identity as JSON
  record    ...             write a reproduction run record (JSON)

Stdlib only.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

LAYOUT_DIR = Path(__file__).resolve().parent
REPO_ROOT = LAYOUT_DIR.parent
CONFIG_PATH = LAYOUT_DIR / "generation-toolchain.json"
ROLES = ("generation", "check")
EXIT_TOOLCHAIN = 2

# Run inside the candidate interpreter with -I. Prints one JSON object.
PROBE = r"""
import json, os, sys
out = {"python_executable": sys.executable,
       "python_version": sys.version.split()[0],
       "klayout_tools_version": None, "klayout_tools_commit": None,
       "klayout_tools_url": None, "klayout_version": None, "errors": []}
try:
    import importlib.metadata as md
    dist = md.distribution("klayout-tools")
    out["klayout_tools_version"] = dist.version
    raw = dist.read_text("direct_url.json")
    if raw:
        du = json.loads(raw)
        out["klayout_tools_url"] = du.get("url")
        out["klayout_tools_commit"] = (du.get("vcs_info") or {}).get("commit_id")
except Exception as exc:
    out["errors"].append("klayout-tools not importable: %s" % exc)
try:
    import klayout
    out["klayout_version"] = getattr(klayout, "__version__", None)
except Exception as exc:
    out["errors"].append("klayout not importable: %s" % exc)
klt = os.path.join(os.path.dirname(sys.executable), "klt")
out["klt_path"] = klt if os.path.isfile(klt) and os.access(klt, os.X_OK) else None
print(json.dumps(out))
"""


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    with open(path) as fh:
        return json.load(fh)


def role_config(cfg: dict[str, Any], role: str) -> dict[str, Any]:
    try:
        return cfg["toolchains"][role]
    except KeyError:
        raise SystemExit(f"FAIL: unknown toolchain role {role!r} (known: {', '.join(cfg['toolchains'])})")


def requirement_specs(rc: dict[str, Any]) -> list[str]:
    kt = rc["klayout_tools"]
    return [f"klayout-tools @ git+{kt['git_url']}@{kt['commit']}", f"klayout=={rc['klayout']}"]


def env_var_for(role: str) -> str:
    return f"GCEDRAM_KLT_{role.upper()}_PYTHON"


def default_venv(role: str, rc: dict[str, Any], env: dict[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    base = Path(env.get("GCEDRAM_TOOLCHAIN_DIR") or (REPO_ROOT / ".toolchains"))
    return base / f"klt-{role}-{rc['klayout_tools']['commit'][:12]}-klayout-{rc['klayout']}"


def resolve_python(role: str, rc: dict[str, Any], env: dict[str, str] | None = None) -> tuple[str, str]:
    """(python path, where it came from)."""
    env = os.environ if env is None else env
    override = env.get(env_var_for(role))
    if override:
        return override, f"${env_var_for(role)}"
    return str(default_venv(role, rc, env) / "bin" / "python"), "default venv"


def install_hint(role: str, rc: dict[str, Any], env: dict[str, str] | None = None) -> str:
    venv = default_venv(role, rc, env)
    specs = " ".join(shlex.quote(s) for s in requirement_specs(rc))
    return (
        f"    python3 layout/generation_toolchain.py install --role {role}\n"
        f"  which runs:\n"
        f"    uv venv {shlex.quote(str(venv))}\n"
        f"    uv pip install --python {shlex.quote(str(venv / 'bin' / 'python'))} {specs}\n"
        f"  or point {env_var_for(role)} at a Python whose environment has: {specs}"
    )


def probe(python: str, timeout: float = 120.0) -> tuple[dict[str, Any] | None, str | None]:
    """Run PROBE in `python`. Returns (identity, error)."""
    if not os.path.exists(python):
        return None, f"interpreter not found: {python}"
    try:
        proc = subprocess.run([python, "-I", "-c", PROBE], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"could not run {python}: {exc}"
    if proc.returncode != 0:
        return None, f"{python} exited {proc.returncode}: {proc.stderr.strip()[:500]}"
    try:
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        return json.loads(lines[-1]), None
    except (ValueError, IndexError):
        return None, f"{python} printed no identity JSON: {proc.stdout.strip()[:500]}"


def identity_problems(rc: dict[str, Any], ident: dict[str, Any]) -> list[str]:
    """Expected-vs-actual mismatches; empty list = toolchain matches the pin."""
    problems = list(ident.get("errors") or [])
    kt = rc["klayout_tools"]
    checks = [
        ("klayout-tools commit", kt["commit"], ident.get("klayout_tools_commit")),
        ("klayout-tools package version", kt["package_version"], ident.get("klayout_tools_version")),
        ("klayout (KLayout Python module) version", rc["klayout"], ident.get("klayout_version")),
    ]
    for label, expected, actual in checks:
        if actual != expected:
            problems.append(f"{label}: expected {expected}, actual {actual}")
    if not ident.get("klt_path"):
        problems.append("no executable `klt` next to the interpreter (klayout-tools console script missing)")
    return problems


def pdk_identity(pdk_root: str | None, pdk: str | None) -> dict[str, Any]:
    ident: dict[str, Any] = {"pdk_root": pdk_root, "pdk": pdk, "sources_file": None, "open_pdks_commit": None}
    if not pdk_root or not pdk:
        return ident
    sources = Path(pdk_root) / pdk / "SOURCES"
    ident["sources_file"] = str(sources)
    if sources.is_file():
        for line in sources.read_text(errors="replace").splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "open_pdks":
                ident["open_pdks_commit"] = parts[1]
                break
    return ident


def pdk_problems(cfg: dict[str, Any], ident: dict[str, Any]) -> list[str]:
    exp = cfg["pdk"]
    problems = []
    if not ident.get("pdk_root") or not ident.get("pdk"):
        return ["PDK_ROOT/PDK not set -- run 'source design/env.sh' first"]
    if ident["pdk"] != exp["variant"]:
        problems.append(f"PDK variant: expected {exp['variant']}, actual {ident['pdk']}")
    if ident.get("open_pdks_commit") != exp["open_pdks_commit"]:
        problems.append(
            f"open_pdks commit ({ident.get('sources_file')}): expected {exp['open_pdks_commit']}, "
            f"actual {ident.get('open_pdks_commit')}  -- fix: pip install ciel==2.6.1; ciel enable --pdk-family sky130 -l sky130_fd_pr {exp['open_pdks_commit']}"
        )
    return problems


def preflight(roles: list[str], check_pdk: bool, cfg: dict[str, Any], env: dict[str, str] | None = None,
              out=sys.stdout, err=sys.stderr) -> int:
    env = os.environ if env is None else env
    failed = False
    assignments = []
    for role in roles:
        rc = role_config(cfg, role)
        python, origin = resolve_python(role, rc, env)
        ident, error = probe(python)
        problems = [error] if error else identity_problems(rc, ident)
        if problems:
            failed = True
            print(f"FAIL: {role} toolchain unavailable or mismatched (pin: layout/generation-toolchain.json)", file=err)
            print(f"  interpreter ({origin}): {python}", file=err)
            for p in problems:
                print(f"  - {p}", file=err)
            print("  fix:", file=err)
            print(install_hint(role, rc, env), file=err)
            continue
        assignments.append(f"KLT_{role.upper()}={shlex.quote(ident['klt_path'])}")
        assignments.append(f"KLT_{role.upper()}_PYTHON={shlex.quote(python)}")
    if check_pdk:
        ident = pdk_identity(env.get("PDK_ROOT"), env.get("PDK"))
        problems = pdk_problems(cfg, ident)
        if problems:
            failed = True
            print("FAIL: PDK does not match the pin (docs/pdk-pin.md)", file=err)
            for p in problems:
                print(f"  - {p}", file=err)
    if failed:
        print("No artifacts were written.", file=err)
        return EXIT_TOOLCHAIN
    for line in assignments:
        print(line, file=out)
    return 0


def cmd_install(args, cfg) -> int:
    rc = role_config(cfg, args.role)
    venv = default_venv(args.role, rc)
    uv = os.environ.get("GCEDRAM_UV", "uv")
    py = venv / "bin" / "python"
    cmds = [[uv, "venv", str(venv)], [uv, "pip", "install", "--python", str(py), *requirement_specs(rc)]]
    if py.exists():
        cmds = cmds[1:]
    for c in cmds:
        print("+ " + " ".join(shlex.quote(x) for x in c), file=sys.stderr)
        try:
            subprocess.run(c, check=True)
        except FileNotFoundError:
            print(f"FAIL: {uv} not found -- install uv, or create the venv by hand:\n{install_hint(args.role, rc)}",
                  file=sys.stderr)
            return EXIT_TOOLCHAIN
        except subprocess.CalledProcessError as exc:
            print(f"FAIL: {' '.join(c)} exited {exc.returncode}", file=sys.stderr)
            return EXIT_TOOLCHAIN
    print(py)
    return 0


def cmd_identity(args, cfg) -> int:
    rc = role_config(cfg, args.role)
    python = args.python or resolve_python(args.role, rc)[0]
    ident, error = probe(python)
    if error:
        print(f"FAIL: {error}", file=sys.stderr)
        return EXIT_TOOLCHAIN
    ident["matches_pin"] = not identity_problems(rc, ident)
    print(json.dumps(ident, indent=2))
    return 0


def git_source() -> dict[str, Any]:
    def run(*a):
        p = subprocess.run(["git", "-C", str(REPO_ROOT), *a], capture_output=True, text=True)
        return p.stdout.strip() if p.returncode == 0 else None
    status = run("status", "--porcelain")
    return {"commit": run("rev-parse", "HEAD"), "dirty": bool(status) if status is not None else None}


def cmd_record(args, cfg) -> int:
    toolchains = {}
    for role in ROLES:
        rc = role_config(cfg, role)
        python = os.environ.get(f"KLT_{role.upper()}_PYTHON") or resolve_python(role, rc)[0]
        ident, error = probe(python)
        toolchains[role] = {"pin": rc, "identity": ident, "error": error,
                            "matches_pin": bool(ident) and not identity_problems(rc, ident)}
    comparison = None
    if args.comparison and Path(args.comparison).is_file():
        comparison = json.loads(Path(args.comparison).read_text())
    statuses = dict(kv.split("=", 1) for kv in args.status)
    commands = Path(args.commands).read_text().splitlines() if args.commands and Path(args.commands).is_file() else []
    record = {
        "schema_version": 1,
        "kind": "gain_cell_2t_array generation reproduction record (issue #91)",
        "recorded_at_utc": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "script": args.script,
        "mode": args.mode,
        "array": args.array,
        "baseline": args.baseline,
        "source": git_source(),
        "toolchains": toolchains,
        "pdk": {"pin": cfg["pdk"], "identity": pdk_identity(os.environ.get("PDK_ROOT"), os.environ.get("PDK"))},
        "commands": commands,
        "statuses": statuses,
        "comparison": comparison,
        "result": args.result,
    }
    Path(args.out).write_text(json.dumps(record, indent=2) + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(CONFIG_PATH))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("install")
    p.add_argument("--role", choices=ROLES, required=True)
    p = sub.add_parser("preflight")
    p.add_argument("--role", choices=ROLES, action="append", required=True)
    p.add_argument("--pdk", action="store_true", help="also verify PDK_ROOT/PDK against the PDK pin")
    p = sub.add_parser("identity")
    p.add_argument("--role", choices=ROLES, required=True)
    p.add_argument("--python")
    p = sub.add_parser("record")
    p.add_argument("--out", required=True)
    p.add_argument("--script", required=True)
    p.add_argument("--mode", required=True)
    p.add_argument("--array", required=True)
    p.add_argument("--baseline", required=True, help="what the run was compared against, or why it was not")
    p.add_argument("--comparison")
    p.add_argument("--commands")
    p.add_argument("--status", action="append", default=[], help="name=value, repeatable")
    p.add_argument("--result", required=True)
    args = ap.parse_args(argv)
    cfg = load_config(Path(args.config))
    if args.cmd == "install":
        return cmd_install(args, cfg)
    if args.cmd == "preflight":
        return preflight(args.role, args.pdk, cfg)
    if args.cmd == "identity":
        return cmd_identity(args, cfg)
    return cmd_record(args, cfg)


if __name__ == "__main__":
    sys.exit(main())
