#!/usr/bin/env python3
"""Apply the NAIG Tiny-layout and hardware-monitor customization to padd.sh.

This script is intentionally strict: it refuses to write when the expected
upstream PADD v4.1.0 anchors are missing or duplicated.
"""

from pathlib import Path


PADD_PATH = Path("padd.sh")
MARKER = "# NAIG Tiny power and UPS monitor"
LEGACY_MARKER = "# NAIG Tiny power monitor"


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

    if LEGACY_MARKER in text:
        raise RuntimeError(
            "Detected a legacy NAIG Tiny customization. Reapply this patcher "
            "to a pristine padd.sh so the UPS layout can be installed safely."
        )

    power_function = r'''# NAIG Tiny power and UPS monitor
GetUPSInformation() {
    local ups_low_raw ups_high_raw ups_low ups_high ups_percentage

    ups_battery="N/A"
    ups_heatmap=${yellow_text}

    # EP-0136 reports battery capacity as a little-endian 16-bit value in
    # registers 0x13 and 0x14 on I2C bus 1, device address 0x17.
    if ! command -v i2cget >/dev/null 2>&1; then
        return
    fi

    ups_low_raw=$(i2cget -y 1 0x17 0x13 b 2>/dev/null) || return
    ups_high_raw=$(i2cget -y 1 0x17 0x14 b 2>/dev/null) || return

    # i2cget should return exactly one byte in 0xNN form. Validate it before
    # passing the values to shell arithmetic.
    case "${ups_low_raw}" in
        0x[0-9a-fA-F][0-9a-fA-F]) ;;
        *) return ;;
    esac
    case "${ups_high_raw}" in
        0x[0-9a-fA-F][0-9a-fA-F]) ;;
        *) return ;;
    esac

    ups_low=$((ups_low_raw))
    ups_high=$((ups_high_raw))
    ups_percentage=$(( (ups_high << 8) | ups_low ))

    if [ "${ups_percentage}" -gt 100 ]; then
        return
    fi

    ups_battery="${ups_percentage}%"
    if [ "${ups_percentage}" -ge 50 ]; then
        ups_heatmap=${green_text}
    elif [ "${ups_percentage}" -ge 25 ]; then
        ups_heatmap=${yellow_text}
    else
        ups_heatmap=${red_text}
    fi
}

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
        "GetSystemInformation() {\n\n    GetPowerInformation\n    GetUPSInformation\n\n    if [ \"${connection_down_flag}\" = true ]; then",
        "GetSystemInformation entry",
    )

    text = replace_once(
        text,
        '''        moveXOffset; printf "%s${clear_line}\\n" "           PADD ${padd_version_heatmap}${padd_version}${reset_text} ${tiny_status}${reset_text}"''',
        '''        moveXOffset; printf "%s${clear_line}\\n" " ${dim_text}by NAIG${reset_text}  PADD ${padd_version_heatmap}${padd_version}${reset_text}  ${tiny_status}${reset_text}"''',
        "Tiny watermark header",
    )

    text = replace_once(
        text,
        '''        moveXOffset; printf " %-10s%-29s${clear_line}\\n" "Blocking:" "${domains_being_blocked} domains"\n        moveXOffset; printf " %-10s[%-30s] %-5s${clear_line}\\n" "Pi-holed:" "${ads_blocked_bar}" "${ads_percentage_today}%"\n        moveXOffset; printf " %-10s%-39s${clear_line}\\n" "Pi-holed:" "${ads_blocked_today} out of ${dns_queries_today}"\n        moveXOffset; printf " %-10s%-39s${clear_line}\\n" "Latest:" "${latest_blocked}"\n        moveXOffset; printf " %-10s%-39s${clear_line}\\n" "Top Ad:" "${top_blocked}"''',
        '''        moveXOffset; printf " %-10s%-29s${clear_line}\\n" "Blocking:" "${domains_being_blocked} domains"\n        moveXOffset; printf " %-10s[%-30s] %-5s${clear_line}\\n" "Pi-holed:" "${ads_blocked_bar}" "${ads_percentage_today}%"\n        moveXOffset; printf " %-10s%-39s${clear_line}\\n" "Latest:" "${latest_blocked}"\n        moveXOffset; printf " %-10s%-39s${clear_line}\\n" "Top Ad:" "${top_blocked}"\n        moveXOffset; printf " %-6s${power_heatmap}%-15s${reset_text} %-6s${power_heatmap}%-8s${reset_text} %-8s${ups_heatmap}%-5s${reset_text}${clear_line}\\n" "Power:" "${power_status} ${power_flags}" "Vcore:" "${core_voltage}" "UPS Bat:" "${ups_battery}"''',
        "Tiny stats and hardware display",
    )

    PADD_PATH.write_text(text, encoding="utf-8", newline="\n")
    print("Applied NAIG Tiny power and UPS monitor with watermark.")


if __name__ == "__main__":
    main()
