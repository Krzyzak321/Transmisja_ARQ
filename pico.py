from machine import Pin
import utime
import machine

# =========== KONFIGURACJA SYSTEMU ===========
TX_PIN = 15
RX_PIN = 21
BIT_LEN_US = 990

# --- Tryb korekcji błędów ---
USE_HAMMING = False

# --- Tryb transmisji ---
USE_SELECTIVE_REPEAT = True  # True = Selective Repeat, False = Stop-and-Wait
WINDOW_SIZE = 3  # Rozmiar okna dla Selective Repeat

# --- Burst / powtórzenia ---
BURST_COUNT = 3              # Ile razy wysyłamy tę samą ramkę pod rząd (ustaw na 2 lub 3)
INTER_FRAME_GAP_MS = 10      # przerwa między powtórzeniami ramek w ms

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

# --- Sygnały ACK/NACK ---
ACK_DATA = "1" * DATA_BITS_LEN
NACK_DATA = "0" * DATA_BITS_LEN

# --- Dane testowe (9 ramek do wysłania) ---
DATA_FRAMES = [
    "11001100110011001100110001",  # Ramka 0
    "11001100110011001100110010",  # Ramka 1
    "11001100110011001100110011",  # Ramka 2
    "11001100110011001100110100",  # Ramka 3
    "11001100110011001100110101",  # Ramka 4
    "11001100110011001100110110",  # Ramka 5
    "11001100110011001100110111",  # Ramka 6
    "11001100110011001100111000",  # Ramka 7
    "11001100110011001100111001",  # Ramka 8
]

# --- Konfiguracja protokołu ---
ACK_TIMEOUT_MS = 1500
MAX_RETRANSMISSIONS = 3

# --- Inicjalizacja pinów ---
tx = Pin(TX_PIN, Pin.OUT)
rx = Pin(RX_PIN, Pin.IN)
tx.value(0)

# =========== FUNKCJE CRC-4 ===========
def calculate_crc4(data_bits):
    poly = 0x13
    data_len = len(data_bits)
    value = 0
    for b in data_bits:
        value = (value << 1) | (1 if b == '1' else 0)
    value <<= CRC_PARITY_LEN
    total_len = data_len + CRC_PARITY_LEN
    for i in range(total_len - 1, CRC_PARITY_LEN - 1, -1):
        if (value >> i) & 1:
            value ^= (poly << (i - CRC_PARITY_LEN))
    rem = value & ((1 << CRC_PARITY_LEN) - 1)
    return "{:04b}".format(rem)

def verify_crc4(data_bits, crc_bits):
    calculated = calculate_crc4(data_bits)
    return calculated == crc_bits

# =========== FUNKCJE HAMMINGA ===========
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
def build_data_frame(data_bits, seq_num=0):
    seq_bits = f"{seq_num:04b}"
    header = FRAME_TYPE_DATA + seq_bits + "1100"
    parity = calculate_parity(data_bits)
    return PREAMBLE + header + data_bits + parity

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

# =========== FUNKCJE TRANSMISJI ===========
def send_bits(bits):
    irq_state = machine.disable_irq()
    try:
        for bit in bits:
            tx.value(1 if bit == '1' else 0)
            utime.sleep_us(BIT_LEN_US)
    finally:
        tx.value(0)
        machine.enable_irq(irq_state)

def is_line_idle(required_us=None):
    # Sprawdź czy linia RX jest nieaktywna (LOW) przez required_us mikrosekund.
    # Jeśli required_us == None, użyj długości preambuły jako czasu do sprawdzenia.
    if required_us is None:
        required_us = PREAMBLE_LEN * BIT_LEN_US
    start = utime.ticks_us()
    while utime.ticks_diff(utime.ticks_us(), start) < required_us:
        if rx.value() == 1:
            return False
    return True

