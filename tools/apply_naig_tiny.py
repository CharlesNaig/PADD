#!/usr/bin/env python3
"""Apply the NAIG Tiny-layout customization to padd.sh.

This script is intentionally strict: it refuses to write when the expected
upstream PADD v4.1.0 anchors are missing or duplicated.
"""

from pathlib import Path


PADD_PATH = Path("padd.sh")
MARKER = "# NAIG Tiny power monitor"


def replace_once(text: str, old: str, new: str, description: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Expected exactly one {description} anchor, found {count}. "
            "The upstream file may have changed."
        )
    return text.replace(old, new, 1)


def main() -> None:
    text = PADD_PATH.read_text(encoding="utf-8")

    if MARKER in text:
        print("NAIG Tiny customization is already present.")
        return

    power_function = r'''# NAIG Tiny power monitor
GetPowerInformation() {
    local throttle_raw throttle_value measured_voltage

    power_status="N/A"
    power_flags="N/A"
    core_voltage="N/A"
    power_heatmap=${yellow_text}

    # vcgencmd is available on supported Raspberry Pi systems. PADD still
    # works on other platforms; the Tiny dashboard simply reports N/A.
    if ! command -v vcgencmd >/dev/null 2>&1; then
        return
    fi

    throttle_raw=$(vcgencmd get_throttled 2>/dev/null)
    case "${throttle_raw}" in
        throttled=0x*)
            power_flags=${throttle_raw#*=}
            throttle_value=$((power_flags))
            ;;
        *)
            power_status="READ ERR"
            power_heatmap=${red_text}
            return
            ;;
    esac

    # This is the SoC core voltage, not the 5 V input rail and not wattage.
    measured_voltage=$(vcgencmd measure_volts core 2>/dev/null | sed -n 's/^volt=\([0-9.]*V\)$/\1/p')
    if [ -n "${measured_voltage}" ]; then
        core_voltage=${measured_voltage}
    fi

    # Current conditions take priority over historical flags.
    if [ $((throttle_value & 0x5)) -eq 5 ]; then
        power_status="UV+THR"
        power_heatmap=${red_text}
    elif [ $((throttle_value & 0x1)) -ne 0 ]; then
        power_status="UV"
        power_heatmap=${red_text}
    elif [ $((throttle_value & 0x4)) -ne 0 ]; then
        power_status="THR"
        power_heatmap=${red_text}
    elif [ $((throttle_value & 0x2)) -ne 0 ]; then
        power_status="CAP"
        power_heatmap=${yellow_text}
    elif [ $((throttle_value & 0x8)) -ne 0 ]; then
        power_status="TEMP"
        power_heatmap=${yellow_text}
    elif [ $((throttle_value & 0xF0000)) -ne 0 ]; then
        power_status="HIST"
        power_heatmap=${yellow_text}
    else
        power_status="OK"
        power_heatmap=${green_text}
    fi
}

'''

    text = replace_once(
        text,
        "GetSystemInformation() {\n",
        power_function + "GetSystemInformation() {\n",
        "GetSystemInformation function",
    )

    text = replace_once(
        text,
        "GetSystemInformation() {\n\n    if [ \"${connection_down_flag}\" = true ]; then",
        "GetSystemInformation() {\n\n    GetPowerInformation\n\n    if [ \"${connection_down_flag}\" = true ]; then",
        "GetSystemInformation entry",
    )

    text = replace_once(
        text,
        '''        top_client=$(truncateString "${top_client_raw}" 41)\n\n    elif [ "$1" = "regular" ] || [ "$1" = "slim" ]; then''',
        '''        top_client=$(truncateString "${top_client_raw}" 41)\n\n        # Leave room for the power-health fields on the Tiny STATS lines.\n        latest_blocked_tiny=$(truncateString "${latest_blocked_raw}" 18)\n        top_blocked_tiny=$(truncateString "${top_blocked_raw}" 18)\n\n    elif [ "$1" = "regular" ] || [ "$1" = "slim" ]; then''',
        "Tiny size-dependent output",
    )

    text = replace_once(
        text,
        '''        moveXOffset; printf "%s${clear_line}\\n" "           PADD ${padd_version_heatmap}${padd_version}${reset_text} ${tiny_status}${reset_text}"''',
        '''        moveXOffset; printf "%s${clear_line}\\n" " ${dim_text}by NAIG${reset_text}  PADD ${padd_version_heatmap}${padd_version}${reset_text}  ${tiny_status}${reset_text}"''',
        "Tiny watermark header",
    )

    text = replace_once(
        text,
        '''        moveXOffset; printf " %-10s%-39s${clear_line}\\n" "Latest:" "${latest_blocked}"\n        moveXOffset; printf " %-10s%-39s${clear_line}\\n" "Top Ad:" "${top_blocked}"''',
        '''        moveXOffset; printf " %-10s%-18s %-6s${power_heatmap}%-14s${reset_text}${clear_line}\\n" "Latest:" "${latest_blocked_tiny}" "Power:" "${power_status} ${power_flags}"\n        moveXOffset; printf " %-10s%-18s %-6s${power_heatmap}%-14s${reset_text}${clear_line}\\n" "Top Ad:" "${top_blocked_tiny}" "Vcore:" "${core_voltage}"''',
        "Tiny power display",
    )

    PADD_PATH.write_text(text, encoding="utf-8", newline="\n")
    print("Applied NAIG Tiny power monitor and watermark.")


if __name__ == "__main__":
    main()
