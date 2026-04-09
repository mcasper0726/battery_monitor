"""
single_battery_diag.py

Diagnostic module for talking directly from a Raspberry Pi to a single smart battery pack.

Purpose:
- Probe a single battery pack on SMBus/I2C
- Read key battery registers
- Show raw and byte-swapped interpretations
- Apply signed conversion where appropriate
- Help determine whether prior bad readings are due to:
    * bad address
    * bus failure
    * endian mismatch
    * signed/unsigned mismatch
    * scaling confusion

Assumptions:
- Pi I2C bus is bus 1
- Battery pack likely responds at 0x0B (common Smart Battery address)
- Voltage register = 0x09
- Current register = 0x0B

Usage examples:
    python3 single_battery_diag.py
    python3 single_battery_diag.py --addr 0x0B
    python3 single_battery_diag.py --loop
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from typing import Dict, Optional, List

try:
    from smbus2 import SMBus
except ImportError:
    SMBus = None


# -----------------------------
# Constants
# -----------------------------

DEFAULT_BUS_NUM = 1
DEFAULT_BAT_ADDR = 0x0B

REG_TEMPERATURE = 0x08
REG_VOLTAGE = 0x09
REG_CURRENT = 0x0B
REG_AVG_CURRENT = 0x0A
REG_REL_STATE_OF_CHARGE = 0x0D
REG_ABS_STATE_OF_CHARGE = 0x0E
REG_REMAINING_CAPACITY = 0x0F
REG_FULL_CHARGE_CAPACITY = 0x10
REG_BATTERY_STATUS = 0x16

DEFAULT_REGS = {
    "TEMPERATURE": REG_TEMPERATURE,
    "VOLTAGE": REG_VOLTAGE,
    "AVG_CURRENT": REG_AVG_CURRENT,
    "CURRENT": REG_CURRENT,
    "REL_SOC": REG_REL_STATE_OF_CHARGE,
    "ABS_SOC": REG_ABS_STATE_OF_CHARGE,
    "REM_CAP": REG_REMAINING_CAPACITY,
    "FULL_CAP": REG_FULL_CHARGE_CAPACITY,
    "BAT_STATUS": REG_BATTERY_STATUS,
}


# -----------------------------
# Helpers
# -----------------------------

def swap16(value: int) -> int:
    """Swap low and high byte of a 16-bit word."""
    return ((value & 0x00FF) << 8) | ((value >> 8) & 0x00FF)


def to_signed16(value: int) -> int:
    """Convert unsigned 16-bit integer to signed 16-bit integer."""
    return value - 0x10000 if (value & 0x8000) else value


def fmt_hex16(value: int) -> str:
    return f"0x{value & 0xFFFF:04X}"


def safe_int(value: Optional[int]) -> str:
    return "None" if value is None else str(value)


@dataclass
class RegisterInterpretation:
    reg_name: str
    reg_addr: int
    raw: int
    swapped: int
    raw_signed: int
    swapped_signed: int


# -----------------------------
# Battery diagnostic class
# -----------------------------

class SingleBatteryDiag:
    def __init__(self, bus_num: int = DEFAULT_BUS_NUM, addr: int = DEFAULT_BAT_ADDR):
        self.bus_num = bus_num
        self.addr = addr
        self.bus: Optional[SMBus] = None

    def open(self) -> None:
        if SMBus is None:
            raise RuntimeError("smbus2 is not installed. Install with: pip install smbus2")
        self.bus = SMBus(self.bus_num)

    def close(self) -> None:
        if self.bus is not None:
            try:
                self.bus.close()
            except Exception:
                pass
            self.bus = None

    def __enter__(self) -> "SingleBatteryDiag":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def probe(self) -> bool:
        """
        Probe whether the battery address responds.
        Uses read_byte because write_quick is not universally supported by all devices/adapters.
        """
        assert self.bus is not None, "Bus is not open"
        try:
            self.bus.read_byte(self.addr)
            return True
        except OSError:
            return False

    def read_word_raw(self, reg: int) -> int:
        """
        Read a 16-bit word directly from SMBus.
        Note: SMBus word order may appear swapped relative to datasheet expectations.
        """
        assert self.bus is not None, "Bus is not open"
        return self.bus.read_word_data(self.addr, reg)

    def interpret_word(self, reg_name: str, reg_addr: int) -> RegisterInterpretation:
        raw = self.read_word_raw(reg_addr)
        swapped = swap16(raw)
        raw_signed = to_signed16(raw)
        swapped_signed = to_signed16(swapped)
        return RegisterInterpretation(
            reg_name=reg_name,
            reg_addr=reg_addr,
            raw=raw,
            swapped=swapped,
            raw_signed=raw_signed,
            swapped_signed=swapped_signed,
        )

    def read_all_default_regs(self) -> Dict[str, RegisterInterpretation]:
        out: Dict[str, RegisterInterpretation] = {}
        for name, reg in DEFAULT_REGS.items():
            out[name] = self.interpret_word(name, reg)
        return out


# -----------------------------
# Human-readable reporting
# -----------------------------

def choose_plausible_voltage(raw: int, swapped: int) -> str:
    """
    Heuristic:
    Smart battery voltage is often reported in mV.
    For many packs, plausible pack voltage might be ~6000 mV to ~35000 mV.
    """
    raw_ok = 6000 <= raw <= 35000
    swapped_ok = 6000 <= swapped <= 35000

    if raw_ok and not swapped_ok:
        return "raw"
    if swapped_ok and not raw_ok:
        return "swapped"
    if raw_ok and swapped_ok:
        return "either"
    return "neither"


def choose_plausible_current(raw_signed: int, swapped_signed: int) -> str:
    """
    Heuristic:
    For bench testing, current might often be a few amps or less.
    Prefer whichever lies in a sane engineering range.
    """
    raw_ok = -10000 <= raw_signed <= 10000
    swapped_ok = -10000 <= swapped_signed <= 10000

    if raw_ok and not swapped_ok:
        return "raw_signed"
    if swapped_ok and not raw_ok:
        return "swapped_signed"
    if raw_ok and swapped_ok:
        return "either"
    return "neither"


def print_register_block(r: RegisterInterpretation) -> None:
    print(f"{r.reg_name} (reg {fmt_hex16(r.reg_addr)})")
    print(f"  raw              : {fmt_hex16(r.raw)}  ({r.raw})")
    print(f"  raw signed       : {r.raw_signed}")
    print(f"  byte-swapped     : {fmt_hex16(r.swapped)}  ({r.swapped})")
    print(f"  swapped signed   : {r.swapped_signed}")


def print_summary(regs: Dict[str, RegisterInterpretation]) -> None:
    print("\nSummary / plausibility")
    print("----------------------")

    if "VOLTAGE" in regs:
        v = regs["VOLTAGE"]
        v_choice = choose_plausible_voltage(v.raw, v.swapped)
        print(f"Voltage interpretation most plausible: {v_choice}")
        if v_choice == "raw":
            print(f"  likely voltage = {v.raw} mV")
        elif v_choice == "swapped":
            print(f"  likely voltage = {v.swapped} mV")
        elif v_choice == "either":
            print("  both raw and swapped look plausible")
        else:
            print("  neither raw nor swapped looks plausible")

    if "CURRENT" in regs:
        c = regs["CURRENT"]
        c_choice = choose_plausible_current(c.raw_signed, c.swapped_signed)
        print(f"Current interpretation most plausible: {c_choice}")
        if c_choice == "raw_signed":
            print(f"  likely current = {c.raw_signed} mA")
        elif c_choice == "swapped_signed":
            print(f"  likely current = {c.swapped_signed} mA")
        elif c_choice == "either":
            print("  both signed interpretations look plausible")
        else:
            print("  neither signed interpretation looks plausible")

    print("\nNotes")
    print("-----")
    print("- Smart Battery current is often signed.")
    print("- Charging commonly appears as negative current.")
    print("- Linux SMBus word reads often need byte swapping relative to the datasheet.")
    print("- The correct interpretation depends on how the original Aardvark helper handled reg_read_word().")


# -----------------------------
# Main read routine
# -----------------------------

def run_once(bus_num: int, addr: int) -> int:
    print(f"Opening I2C bus {bus_num}, target battery address 0x{addr:02X}")

    try:
        with SingleBatteryDiag(bus_num=bus_num, addr=addr) as diag:
            if not diag.probe():
                print(f"ERROR: No response from battery at 0x{addr:02X}")
                return 2

            print(f"Battery responded at 0x{addr:02X}")

            regs = diag.read_all_default_regs()

            print("\nDetailed register dump")
            print("----------------------")
            for name in DEFAULT_REGS.keys():
                print_register_block(regs[name])
                print()

            print_summary(regs)
            return 0

    except OSError as e:
        print(f"I2C/SMBus error: {e}")
        return 3
    except Exception as e:
        print(f"Unexpected error: {e}")
        return 4


def run_loop(bus_num: int, addr: int, interval_s: float) -> int:
    print(f"Loop mode: bus={bus_num}, addr=0x{addr:02X}, interval={interval_s}s")
    print("Press Ctrl+C to stop.\n")

    try:
        while True:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            print("=" * 70)
            print(ts)
            rc = run_once(bus_num, addr)
            if rc != 0:
                print(f"Read failed with code {rc}")
            time.sleep(interval_s)
    except KeyboardInterrupt:
        print("\nStopped by user.")
        return 0


# -----------------------------
# CLI
# -----------------------------

def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Direct single smart-battery diagnostic reader")
    parser.add_argument("--bus", type=int, default=DEFAULT_BUS_NUM, help="I2C bus number (default: 1)")
    parser.add_argument(
        "--addr",
        type=lambda x: int(x, 0),
        default=DEFAULT_BAT_ADDR,
        help="Battery address in hex or decimal (default: 0x0B)",
    )
    parser.add_argument("--loop", action="store_true", help="Read continuously")
    parser.add_argument("--interval", type=float, default=2.0, help="Loop interval in seconds")
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)

    if args.loop:
        return run_loop(bus_num=args.bus, addr=args.addr, interval_s=args.interval)

    return run_once(bus_num=args.bus, addr=args.addr)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
