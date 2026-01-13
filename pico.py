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
BURST_COUNT = 1              # Ile razy wysyłamy tę samą ramkę pod rząd (ustaw na 2 lub 3)
INTER_FRAME_GAP_MS = 10      # przerwa między powtórzeniami ramek w ms

# --- Stałe ramki ---
PREAMBLE_LEN = 16
HEADER_LEN = 12
DATA_BITS_LEN = 26
HAMMING_PARITY_LEN = 5
CRC_PARITY_LEN = 4
PARITY_LEN = HAMMING_PARITY_LEN if USE_HAMMING else CRC_PARITY_LEN
BITS_AFTER_PREAMBLE = HEADER_LEN + DATA_BITS_LEN + PARITY_LEN
FRAME_LEN = PREAMBLE_LEN+BITS_AFTER_PREAMBLE

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
    "10000000000000000000000000",  # Ramka 1
    "11000000000000000000000000",  # Ramka 2
    "11100000000000000000000000",  # Ramka 3
    "11110000000000000000000000",  # Ramka 4
    "11111000000000000000000000",  # Ramka 5
    "11111100000000000000000000",  # Ramka 6
    "11111110000000000000000000",  # Ramka 7
    "11111111000000000000000000",  # Ramka 8
    "11111111100000000000000000",  # Ramka 9
    "11111111110000000000000000",  # Ramka 10
    "11111111111000000000000000",  # Ramka 11
    "11111111111100000000000000",  # Ramka 12
    "11111111111110000000000000",  # Ramka 13
    "11111111111111000000000000",  # Ramka 14
    "11111111111111100000000000",  # Ramka 15	
    "11111111111111110000000000",  # Ramka 16
]


retransmission_count = 0
acks=0
nacks=0

# --- Konfiguracja protokołu ---
ACK_TIMEOUT_MS = 3000
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

def build_data_frame(data_bits, seq_num=0, grup="00"):
    seq_bits = f"{seq_num:04b}"
    header = FRAME_TYPE_DATA + seq_bits + grup +"00"
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
    start_waiting = utime.ticks_ms()
    bit_count = 0
    last_state = rx.value()
    # Zmienne do pomiaru czasu trwania całej preambuły
    preamble_start_time = 0 
    
    while utime.ticks_diff(utime.ticks_ms(), start_waiting) < timeout_ms:
        current = rx.value()
        if current != last_state:
            now = utime.ticks_us()
            # Jeśli to pierwszy bit preambuły, zapisz czas startu
            if bit_count == 0:
                preamble_start_time = now
            
            # Mierzymy czas od ostatniego zbocza
            # Uwaga: w pierwszym obiegu last_edge może być stary, ale bit_count zresetuje się
            # jeśli pulse_width będzie bez sensu, więc to ok.
            
            # Tutaj uproszczona logika detekcji 1010...
            # Zakładamy, że zbocze następuje co BIT_LEN
            # W idealnym świecie zbocza są co ~990us
            
            # W tym miejscu po prostu czekamy na sekwencję 16 zmian stanu
            # pasujących do wzorca czasowego (0.5x do 1.5x BIT_LEN)
            pulse_width = utime.ticks_diff(now, preamble_start_time if bit_count == 0 else last_edge)
            
            # Jeśli to nie pierwszy bit, sprawdzamy czy szerokość impulsu ma sens
            if bit_count > 0:
                if pulse_width > BIT_LEN_US * 0.5 and pulse_width < BIT_LEN_US * 1.5:
                    bit_count += 1
                else:
                    # Zły timing - reset
                    bit_count = 0
                    # Jeśli obecny stan to '1' (początek preambuły), to może to być nowy start
                    if current == 1: 
                        bit_count = 1
                        preamble_start_time = now
            else:
                # Czekamy na '1' jako start preambuły
                if current == 1:
                    bit_count = 1
                    preamble_start_time = now
            
            last_edge = now
            last_state = current
            
            if bit_count == PREAMBLE_LEN:
                # Sukces! Obliczamy rzeczywisty czas trwania bitu
                total_duration = utime.ticks_diff(now, preamble_start_time)
                # Dzielimy przez (PREAMBLE_LEN - 1) bo mierzymy od zbocza do zbocza
                # Ale bezpieczniej przyjąć średnią z całości.
                # Preambuła ma 16 bitów, czyli 16 okresów "stanu"? 
                # Nie, 1010... to 16 bitów czasu.
                # Czas od pierwszego zbocza (start bitu 0) do ostatniego zbocza (koniec bitu 15)
                # to około 15.5 bitu lub 16 bitów zależnie jak łapiemy.
                # Uprośćmy: duration / (PREAMBLE_LEN - 0.5) daje niezły wynik
                actual_bit_len = total_duration / (PREAMBLE_LEN - 0.5)
                return now, actual_bit_len

    return None, None

