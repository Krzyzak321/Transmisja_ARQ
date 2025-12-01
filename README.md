# Transmisja ARQ między ESP32 a Raspberry Pi Pico

Projekt: bezprzewodowa komunikacja między ESP32 a Raspberry Pi Pico z użyciem nadajników/odbiorników 433 MHz. Obecna implementacja używa kodu Hamminga (31,26) do wykrywania/korekcji błędów oraz prostego protokołu ARQ w wariancie Stop‑and‑Wait (wysyłka → oczekiwanie na ACK/NACK → ewentualna retransmisja).

Ten README opisuje aktualny stan kodu z brancha `hammingpruba` (pliki: `pico-fixed.py` oraz `esp32.ino`) i wskazuje najważniejsze miejsca do rozbudowy (np. dodanie CRC‑8, nowych protokołów ARQ).

## Krótkie podsumowanie zmian / stanu obecnego

- Obie strony używają tej samej struktury ramki:
  - preambuła (16 bitów, stała: `1010101010101010`)
  - nagłówek (12 bitów: typ ramki 4 bity + numer sekwencji 4 bity + pola dodatkowe)
  - dane (26 bitów w obecnym przykładzie)
  - bity parzystości Hamminga (5 bitów) — kod Hamminga (31,26)
- Stałe (przykładowo):
  - BIT_LEN_US = 990
  - PREAMBLE_LEN = 16, HEADER_LEN = 12, DATA_BITS_LEN = 26, HAMMING_PARITY_LEN = 5
- Piny:
  - Pico: TX_PIN = 15, RX_PIN = 21
  - ESP32: RX_PIN = 21, TX_PIN = 47
- Protokół ARQ: Stop‑and‑Wait z timeoutem ACK (ACK_TIMEOUT_MS = 2000 ms) i licznikiem retransmisji.

Pliki źródłowe w branchu:
- pico-fixed.py — nadajnik / testowy transceiver w MicroPython na Raspberry Pi Pico
- esp32.ino — odbiornik / ACK/NACK na ESP32 (Arduino/C++)

## Jak działa transmisja (wysokopoziomowo)

1. Nadajnik (Pico) buduje ramkę: preambuła + nagłówek (typ + seq) + dane + parzystość Hamminga.
2. Nadajnik wysyła bity przez TX, każdemu bitowi odpowiada stała długość (BIT_LEN_US).
3. Odbiornik (ESP32) nasłuchuje linii RX na zmianę stanu; wykrywa preambułę, mierzy rzeczywisty czas bitu na podstawie preambuły i synchronizuje próbkowanie.
4. Po synchronizacji odbiornik odczytuje nagłówek + dane + parzystość, weryfikuje modalność ramki i poprawność parzystości Hamminga.
5. Jeśli ramka poprawna → odbiornik wysyła ACK (ramka z typem ACK), w przeciwnym razie wysyła NACK.
6. Nadajnik czeka na ACK w pętli z timeoutem; w razie braku ACK wykonuje retransmisję, inkrementując licznik retransmisji i (w razie potrzeby) numer sekwencji.

## Najważniejsze funkcje / sekcje kodu (co, gdzie i po co)

W obu plikach (pico-fixed.py i esp32.ino) znajdziesz analogiczne sekcje — warto je znać, żeby szybko wprowadzić zmiany lub dodać nowe tryby:

- Sekcja konfiguracji
  - Stałe: piny, BIT_LEN_US, długości pól ramki i preambuły, wartości ACK/NACK, timeouty.
  - Tu warto dodać parametry konfiguracyjne dla trybów CRC‑8, długości danych itp.

- Funkcje Hamminga
  - calculate_hamming_parity(data)
    - Buduje „word” zgodnie z pozycjami danych w kodzie Hamminga (pozycje bitów informacyjnych) i oblicza pięć bitów parzystości.
  - verify_hamming(data, parity)
    - Porównuje obliczoną parzystość z otrzymaną; w kodzie jest też log (drukowanie porównania).
  - Miejsce rozbudowy:
    - Dodaj nową funkcję calculate_crc8(data) i verify_crc8(data,crc), a następnie warunkowo wybieraj mechanizm kontroli błędów (Hamming/CRC).

- Budowanie ramek
  - build_data_frame(seq_num)
  - build_ack_frame()
  - build_nack_frame()
  - Ramka jest konkatencją preambuły + header + payload + parzystość.
  - Miejsce rozbudowy:
    - Ujednolić konstrukcję ramki w oddzielnym module/klasie, aby łatwo dodawać nowe typy ramek (np. z polem długości, różnym payloadem).

