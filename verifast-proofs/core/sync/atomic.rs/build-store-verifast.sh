#!/usr/bin/env bash
# Build a patched VeriFast executable and pair it with the 26.10 release tools.
set -euo pipefail

proof_dir=$(cd -- "$(dirname -- "$0")" && pwd)
work=$(realpath -m -- "${1:?usage: build-store-verifast.sh NEW_BUILD_DIRECTORY [ARCHIVES]}")
archives=${2:+$(realpath -- "$2")}
mkdir -- "$work"
cd -- "$work"

download() {
    local file=$1 url=$2 digest=$3
    if [[ -n $archives && -f $archives/$file ]]; then
        cp -- "$archives/$file" "$file"
    else
        curl --fail --location --retry 2 --output "$file" "$url"
    fi
    echo "$digest  $file" | sha256sum --check --strict
}

source_commit=f76012fb518703b1d98e243ac4f487f16877cfcb # tag 26.10
if [[ -n $archives && -f $archives/source.tgz ]] || \
    curl --fail --location --retry 2 --output source.tgz \
        https://api.github.com/repos/verifast/verifast/tarball/26.10; then
    [[ -f source.tgz ]] || cp -- "$archives/source.tgz" source.tgz
    echo "8059ea1041685da2d2da52f720a28c22b0f13b963f38a02abdfff5ed51673493  source.tgz" |
        sha256sum --check --strict
    mkdir source
    tar -xzf source.tgz -C source --strip-components=1
else
    # Some networks block the tarball endpoint. Fall back to the tagged commit.
    git clone --quiet --depth 1 --branch 26.10 https://github.com/verifast/verifast source
    [[ $(git -C source rev-parse HEAD) == "$source_commit" ]] ||
        { echo "VeriFast tag 26.10 does not name commit $source_commit" >&2; exit 1; }
fi
download deps.txz https://github.com/verifast/vfdeps/releases/download/25.01/vfdeps-adf88dc-linux.txz \
    8d022c93d51a1d13ec1e782d767c60462405f6865d5ee416f82d6234e93ee580
download runtime.tgz https://github.com/verifast/verifast/releases/download/26.10/verifast-26.10-linux.tar.gz \
    5ad2a65997457fd5996a27f93107ef7e52c90c0d12b63b6e67f7acbc73e90efd

tar -xjf deps.txz
tar -xzf runtime.tgz

deps="$work/vfdeps-adf88dc"
runtime="$work/verifast-26.10/bin"
export PATH="$work/decoder/bin:$deps/bin:$PATH"
export OCAMLLIB="$deps/lib/ocaml" OCAMLPATH="$deps/lib/ocaml"
export OCAMLFIND_CONF="$deps/etc/findlib-relocated.conf"
export CAML_LD_LIBRARY_PATH="$deps/lib/ocaml/stublibs"
export CAPNP_INC_DIR="$deps/include" CAPNP_INCLUDE="$deps/include"
export LIBRARY_PATH="$deps/lib:$runtime"
export LD_LIBRARY_PATH="$deps/lib:$runtime"
cat > "$OCAMLFIND_CONF" <<CONFIG
destdir="$deps/lib/ocaml"
path="$deps/lib/ocaml"
ocamlc="ocamlc.opt"
ocamlopt="ocamlopt.opt"
ocamlmklib="ocamlmklib"
CONFIG

cargo +nightly-2026-09-25 install --locked --git https://github.com/btj/capnpc-ocaml-decoder \
    --rev 2d6606d9b59cd0c88a66729f3f076c10c0c8e0b2 --root "$work/decoder"
git -C source apply "$proof_dir/verifast-26.10.patch"
rust_sysroot=$(rustc +nightly-2026-09-25 --print sysroot)
LIBRARY_PATH="$LIBRARY_PATH:$rust_sysroot/lib" \
    cargo +nightly-2026-09-25 build --release --locked \
    --manifest-path source/src/rust_frontend/vf_mir_exporter/Cargo.toml
(cd source/src && dune build -j "${CARGO_BUILD_JOBS:-4}" vfconsole/vfconsole.exe refinement_checker/main.exe)
rm -- "$runtime/vf-rust-mir-exporter"
cp source/src/rust_frontend/vf_mir_exporter/target/release/vf_mir_exporter "$runtime/vf-rust-mir-exporter"
rm -- "$runtime/verifast"
cp source/src/_build/default/vfconsole/vfconsole.exe "$runtime/verifast"
rm -- "$runtime/refinement-checker"
cp source/src/_build/default/refinement_checker/main.exe "$runtime/refinement-checker"
rm -- "$runtime/rust/std/lib.rsspec"
cp source/bin/rust/std/lib.rsspec "$runtime/rust/std/lib.rsspec"
printf 'Run the patched binary with LD_LIBRARY_PATH=%s\n' "$runtime:$deps/lib"
