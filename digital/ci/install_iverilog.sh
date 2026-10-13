#!/usr/bin/env bash
# Build the pinned Icarus Verilog from source into a prefix.
# usage: install_iverilog.sh PREFIX [WORKDIR]
# The source is fetched by exact git commit and verified: the checked-out
# release commit ships a generated configure.
# HEAD must equal IVERILOG_COMMIT (git object ids are content hashes), so a
# moved tag or tampered mirror fails the build.
set -euo pipefail
IVERILOG_TAG="v13_0"
IVERILOG_COMMIT="dfeee909ed9f20b4870dd93423156c0170c0e1ff"   # peeled commit of v13_0
prefix="${1:?usage: install_iverilog.sh PREFIX [WORKDIR]}"
work="${2:-$(mktemp -d)}"
jobs="${IVERILOG_JOBS:-2}"
mkdir -p "$work/src"
cd "$work/src"
git init -q .
git fetch -q --depth 1 https://github.com/steveicarus/iverilog.git "$IVERILOG_COMMIT"
git checkout -q --detach FETCH_HEAD
got="$(git rev-parse HEAD)"
if [ "$got" != "$IVERILOG_COMMIT" ]; then
  echo "iverilog source mismatch: got $got, want $IVERILOG_COMMIT" >&2
  exit 1
fi
./configure --prefix="$prefix"
make -j"$jobs"
make install
"$prefix/bin/iverilog" -V | head -1
