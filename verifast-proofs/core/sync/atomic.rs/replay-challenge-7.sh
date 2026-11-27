#!/usr/bin/env bash
# Build VeriFast from pinned inputs and replay the Challenge 7 proof and test matrix.
set -euo pipefail

proof_dir=$(cd -- "$(dirname -- "$0")" && pwd)
work=$(realpath -m -- "${1:?usage: replay-challenge-7.sh NEW_WORK_DIRECTORY [VERIFAST_ARCHIVES]}")
shift
mkdir -- "$work"
logs="$work/evidence"
mkdir -- "$logs"
# The source nightly follows the fork's toolchain file so subtree updates need no edit here.
source_nightly=$(sed -n 's/^channel = "\(.*\)"$/\1/p' "$proof_dir/../../../../rust-toolchain.toml")
[[ -n $source_nightly ]] || { echo "No channel in rust-toolchain.toml" >&2; exit 1; }
verifier_nightly=nightly-2026-09-25
cross_target=aarch64-unknown-linux-gnu
export CARGO_BUILD_JOBS="${CARGO_BUILD_JOBS:-4}"

run() {
    local name=$1
    shift
    printf '\n=== %s ===\n' "$name"
    "$@" 2>&1 | tee "$logs/$name.log"
}

rustc_path=$(rustup which --toolchain "$source_nightly" rustc)
{
    "$rustc_path" -vV
    rustc "+$verifier_nightly" -vV
    sha256sum "$proof_dir/verifast-26.10-u8-store.patch"
} > "$logs/toolchains-and-patch.txt"

run build bash "$proof_dir/build-store-verifast.sh" "$work/verifast" "$@"
runtime="$work/verifast/verifast-26.10/bin"
export LD_LIBRARY_PATH="$runtime:$work/verifast/vfdeps-adf88dc${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

run bool-clients python3 "$proof_dir/check-bool-clients.py" "$rustc_path"
prove() {
    local name=$1 script=$2
    shift 2
    run "$name" env RUSTUP_TOOLCHAIN="$verifier_nightly" \
        python3 "$proof_dir/$script.py" "$runtime" "$rustc_path" "$logs/$name" "$@"
}

prove constructors check-from-ptr
prove generic-helpers check-generic-helpers
prove bool-access check-bool-store
prove u16-mixed-width check-u16
prove integer-access check-integer-access
prove exchange check-swap
prove compare-exchange check-compare-exchange
prove arithmetic check-arithmetic
prove bitwise check-arithmetic --bitwise
prove extrema check-arithmetic --extrema

# Compile the clients in a standalone dependency-free package. Each file remains
# a separate test crate so context-specific nightly features stay local to it.
clients="$work/clients"
mkdir -p -- "$clients/tests"
cat >"$clients/Cargo.toml" <<'TOML'
[package]
name = "challenge-7-clients"
version = "0.0.0"
edition = "2024"
TOML
for client in bool-clients ptr-client integer-access-client swap-client compare-exchange-client arithmetic-client bitwise-client extrema-client scope-lifecycle-client; do
    cp -- "$proof_dir/$client.rs" "$clients/tests/$client.rs"
done
manifest="$clients/Cargo.toml"
export MIRIFLAGS="-Zmiri-tree-borrows -Zmiri-seed=0"
run native cargo "+$source_nightly" test --offline --manifest-path "$manifest"
run miri-x86-64 cargo "+$source_nightly" miri test --offline --manifest-path "$manifest"
run miri-aarch64 cargo "+$source_nightly" miri test --offline --manifest-path "$manifest" \
    --target "$cross_target"
run miri-weak-failure env MIRIFLAGS="$MIRIFLAGS -Zmiri-compare-exchange-weak-failure-rate=0.9" \
    cargo "+$source_nightly" miri test --offline --manifest-path "$manifest" \
    --test compare-exchange-client -- --ignored

printf 'All Challenge 7 proofs and clients passed. Evidence in %s\n' "$logs" | tee "$logs/result.log"
