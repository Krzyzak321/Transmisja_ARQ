from machine import Pin
import utime
import machine

# =========== KONFIGURACJA SYSTEMU ===========
TX_PIN = 15
RX_PIN = 21
BIT_LEN_US = 990

# --- Tryb korekcji błędów ---
USE_HAMMING = False  # True = Hamming (31,26), False = CRC-4

# --- Stałe ramki ---
PREAMBLE_LEN = 16
HEADER_LEN = 12
DATA_BITS_LEN = 26
HAMMING_PARITY_LEN = 5
CRC_PARITY_LEN = 4
PARITY_LEN = HAMMING_PARITY_LEN if USE_HAMMING else CRC_PARITY_LEN
BITS_AFTER_PREAMBLE = HEADER_LEN + DATA_BITS_LEN + PARITY_LEN

PREAMBLE = "1010101010101010"

# --- Typy ramek ---
FRAME_TYPE_DATA = "0001"
FRAME_TYPE_ACK = "0010"
FRAME_TYPE_NACK = "0011"
FRAME_TYPE_SREJ = "0100"

# --- Sygnały ACK/NACK ---
ACK_DATA = "1" * DATA_BITS_LEN
NACK_DATA = "0" * DATA_BITS_LEN

# --- Dane testowe ---
DATA_BITS = "11001100110011001100110001"

# --- Konfiguracja protokołu ---
ACK_TIMEOUT_MS = 1000
MAX_RETRANSMISSIONS = 1000

# --- Inicjalizacja pinów ---
tx = Pin(TX_PIN, Pin.OUT)
rx = Pin(RX_PIN, Pin.IN)
tx.value(0)

# =========== FUNKCJE CRC-4 ===========
def calculate_crc4(data_bits):
    """
    data_bits: string "0"/"1", MSB first
    return: 4-bit string CRC (MSB first)
    """
    poly = 0x13  # 0b10011 (stopień 4 generatora)
    data_len = len(data_bits)

    # zbuduj integer z bitów i dopisz 4 zera (miejsce na CRC)
    value = 0
    for b in data_bits:
        value = (value << 1) | (1 if b == '1' else 0)
    value <<= CRC_PARITY_LEN

    total_len = data_len + CRC_PARITY_LEN

    # wykonaj dzielenie modulo-2: przesuwamy od najwyższego bitu (total_len-1) do CRC_PARITY_LEN
    for i in range(total_len - 1, CRC_PARITY_LEN - 1, -1):
        if (value >> i) & 1:
            # XOR z polynomem wyrównanym do pozycji i
            value ^= (poly << (i - CRC_PARITY_LEN))

    # reszta to dolne 4 bity
    rem = value & ((1 << CRC_PARITY_LEN) - 1)
    return "{:04b}".format(rem)

def verify_crc4(data_bits, crc_bits):
    calculated = calculate_crc4(data_bits)
    return calculated == crc_bits

# =========== FUNKCJE HAMMINGA (31,26) ===========
def calculate_hamming_parity(data):
    data_positions = [3,5,6,7,9,10,11,12,13,14,15,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31]
    word = [0] * 32
    for i in range(26):
        pos = data_positions[i]
        word[pos] = 1 if data[i] == '1' else 0
    p1 = p2 = p4 = p8 = p16 = 0
    for j in range(1, 32):
        if j & 1: p1 ^= word[j]
        if j & 2: p2 ^= word[j]
        if j & 4: p4 ^= word[j]
        if j & 8: p8 ^= word[j]
        if j & 16: p16 ^= word[j]
    return str(p1) + str(p2) + str(p4) + str(p8) + str(p16)

def verify_hamming(data, parity):
    calculated_parity = calculate_hamming_parity(data)
    return calculated_parity == parity

# =========== FUNKCJE UNIWERSALNE ===========
def calculate_parity(data):
    if USE_HAMMING:
        return calculate_hamming_parity(data)
    else:
        return calculate_crc4(data)

def verify_parity(data, parity):
    if USE_HAMMING:
        return verify_hamming(data, parity)
    else:
        return verify_crc4(data, parity)

# =========== FUNKCJE BUDOWANIA RAMEK ===========
def build_data_frame(seq_num=0):
    seq_bits = f"{seq_num:04b}"
    header = FRAME_TYPE_DATA + seq_bits + "1100"
    parity = calculate_parity(DATA_BITS)
    print(f"Tryb: {'Hamming' if USE_HAMMING else 'CRC-4'}")
    print(f"Wysyłane dane: {DATA_BITS}, Wysyłana parzystość: {parity}")
    return PREAMBLE + header + DATA_BITS + parity

def build_ack_frame(seq_num=0):
    seq_bits = f"{seq_num:04b}"
    header = FRAME_TYPE_ACK + seq_bits + "1100"
    parity = calculate_parity(ACK_DATA)
    return PREAMBLE + header + ACK_DATA + parity

def build_nack_frame(seq_num=0):
    seq_bits = f"{seq_num:04b}"
    header = FRAME_TYPE_NACK + seq_bits + "1100"
    parity = calculate_parity(NACK_DATA)
    return PREAMBLE + header + NACK_DATA + parity

