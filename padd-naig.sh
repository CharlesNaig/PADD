#!/usr/bin/env sh

# Launch the NAIG-customized Tiny dashboard without modifying the tracked
# upstream padd.sh file. The temporary copy is patched on every launch so the
# customization remains easy to rebase onto later PADD releases.

set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
temp_dir=$(mktemp -d "${TMPDIR:-/tmp}/padd-naig.XXXXXX")

cleanup() {
    rm -rf "${temp_dir}"
}
trap cleanup EXIT INT TERM

# The Waveshare 480x320 tty normally provides 60 columns by 20 rows. PADD Tiny
# is 53 columns wide, so keeping the tty at 60 columns lets PADD's native
# xOffset calculation center the dashboard instead of pinning it to the left.
# These can be overridden for a different terminal.
if [ -t 0 ] || [ -t 1 ]; then
    stty rows "${PADD_NAIG_ROWS:-20}" cols "${PADD_NAIG_COLS:-60}" 2>/dev/null || true
fi

cp "${script_dir}/padd.sh" "${temp_dir}/padd.sh"
mkdir -p "${temp_dir}/tools"
cp "${script_dir}/tools/apply_naig_tiny.py" "${temp_dir}/tools/apply_naig_tiny.py"

(
    cd "${temp_dir}"
    python3 tools/apply_naig_tiny.py >/dev/null
    dash -n padd.sh
    chmod +x padd.sh
    ./padd.sh "$@"
)
