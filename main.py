from smbus2 import SMBus
import csv
import time
from datetime import datetime

# -------- CONFIG --------
ADDR = 0x0B
BUS_NUM = 1

REG_VOLTAGE = 0x09
REG_CURRENT = 0x0B

CSV_FILE = "battery_log.csv"
NUM_SAMPLES = 100
INTERVAL_SEC = 5


# -------- HELPERS --------
def swap16(x):
    return ((x & 0xFF) << 8) | ((x >> 8) & 0xFF)


def to_signed16(x):
    return x - 65536 if x & 0x8000 else x


def read_once():
    with SMBus(BUS_NUM) as bus:
        raw_v = bus.read_word_data(ADDR, REG_VOLTAGE)
        raw_c = bus.read_word_data(ADDR, REG_CURRENT)

    voltage_mV = swap16(raw_v)
    current_mA = to_signed16(raw_c)

    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "voltage_mV": voltage_mV,
        "current_mA": current_mA,
    }


# -------- MAIN --------
def main():
    print(f"\nLogging {NUM_SAMPLES} samples every {INTERVAL_SEC} seconds")
    print(f"Output file: {CSV_FILE}")
    print("Press Ctrl+C to abort\n")

    with open(CSV_FILE, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["timestamp", "voltage_mV", "current_mA"]
        )
        writer.writeheader()

        try:
            for i in range(NUM_SAMPLES):
                row = read_once()
                writer.writerow(row)

                print(
                    f"{i+1:03d}/{NUM_SAMPLES}  "
                    f"{row['timestamp']}  "
                    f"V={row['voltage_mV']} mV  "
                    f"I={row['current_mA']} mA"
                )

                time.sleep(INTERVAL_SEC)

        except KeyboardInterrupt:
            print("\nAborted by user (Ctrl+C)")

    print("\nDone.\n")


if __name__ == "__main__":
    main()