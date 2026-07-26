#!/usr/bin/env bash
set -euo pipefail

readonly LUAJIT_REPOSITORY=https://github.com/LuaJIT/LuaJIT.git
readonly LUAJIT_REVISION=a471ab78c7b670b4f92dae111fc3c96fb824c768
readonly LUAUTF8_REPOSITORY=https://github.com/starwing/luautf8.git
readonly LUAUTF8_REVISION=08b0fc930f5a52eff36348ed1ea39aadfc697fa6

engine_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
runtime_prefix="$engine_root/.runtime"

usage() {
  echo "usage: engine/runtime/build.sh [--prefix ABSOLUTE_PATH]" >&2
  exit 64
}

if (($#)); then
  [[ $# == 2 && $1 == "--prefix" && $2 == /* ]] || usage
  runtime_prefix=$2
fi

for command_name in cc git make mktemp; do
  command -v "$command_name" >/dev/null || {
    echo "runtime build: missing required command: $command_name" >&2
    exit 69
  }
done

runtime_manifest=$(printf '%s\n' \
  "luajit=$LUAJIT_REVISION" \
  "lua-utf8=$LUAUTF8_REVISION")
manifest_path="$runtime_prefix/manifest"
if [[ -x "$runtime_prefix/bin/luajit" \
      && -f "$runtime_prefix/lib/lua/5.1/lua-utf8.so" \
      && -f "$manifest_path" \
      && $(<"$manifest_path") == "$runtime_manifest" ]]; then
  echo "runtime build: pinned runtime already present at $runtime_prefix"
  exit 0
fi

if [[ -e $runtime_prefix ]]; then
  echo "runtime build: refusing to overwrite unmatched path: $runtime_prefix" >&2
  exit 73
fi

runtime_parent=$(dirname "$runtime_prefix")
mkdir -p "$runtime_parent"
task_build_root=$(mktemp -d)
runtime_stage=$(mktemp -d "$runtime_parent/.pobcalc-runtime.XXXXXX")
cleanup() {
  rm -rf -- "$task_build_root"
  if [[ -n ${runtime_stage:-} && -d $runtime_stage ]]; then
    rm -rf -- "$runtime_stage"
  fi
}
trap cleanup EXIT

fetch_revision() {
  local repository=$1
  local revision=$2
  local destination=$3
  git init -q "$destination"
  git -C "$destination" remote add origin "$repository"
  git -C "$destination" fetch -q --depth 1 origin "$revision"
  git -C "$destination" checkout -q --detach FETCH_HEAD
  local actual_revision
  actual_revision=$(git -C "$destination" rev-parse HEAD)
  [[ $actual_revision == "$revision" ]] || {
    echo "runtime build: revision mismatch for $repository" >&2
    exit 65
  }
}

luajit_source="$task_build_root/LuaJIT"
luautf8_source="$task_build_root/lua-utf8"
fetch_revision "$LUAJIT_REPOSITORY" "$LUAJIT_REVISION" "$luajit_source"
fetch_revision "$LUAUTF8_REPOSITORY" "$LUAUTF8_REVISION" "$luautf8_source"

parallelism=$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1)
make -s -C "$luajit_source" -j"$parallelism"
make -s -C "$luajit_source" install PREFIX="$runtime_stage"

mkdir -p "$runtime_stage/lib/lua/5.1"
cc -O2 -fPIC -shared \
  -I"$runtime_stage/include/luajit-2.1" \
  -o "$runtime_stage/lib/lua/5.1/lua-utf8.so" \
  "$luautf8_source/lutf8lib.c"
printf '%s\n' "$runtime_manifest" >"$runtime_stage/manifest"

"$runtime_stage/bin/luajit" -e \
  "package.cpath='$runtime_stage/lib/lua/5.1/?.so;;'; require('lua-utf8')"

mv "$runtime_stage" "$runtime_prefix"
runtime_stage=
echo "runtime build: installed pinned runtime at $runtime_prefix"
