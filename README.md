# Transmisja ARQ między ESP32 a Raspberry Pi Pico

Projekt realizuje bezprzewodową transmisję danych pomiędzy ESP32 i Raspberry Pi Pico z użyciem prostych nadajników i odbiorników 433 MHz. Całość komunikacji opiera się o **protokół ARQ (Automatic Repeat reQuest)** w odmianie **Stop-and-Wait**, z kontrolą błędów na poziomie ramki przy pomocy kodu Hamminga (31,26).

Projekt będzie sukcesywnie rozbudowywany o obsługę różnych metod wykrywania/transmisji błędów (np. Hamming, CRC-8) i różne protokoły ARQ (np. Go-Back-N, Selective Repeat).

---

## Najważniejsze cechy

- Zabezpieczenie przed błędami transmisji przez kod Hamminga (31,26)
- Detekcja preambuły i synchronizacja odbioru w czasie rzeczywistym
- Realizacja transmisji Stop-and-Wait ARQ (transmisja, oczekiwanie na ACK/NACK, retransmisje)
- Oddzielne implementacje dla nadajnika (Raspberry Pi Pico, Python) i odbiornika (ESP32, C++/Arduino)
- Gotowość do rozbudowy o nowe tryby transmisji (Hamming / CRC-8) i protokoły ARQ

---

## Schemat działania

1. **Nadajnik (pico-fixed.py)** buduje ramkę danych (preambuła + nagłówek + dane + bity parzystości Hamminga), wysyła ją przez GPIO oraz czeka na odpowiedź z odbiornika.
2. **Odbiornik (esp32.ino)** wykrywa preambułę, synchronizuje czas bitu, odczytuje ramkę, sprawdza jej poprawność (kod Hamminga), a następnie odsyła ACK (jeśli poprawna) lub NACK (w przypadku błędu).
3. Proces powtarza się do momentu uzyskania potwierdzenia lub przekroczenia liczby retransmisji.

---

## Najważniejsze części kodu

### `pico-fixed.py` - nadajnik (raspberry pi pico, MicroPython)

- **Konfiguracja:** Określenie pinów, długości bitu, długości preambuły itd.
- **calculate_hamming_parity(data):** Funkcja licząca bity parzystości kodu Hamminga (31,26) dla transmitowanych danych.
- **build_data_frame(seq_num):** Buduje ramkę zawierającą m.in. typ ramki ("data"), numer sekwencyjny, dane i bity parzystości.
- **send_bits(bits):** Wysyła kolejne bity przez pin TX, zachowując zadany czas trwania bitu.
- **wait_for_preamble_with_sync():** Odbiera preambułę, pozwalając na dokładne zsynchronizowanie czasu próbkowania odbiornika.
- **Główna pętla:** Budowanie ramki danych, wysyłka, oczekiwanie na ACK/NACK, retransmisje w razie braku potwierdzenia.

### `esp32.ino` - odbiornik (ESP32, Arduino/C++)

- **calculate_hamming_parity(data):** Tożsama implementacja algorytmu Hamminga do kontroli poprawności ramki.
- **wait_for_preamble_with_sync():** Oczekiwanie na sygnał preambuły, pomiar czasu trwania bitu.
- **read_frame_with_sync():** Odczytywanie kompletnej ramki po synchronizacji.
- **verify_frame():** Sprawdzenie poprawności długości ramki i bitów parzystości Hamminga.
- **Loop:** Cyklicznie nasłuchuje transmisji, w razie poprawnej ramki odsyła ACK, w przeciwnym razie NACK.

---

## Rozwój projektu

Obecnie obsługiwany jest tylko tryb z kodowaniem Hamminga w protokole Stop-and-Wait ARQ. Kolejne plany rozwojowe projektu:

- **Podział kodu** na podmoduły: transmisje z kodem Hamminga / transmisje z CRC-8 (lub innymi kodami detekcji błędów)
- **Wdrożenie innych protokołów ARQ:** np. Go-Back-N i Selective Repeat
- **Konfiguracja protokołu i kodowania** przez użytkownika (parametryzacja)
- **Testy wydajnościowe i odporności na błędy**

---

## Pliki kodu

- [`pico-fixed.py`] kod dla Raspberry Pi Pico, logika nadawcza
- [`esp32.ino`] kod dla ESP32, logika odbiorcza

---

## Przykład transmisji

1. Pico buduje i wysyła ramkę (preambuła, nagłówek, dane, parzystość).
2. ESP32 synchronizuje się na podstawie preambuły, odczytuje ramkę.
3. Jeśli parzystość Hamminga się zgadza: ESP32 odsyła ACK, Pico przechodzi do następnej ramki.
4. W przeciwnym razie ESP32 odsyła NACK, Pico powtarza transmisję.

---
