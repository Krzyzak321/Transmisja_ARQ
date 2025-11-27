from machine import Pin
import utime
import machine

# =========== KONFIGURACJA SYSTEMU ===========
TX_PIN = 15
RX_PIN = 21
BIT_LEN_US = 990

# --- Stałe dla Hamminga ---
PREAMBLE_LEN = 16
HEADER_LEN = 12
DATA_BITS_LEN = 26
HAMMING_PARITY_LEN = 5
TOTAL_FRAME_LEN = PREAMBLE_LEN + HEADER_LEN + DATA_BITS_LEN + HAMMING_PARITY_LEN

PREAMBLE = "1010101010101010"

# --- Typy ramek ---
FRAME_TYPE_DATA = "0001"
FRAME_TYPE_ACK = "0010"
FRAME_TYPE_NACK = "0011"

# --- Sygnały ACK/NACK ---
ACK_DATA = "11111111111111111111111111"
NACK_DATA = "00000000000000000000000000"

# --- Dane testowe ---
DATA_BITS = "11001100110011001100110001"

# --- Konfiguracja protokołu ---
ACK_TIMEOUT_MS = 2000
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
    print(f"Hamming - Odebrane dane: {data}, Odebrana parzystość: {parity}, Obliczona parzystość: {calculated_parity}")
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

# =========== FUNKCJE KOMUNIKACJI ===========
def send_bits(bits):
    print("Wysyłanie ramki Hamminga")
    irq_state = machine.disable_irq()
    try:
        for bit in bits:
            tx.value(1 if bit == '1' else 0)
            utime.sleep_us(BIT_LEN_US)
    finally:
        tx.value(0)
        machine.enable_irq(irq_state)

def wait_for_preamble_with_sync(timeout_ms=3000):
    start_time = utime.ticks_ms()
    bit_count = 0
    last_state = rx.value()
    last_edge = utime.ticks_us()
    first_edge_time = 0
    last_edge_time = 0
    
    while utime.ticks_diff(utime.ticks_ms(), start_time) < timeout_ms:
        current_state = rx.value()
        
        if current_state != last_state:
            now = utime.ticks_us()
            pulse_width = utime.ticks_diff(now, last_edge)
            
            if pulse_width > BIT_LEN_US * 0.6 and pulse_width < BIT_LEN_US * 1.4:
                target_time = now + (pulse_width // 2)
                while utime.ticks_diff(target_time, utime.ticks_us()) > 0:
                    pass
                
                sampled_bit = rx.value()
                expected_bit = PREAMBLE[bit_count]
                
                if (expected_bit == '1' and sampled_bit == 1) or (expected_bit == '0' and sampled_bit == 0):
                    if bit_count == 0:
                        first_edge_time = now
                    bit_count += 1
                    last_edge_time = now
                    
                    if bit_count == PREAMBLE_LEN:
                        measured_bit_len = (last_edge_time - first_edge_time) // (PREAMBLE_LEN - 1)
                        print(f"Zmierzony czas bitu: {measured_bit_len}")
                        return True, measured_bit_len, last_edge_time
                else:
                    bit_count = 0
            
            last_edge = now
            last_state = current_state
        
        if utime.ticks_diff(utime.ticks_us(), last_edge) > BIT_LEN_US * 3:
            bit_count = 0
            last_state = rx.value()
            last_edge = utime.ticks_us()
    
    return False, BIT_LEN_US, 0

def read_frame_with_sync(bit_duration, preamble_end_time):
    frame = ""
    bits_to_read = HEADER_LEN + DATA_BITS_LEN + HAMMING_PARITY_LEN
    
    # Poczekaj do środka pierwszego bitu danych
    first_bit_center = preamble_end_time + bit_duration + (bit_duration // 2)
    while utime.ticks_diff(first_bit_center, utime.ticks_us()) > 0:
        pass
    
    for i in range(bits_to_read):
        frame += '1' if rx.value() else '0'
        
        if i < bits_to_read - 1:
            next_bit_center = utime.ticks_us() + bit_duration
            while utime.ticks_diff(next_bit_center, utime.ticks_us()) > 0:
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
    
    print("\n=== PRÓBA WYSŁANIA RAMKI HAMMINGA ===")
    
    # KROK 1: Przygotuj i wyślij ramkę danych
    frame_to_send = build_data_frame(sequence_number)
    print(f"Wysyłana ramka: {frame_to_send}")
    send_bits(frame_to_send)
    
    # KROK 2: Czekaj na ACK z synchronizacją
    print("Oczekiwanie na ACK...")
    ack_wait_start = utime.ticks_ms()
    
    while utime.ticks_diff(utime.ticks_ms(), ack_wait_start) < ACK_TIMEOUT_MS:
        found, bit_duration, preamble_end = wait_for_preamble_with_sync(ACK_TIMEOUT_MS)
        if found:
            ack_frame = read_frame_with_sync(bit_duration, preamble_end)
            print(f"Odebrana ramka ACK ({len(ack_frame)} bitów): {ack_frame}")
            
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
                print("❓ Odebrano nieznany sygnał")
    
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
