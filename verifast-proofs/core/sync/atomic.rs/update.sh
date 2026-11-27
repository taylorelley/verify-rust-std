set -x -e

cd "$(dirname "$0")"
if ! git diff --quiet .; then
  echo "Working directory not clean. Please stash your changes and try again"
  false
else
  upstream=../../../../library/core/src/sync
  sed 's/^#\[rustc_diagnostic_item = /#[doc = /' $upstream/atomic.rs > atomic.rs.upstream
  git merge-file --diff3 verified/atomic.rs original/atomic.rs atomic.rs.upstream
  mv atomic.rs.upstream original/atomic.rs
  for doc in atomic_load_volatile.md atomic_store_volatile.md; do
    cp $upstream/$doc original/$doc
    cp $upstream/$doc verified/$doc
  done
fi
