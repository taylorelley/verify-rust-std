set -e -x

# Run with the patched VeriFast 26.10 from build-store-verifast.sh on PATH.
# Once a VeriFast release includes the patch, set VFVERSION here instead.
cd "$(dirname "$0")"
flags="--edition=2024 --crate-type=lib"

verifast -rustc_args "$flags" -skip_specless_fns verified/lib.rs
refinement-checker --rustc-args "$flags" original/lib.rs verified/lib.rs > /dev/null

# The crate redefines core's diagnostic items, so the copies turn those four
# attributes into doc attributes. Everything else must match the library.
upstream=../../../../library/core/src/sync
for file in atomic.rs atomic_load_volatile.md atomic_store_volatile.md; do
  if ! diff original/$file <(sed 's/^#\[rustc_diagnostic_item = /#[doc = /' $upstream/$file); then
    echo "::error title=Please run verifast-proofs/core/sync/atomic.rs/update.sh::The Challenge 7 VeriFast proof is out of date."
    false
  fi
done
