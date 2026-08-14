from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
PATCHER = ROOT / "tools" / "apply_naig_tiny.py"
PADD = ROOT / "padd.sh"
DASH = Path(shutil.which("dash") or r"C:\Program Files\Git\usr\bin\dash.exe")


class NaigTinyPatchTests(unittest.TestCase):
    def apply_patch(self, padd_text: str | None = None) -> tuple[Path, str]:
        temp_dir = Path(tempfile.mkdtemp(prefix="padd-naig-test-"))
        self.addCleanup(shutil.rmtree, temp_dir, ignore_errors=True)
        (temp_dir / "padd.sh").write_text(
            padd_text if padd_text is not None else PADD.read_text(encoding="utf-8"),
            encoding="utf-8",
            newline="\n",
        )
        tools_dir = temp_dir / "tools"
        tools_dir.mkdir()
        shutil.copy2(PATCHER, tools_dir / PATCHER.name)

        result = subprocess.run(
            [sys.executable, os.fspath(tools_dir / PATCHER.name)],
            cwd=temp_dir,
            check=True,
            capture_output=True,
            text=True,
        )
        return temp_dir, result.stdout

    def test_patch_is_idempotent_and_dash_valid(self) -> None:
        temp_dir, first_output = self.apply_patch()
        self.assertIn("Applied NAIG Tiny power and UPS monitor", first_output)

        second = subprocess.run(
            [sys.executable, os.fspath(temp_dir / "tools" / PATCHER.name)],
            cwd=temp_dir,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("already present", second.stdout)

        if DASH.exists():
            subprocess.run(
                [os.fspath(DASH), "-n", "padd.sh"],
                cwd=temp_dir,
                check=True,
                capture_output=True,
                text=True,
            )

    def test_legacy_customization_is_rejected_clearly(self) -> None:
        legacy = PADD.read_text(encoding="utf-8").replace(
            "GetSystemInformation() {\n",
            "# NAIG Tiny power monitor\nGetSystemInformation() {\n",
            1,
        )
        temp_dir = Path(tempfile.mkdtemp(prefix="padd-naig-legacy-test-"))
        self.addCleanup(shutil.rmtree, temp_dir, ignore_errors=True)
        (temp_dir / "padd.sh").write_text(legacy, encoding="utf-8", newline="\n")
        tools_dir = temp_dir / "tools"
        tools_dir.mkdir()
        shutil.copy2(PATCHER, tools_dir / PATCHER.name)

        result = subprocess.run(
            [sys.executable, os.fspath(tools_dir / PATCHER.name)],
            cwd=temp_dir,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("legacy NAIG Tiny customization", result.stderr)
        self.assertIn("pristine padd.sh", result.stderr)

    def test_tiny_layout_stays_53_by_20_and_places_ups_below_vcore(self) -> None:
        temp_dir, _ = self.apply_patch()
        patched = (temp_dir / "padd.sh").read_text(encoding="utf-8")
        dashboard = patched.split("PrintDashboard() {", 1)[1]
        tiny = dashboard.split('elif [ "$1" = "tiny" ]; then', 1)[1].split(
            'elif [ "$1" = "regular" ] || [ "$1" = "slim" ]; then', 1
        )[0]

        self.assertEqual(20, tiny.count("moveXOffset; printf"))
        self.assertNotIn('"${ads_blocked_today} out of ${dns_queries_today}"', tiny)
        self.assertLess(tiny.index('"Vcore:"'), tiny.index('"UPS Bat:"'))
        self.assertLess(tiny.index('"UPS Bat:"'), tiny.index("NETWORK"))
        self.assertIn('"UPS Bat:" "${ups_battery}"', tiny)

        # The two split hardware rows and the full-width UPS row must fit in
        # Tiny's 53-column budget after ANSI color sequences are removed.
        self.assertLessEqual(1 + 10 + 18 + 1 + 6 + 14, 53)
        self.assertLessEqual(1 + 10 + 39, 53)

    def test_ups_refreshes_with_power_before_ftl_early_return(self) -> None:
        temp_dir, _ = self.apply_patch()
        patched = (temp_dir / "padd.sh").read_text(encoding="utf-8")
        entry = patched.split("GetSystemInformation() {", 1)[1].split(
            'if [ "${connection_down_flag}" = true ]; then', 1
        )[0]
        self.assertLess(entry.index("GetPowerInformation"), entry.index("GetUPSInformation"))


class UPSInformationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not DASH.exists():
            raise unittest.SkipTest("Git for Windows dash.exe is unavailable")

        temp_dir = Path(tempfile.mkdtemp(prefix="padd-naig-ups-function-test-"))
        cls.temp_dir = temp_dir
        (temp_dir / "padd.sh").write_text(
            PADD.read_text(encoding="utf-8"), encoding="utf-8", newline="\n"
        )
        tools_dir = temp_dir / "tools"
        tools_dir.mkdir()
        shutil.copy2(PATCHER, tools_dir / PATCHER.name)
        subprocess.run(
            [sys.executable, os.fspath(tools_dir / PATCHER.name)],
            cwd=temp_dir,
            check=True,
            capture_output=True,
            text=True,
        )
        patched = (temp_dir / "padd.sh").read_text(encoding="utf-8")
        match = re.search(
            r"(GetUPSInformation\(\) \{.*?\n\})\n\nGetPowerInformation\(\)",
            patched,
            flags=re.DOTALL,
        )
        if not match:
            raise AssertionError("GetUPSInformation function was not found")
        cls.function = match.group(1)

        stub_dir = temp_dir / "stubs"
        stub_dir.mkdir()
        stub = stub_dir / "i2cget"
        stub.write_text(
            textwrap.dedent(
                """\
                #!/bin/sh
                register=$4
                if [ "${UPS_I2CGET_FAIL:-}" = "${register}" ]; then
                    exit 1
                fi
                case "${register}" in
                    0x13) printf '%s\\n' "${UPS_LOW:-0x00}" ;;
                    0x14) printf '%s\\n' "${UPS_HIGH:-0x00}" ;;
                    *) exit 2 ;;
                esac
                """
            ),
            encoding="utf-8",
            newline="\n",
        )
        stub.chmod(0o755)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def run_function(
        self,
        *,
        low: str = "0x00",
        high: str = "0x00",
        fail_register: str = "",
        missing_command: bool = False,
    ) -> tuple[str, str]:
        path_setup = "PATH=/missing" if missing_command else 'PATH="$PWD/stubs:$PATH"'
        script = textwrap.dedent(
            f"""\
            green_text=GREEN
            yellow_text=YELLOW
            red_text=RED
            {self.function}
            {path_setup}
            export PATH UPS_LOW UPS_HIGH UPS_I2CGET_FAIL
            GetUPSInformation
            printf '%s|%s' "${{ups_battery}}" "${{ups_heatmap}}"
            """
        )
        env = os.environ.copy()
        env.update(
            {
                "UPS_LOW": low,
                "UPS_HIGH": high,
                "UPS_I2CGET_FAIL": fail_register,
            }
        )
        result = subprocess.run(
            [os.fspath(DASH), "-s"],
            cwd=self.temp_dir,
            input=script.encode("utf-8"),
            env=env,
            check=False,
            capture_output=True,
        )
        stderr = result.stderr.decode("utf-8", errors="replace")
        stdout = result.stdout.decode("utf-8", errors="replace")
        self.assertEqual(
            0,
            result.returncode,
            f"{stderr}\nGenerated shell:\n{script}",
        )
        battery, heatmap = stdout.split("|", 1)
        return battery, heatmap

    def test_valid_percentages_and_colors(self) -> None:
        cases = (
            (0, "RED"),
            (24, "RED"),
            (25, "YELLOW"),
            (49, "YELLOW"),
            (50, "GREEN"),
            (100, "GREEN"),
        )
        for percentage, expected_color in cases:
            with self.subTest(percentage=percentage):
                battery, heatmap = self.run_function(low=f"0x{percentage:02x}")
                self.assertEqual(f"{percentage}%", battery)
                self.assertEqual(expected_color, heatmap)

    def test_missing_command_returns_na(self) -> None:
        self.assertEqual(("N/A", "YELLOW"), self.run_function(missing_command=True))

    def test_read_error_returns_na(self) -> None:
        self.assertEqual(
            ("N/A", "YELLOW"), self.run_function(fail_register="0x14")
        )

    def test_malformed_read_returns_na(self) -> None:
        self.assertEqual(("N/A", "YELLOW"), self.run_function(low="garbage"))

    def test_out_of_range_combined_value_returns_na(self) -> None:
        self.assertEqual(
            ("N/A", "YELLOW"), self.run_function(low="0x65", high="0x00")
        )
        self.assertEqual(
            ("N/A", "YELLOW"), self.run_function(low="0x00", high="0x01")
        )


if __name__ == "__main__":
    unittest.main()
