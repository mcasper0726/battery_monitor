from smbus2 import SMBus

# -------- CONFIG --------
ADDR = 0x0B        # Smart battery SMBus address
BUS_NUM = 1        # Raspberry Pi I2C bus

REG_VOLTAGE = 0x09
REG_CURRENT = 0x0B


# -------- HELPERS --------
def swap16(x):
    """Swap the two bytes of a 16-bit word."""
    return ((x & 0xFF) << 8) | ((x >> 8) & 0xFF)


def to_signed16(x):
    """Convert unsigned 16-bit integer to signed 16-bit integer."""
    return x - 65536 if x & 0x8000 else x


def read_battery():
    with SMBus(BUS_NUM) as bus:
        raw_v = bus.read_word_data(ADDR, REG_VOLTAGE)
        raw_c = bus.read_word_data(ADDR, REG_CURRENT)

    voltage_mV = swap16(raw_v)
    current_mA = to_signed16(raw_c)

    print()
    print("===== BATTERY READ =====")
    print(f"Address           : 0x{ADDR:02X}")
    print()
    print("Voltage Register (0x09)")
    print(f"  Raw             : 0x{raw_v:04X} ({raw_v})")
    print(f"  Corrected       : {voltage_mV} mV")
    print()
    print("Current Register (0x0B)")
    print(f"  Raw             : 0x{raw_c:04X} ({raw_c})")
    print(f"  Corrected       : {current_mA} mA")
    print()
    print("===== END READ =====")
    print()


if __name__ == "__main__":
    try:
        read_battery()
    except Exception as e:
        print(f"[ERROR] {e}")