# =========== POZOSTAŁE FUNKCJE (TIMING) ===========
def send_bits(bits):
    irq_state = machine.disable_irq()
    try:
        for bit in bits:
            tx.value(1 if bit == '1' else 0)
            utime.sleep_us(BIT_LEN_US)
    finally:
        tx.value(0)
        machine.enable_irq(irq_state)

def wait_for_preamble(timeout_ms=1000):
    start_time = utime.ticks_ms()
    bit_count = 0
    last_state = rx.value()
    last_edge = utime.ticks_us()

    while utime.ticks_diff(utime.ticks_ms(), start_time) < timeout_ms:
        current = rx.value()
        if current != last_state:
            now = utime.ticks_us()
            pulse_width = utime.ticks_diff(now, last_edge)
            if pulse_width > BIT_LEN_US * 0.4 and pulse_width < BIT_LEN_US * 1.6:
                sample_time = utime.ticks_add(last_edge, pulse_width // 2)
                while utime.ticks_diff(sample_time, utime.ticks_us()) > 0:
                    pass
                sampled = rx.value()
                expected = PREAMBLE[bit_count]
                if (expected == '1' and sampled == 1) or (expected == '0' and sampled == 0):
                    bit_count += 1
                    if bit_count == PREAMBLE_LEN:
                        return now
                else:
                    bit_count = 0
            else:
                bit_count = 0

            last_edge = now
            last_state = current

        if utime.ticks_diff(utime.ticks_us(), last_edge) > BIT_LEN_US * 3:
            bit_count = 0
            last_state = rx.value()
            last_edge = utime.ticks_us()

    return None

def read_frame_after_preamble(preamble_ts):
    frame = ""
    bits_to_read = BITS_AFTER_PREAMBLE

    first_sample = utime.ticks_add(preamble_ts, BIT_LEN_US)
    first_sample = utime.ticks_add(first_sample, int(BIT_LEN_US * 0.5))

    while utime.ticks_diff(first_sample, utime.ticks_us()) > 0:
        pass

    t = first_sample
    for i in range(bits_to_read):
        frame += '1' if rx.value() else '0'
        t = utime.ticks_add(t, BIT_LEN_US)
        if i < bits_to_read - 1:
            while utime.ticks_diff(t, utime.ticks_us()) > 0:
                pass

    return frame

def verify_frame(frame):
    expected_len = HEADER_LEN + DATA_BITS_LEN + PARITY_LEN
    if len(frame) != expected_len:
        print(f"❌ Błędna długość ramki: {len(frame)}, oczekiwano: {expected_len}")
        return False

    header = frame[:HEADER_LEN]
    data = frame[HEADER_LEN:HEADER_LEN + DATA_BITS_LEN]
    parity = frame[HEADER_LEN + DATA_BITS_LEN:]

    print(f"Odebrany nagłówek: {header}")
    print(f"Odebrane dane: {data}")
    print(f"Odebrana parzystość: {parity}")

    return verify_parity(data, parity)

# =========== GŁÓWNA PĘTLA ===========
print("=== Raspberry Pi Pico TX/RX ready ===")
print(f"Tryb korekcji: {'Hamming (31,26)' if USE_HAMMING else 'CRC-4'}")
print(f"Bitów parzystości: {PARITY_LEN}")
print(f"Długość ramki bez preambuły: {BITS_AFTER_PREAMBLE}")
retransmission_count = 0
sequence_number = 0

while True:
    ack_received = False

    print(f"\n=== PRÓBA WYSŁANIA RAMKI (SEQ={sequence_number}) ===")
    frame_to_send = build_data_frame(sequence_number)
    print(f"Wysyłana ramka: {frame_to_send}")
    send_bits(frame_to_send)

    print("\n=== Oczekiwanie na ACK ===")
    ack_wait_start = utime.ticks_ms()

    while utime.ticks_diff(utime.ticks_ms(), ack_wait_start) < ACK_TIMEOUT_MS:
        preamble_time = wait_for_preamble(ACK_TIMEOUT_MS)
        if preamble_time is None:
            continue

        ack_frame = read_frame_after_preamble(preamble_time)
        print(f"Odebrana ramka ACK ({len(ack_frame)} bit): {ack_frame}")

        if verify_frame(ack_frame):
            header = ack_frame[:HEADER_LEN]
            frame_type = header[:4]

            if frame_type == FRAME_TYPE_ACK:
                print("✅ Otrzymano ACK - transmisja udana!")
                ack_received = True
                retransmission_count = 0
                sequence_number = (sequence_number + 1) % 16
                break
            elif frame_type == FRAME_TYPE_NACK:
                print("❌ Otrzymano NACK - błąd transmisji")
                break
        else:
            print("❓ Odebrano nieznany sygnał / ramka z błędem")

    if not ack_received:
        print("⏰ Timeout ACK - brak odpowiedzi")
        retransmission_count += 1

        if retransmission_count >= MAX_RETRANSMISSIONS:
            print("🛑 Przekroczono maksymalną liczbę retransmisji")
            retransmission_count = 0
            sequence_number = (sequence_number + 1) % 16
        else:
            print(f"🔄 Retransmisja #{retransmission_count}")

    utime.sleep_ms(2000)