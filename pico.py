from machine import Pin
import utime
import machine

# =========== KONFIGURACJA SYSTEMU ===========
TX_PIN = 15
RX_PIN = 21
BIT_LEN_US = 990

# --- Nowe stałe dla Hamminga ---
PREAMBLE_LEN = 16
HEADER_LEN = 12           # 4 typ + 4 sekw + 3 długość + 1 rezerwa
DATA_BITS_LEN = 26        # 26 bitów danych
CRC_PARITY_LEN = 4
HAMMING_PARITY_LEN = 5    # 5 bitów parzystości Hamminga
# długość ramki bez preambuły
BITS_AFTER_PREAMBLE = HEADER_LEN + DATA_BITS_LEN + HAMMING_PARITY_LEN

PREAMBLE = "1010101010101010"

# Tryby
MODE_HAMMING = 0
MODE_CRC4 = 1

# --- Typy ramek ---
FRAME_TYPE_DATA = "0001"
FRAME_TYPE_ACK = "0010"
FRAME_TYPE_NACK = "0011"
FRAME_TYPE_SREJ = "0100"

# --- Sygnały ACK/NACK ---
ACK_DATA = "1" * DATA_BITS_LEN
NACK_DATA = "0" * DATA_BITS_LEN

# --- Dane testowe ---
DATA_BITS = "11001100110011001100110001"  # 26 bitów danych

# --- Konfiguracja protokołu ---
ACK_TIMEOUT_MS = 1000
MAX_RETRANSMISSIONS = 1000

# --- Inicjalizacja pinów ---
tx = Pin(TX_PIN, Pin.OUT)
rx = Pin(RX_PIN, Pin.IN)
tx.value(0)

# =========== FUNKCJE CRC-4 ===========
# polynomial: x^4 + x + 1 -> 0b0011 (0x3) (bez bitu x^4 w reprezentacji reszty)
def calculate_crc4(data_bits):
    # data_bits: string "0"/"1", MSB first
    # perform binary long division, return 4-bit string
    poly = 0x3  # reprezentacja bez najwyższego bitu (x^4)
    # build integer from bits, shift left by 4 (space for CRC)
    value = 0
    for b in data_bits:
        value = (value << 1) | (1 if b == '1' else 0)
    value <<= CRC_PARITY_LEN
    # degree of poly is 4, so mask for top bit is 1 << (len(data)+4-1) ... we iterate
    total_len = len(data_bits) + CRC_PARITY_LEN
    for i in range(len(data_bits)):
        # check bit at position (total_len - 1 - i)
        shift = total_len - 1 - i
        if (value >> shift) & 1:
            # XOR poly shifted to align with current top
            value ^= (poly << (shift - CRC_PARITY_LEN))
    # remainder is lower 4 bits
    rem = value & ((1 << CRC_PARITY_LEN) - 1)
    return f"{rem:04b}"

def verify_crc4(data_bits, crc_bits):
    calculated = calculate_crc4(data_bits)
    # print(f"CRC calc {calculated} vs recv {crc_bits}")
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
    # print(f"Hamming - Odebrane dane: {data}, Odebrana parzystość: {parity}, Obliczona parzystość: {calculated_parity}")
    return calculated_parity == parity

# =========== FUNKCJE BUDOWANIA RAMEK ===========
def build_data_frame(seq_num=0, mode=MODE_HAMMING):
    seq_bits = f"{seq_num:04b}"
    mode_flag = '1' if mode == MODE_CRC4 else '0'
    # nagłówek: typ(4) + seq(4) + długość(3) + tryb(1)
    header = FRAME_TYPE_DATA + seq_bits + "110" + mode_flag
    if mode == MODE_HAMMING:
        parity = calculate_hamming_parity(DATA_BITS)
    else:
        parity = calculate_crc4(DATA_BITS)
    print(f"Wysyłane dane: {DATA_BITS}, Parzystość ({'CRC4' if mode==MODE_CRC4 else 'Hamming'}): {parity}")
    return PREAMBLE + header + DATA_BITS + parity

def build_ack_frame(seq_num=0, mode=MODE_HAMMING):
    seq_bits = f"{seq_num:04b}"
    mode_flag = '1' if mode == MODE_CRC4 else '0'
    header = FRAME_TYPE_ACK + seq_bits + "110" + mode_flag
    data = ACK_DATA
    parity = calculate_crc4(data) if mode==MODE_CRC4 else calculate_hamming_parity(data)
    return PREAMBLE + header + data + parity

def build_nack_frame(seq_num=0, mode=MODE_HAMMING):
    seq_bits = f"{seq_num:04b}"
    mode_flag = '1' if mode == MODE_CRC4 else '0'
    header = FRAME_TYPE_NACK + seq_bits + "110" + mode_flag
    data = NACK_DATA
    parity = calculate_crc4(data) if mode==MODE_CRC4 else calculate_hamming_parity(data)
    return PREAMBLE + header + data + parity
# =========== POZOSTAŁE FUNKCJE (TIMING) ===========
def send_bits(bits):
    # wyłącz przerwania na czas nadawania -> stabilność timingu
    irq_state = machine.disable_irq()
    try:
        for bit in bits:
            tx.value(1 if bit == '1' else 0)
            utime.sleep_us(BIT_LEN_US)
    finally:
        tx.value(0)
        machine.enable_irq(irq_state)

