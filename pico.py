from machine import Pin
import utime

# =========== KONFIGURACJA SYSTEMU ===========
TX_PIN = 15
RX_PIN = 21
BIT_LEN_US = 990

# --- Nowe stałe dla Hamminga ---
PREAMBLE_LEN = 16
HEADER_LEN = 12           # 4 typ + 4 sekw + 3 długość + 1 rezerwa  
DATA_BITS_LEN = 26        # 26 bitów danych
HAMMING_PARITY_LEN = 5    # 5 bitów parzystości Hamminga
TOTAL_FRAME_LEN = PREAMBLE_LEN + HEADER_LEN + DATA_BITS_LEN + HAMMING_PARITY_LEN

PREAMBLE = "1010101010101010"

# --- Typy ramek ---
FRAME_TYPE_DATA = "0001"
FRAME_TYPE_ACK = "0010"
FRAME_TYPE_NACK = "0011" 
FRAME_TYPE_SREJ = "0100"

# --- Sygnały ACK/NACK ---
ACK_DATA = "11111111111111111111111111"   # 26 jedynek
NACK_DATA = "00000000000000000000000000"  # 26 zer

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
    # Tablica pozycji bitów danych w słowie 31-bitowym (indeksy 1..31)
    data_positions = [3,5,6,7,9,10,11,12,13,14,15,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31]
    word = [0] * 32  # Słowie kodowe 31-bitowe (indeksy 1..31)
    
    # Wstaw bity danych na odpowiednie pozycje
    for i in range(26):
        pos = data_positions[i]
        word[pos] = 1 if data[i] == '1' else 0
    
    # Oblicz bity parzystości
    p1 = p2 = p4 = p8 = p16 = 0
    
    for j in range(1, 32):
        if j & 1: p1 ^= word[j]   # Bit 0: pozycje z ustawionym bitem 0
        if j & 2: p2 ^= word[j]   # Bit 1: pozycje z ustawionym bitem 1
        if j & 4: p4 ^= word[j]   # Bit 2: pozycje z ustawionym bitem 2
        if j & 8: p8 ^= word[j]   # Bit 3: pozycje z ustawionym bitem 3
        if j & 16: p16 ^= word[j] # Bit 4: pozycje z ustawionym bitem 4
    
    return str(p1) + str(p2) + str(p4) + str(p8) + str(p16)

def verify_hamming(data, parity):
    calculated_parity = calculate_hamming_parity(data)
    print(f"Hamming - Odebrane dane: {data}, Odebrana parzystość: {parity}, Obliczona parzystość: {calculated_parity}")
    return calculated_parity == parity

# =========== FUNKCJE BUDOWANIA RAMEK ===========

def build_data_frame(seq_num=0):
    # Nagłówek: typ(4) + sekw(4) + długość(3) + rezerwa(1)
    seq_bits = f"{seq_num:04b}"
    header = FRAME_TYPE_DATA + seq_bits + "1100"  # długość=6 (110), rezerwa=0
    parity = calculate_hamming_parity(DATA_BITS)
    print(f"Wysyłane dane: {DATA_BITS}, Wysyłana parzystość: {parity}")
    return PREAMBLE + header + DATA_BITS + parity

def build_ack_frame(seq_num=0):
    seq_bits = f"{seq_num:04b}"
    header = FRAME_TYPE_ACK + seq_bits + "1100"  # długość=6 (110), rezerwa=0
    parity = calculate_hamming_parity(ACK_DATA)
    return PREAMBLE + header + ACK_DATA + parity

def build_nack_frame(seq_num=0):
    seq_bits = f"{seq_num:04b}"
    header = FRAME_TYPE_NACK + seq_bits + "1100"  # długość=6 (110), rezerwa=0
    parity = calculate_hamming_parity(NACK_DATA)
    return PREAMBLE + header + NACK_DATA + parity

# =========== POZOSTAŁE FUNKCJE (POPRAWIONE TIMINGI) ===========

def send_bits(bits):
    print("Wysyłanie ramki Hamminga")
    irq_state = machine.disable_irq()   # wyłącz przerwania na czas nadawania
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
    
    while utime.ticks_diff(utime.ticks_ms(), start_time) < timeout_ms:
        last_state = rx.value()
        edge_time = utime.ticks_us()
        
        while rx.value() == last_state:
            if utime.ticks_diff(utime.ticks_us(), edge_time) > BIT_LEN_US * 2:
                bit_count = 0
                break
        
        if utime.ticks_diff(utime.ticks_us(), edge_time) > BIT_LEN_US * 2:
            continue
        
        # Ujednolicone timingi - 0.5 bitu do środka
        utime.sleep_us(int(BIT_LEN_US * 0.5))
        current_bit = rx.value()
        expected_bit = PREAMBLE[bit_count]
        
        if (expected_bit == '1' and current_bit == 1) or (expected_bit == '0' and current_bit == 0):
            bit_count += 1
            if bit_count == PREAMBLE_LEN:
                return True
        else:
            bit_count = 0
    
    return False

def read_frame_after_preamble():
    frame = ""
    bits_to_read = HEADER_LEN + DATA_BITS_LEN + HAMMING_PARITY_LEN
    
    # Ujednolicone timingi - czekaj 0.5 bitu do środka pierwszego bitu
    target_time = utime.ticks_us() + int(BIT_LEN_US * 0.5)
    while utime.ticks_diff(target_time, utime.ticks_us()) > 0:
        pass
    
    for i in range(bits_to_read):
        frame += '1' if rx.value() else '0'
        
        # Czekaj pełny okres bitu przed następnym odczytem
        if i < bits_to_read - 1:
            target_time = utime.ticks_us() + BIT_LEN_US
            while utime.ticks_diff(target_time, utime.ticks_us()) > 0:
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
    
    # KROK 1: Przygotuj i wyślij ramkę danych z Hammingiem
    frame_to_send = build_data_frame(sequence_number)
    print(f"Wysyłana ramka: {frame_to_send}")
    send_bits(frame_to_send)
    
    # KROK 2: Czekaj na ACK
    print("Oczekiwanie na ACK...")
    ack_wait_start = utime.ticks_ms()
    
    while utime.ticks_diff(utime.ticks_ms(), ack_wait_start) < ACK_TIMEOUT_MS:
        if wait_for_preamble(ACK_TIMEOUT_MS):
            ack_frame = read_frame_after_preamble()
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
