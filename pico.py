from machine import Pin
import utime

# =========== KONFIGURACJA SYSTEMU ===========
# Definicja pinów do komunikacji
TX_PIN = 15              # Pin do wysyłania danych (Transmit)
RX_PIN = 21              # Pin do odbierania danych (Receive)

# Konfiguracja czasowa i struktury ramki
BIT_LEN_US = 1000         # Czas trwania jednego bitu w mikrosekundach
PREAMBLE_LEN = 16        # Długość preambuły synchronizacyjnej
DATA_BITS_LEN = 42        # Długość danych w bitach
TOTAL_BITS_LEN = PREAMBLE_LEN + DATA_BITS_LEN + 1  # Całkowita długość ramki

# Definicja stałych sygnałów
PREAMBLE = "1010101010101010"  # Sygnał synchronizujący - pomaga odbiorcy zsynchronizować się z nadajnikiem
DATA_BITS = "11100010"         # Dane które chcemy przesłać
ACK_SIGNAL = "11111111"        # Potwierdzenie poprawnego odbioru (ACKnowledge)
NACK_SIGNAL = "00000000"       # Sygnał błędu (Negative ACKnowledge)

# Konfiguracja protokołu komunikacyjnego
ACK_TIMEOUT_MS = 1000          # Czas oczekiwania na potwierdzenie
MAX_RETRANSMISSIONS = 1000        # Maksymalna liczba ponownych wysłań przy braku potwierdzenia

# Inicjalizacja pinów
tx = Pin(TX_PIN, Pin.OUT)      # Ustaw pin TX jako wyjście
rx = Pin(RX_PIN, Pin.IN)       # Ustaw pin RX jako wejście
tx.value(0)                    # Upewnij się że nadajnik jest wyłączony na starcie

# =========== FUNKCJE POMOCNICZE ===========

def calculate_parity(data):
    """
    Oblicza bit parzystości dla danych
    Bit parzystości to dodatkowy bit dodawany do danych, który pozwala wykryć błędy
    Zasada: jeśli liczba jedynek w danych jest parzysta, bit parzystości = 0, w przeciwnym razie = 1
    """
    count = 0  # Licznik jedynek
    for bit in data:
        if bit == '1':
            count += 1  # Zliczamy wszystkie jedynki w danych
    
    # Jeśli liczba jedynek jest parzysta, zwracamy '0', w przeciwnym razie '1'
    return '0' if count % 2 == 0 else '1'

def build_frame():
    """
    Buduje kompletną ramkę danych do wysłania
    Ramka składa się z: PREAMBUŁA + DANE + BIT_PARZYSTOŚCI
    """
    parity = calculate_parity(DATA_BITS)  # Oblicz bit parzystości dla danych
    return PREAMBLE + DATA_BITS + parity  # Połącz wszystkie części w ramkę

def build_ack_frame():
    """Buduje ramkę potwierdzenia (ACK) - informuje nadajnik, że dane dotarły poprawnie"""
    return PREAMBLE + ACK_SIGNAL + calculate_parity(ACK_SIGNAL)

def build_nack_frame():
    """Buduje ramkę braku potwierdzenia (NACK) - informuje nadajnik o błędzie w danych"""
    return PREAMBLE + NACK_SIGNAL + calculate_parity(NACK_SIGNAL)

def send_bits(bits):
    """
    Wysyła ciąg bitów przez pin TX
    Każdy bit jest ustawiany na pinie na określony czas (BIT_LEN_US)
    Technika ta nazywa się modulacją OOK (On-Off Keying)
    """
    print("Wysyłanie:", bits)
    
    # Dla każdego bitu w ciągu...
    for bit in bits:
        # Ustaw stan wysoki jeśli bit = '1', niski jeśli bit = '0'
        tx.value(1 if bit == '1' else 0)
        # Czekaj przez czas trwania jednego bitu
        utime.sleep_us(BIT_LEN_US)
    
    # Po wysłaniu wszystkich bitów ustaw pin w stan niski (bezczynność)
    tx.value(0)

def wait_for_preamble(timeout_ms=1000):
    """
    Nasłuchuje na preambułę - czeka na sygnał synchronizujący od odbiorcy
    Preambuła to znany wzór bitów który pomaga zsynchronizować się z nadawcą
    """
    start_time = utime.ticks_ms()  # Zapamiętaj czas rozpoczęcia nasłuchiwania
    bit_count = 0                  # Licznik poprawnie odebranych bitów preambuły
    
    # Nasłuchuj przez określony czas (timeout)
    while utime.ticks_diff(utime.ticks_ms(), start_time) < timeout_ms:
        last_state = rx.value()  # Zapamiętaj aktualny stan pinu
        edge_time = utime.ticks_us()  # Czas kiedy zaczęliśmy czekać na zmianę
        
        # Czekaj na zmianę stanu pinu (zbocze sygnału)
        while rx.value() == last_state:
            # Jeśli czekamy zbyt długo bez zmiany, przerwij i zacznij od nowa
            if utime.ticks_diff(utime.ticks_us(), edge_time) > BIT_LEN_US * 2:
                bit_count = 0
                break
        
        # Jeśli nie było zmiany w odpowiednim czasie, kontynuuj nasłuchiwanie
        if utime.ticks_diff(utime.ticks_us(), edge_time) > BIT_LEN_US * 2:
            continue
        
        # Poczekaj do środka czasu trwania bitu (dla lepszej synchronizacji)
        utime.sleep_us(int(BIT_LEN_US * 0.7))
        # Odczytaj aktualną wartość bitu
        current_bit = rx.value()
        
        # Sprawdź czy odebrany bit zgadza się z oczekiwanym bitem preambuły
        expected_bit = PREAMBLE[bit_count]
        if (expected_bit == '1' and current_bit == 1) or (expected_bit == '0' and current_bit == 0):
            bit_count += 1  # Bit się zgadza - zwiększ licznik
            # Jeśli odebrano całą preambułę, zwróć sukces
            if bit_count == PREAMBLE_LEN:
                return True
        else:
            bit_count = 0  # Bit się nie zgadza - zacznij szukać preambuły od nowa
    
    return False  # Timeout - nie znaleziono preambuły w określonym czasie

