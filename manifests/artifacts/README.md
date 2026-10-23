# manifests/artifacts

Manifests for sim and signoff evidence stored in the fleet artifact store
(issue #218). Git keeps, per run, a `<bench>-<run-id>.manifest.json` and a
`<bench>-<run-id>.summary.md` (name, size, sha256 per object). The raw bytes
are not in the repo.

- Write them with [`sim/store_evidence.py`](../../sim/store_evidence.py), which
  calls `klt artifact put` on files staged in the git-ignored
  `evidence-scratch/<bench>-<run-id>/` directory. It fails closed: no broker
  (`$KLT_ARTIFACT_BROKER`), no `klt artifact put`, or an unreachable broker
  means a nonzero exit and nothing written.
- Every entry's `uri` must start with `artifact:`. No file here may name a
  storage bucket, cloud account or `s3://` URI, and the broker URL is never
  written down: `git grep -nE 's3://|arn:aws:' -- manifests/` must be empty.
- CI runs [`scripts/check_artifact_manifests.py`](../../scripts/check_artifact_manifests.py)
  (schema, `artifact:` URIs, and no stored object's bytes committed). It never
  contacts the broker. On a fleet worker, confirm the bytes with
  `klt artifact verify manifests/artifacts/<name>.manifest.json`.
- Manifest-forward only: evidence already committed under `sim/` stays put.
