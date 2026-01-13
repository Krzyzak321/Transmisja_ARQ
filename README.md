# ARQ (ESP32 ↔ Raspberry Pi Pico)

Podsumowanie projektu: prosty protokół ARQ (ACK/NACK) nadawany przez GPIO (np. 433 MHz TX/RX moduły). Repo zawiera implementacje po stronie odbiorcy (ESP32) i nadajnika (Raspberry Pi Pico, MicroPython).

## Pliki
- `esp32.ino` — odbiornik (ESP32): detekcja preambuły, odczyt ramki, weryfikacja (Hamming/CRC), wysyłanie ACK/NACK.
- `pico.py` — nadajnik (Raspberry Pi Pico, MicroPython): generowanie ramek, wysyłka, oczekiwanie na ACK/NACK, Selective Repeat / Stop-and-Wait.

## Krótkie założenia
- Medium: GPIO sterujące nadajnikiem/odbiornikiem (np. 433 MHz).
- Synchronizacja bitów: software timing (BIT_LEN_US ~ 990 µs domyślnie).
- ARQ: Stop‑and‑Wait lub Selective‑Repeat (konfigurowalne).
- FEC: Hamming(31,26) (5 bitów parzystości) lub CRC‑4 (4 bity) — wybieralne w kodzie.

## Struktura ramki 
- Preambuła: 16 bitów — `1010101010101010`
- Nagłówek: 12 bitów:
  - 4 bity — typ ramki (DATA / ACK / NACK)
  - 4 bity — numer sekwencji (seq)
  - 3 bity — długość/grupa (grupowanie w Selective Repeat)
  - 1 bit — rezerwa
- Dane: 26 bitów
- Parzystość: Hamming = 5 bitów lub CRC‑4 = 4 bity (w zależności od konfiguracji)

ACK / NACK: payload to stała sekwencja (ACK = wszystkie `1`, NACK = wszystkie `0`) + parzystość.

## Domyślne piny i timing
- ESP32:
  - RX_PIN = 21, TX_PIN = 47
  - BIT_LEN_US = 990, BIT_READ_DELAY_US (opóźnienie próbkowania)
- Pico:
  - TX_PIN = 15, RX_PIN = 21
  - BIT_LEN_US = 990
Uwaga: dostosuj piny i BIT_LEN_US do sprzętu i jakości łącza RF.

## Tryby działania (jak przełączać)
- Hamming vs CRC: ustaw `USE_HAMMING = True/False` w obu plikach.
- ARQ: `USE_SELECTIVE_REPEAT = True/False` (Pico i ESP32 muszą zgadzać się co do trybu).
- Parametry okna: `WINDOW_SIZE`, `GROUP_SIZE`, `BURST_COUNT`, `INTER_FRAME_GAP_MS`, `ACK_TIMEOUT_MS` — edytuj w plikach.

## Jak to działa – skrót
Sender (Pico):
1. Buduje `DATA` frame (preambuła + header + data + parity).
2. Wysyła ramki (może wysyłać grupy — Selective Repeat — lub pojedynczo).
3. Czeka na ACK/NACK: wykrywa preambułę, odczytuje ramkę odpowiedzi, weryfikuje.
4. Jeśli ACK → przechodzi dalej; jeśli NACK → retransmituje brakujące ramki lub całą grupę.

Receiver (ESP32):
1. Nasłuchuje na preambułę (przez detekcję zboczy i próbkowanie w środku bitu).
2. Odczytuje header + data + parity, weryfikuje (Hamming/CRC).
3. Jeśli OK → wysyła ACK (może wysyłać burst); jeśli nie → wysyła NACK (maską/seq wskazuje brakujące ramki).

NACK maska: 4‑bitowy mask (w implementacji) określający które ramki grupy są obecne; nadajnik interpretuje `0` jako brak i retransmituje te ramki.

## Testy i debug
- W ESP32 jest funkcja testowa `introduce_random_errors(frame, p)` — użyj jej, by zasymulować błędy i testować ARQ.
- Logi: `Serial.print` / `print` informują o:
  - wykryciu preambuły,
  - numerze sekwencji,
  - wyniku weryfikacji (naprawiono błąd Hamming / CRC fail),
  - wysłanych ACK/NACK i liczbie retransmisji.
- Jeśli pojawiają się fałszywe preambuły / złe synchronizacje:
  - dopasuj BIT_LEN_US,
  - zwiększ preambułę lub zmień sekwencję (np. Barker),
  - dopasuj BIT_READ_DELAY_US na ESP32.

## Strojenie i wskazówki praktyczne
- Najważniejszy parametr: BIT_LEN_US — zależy od jakości łącza RF i dokładności timera platformy.
- Bursty: ustaw `BURST_COUNT = 2..3`, jeśli sygnał jest niestabilny.
- Linia idle: przed wysyłką sprawdź `is_line_idle()` (kod ma prosty backoff).
- Wspólna konfiguracja: upewnij się, że oba urządzenia mają ten sam tryb korekcji i te same wartości timingowe.

## Rozszerzenia (gdzie warto rozbudować)
- Dodać CRC‑8 lub CRC‑16 zamiast/obok Hamming:
  - dodać `calculate_crc8(...)` w obu plikach i użyć jako `calculate_parity`.
- Uporządkować kod modularnie:
  - moduły: `phy` (GPIO/timing), `frame` (parsowanie/konstrukcja), `fec` (Hamming/CRC), `arq` (logika retransmisji).
- Inne ARQ: dodać Go‑Back‑N lub alternatyczne heurystyki transmisji.
- Większe okno: zwiększyć liczbę bitów numeru sekwencji (obecnie 4 bity = 0–15).

## Szybkie komendy (upraszczające wgrywanie)
- ESP32: wgraj `esp32.ino` z Arduino IDE lub Arduino CLI.
- Pico: wrzuć `pico.py` na urządzenie przez Thonny / rshell / ampy.

Przykład (Thonny): otwórz urządzenie → zapisz jako `main.py` lub `pico.py` na PICO.
Przykład (Arduino IDE): potrzeba dodać rozszerzenie od espressif systems ustawić odpowiednio ustawienei urządzenie w zalezności od wersji esp i wysłać do urządzenia

## Czego oczekiwać i testy
- Po wgraniu: otwórz oba terminale szeregowe (115200). Nadajnik zacznie wysyłać ramki, odbiornik będzie logował preambułę, weryfikacje oraz wysyłał ACK/NACK.
- Obserwuj licznik retransmisji oraz ilość odebranych ACK/NACK.

## Autorzy
Kacper😶‍🌫️, Maciek🥀
