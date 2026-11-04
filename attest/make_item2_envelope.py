#!/usr/bin/env python3
"""Write attest/item2.envelope.json: the hand-written generic envelope for T1
item 2 (Layout).

`klt signoff --attest` does not produce item 2 (its binding is the committed
layout itself), so this binds the two layouts and their generator scripts via
`provenance.input.paths` (a set binding, klayout-tools#3044). The combined
digest follows klt's `input_set_digest`: sha256 over the lines
"<hex>  <path>\\n", sorted bytewise by path. Editing any member turns the
manifest row stale. Stdlib only; run from the repo root:

    python3 -I attest/make_item2_envelope.py
"""
import hashlib
import json
import os

MEMBERS = [
    "layout/gain_cell_2t.gds",
    "layout/gain_cell_2t_array.gds",
    "layout/generate.sh",
    "layout/generate_array.sh",
    "layout/generation_toolchain.py",
]
OUT = "attest/item2.envelope.json"


def _sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def main():
    hashes = {p: _sha(p) for p in MEMBERS}
    body = "".join(f"{hashes[p]}  {p}\n" for p in sorted(MEMBERS, key=lambda p: p.encode()))
    combined = "sha256:" + hashlib.sha256(body.encode()).hexdigest()
    env = {
        "schema_version": 1,
        "kind": "generic",
        "status": "pass",
        "t1_item": 2,
        "summary": "T1 item 2 (Layout): the committed bitcell and 4x4 array GDS "
                   "bound to the scripts that generate them",
        "source": "attest/make_item2_envelope.py",
        "provenance": {
            "klt_version": None,
            "klayout_version": None,
            "pdk": None,
            "deck": None,
            "input": {
                "paths": [
                    {"path": {"path": p, "scope": "repo"}, "content_hash": "sha256:" + hashes[p]}
                    for p in sorted(MEMBERS)
                ],
                "content_hash": combined,
            },
        },
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(env, fh, indent=2)
        fh.write("\n")
    print(combined)


if __name__ == "__main__":
    main()
