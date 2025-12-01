# Transmisja ARQ (ESP32 <-> Raspberry Pi Pico) — zwięzłe podsumowanie

Ten README opisuje aktualny stan implementacji dwóch plików dostarczonych poniżej: `esp32.ino` (ESP32, odbiornik/ACK) oraz `pico.py` (Raspberry Pi Pico, nadajnik/tx+rx w MicroPython). Opis jest celowo krótki i praktyczny — skupia się na tym, co robi kod, jakie są kluczowe parametry i gdzie można łatwo rozbudować projekt (CRC‑8, inne protokoły ARQ).

## Krótkie podsumowanie
- Mechanizm: Stop‑and‑Wait ARQ (nadajnik wysyła ramkę → oczekuje ACK/NACK → ewentualna retransmisja).
- Kontrola błędów: Hamming (31,26) — 26 bitów danych + 5 bitów parzystości.
- Nośnik fizyczny: proste nadajniki/odbiorniki 433 MHz, sterowane GPIO (bit timing software).
- Główne pliki:
  - esp32.ino — odbiornik, detekcja preambuły, odczyt ramki, weryfikacja, wysyłanie ACK/NACK.
  - pico.py — nadajnik, budowa ramek Hamming, wysyłka bitów, oczekiwanie na ACK z synchronizacją.

## Struktura ramki
- Preambuła: 16 bitów, stała = "1010101010101010"
- Nagłówek: 12 bitów (4 bity typ ramki, 4 bity numer sekwencji, 3 bity długość, 1 bit rezerwa)
- Dane: 26 bitów
- Parzystość: 5 bitów (Hamming)
- Długość po preambule = HEADER_LEN + DATA_BITS_LEN + HAMMING_PARITY_LEN (w kodzie stałe)

## Piny i timing (domyślne w kodzie)
- ESP32: RX_PIN = 21, TX_PIN = 47
- Pico: TX_PIN = 15, RX_PIN = 21
- BIT_LEN_US ≈ 990 μs — czas trwania bitu (wartość kluczowa do dopasowania)
- ESP32 ma dodatkowy parametr BIT_READ_DELAY_US (optymalne opóźnienie przy odczycie)

## Kluczowe funkcje — co robią (najważniejsze miejsca w kodzie)

ESP32 (esp32.ino)
- calculate_hamming_parity(data) — tworzy 5‑bitową parzystość Hamminga dla 26 bitów danych.
- verify_hamming(data, parity) — porównuje obliczoną parzystość z odebraną.
- wait_for_preamble() — prosty detektor preambuły: czeka na krawędzie, przesuwa próbkę do środka bitu i porównuje sekwencję.
- read_frame_after_preamble() — po wykryciu preambuły odczytuje kolejne bity, próbkowane w środku ich trwania.
- introduce_random_errors(frame, p) — (testowo) losowo flipuje bity po preambule, by symulować błędy.
- send_bits(bits) — wysyła bity przez TX pin, z opóźnieniem BIT_LEN_US.
- build_ack_frame()/build_nack_frame() — budują ramki ACK/NACK z preambułą + header + stały payload + parzystość.

Pico (pico.py)
- calculate_hamming_parity(data) / verify_hamming(...) — analogicznie jak w ESP32 (wersje w Pythonie).
- build_data_frame(seq_num) / build_ack_frame() / build_nack_frame() — konstruują ramki do nadania.
- send_bits(bits) — wyłącza przerwania (stabilność timingowa) i nadaje bity przez GPIO z utime.sleep_us(BIT_LEN_US).
- wait_for_preamble(timeout) — wykrywa preambułę mierząc odstępy między krawędziami i sprawdzając próbki po środku impulsów; zwraca timestamp końca preambuły.
- read_frame_after_preamble(preamble_ts) — wyrównane próbkowanie do środków bitów zaczynając od preamble_ts + 1*BIT_LEN_US + 0.5*BIT_LEN_US.
- verify_frame(frame) — sprawdza długość i parzystość.

## Główny przebieg (sender — Pico)
1. build_data_frame(seq) → send_bits(frame).
2. Czekaj na ACK w pętli z timeoutem ACK_TIMEOUT_MS:
   - wait_for_preamble() — synchronizacja; jeśli znaleziono, read_frame_after_preamble(preamble_ts).
   - verify_frame(ack_frame) → sprawdź typ w nagłówku (ACK/NACK).
3. Jeśli ACK → inkrementuj numer sekwencji; jeśli brak → retransmituj (licznik retransmisji).
4. Pauza między transmisjami (utime.sleep_ms).

Główne przebiegi (receiver — ESP32)
1. wait_for_preamble(); po wykryciu → read_frame_after_preamble().
2. verify_frame(frame) → jeśli OK → send_bits(build_ack_frame()); w przeciwnym razie send_bits(build_nack_frame()).
3. (Opcjonalnie) podczas testów wprowadź błędy do odebranej ramki, żeby sprawdzić ARQ.

## Jak i gdzie rozszerzać projekt (krótkie wskazówki)
- Dodanie CRC‑8:
  - Dodaj funkcję calculate_crc8(data) w obu plikach; w funkcji build_*_frame wstaw CRC zamiast bitów Hamminga (lub w dodatkowym polu).
  - W verify_frame sprawdzaj CRC zamiast/obok Hamminga.
- Obsługa innych protokołów ARQ:
  - Wydziel logikę ARQ z pętli głównej do oddzielnego modułu (np. arq.py / arq.cpp), żeby później podmienić Stop‑and‑Wait na Go‑Back‑N lub Selective‑Repeat.
  - Zwiększ liczbę bitów numeru sekwencji w nagłówku, jeśli planujesz okna większe niż 16.
- Uporządkowanie kodu:
  - Wydziel moduły: phy (GPIO/timing), frame (parsowanie/konstrukcja), fec (Hamming/CRC), arq (logika retransmisji).
- Strojenie timingów:
  - BIT_LEN_US i BIT_READ_DELAY_US dostosuj do jakości łącza RF i opóźnień platformy. Testuj z `introduce_random_errors` aby zmierzyć odporność.

## Testy i debug
- Oba programy logują informacje (Serial.print / print): wykrycie preambuły, zmierzony czas, odebrane pola, parzystości.
- Użyj `introduce_random_errors` (ESP32) oraz testowych danych w Pico, by sprawdzić zachowanie retransmisji.
- Jeśli występują fałszywe detekcje preambuły lub błędy synchronizacji, spróbuj:
  - Zwiększyć/zmniejszyć BIT_LEN_US,
  - Dostosować BIT_READ_DELAY_US,
  - Zmienić preambułę na dłuższą lub bardziej odporne sekwencje (np. Barker).

## Uruchomienie (szybkie)
- Wgraj `esp32.ino` do ESP32 (ustaw RX/TX pin zgodnie ze sprzętem).
- Wgraj `pico.py` na Raspberry Pi Pico (MicroPython), ustaw piny zgodnie z połączeniami.
- Otwórz terminaly szeregowe obu urządzeń (115200) i obserwuj logi — nadajnik wysyła, odbiornik odpowiada ACK/NACK.

---

Plików nie modyfikuję tutaj — to zwięzłe wyjaśnienie ich działania i miejsc, gdzie warto dodać CRC‑8 i nowe protokoły ARQ. Jeśli chcesz, przygotuję wersję README z dodatkowymi przykładami komend do testów lub szablonem modułowej struktury kodu (krótki plan plików i zależności).
