#!/usr/bin/env bash
# Replay the supplementary analysis with the verifier built for Challenge 7.
set -euo pipefail

proof_dir=$(cd -- "$(dirname -- "$0")" && pwd)
work=$(realpath -e -- "${1:?usage: replay-scoped-threads.sh CHALLENGE_7_WORK_DIRECTORY}")
runtime="$work/verifast/verifast-26.10/bin"
deps="$work/verifast/vfdeps-adf88dc"

if [[ ! -x $runtime/verifast || ! -f $deps/lib/libz3.so ]]; then
    echo "Expected a Challenge 7 VeriFast build in $work/verifast" >&2
    exit 1
fi

logs="$work/scoped-thread-evidence"
mkdir -p -- "$logs"
source_nightly=$(sed -n 's/^channel = "\(.*\)"$/\1/p' "$proof_dir/../../../../../rust-toolchain.toml")
[[ -n $source_nightly ]] || { echo "No channel in rust-toolchain.toml" >&2; exit 1; }
rustc_path=$(rustup which --toolchain "$source_nightly" rustc)
export LD_LIBRARY_PATH="$runtime:$deps${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

run() {
    local name=$1
    shift
    "$@" 2>&1 | tee "$logs/$name.log"
}

run scoped-thread-boundary env RUSTUP_TOOLCHAIN=nightly-2026-09-25 \
    python3 "$proof_dir/check-scope-boundary.py" "$runtime" "$rustc_path" "$logs/scoped-thread-boundary"
run scoped-counter python3 "$proof_dir/check-scope-counter.py" "$deps/lib/libz3.so" "$logs/scoped-counter"
run scoped-composition python3 "$proof_dir/check-scope-composition.py" "$deps/lib/libz3.so" "$logs/scoped-composition"