# WAIT FOR PREAMBLE: zwraca timestamp (us) ostatniej krawędzi preambuły lub None
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
            # jeśli pulse_width wygląda sensownie (około jednego BIT_LEN_US), próbkuj w połowie impulsu
            # (próbkujemy od krawędzi poprzedniej, by trafić w środek)
            if pulse_width > BIT_LEN_US * 0.4 and pulse_width < BIT_LEN_US * 1.6:
                sample_time = utime.ticks_add(last_edge, pulse_width // 2)
                # czekaj do sample_time
                while utime.ticks_diff(sample_time, utime.ticks_us()) > 0:
                    pass
                sampled = rx.value()
                expected = PREAMBLE[bit_count]
                if (expected == '1' and sampled == 1) or (expected == '0' and sampled == 0):
                    bit_count += 1
                    if bit_count == PREAMBLE_LEN:
                        # zwróć czas tej ostatniej krawędzi (koniec preambuły)
                        return now
                else:
                    bit_count = 0
            else:
                # jeśli impuls był zbyt krótki/długi, zresetuj i kontynuuj
                bit_count = 0

            last_edge = now
            last_state = current

        # jeśli nie ma żadnych krawędzi przez długo > 3 bitów, zresetuj licznik
        if utime.ticks_diff(utime.ticks_us(), last_edge) > BIT_LEN_US * 3:
            bit_count = 0
            last_state = rx.value()
            last_edge = utime.ticks_us()

    return None

# READ FRAME AFTER PREAMBLE: wyrównane próbkowanie od preamble_ts
def read_frame_after_preamble(preamble_ts):
    # najpierw wczytaj HEADER_LEN bitów (wyrównane tak jak wcześniej)
    frame_header = ""
    # first sample same jak wcześniej
    first_sample = utime.ticks_add(preamble_ts, BIT_LEN_US)
    first_sample = utime.ticks_add(first_sample, int(BIT_LEN_US * 0.5))
    while utime.ticks_diff(first_sample, utime.ticks_us()) > 0:
        pass
    t = first_sample
    for i in range(HEADER_LEN):
        frame_header += '1' if rx.value() else '0'
        t = utime.ticks_add(t, BIT_LEN_US)
        if i < HEADER_LEN - 1:
            while utime.ticks_diff(t, utime.ticks_us()) > 0:
                pass

    # odczytaj tryb z ostatniego bitu nagłówka
    mode_flag = frame_header[-1]
    parity_len = CRC_PARITY_LEN if mode_flag == '1' else HAMMING_PARITY_LEN

    # teraz wczytaj DATA_BITS_LEN + parity_len
    rest = ""
    # już ustawiony czas t = first_sample + HEADER_LEN * BIT_LEN_US
    for i in range(DATA_BITS_LEN + parity_len):
        rest += '1' if rx.value() else '0'
        t = utime.ticks_add(t, BIT_LEN_US)
        if i < DATA_BITS_LEN + parity_len - 1:
            while utime.ticks_diff(t, utime.ticks_us()) > 0:
                pass

    return frame_header + rest

def verify_frame(frame):
    # minimalna długość header+data+4 = 12+26+4 = 42 albo +5 = 43
    if len(frame) < HEADER_LEN + DATA_BITS_LEN + CRC_PARITY_LEN:
        print(f"❌ Zbyt krótka ramka: {len(frame)}")
        return False

    header = frame[:HEADER_LEN]
    mode_flag = header[-1]
    parity_len = CRC_PARITY_LEN if mode_flag == '1' else HAMMING_PARITY_LEN

    expected_len = HEADER_LEN + DATA_BITS_LEN + parity_len
    if len(frame) != expected_len:
        print(f"❌ Błędna długość ramki: {len(frame)}, oczekiwano: {expected_len}")
        return False

    data = frame[HEADER_LEN:HEADER_LEN + DATA_BITS_LEN]
    parity = frame[HEADER_LEN + DATA_BITS_LEN:]

    print(f"Odebrany nagłówek: {header} (mode_flag={mode_flag})")
    print(f"Odebrane dane: {data}")
    print(f"Odebrana parzystość: {parity}")

    if mode_flag == '1':  # CRC4
        return verify_crc4(data, parity)
    else:
        return verify_hamming(data, parity)

# =========== GŁÓWNA PĘTLA ===========
print("=== Raspberry Pi Pico TX/RX ready (Hamming) ===")
retransmission_count = 0
sequence_number = 0
CURRENT_MODE = MODE_CRC4 
while True:
    ack_received = False

    print("\n=== PRÓBA WYSŁANIA RAMKI  ===")
    # KROK 1: Przygotuj i wyślij ramkę danych z Hammingiem
    frame_to_send = build_data_frame(sequence_number)
    print(f"Wysyłana ramka: {frame_to_send}")
    send_bits(frame_to_send)

    # KROK 2: Czekaj na ACK
    print("\n=== Oczekiwanie na ACK ===")
    ack_wait_start = utime.ticks_ms()

    while utime.ticks_diff(utime.ticks_ms(), ack_wait_start) < ACK_TIMEOUT_MS:
        preamble_time = wait_for_preamble(ACK_TIMEOUT_MS)
        if preamble_time is None:
            # brak preambuły w tym okresie - kontynuuj oczekiwanie
            continue

        # mamy timestamp końca preambuły -> czytaj ramkę względem tego czasu
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

    # KROK 3: Obsłuż brak potwierdzenia
    if not ack_received:
        print("⏰ Timeout ACK - brak odpowiedzi")
        retransmission_count += 1

        if retransmission_count >= MAX_RETRANSMISSIONS:
            print("🛑 Przekroczono maksymalną liczbę retransmisji")
            retransmission_count = 0
            sequence_number = (sequence_number + 1) % 16
        else:
            print("🔄 Retransmisja #" + str(retransmission_count))

    # KROK 4: Przerwa przed następną transmisją
    utime.sleep_ms(2000)


