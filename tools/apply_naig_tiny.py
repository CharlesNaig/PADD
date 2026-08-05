#!/usr/bin/env python3
"""Apply the NAIG Tiny-layout customization to padd.sh.

The patch is deliberately scoped to the PADD v4.1.0 Tiny layout. It refuses to
write when a required anchor is missing or duplicated inside its target block.
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


def replace_once_in_block(
    text: str,
    block_start: str,
    block_end: str,
    old: str,
    new: str,
    description: str,
) -> str:
    start_count = text.count(block_start)
    if start_count != 1:
        raise RuntimeError(
            f"Expected exactly one {description} block start, found {start_count}."
        )

    start = text.index(block_start)
    end = text.find(block_end, start + len(block_start))
    if end < 0:
        raise RuntimeError(f"Could not find the end of the {description} block.")

    block = text[start:end]
    anchor_count = block.count(old)
    if anchor_count != 1:
        raise RuntimeError(
            f"Expected exactly one {description} anchor in its block, "
            f"found {anchor_count}. The upstream file may have changed."
        )

    patched = block.replace(old, new, 1)
    return text[:start] + patched + text[end:]


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
    power_compact="P:N/A N/A V:N/A"
    power_heatmap=${yellow_text}

    # vcgencmd is available on supported Raspberry Pi systems. PADD still
    # works elsewhere; the Tiny dashboard simply reports N/A.
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
            power_flags="N/A"
            power_heatmap=${red_text}
            power_compact="P:${power_status} ${power_flags} V:${core_voltage}"
            return
            ;;
    esac

    # This is SoC Vcore, not the 5 V input rail and not total wattage.
    measured_voltage=$(vcgencmd measure_volts core 2>/dev/null | sed -n 's/^volt=\([0-9.]*V\)$/\1/p')
    if [ -n "${measured_voltage}" ]; then
        core_voltage=$(printf '%s\n' "${measured_voltage%V}" | awk '{printf "%.3fV", $1}')
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

    # Kept at 25 printable characters or fewer for the 53-column Tiny row.
    power_compact="P:${power_status} ${power_flags} V:${core_voltage}"
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
        '''    elif [ "$1" = "tiny" ]; then\n        ads_blocked_bar=$(BarGenerator "${ads_percentage_today}" 30 "color")''',
        '''    elif [ "$1" = "tiny" ]; then\n        # Compact bar leaves room for power health and Vcore on the same row.\n        ads_blocked_bar=$(BarGenerator "${ads_percentage_today}" 8 "color")''',
        "Tiny bar generator",
    )

    text = replace_once_in_block(
        text,
        '''    elif [ "$1" = "tiny" ]; then\n         # tiny is a screen at least 53x20 (columns x lines)\n''',
        '''    elif [ "$1" = "regular" ] || [ "$1" = "slim" ]; then\n''',
        '''        moveXOffset; printf "%s${clear_line}\\n" "           PADD ${padd_version_heatmap}${padd_version}${reset_text} ${tiny_status}${reset_text}"''',
        '''        moveXOffset; printf "%s${clear_line}\\n" " ${dim_text}by NAIG${reset_text}   PADD ${padd_version_heatmap}${padd_version}${reset_text} ${tiny_status}${reset_text}"''',
        "Tiny watermark header",
    )

    text = replace_once_in_block(
        text,
        '''    elif [ "$1" = "tiny" ]; then\n         # tiny is a screen at least 53x20 (columns x lines)\n''',
        '''    elif [ "$1" = "regular" ] || [ "$1" = "slim" ]; then\n''',
        '''        moveXOffset; printf " %-10s[%-30s] %-5s${clear_line}\\n" "Pi-holed:" "${ads_blocked_bar}" "${ads_percentage_today}%"''',
        '''        moveXOffset; printf " %-9s[%-8s] %-6s ${power_heatmap}%-25s${reset_text}${clear_line}\\n" "Pi-holed:" "${ads_blocked_bar}" "${ads_percentage_today}%" "${power_compact}"''',
        "Tiny compact power row",
    )

    PADD_PATH.write_text(text, encoding="utf-8", newline="\n")
    print("Applied NAIG Tiny compact power row and watermark.")


if __name__ == "__main__":
    main()
