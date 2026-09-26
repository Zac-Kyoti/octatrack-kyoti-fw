#!/usr/bin/env sh
# Sweep the ecosystem for repos we do NOT track yet.
#
# Two blind spots that `whatsnew.py` structurally cannot see, both of which cost us
# real material before 2026-09-24:
#
#   1. A contributor publishes a NEW repo. whatsnew.py only looks at what is already
#      in MANIFEST.toml, so a new repo is invisible forever.  -> pass 1
#   2. An upstream repo CREDITS somebody we do not track. octabam's
#      docs/firmware/CONTRIBUTIONS.md is the ecosystem's credit ledger and is where
#      nordseele and markandrus were found.                    -> pass 2
#
# Read-only: needs `gh` (authenticated) for pass 1; pass 2 greps the existing clones.
# Prints candidates only — adding one to MANIFEST.toml is a judgement call (scope:
# Elektron RE, specifically the Octatrack and the Analog Rytm).
set -eu
cd "$(dirname "$0")/../.."

ACCOUNTS="mxldyn mischa85 snugsound emuyia bryantysinger sambanks bkkbrls-del dsp56300 nordseele markandrus repeat98"

tracked() { grep -oE 'url *= *"[^"]+"' refs/MANIFEST.toml | sed 's|.*github.com/||; s|\.git"$||'; }

echo "=== tracked (refs/MANIFEST.toml) ==="
tracked | sort | sed 's/^/  /'

if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  echo
  echo "=== pass 1: repos on contributor accounts that we do NOT track ==="
  tracked | sort > /tmp/.kb_tracked.$$
  for u in $ACCOUNTS; do
    gh api "users/$u/repos?per_page=100&sort=pushed" \
      --jq '.[] | select(.fork == false) | "\(.full_name)\t\(.pushed_at[0:10])\t\(.description // "")"' 2>/dev/null \
    | while IFS="$(printf '\t')" read -r full pushed desc; do
        grep -qxF "$full" /tmp/.kb_tracked.$$ && continue
        case "$desc$full" in
          *[Ee]lektron*|*[Oo]ctatrack*|*octa*|*[Rr]ytm*|*[Mm]achinedrum*|*[Mm]onomachine*|*[Dd]igitakt*|*[Aa]nalog*)
            printf '  %-42s %s  %s\n' "$full" "$pushed" "$(echo "$desc" | cut -c1-70)" ;;
        esac
      done
  done
  rm -f /tmp/.kb_tracked.$$
else
  echo
  echo "(pass 1 skipped: gh not installed or not authenticated)"
fi

echo
echo "=== pass 2: repo URLs referenced INSIDE the clones that we do NOT track ==="
echo "    (octabam/docs/firmware/CONTRIBUTIONS.md is the credit ledger — read it by hand too)"
tracked | sort > /tmp/.kb_tracked.$$
# Exclude vendored third-party trees, or every C++ dependency of dsp56300 shows up.
grep -rIhoE 'https?://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+' \
     --include='*.md' --include='*.toml' --include='*.json' --include='*.py' --include='*.sh' \
     --exclude-dir=vendor --exclude-dir=node_modules --exclude-dir=.git \
     --exclude-dir=3rdparty --exclude-dir=third_party --exclude-dir=deps \
     refs/*/ 2>/dev/null \
  | sed 's|https://github.com/||; s|\.git$||' | sort | uniq -c | sort -rn \
  | while read -r n full; do
      grep -qxF "$full" /tmp/.kb_tracked.$$ && continue
      case "$full" in
        sponsors/*|*/sponsors) continue ;;
      esac
      # keep only names that look Elektron/Octatrack-adjacent; everything else is a
      # build dependency of somebody's emulator, not RE research.
      case "$full" in
        *octa*|*Octa*|*OCTA*|*elektron*|*Elektron*|*rytm*|*Rytm*|*ems-*|*midisc*|*mc68k*|*dsp56300*|*machinedrum*|*monomachine*|*gearmulator*)
          printf '  %4s refs  %s\n' "$n" "$full" ;;
      esac
    done
rm -f /tmp/.kb_tracked.$$

echo
echo "Scope gate before adding any of the above to refs/MANIFEST.toml:"
echo "  Elektron reverse engineering, specifically the OCTATRACK and the ANALOG RYTM."
echo "  Machinedrum / Monomachine / Digitakt work is adjacent, not in scope — note it,"
echo "  do not track it, unless it states facts about OT or AR hardware."