def read_frame_after_preamble():
    """
    Odczytuje ramkę danych PO tym jak została już wykryta preambuła
    Zakładamy, że jesteśmy zsynchronizowani z nadajnikiem
    """
    frame = ""  # Bufor na odebrane bity
    
    # Odczytaj określoną liczbę bitów (dane + bit parzystości)
    for i in range(DATA_BITS_LEN + 1):
        utime.sleep_us(int(BIT_LEN_US*0.8))
        frame += '1' if rx.value() else '0'  # Odczytaj bit i dodaj do ramki
                # Poczekaj do następnego bitu

    return frame

def verify_frame(frame):
    """
    Sprawdza poprawność odebranej ramki
    Weryfikuje bit parzystości i długość ramki
    """
    # Sprawdź czy ramka ma oczekiwaną długość
    if len(frame) != DATA_BITS_LEN + 1:
        return False
    
    # Podziel ramkę na dane i bit parzystości
    data = frame[:DATA_BITS_LEN]
    received_parity = frame[DATA_BITS_LEN:]
    
    # Oblicz jaki powinien być bit parzystości dla odebranych danych
    calculated_parity = calculate_parity(data)
    
    # Porównaj obliczony bit parzystości z odebranym
    return received_parity == calculated_parity

# =========== GŁÓWNA PĘTLA PROGRAMU ===========

print("=== Raspberry Pi Pico TX/RX ready ===")
retransmission_count = 0  # Licznik ponownych wysłań

while True:
    ack_received = False  # Flaga czy otrzymaliśmy potwierdzenie
    
    print("\n=== PRÓBA WYSŁANIA RAMKI ===")
    
    # KROK 1: Przygotuj i wyślij ramkę danych
    frame_to_send = build_frame()   # Zbuduj ramkę z danymi
    #print("Wysyłam ramkę:", frame_to_send)
    send_bits(frame_to_send)        # Wyślij ramkę przez radio
    
    # KROK 2: Przejdź w tryb odbioru i czekaj na potwierdzenie (ACK)
    print("\n=== Oczekiwanie na ACK ===")
    #print("Oczekiwanie na ACK...")
    ack_wait_start = utime.ticks_ms()  # Zapamiętaj czas rozpoczęcia oczekiwania
    
    # Czekaj na ACK przez określony czas (ACK_TIMEOUT_MS)
    while utime.ticks_diff(utime.ticks_ms(), ack_wait_start) < ACK_TIMEOUT_MS:
        # Sprawdź czy nadchodzi preambuła (czy odbiorca odpowiada)
        if wait_for_preamble(ACK_TIMEOUT_MS):
            # Odbierz ramkę odpowiedzi
            ack_data = read_frame_after_preamble()
            print("Odebrana odpowiedź:", ack_data)
            
            # Sprawdź co to za odpowiedź
            data = ack_data[:DATA_BITS_LEN]
            if data == ACK_SIGNAL:
                # Otrzymaliśmy potwierdzenie - transmisja się udała!
                print("✅ Otrzymano ACK - transmisja udana!")
                ack_received = True
                retransmission_count = 0  # Zresetuj licznik ponownych wysłań
                break  # Wyjdź z pętli oczekiwania
            elif data == NACK_SIGNAL:
                # Otrzymaliśmy informację o błędzie
                print("❌ Otrzymano NACK - błąd transmisji")
                break  # Wyjdź z pętli oczekiwania
            else:
                # Otrzymaliśmy nieznany sygnał
                print("❓ Odebrano nieznany sygnał")
    
    # KROK 3: Obsłuż sytuację gdy nie otrzymano potwierdzenia
    if not ack_received:
        print("⏰ Timeout ACK - brak odpowiedzi")
        retransmission_count += 1  # Zwiększ licznik ponownych wysłań
        
        # Sprawdź czy nie przekroczono maksymalnej liczby ponownych wysłań
        if retransmission_count >= MAX_RETRANSMISSIONS:
            print("🛑 Przekroczono maksymalną liczbę retransmisji")
            retransmission_count = 0  # Zresetuj licznik
        else:
            # Jeszcze możemy próbować ponownie
            print("🔄 Retransmisja #" + str(retransmission_count))
            # UWAGA: Tutaj nie ma delay(), więc retransmisja nastąpi natychmiast w następnym obiegu pętli
    
    # KROK 4: Zrób przerwę przed następną próbą komunikacji
    utime.sleep_ms(2000)  # Czekaj 2 sekundy przed następną transmisją