- Wysyłanie bitów
  - send_bits(bits)
    - Ustawia stan TX na HIGH/LOW zgodnie z kolejnymi bitami; w Pico wyłączany jest IRQ na czas wysyłki, w ESP32 używane są delay/us.
  - Uwaga: precyzja czasowa zależy od platformy i metod opóźniania (utime.sleep_us, ets_delay_us).

- Synchronizacja i detekcja preambuły
  - wait_for_preamble_with_sync()
    - Odczytuje krawędzie na linii RX, mierzy szerokość impulsu; jeśli kolejne próbki odpowiadają preambule, oblicza średni czas trwania bitu i zwraca moment końca preambuły.
  - read_frame_with_sync(bit_duration, preamble_end_time)
    - Po synchronizacji próbuje odczytać pozostałe bity, korzystając z pomiaru czasu bitu (próbkowanie w środku trwania bitu).
  - To kluczowe miejsce, jeżeli planujesz inne preambuły, różne taktowanie lub adaptacyjne próbkowanie.

- Weryfikacja ramki
  - verify_frame(frame)
    - Sprawdza długość ramki, rozbija na nagłówek/dane/parzystość i wywołuje verify_hamming lub inny mechanizm kontroli błędów.

- Główna pętla (Nadajnik i Odbiornik)
  - Nadajnik: budowa ramki → send → oczekiwanie na ACK/NACK (z synchronizacją) → obsługa timeoutu i retransmisji → pauza.
  - Odbiornik: nasłuch → po wykryciu preambuły → read_frame_with_sync → verify_frame → wysłanie ACK/NACK.

## Wskazówki do rozbudowy (gdzie i jak dodać funkcje)

- Dodanie CRC‑8:
  - Dodaj plik/module `crc.py` (dla PICO) i funkcję `calculate_crc8(data)` oraz analogiczną funkcję w ESP32.
  - W budowaniu ramki dodaj warunkowe wstawianie sumy kontrolnej zamiast bitów Hamminga; w verify_frame wybierz odpowiedni algorytm (Hamming vs CRC).
- Nowe protokoły ARQ (Go‑Back‑N, Selective Repeat):
  - Wydziel logikę ARQ do osobnego modułu (`arq.py` / `arq.h/cpp`), który będzie zarządzał kolejkami, oknami i timerami.
  - Zadbaj o numerowanie sekwencji i pola nagłówka (np. zwiększ liczbę bitów numeru sekwencji gdy potrzebne większe okno).
- Uporządkowanie kodu:
  - Rozdziel implementacje: `phy_*` (fizyczne wysyłanie/odbieranie), `frame_*` (konstruowanie/parsing ramek), `fec_*` (kodowanie/kontrola błędów), `arq_*` (logika ARQ).
  - Dzięki temu łatwiej testować i wymieniać poszczególne warstwy.

## Debug / testowanie

- Obie implementacje logują (Serial.print / print) przebieg: wykrywanie preambuły, zmierzony czas bitu, odebrane pola, porównanie parzystości. To podstawowa pomoc przy strojenia transmisji.
- Podczas testów zwróć uwagę na:
  - Różnice w opóźnieniach systemowych między platformami (MicroPython vs natywne funkcje esp).
  - Stabilność preambuły przy szumie RF — ewentualnie rozważyć bardziej odporne preambuły (np. sekwencje Barker).
  - Dopasowanie BIT_LEN_US do warunków (dystans, jakość nadajnika/odbiornika).

## Gdzie szukać zmian w kodzie

- `pico-fixed.py`
  - Sprawdź: funkcje `calculate_hamming_parity`, `build_*_frame`, `wait_for_preamble_with_sync`, `read_frame_with_sync`, główna pętla (send → wait for ACK → retry).
- `esp32.ino`
  - Sprawdź: `calculate_hamming_parity`, `wait_for_preamble_with_sync`, `read_frame_with_sync`, `verify_frame`, procedura wysyłania ACK/NACK.

Bezpośrednie odnośniki do plików w branchzie `hammingpruba`:
- https://github.com/Krzyzak321/Transmisja_ARQ/blob/hammingpruba/pico-fixed.py
- https://github.com/Krzyzak321/Transmisja_ARQ/blob/hammingpruba/esp32.ino

---

Jeśli chcesz, mogę:
- przygotować szablon modułowej struktury (np. propozycję katalogów i plików) aby łatwiej dodać CRC‑8 i nowe protokoły ARQ,
- napisać funkcję CRC‑8 i pokazać, gdzie ją wpiąć w istniejący kod,
- zaproponować testy automatyczne / skrypty symulujące losowe błędy bitowe, żeby sprawdzić odporność kodu.