def send_frame_burst(bits, burst_count=BURST_COUNT):
    # Najpierw upewnij się, że linia wolna - jeśli nie, poczekaj krótki losowy backoff
    attempts = 0
    while not is_line_idle() and attempts < 5:
        # prosty pseudo-random backoff (nie wymaga modułu random)
        delay_ms = (utime.ticks_us() & 0xFF) % 50 + 5
        utime.sleep_ms(delay_ms)
        attempts += 1

    for i in range(burst_count):
        send_bits(bits)
        # mała przerwa między powtórzeniami, aby druga strona mogła odróżnić powtórzenia
        utime.sleep_ms(INTER_FRAME_GAP_MS)
    # po burst ustaw linię low
    tx.value(0)

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
        return None, None, None
    
    header = frame[:HEADER_LEN]
    data = frame[HEADER_LEN:HEADER_LEN + DATA_BITS_LEN]
    parity = frame[HEADER_LEN + DATA_BITS_LEN:]
    
    frame_type = header[:4]
    seq_num = int(header[4:8], 2)
    
    valid = verify_parity(data, parity)
    
    return frame_type, seq_num, valid

# =========== SELECTIVE REPEAT - GŁÓWNA LOGIKA ===========
def selective_repeat_transmission():
    total_frames = len(DATA_FRAMES)
    num_groups = (total_frames + WINDOW_SIZE - 1) // WINDOW_SIZE
    
    print(f"Rozpoczynam transmisję {total_frames} ramek w {num_groups} grupach")
    
    for group in range(num_groups):
        group_start = group * WINDOW_SIZE
        group_end = min(group_start + WINDOW_SIZE, total_frames)
        
        print(f"\n=== GRUPA {group + 1}/{num_groups} (ramki {group_start} do {group_end-1}) ===")
        
        # Lista ramek do wysłania w tej grupie
        frames_to_send = list(range(group_start, group_end))
        unacked_frames = frames_to_send.copy()
        retry_count = 0
        
        while unacked_frames and retry_count < MAX_RETRANSMISSIONS:
            print(f"\nPróba {retry_count + 1} dla grupy {group + 1}")
            print(f"Ramki do potwierdzenia: {unacked_frames}")
            
            for seq_num in frames_to_send:
                if seq_num not in unacked_frames:
                    continue  # Ramka już potwierdzona
                    
                print(f"\n📤 Wysyłam ramkę {seq_num} (burst x{BURST_COUNT})")
                data = DATA_FRAMES[seq_num]
                frame_to_send = build_data_frame(data, seq_num)
                print(f"Tryb: {'Hamming' if USE_HAMMING else 'CRC-4'}")
                print(f"Dane: {data}")
                print(f"Parzystość: {calculate_parity(data)}")
                send_frame_burst(frame_to_send, BURST_COUNT)
                
                # Czekaj na ACK/NACK
                ack_received = False
                ack_wait_start = utime.ticks_ms()
                
                while utime.ticks_diff(utime.ticks_ms(), ack_wait_start) < ACK_TIMEOUT_MS:
                    preamble_time = wait_for_preamble(ACK_TIMEOUT_MS // 2)
                    if preamble_time is None:
                        continue
                    
                    response_frame = read_frame_after_preamble(preamble_time)
                    frame_type, resp_seq, valid = verify_frame(response_frame)
                    
                    if valid and frame_type in [FRAME_TYPE_ACK, FRAME_TYPE_NACK]:
                        if resp_seq == seq_num:
                            if frame_type == FRAME_TYPE_ACK:
                                print(f"✅ Otrzymano ACK dla ramki {seq_num}")
                                if seq_num in unacked_frames:
                                    unacked_frames.remove(seq_num)
                                ack_received = True
                            else:
                                print(f"❌ Otrzymano NACK dla ramki {seq_num}")
                            break
                        else:
                            print(f"⚠️  Otrzymano odpowiedź dla innej ramki ({resp_seq}), ignoruję")
                    else:
                        print("⚠️  Odebrano nieprawidłową ramkę odpowiedzi")
                
                if not ack_received and seq_num in unacked_frames:
                    print(f"⏰ Timeout dla ramki {seq_num}")
                
                utime.sleep_ms(500)  # Przerwa między ramkami
            
            # Sprawdź które ramki nadal nie są potwierdzone
            if unacked_frames:
                print(f"\nNiepotwierdzone ramki po próbie {retry_count + 1}: {unacked_frames}")
                retry_count += 1
                # W następnej próbie wyślij tylko niepotwierdzone ramki
                frames_to_send = unacked_frames.copy()
            else:
                print(f"✅ Wszystkie ramki w grupie {group + 1} potwierdzone")
                break
        
        if unacked_frames:
            print(f"🛑 Nie udało się przesłać ramek {unacked_frames} po {MAX_RETRANSMISSIONS} próbach")
            # Kontynuuj z następną grupą
            unacked_frames.clear()
        
        utime.sleep_ms(2000)  # Przerwa między grupami
    
    print("\n" + "="*50)
    print("TRANSMISJA ZAKOŃCZONA")
    print(f"Wysłano {total_frames} ramek w {num_groups} grupach")
    print("="*50)

# =========== STOP-AND-WAIT - GŁÓWNA LOGIKA ===========
def stop_and_wait_transmission():
    total_frames = len(DATA_FRAMES)
    seq_num = 0
    
    print(f"Rozpoczynam transmisję {total_frames} ramek (Stop-and-Wait)")
    
    while seq_num < total_frames:
        print(f"\n=== RAMKA {seq_num + 1}/{total_frames} ===")
        
        data = DATA_FRAMES[seq_num]
        frame_to_send = build_data_frame(data, seq_num)
        print(f"Tryb: {'Hamming' if USE_HAMMING else 'CRC-4'}")
        print(f"Dane: {data}")
        print(f"Parzystość: {calculate_parity(data)}")
        
        print("📤 Wysyłam ramkę...")
        send_frame_burst(frame_to_send, BURST_COUNT)
        
        # Czekaj na ACK
        ack_received = False
        retry_count = 0
        
        while not ack_received and retry_count < MAX_RETRANSMISSIONS:
            print(f"\nOczekiwanie na ACK (próba {retry_count + 1}/{MAX_RETRANSMISSIONS})...")
            ack_wait_start = utime.ticks_ms()
            
            while utime.ticks_diff(utime.ticks_ms(), ack_wait_start) < ACK_TIMEOUT_MS:
                preamble_time = wait_for_preamble(ACK_TIMEOUT_MS // 2)
                if preamble_time is None:
                    continue
                
                response_frame = read_frame_after_preamble(preamble_time)
                frame_type, resp_seq, valid = verify_frame(response_frame)
                
                if valid and frame_type == FRAME_TYPE_ACK and resp_seq == seq_num:
                    print(f"✅ Otrzymano ACK dla ramki {seq_num}")
                    ack_received = True
                    seq_num += 1
                    break
                elif valid and frame_type == FRAME_TYPE_NACK and resp_seq == seq_num:
                    print(f"❌ Otrzymano NACK dla ramki {seq_num}")
                    break
            
            if not ack_received:
                retry_count += 1
                if retry_count < MAX_RETRANSMISSIONS:
                    print(f"🔄 Retransmisja ramki {seq_num}")
                    send_frame_burst(frame_to_send, BURST_COUNT)
                else:
                    print(f"🛑 Przekroczono maksymalną liczbę retransmisji dla ramki {seq_num}")
                    seq_num += 1  # Przejdź do następnej ramki mimo braku ACK
        
        utime.sleep_ms(2000)  # Przerwa między ramkami
    
    print("\n" + "="*50)
    print("TRANSMISJA ZAKOŃCZONA")
    print(f"Wysłano {total_frames} ramek")
    print("="*50)

# =========== GŁÓWNA PĘTLA ===========
print("=== Raspberry Pi Pico TX/RX ready ===")
print(f"Tryb korekcji: {'Hamming (31,26)' if USE_HAMMING else 'CRC-4'}")
print(f"Tryb transmisji: {'Selective Repeat' if USE_SELECTIVE_REPEAT else 'Stop-and-Wait'}")
print(f"Rozmiar okna: {WINDOW_SIZE}")
print(f"Maksymalna liczba retransmisji: {MAX_RETRANSMISSIONS}")
print(f"Liczba ramek do wysłania: {len(DATA_FRAMES)}")
print(f"BURST_COUNT: {BURST_COUNT}, INTER_FRAME_GAP_MS: {INTER_FRAME_GAP_MS}")

while True:
    if USE_SELECTIVE_REPEAT:
        selective_repeat_transmission()
    else:
        stop_and_wait_transmission()
    
    print("\n🔁 Rozpoczynam nową transmisję za 5 sekund...")
    utime.sleep(5)
