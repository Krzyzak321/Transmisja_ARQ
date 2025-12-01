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
HAMMING_PARITY_LEN = 5    # 5 bitów parzystości Hamminga
# długość ramki bez preambuły
BITS_AFTER_PREAMBLE = HEADER_LEN + DATA_BITS_LEN + HAMMING_PARITY_LEN

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
DATA_BITS = "11001100110011001100110001"  # 26 bitów danych

# --- Konfiguracja protokołu ---
ACK_TIMEOUT_MS = 1000
MAX_RETRANSMISSIONS = 1000

# --- Inicjalizacja pinów ---
tx = Pin(TX_PIN, Pin.OUT)
rx = Pin(RX_PIN, Pin.IN)
tx.value(0)

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
def build_data_frame(seq_num=0):
    seq_bits = f"{seq_num:04b}"
    header = FRAME_TYPE_DATA + seq_bits + "1100"
    parity = calculate_hamming_parity(DATA_BITS)
    print(f"Wysyłane dane: {DATA_BITS}, Wysyłana parzystość: {parity}")
    return PREAMBLE + header + DATA_BITS + parity

def build_ack_frame(seq_num=0):
    seq_bits = f"{seq_num:04b}"
    header = FRAME_TYPE_ACK + seq_bits + "1100"
    parity = calculate_hamming_parity(ACK_DATA)
    return PREAMBLE + header + ACK_DATA + parity

def build_nack_frame(seq_num=0):
    seq_bits = f"{seq_num:04b}"
    header = FRAME_TYPE_NACK + seq_bits + "1100"
    parity = calculate_hamming_parity(NACK_DATA)
    return PREAMBLE + header + NACK_DATA + parity

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
    frame = ""
    bits_to_read = BITS_AFTER_PREAMBLE

    # pierwszy bit nagłówka zaczyna się 1*BIT_LEN_US po końcu preambuły
    first_sample = utime.ticks_add(preamble_ts, BIT_LEN_US)
    # przesunięcie do środka bitu
    first_sample = utime.ticks_add(first_sample, int(BIT_LEN_US * 0.5))

    # czekaj do pierwszego sample
    while utime.ticks_diff(first_sample, utime.ticks_us()) > 0:
        pass

    t = first_sample
    for i in range(bits_to_read):
        frame += '1' if rx.value() else '0'
        # przygotuj następny czas próbkowania
        t = utime.ticks_add(t, BIT_LEN_US)
        # czekaj do czasu
        if i < bits_to_read - 1:
            while utime.ticks_diff(t, utime.ticks_us()) > 0:
                pass

    return frame

def verify_frame(frame):
    if len(frame) != HEADER_LEN + DATA_BITS_LEN + HAMMING_PARITY_LEN:
        print(f"❌ Błędna długość ramki: {len(frame)}, oczekiwano: {HEADER_LEN + DATA_BITS_LEN + HAMMING_PARITY_LEN}")
        return False

    header = frame[:HEADER_LEN]
    data = frame[HEADER_LEN:HEADER_LEN + DATA_BITS_LEN]
    parity = frame[HEADER_LEN + DATA_BITS_LEN:]

    print(f"Odebrany nagłówek: {header}")
    print(f"Odebrane dane: {data}")
    print(f"Odebrana parzystość: {parity}")

    return verify_hamming(data, parity)

# =========== GŁÓWNA PĘTLA ===========
print("=== Raspberry Pi Pico TX/RX ready (Hamming) ===")
retransmission_count = 0
sequence_number = 0

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

