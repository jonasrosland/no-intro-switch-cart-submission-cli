#!/usr/bin/env bash
# Sort nxdt / No-Intro gamecard dumps into: Game Title/<version>/filename
# Submission XML: ... - hitsaveorg - YYYY-MM-DD Submission.xml -> Title/_metadata/

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Tree to sort: "." = directory containing this script
SOURCE_ROOT="."
# If set, skip when destination path already exists
SKIP_EXISTING=1

sanitize() {
	local s="$1"
	s="${s//$'\r'/}"
	s="${s//\//_}"
	s="${s//\\/_}"
	s="${s//:/_}"
	s="${s//\*/_}"
	s="${s//\?/_}"
	s="${s//\"/_}"
	s="${s//</_}"
	s="${s//>/_}"
	s="${s//|/_}"
	s="${s#"${s%%[![:space:]]*}"}"
	s="${s%"${s##*[![:space:]]}"}"
	[[ -n "$s" ]] || s="_"
	printf '%s' "$s"
}

is_version_token() {
	local t="$1"
	# App semver-ish (1.2.3, 1.2.3a, …) and nxdt ".Switch" tails
	[[ "$t" =~ ^[0-9]+(\.[0-9]+)*([a-zA-Z]+|\.Switch)?$ ]] && return 0
	# Build / dated revisions (e.g. Melatonin 231013_2 …)
	[[ "$t" =~ ^[0-9]+(_[0-9A-Za-z]+)+$ ]] && return 0
	return 1
}

split_prefix() {
	local prefix="$1" last rest
	last="${prefix##* }"
	rest="${prefix% $last}"
	if is_version_token "$last"; then
		printf '%s\n%s\n' "$rest" "$last"
	else
		printf '%s\n\n' "$prefix"
	fi
}

classify() {
	local base="$1" prefix title ver
	# Prefix stops before the first "[" so dual-game carts ("Game A [tid][v] + Game B … [tid][v]")
	# still bind to the first title id / version block only.
	if [[ "$base" =~ ^([^[]+)[[:space:]]+\[(0100[0-9A-Fa-f]{12})\]\[(v[0-9]+)\] ]]; then
		prefix="${BASH_REMATCH[1]}"
		prefix="${prefix#"${prefix%%[![:space:]]*}"}"
		prefix="${prefix%"${prefix##*[![:space:]]}"}"
		readarray -t pair < <(split_prefix "$prefix")
		title="${pair[0]:-}"
		ver="${pair[1]:-}"
		if [[ -n "$title" && -n "$ver" ]]; then
			printf '%s\t%s\t%s\n' dump "$title" "$ver"
			return 0
		fi
	fi
	shopt -s nocasematch
	if [[ "$base" =~ ^(.+)[[:space:]]-[[:space:]]hitsaveorg[[:space:]]-[[:space:]][0-9]{4}-[0-9]{2}-[0-9]{2}[[:space:]]Submission\.xml$ ]]; then
		shopt -u nocasematch
		title="${BASH_REMATCH[1]}"
		title="${title#"${title%%[![:space:]]*}"}"
		title="${title%"${title##*[![:space:]]}"}"
		printf '%s\t%s\t%s\n' submission "$title" ""
		return 0
	fi
	shopt -u nocasematch
	return 1
}

destination_for() {
	local root="$1" fname="$2" title="$3" ver="$4"
	local st sv
	st="$(sanitize "$title")"
	if [[ -n "$ver" ]]; then
		sv="$(sanitize "$ver")"
		printf '%s\n' "${root}/${st}/${sv}/${fname}"
	else
		printf '%s\n' "${root}/${st}/_metadata/${fname}"
	fi
}

ROOT="$SOURCE_ROOT"
[[ "$ROOT" == /* ]] || ROOT="$SCRIPT_DIR/$ROOT"
ROOT="$(realpath "$ROOT")"

EXECUTE=0
[[ "${1:-}" == "--execute" ]] && EXECUTE=1

MOVES_SRC=()
MOVES_DST=()
MOVES_KIND=()
SKIP_MSG=()

while IFS= read -r -d '' f; do
	base="$(basename "$f")"
	if ! line="$(classify "$base")"; then
		SKIP_MSG+=("$f|no recognized dump or submission pattern")
		continue
	fi
	IFS=$'\t' read -r kind title ver <<<"$line"
	dest="$(destination_for "$ROOT" "$base" "$title" "$ver")"
	src_real="$(realpath "$f")"
	dest_real="$(realpath -m "$dest")"
	if [[ "$src_real" == "$dest_real" ]]; then
		SKIP_MSG+=("$f|already in place")
		continue
	fi
	if [[ "$SKIP_EXISTING" -ne 0 && -e "$dest" ]]; then
		SKIP_MSG+=("$f|destination exists: $dest")
		continue
	fi
	MOVES_SRC+=("$f")
	MOVES_DST+=("$dest")
	MOVES_KIND+=("$kind")
done < <(find "$ROOT" -type f \
	! -name 'sort_gamecard.sh' \
	-print0 | sort -z)

echo "Root: $ROOT"
if [[ "$EXECUTE" -eq 1 ]]; then echo "Mode: MOVE"; else echo "Mode: DRY RUN"; fi
echo

for i in "${!MOVES_SRC[@]}"; do
	printf '[%s] %s\n    -> %s\n' "${MOVES_KIND[$i]}" "${MOVES_SRC[$i]#"$ROOT"/}" "${MOVES_DST[$i]#"$ROOT"/}"
done

if ((${#SKIP_MSG[@]})); then
	echo
	echo "Skipped:"
	for e in "${SKIP_MSG[@]}"; do
		path="${e%%|*}"
		reason="${e#*|}"
		echo "  ${path#"$ROOT"/}: $reason"
	done
fi

if ((${#MOVES_SRC[@]} == 0)); then
	echo "Nothing to do."
	exit 0
fi

if [[ "$EXECUTE" -eq 0 ]]; then
	echo
	echo "Dry run. Run with: $0 --execute"
	exit 0
fi

for dest in "${MOVES_DST[@]}"; do mkdir -p "$(dirname "$dest")"; done

for i in "${!MOVES_SRC[@]}"; do mv -- "${MOVES_SRC[$i]}" "${MOVES_DST[$i]}"; done

echo
echo "Moved ${#MOVES_SRC[@]} file(s)."