def read_frame_after_preamble(preamble_end_ts, actual_bit_len):
    frame = ""
    bits_to_read = BITS_AFTER_PREAMBLE
    
    # Używamy zmierzonej długości bitu zamiast stałej BIT_LEN_US!
    # Ustawiamy punkt próbkowania na 0.5 lub 1.5 bitu od ostatniego zbocza preambuły
    # Ostatnie zbocze preambuły to koniec bitu "0" (jeśli preambuła kończy się zerem).
    # Następny bit zaczyna się od razu.
    
    # Startujemy od punktu "teraz" (koniec preambuły)
    next_sample_time = utime.ticks_add(preamble_end_ts, int(actual_bit_len * 0.5))
    
    # Musimy uwzględnić, że funkcja wait_for_preamble trochę trwałą i 'now' jest lekko w przeszłości
    # ale ticks_diff sobie z tym poradzi.
    
    for i in range(bits_to_read):
        # Przesuwamy się o 1 pełny (zmierzony) bit
        next_sample_time = utime.ticks_add(next_sample_time, int(actual_bit_len))
        
        # Czekamy aktywnie na ten moment
        while utime.ticks_diff(next_sample_time, utime.ticks_us()) > 0:
            pass
            
        frame += '1' if rx.value() else '0'

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
#======================SELECTIVE REPEAT ===========================
def selective_repeat_transmission():
    global retransmission_count
    global acks
    global nacks
    total_frames = len(DATA_FRAMES)
    GROUP_SIZE = 4  # twardo ustawiona liczba ramek w grupie
    num_groups = (total_frames + GROUP_SIZE - 1) // GROUP_SIZE
    
    print(f"Rozpoczynam transmisję {total_frames} ramek w {num_groups} grupach po {GROUP_SIZE} ramek")
    
    group = 0
    while group < num_groups:
        group_start = group * GROUP_SIZE
        group_end = min(group_start + GROUP_SIZE, total_frames)
        frames_to_send = list(range(group_start, group_end))
        retry_count = 0
        group_ack_received=False
        
        #while group_ack_received==False:
        while retry_count<MAX_RETRANSMISSIONS:
            print(f"\n=== GRUPA {group + 1}/{num_groups} (ramki {group_start} do {group_end-1}), próba {retry_count + 1} ===")
            
            # --- Wysyłamy wszystkie ramki w grupie ---
            for seq_num in frames_to_send:
                data = DATA_FRAMES[seq_num]
                grup="11"
                if(len(frames_to_send)==4):
                    grup="11"
                elif len(frames_to_send) == 3:
                    grup="10"
                elif len(frames_to_send) == 2:
                    grup="01"
                elif len(frames_to_send) == 1:
                    grup="00"
                frame_to_send = build_data_frame(data, seq_num, grup)
                print(f"📤 Wysyłam ramkę {seq_num} (burst x{BURST_COUNT})")
                send_frame_burst(frame_to_send, BURST_COUNT)
                utime.sleep_ms(100)  # krótkie odstępy między ramkami
            
            # --- Teraz czekamy na ACK/NACK dla całej grupy ---
            print("👂 Nasłuchiwanie odpowiedzi dla grupy...")
            group_ack_received = False
            ack_wait_start = utime.ticks_us()
            
            while utime.ticks_diff(utime.ticks_us(), ack_wait_start) < 1000*ACK_TIMEOUT_MS+BIT_LEN_US*FRAME_LEN*(4-len(frames_to_send)):
                preamble_end, real_bit_len = wait_for_preamble(ACK_TIMEOUT_MS // 2)
                if preamble_end is None:
                    continue
                
                response_frame = read_frame_after_preamble(preamble_end, real_bit_len)
                frame_type, resp_seq, valid = verify_frame(response_frame)
                
        
                
                # Sprawdzenie, czy odpowiedź dotyczy tej grupy
                if frame_type == FRAME_TYPE_ACK:
                    # Jeśli ACK obejmuje ostatnią ramkę grupy → cała grupa OK
                    if resp_seq in frames_to_send:
                        print(f"✅ Otrzymano ACK dla grupy {group + 1} (ramka {resp_seq})")
                        acks+=1
                        group_ack_received = True
                        break
                elif frame_type == FRAME_TYPE_NACK:
                    #if resp_seq in frames_to_send:
                        mask='{0:04b}'.format(resp_seq)
                        print(f"❌ Otrzymano NACK - Brakuje ramek: {mask}")
                        nacks+=1
                        frames_to_send = []
                        
                        for i in range(4):
                            if mask[i]=='0':
                                frames_to_send.append(group_start+i)
                        group_ack_received = False
                        break
            
            if group_ack_received:
                print(f"✅ Wszystkie ramki w grupie {group + 1} potwierdzone")
                break  # przechodzimy do kolejnej grupy
            else:
                retry_count += 1
                print(f"🔄 Retransmisja grupy {group + 1} (próba {retry_count + 1})")
                retransmission_count+=1
                utime.sleep_ms(500)  # krótka przerwa przed retransmisją
                
            if not valid:
                    print("⚠️ Odebrano nieprawidłową ramkę odpowiedzi")
                    continue
        if retry_count == MAX_RETRANSMISSIONS:
            print(f"🛑 Nie udało się przesłać grupy {group + 1} po {MAX_RETRANSMISSIONS} próbach")
        
        group += 1
        utime.sleep_ms(1000)  # przerwa między grupami
    
    print("\n" + "="*50)
    print("TRANSMISJA ZAKOŃCZONA")
    print(f"Wysłano {total_frames} ramek w {num_groups} grupach")
    print(f"==============\n Laczna liczba retransmisji: {retransmission_count}\n================")
    print(f"Odebrane ACK: {acks}")
    print(f"Odebrane NACK: {nacks}")
    print("="*50)


# =========== STOP-AND-WAIT - GŁÓWNA LOGIKA ===========
def stop_and_wait_transmission():
    global retransmission_count
    global acks
    global nacks
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
                preamble_end, real_bit_len = wait_for_preamble(ACK_TIMEOUT_MS // 2)
                if preamble_end is None:
                    continue
                
                response_frame = read_frame_after_preamble(preamble_end, real_bit_len)
                frame_type, resp_seq, valid = verify_frame(response_frame)
                
                if valid and frame_type == FRAME_TYPE_ACK and resp_seq == seq_num:
                    print(f"✅ Otrzymano ACK dla ramki {seq_num}")
                    acks+=1
                    ack_received = True
                    seq_num += 1
                    break
                elif valid and frame_type == FRAME_TYPE_NACK and resp_seq == seq_num:
                    print(f"❌ Otrzymano NACK dla ramki {seq_num}")
                    nacks+=1
                    break
            
            if not ack_received:
                retry_count += 1
                if retry_count < MAX_RETRANSMISSIONS:
                    print(f"🔄 Retransmisja ramki {seq_num}")
                    retransmission_count+=1
                    send_frame_burst(frame_to_send, BURST_COUNT)
                else:
                    print(f"🛑 Przekroczono maksymalną liczbę retransmisji dla ramki {seq_num}")
                    seq_num += 1  # Przejdź do następnej ramki mimo braku ACK
        
        utime.sleep_ms(2000)  # Przerwa między ramkami
    
    print("\n" + "="*50)
    print("TRANSMISJA ZAKOŃCZONA")
    print(f"Wysłano {total_frames} ramek")
    print(f"==============\n Laczna liczba retransmisji: {retransmission_count}\n================")
    print(f"Odebrane ACK: {acks}")
    print(f"Odebrane NACK: {nacks}")
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
