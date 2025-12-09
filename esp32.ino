#include <Arduino.h>
#include <esp_timer.h>

const int RX_PIN = 21;
const int TX_PIN = 47;
const unsigned long BIT_LEN_US = 990;
const unsigned long BIT_READ_DELAY_US = 1030; // OPTYMALNE OPOŹNIENIE OD CZYTU
const int CRC_PARITY_LEN = 4;
const int HAMMING_PARITY_LEN = 5;
// --- Stałe ramki ---
const int PREAMBLE_LEN = 16;
const int HEADER_LEN = 12;
const int DATA_BITS_LEN = 26;
const int TOTAL_FRAME_LEN = PREAMBLE_LEN + HEADER_LEN + DATA_BITS_LEN + HAMMING_PARITY_LEN;

enum Mode { MODE_HAMMING = 0, MODE_CRC4 = 1 };
Mode CURRENT_MODE = MODE_CRC4;

const String PREAMBLE = "1010101010101010";
const String DATA_BITS="11001100110011001100110001";
// --- Typy ramek ---
const String FRAME_TYPE_DATA = "0001";
const String FRAME_TYPE_ACK = "0010"; 
const String FRAME_TYPE_NACK = "0011";
const String FRAME_TYPE_SREJ = "0100";

// --- Dane ACK/NACK ---
const String ACK_DATA = "11111111111111111111111111";  // 26 jedynek
const String NACK_DATA = "00000000000000000000000000"; // 26 zer

String calculate_crc4(const String &data) {
    // Wielomian CRC x^4 + x + 1 -> 0b0011
    const int poly = 0x3; // Wielomian
    int value = 0;         // Zmienna przechowująca dane

    // Konstruowanie liczby z bitów ciągu 'data'
    for (int i = 0; i < data.length(); i++) {
        value = (value << 1) | (data[i] == '1' ? 1 : 0); // Dodajemy każdy bit do value
    }

    // Długość CRC, czyli 4 bity (zatem trzeba je "rozwinąć" do miejsca na 4 bity)
    int crc_len = 4;
    value <<= crc_len; // Przesuwamy bity, zostawiając miejsce na CRC

    // Proces obliczania CRC (dzielenie przez wielomian)
    for (int i = 0; i < data.length(); i++) {
        if (value & (1 << (data.length() + crc_len - 1))) { // Sprawdzamy najstarszy bit
            value ^= (poly << (data.length() + crc_len - 1 - i)); // XOR z wielomianem
        }
        value <<= 1; // Przesunięcie bitów w lewo
    }

    // Wydobywamy 4 bity CRC (reszta z dzielenia przez wielomian)
    value &= 0xF; // Zostawiamy tylko 4 ostatnie bity (CRC-4)

    // Formatowanie wyniku CRC do formy binarnej
    String out = "";
    for (int i = 3; i >= 0; i--) { // 4 bity CRC
        out += ((value >> i) & 1) ? '1' : '0';
    }

    return out; // Zwracamy CRC w postaci binarnej
}
bool verify_crc4(const String &data, const String &crc) {
  return calculate_crc4(data) == crc;
}


// --- Funkcje Hamminga ---
String calculate_hamming_parity(const String &data) {
  int data_positions[26] = {3,5,6,7,9,10,11,12,13,14,15,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31};
  int word[32] = {0};
  
  for (int i = 0; i < 26; i++) {
    word[data_positions[i]] = (data[i] == '1') ? 1 : 0;
  }

  int p1=0, p2=0, p4=0, p8=0, p16=0;
  for (int j = 1; j <= 31; j++) {
    if (j & 1) p1 ^= word[j];
    if (j & 2) p2 ^= word[j];
    if (j & 4) p4 ^= word[j];
    if (j & 8) p8 ^= word[j];
    if (j & 16) p16 ^= word[j];
  }

  return String(p1) + String(p2) + String(p4) + String(p8) + String(p16);
}

bool verify_hamming(const String &data, const String &parity) {
  String calculated = calculate_hamming_parity(data);
  Serial.print("Hamming - Dane: "); Serial.print(data);
  Serial.print(", Parzystość: "); Serial.print(parity);
  Serial.print(", Obliczona: "); Serial.println(calculated);
  return calculated == parity;
}

// --- Budowanie ramek i ACK/NACK ---
String build_data_frame(int seq_num = 0, Mode mode = MODE_HAMMING) {
  String seq_bits = String((seq_num & 0x0F), BIN);
  while (seq_bits.length() < 4) seq_bits = "0" + seq_bits;
  char mode_flag = (mode == MODE_CRC4) ? '1' : '0';
  String header = FRAME_TYPE_DATA + seq_bits + "110" + String(mode_flag);
  String parity = (mode==MODE_CRC4) ? calculate_crc4(DATA_BITS) : calculate_hamming_parity(DATA_BITS);
  Serial.print("Wysyłane (mode ");
  Serial.print(mode_flag);
  Serial.print("): ");
  Serial.print(DATA_BITS);
  Serial.print(" parz:");
  Serial.println(parity);
  return PREAMBLE + header + DATA_BITS + parity;
}
String build_ack_frame(Mode mode = MODE_HAMMING) {
  String header = FRAME_TYPE_ACK + "0000" + "110" + String((mode==MODE_CRC4)?'1':'0');
  String parity = (mode==MODE_CRC4) ? calculate_crc4(ACK_DATA) : calculate_hamming_parity(ACK_DATA);
  return PREAMBLE + header + ACK_DATA + parity;
}

String build_nack_frame(Mode mode = MODE_HAMMING) {
  String header = FRAME_TYPE_NACK + "0000" + "110" + String((mode==MODE_CRC4)?'1':'0');
  String parity = (mode==MODE_CRC4) ? calculate_crc4(NACK_DATA) : calculate_hamming_parity(NACK_DATA);
  return PREAMBLE + header + NACK_DATA + parity;
}


// --- Wysyłanie bitów ---
void send_bits(const String &bits) {
  Serial.print("Wysyłanie: "); Serial.println(bits);
  for (int i=0; i < bits.length(); i++) {
    digitalWrite(TX_PIN, bits[i]=='1'?HIGH:LOW);
    ets_delay_us(BIT_LEN_US);
  }
  digitalWrite(TX_PIN, LOW);
}

// --- Odbiór preambuły ---
uint64_t wait_for_preamble_and_get_end_ts(uint64_t timeout_us = 2000000) {
  uint64_t start_time = esp_timer_get_time();
  int bit_count = 0;
  int last_state = digitalRead(RX_PIN);
  uint64_t last_edge_time = esp_timer_get_time();

  while ((esp_timer_get_time() - start_time) < timeout_us) {
    int cur = digitalRead(RX_PIN);
    if (cur != last_state) {
      uint64_t now = esp_timer_get_time();
      uint64_t pulse_width = now - last_edge_time;

      // akceptujemy krawędź tylko jeżeli pulse width ~ jedno BIT_LEN_US (tolerancja)
      if (pulse_width > (BIT_LEN_US * 0.4) && pulse_width < (BIT_LEN_US * 1.6)) {
        // próbkuj w połowie impulsu poprzedniego
        uint64_t sample_time = last_edge_time + (pulse_width / 2);
        while (esp_timer_get_time() < sample_time) {}
        int sampled = digitalRead(RX_PIN);
        char expected = PREAMBLE[bit_count];
        if ( (expected == '1' && sampled == HIGH) || (expected == '0' && sampled == LOW) ) {
          bit_count++;
          if (bit_count == PREAMBLE_LEN) {
            // teraz 'now' jest czas krawędzi kończącej preambułę — zwracamy go
            return now;
          }
        } else {
          bit_count = 0;
        }
      } else {
        // zbyt krótki/długi impuls -> reset licznika
        bit_count = 0;
      }

      last_edge_time = now;
      last_state = cur;
    }

    // jeśli brak krawędzi dłużej niż 3 bitów, resetujemy
    if ((esp_timer_get_time() - last_edge_time) > (BIT_LEN_US * 3)) {
      bit_count = 0;
      last_state = digitalRead(RX_PIN);
      last_edge_time = esp_timer_get_time();
    }
  }

  return 0; // timeout
}

// Czyta ramkę zaczynając od końca preambuły (preamble_ts = wartość zwrócona przez wait_for_preamble_and_get_end_ts)
// Zwraca String zawierającą HEADER + DATA + PARITY
String read_frame_after_preamble_ts(uint64_t preamble_ts) {
  // jeśli preamble_ts==0 -> błąd
  if (preamble_ts == 0) return String("");

  String header = "";
  // pierwszy bit po preambule zaczyna się ~one BIT_LEN_US po końcu preambuły
  // chcemy próbować dokładnie w środku bitu:
  // first_sample = preamble_ts + BIT_LEN_US + BIT_LEN_US/2  => preamble_ts + 1.5*BIT_LEN_US
  uint64_t first_sample = preamble_ts + BIT_LEN_US + (BIT_LEN_US / 2);
  while (esp_timer_get_time() < first_sample) {}

  uint64_t t = first_sample;
  // czytamy HEADER_LEN bitów
  for (int i = 0; i < HEADER_LEN; ++i) {
    header += (digitalRead(RX_PIN) ? '1' : '0');
    if (i < HEADER_LEN - 1) {
      t += BIT_READ_DELAY_US;
      while (esp_timer_get_time() < t) {}
    }
  }

  // odczytujemy tryb/flagę z ostatniego bitu nagłówka
  char mode_flag = header.charAt(HEADER_LEN - 1);
  int parity_len = (mode_flag == '1') ? CRC_PARITY_LEN : HAMMING_PARITY_LEN;

  String rest = "";
  // teraz czytamy DATA_BITS_LEN + parity_len
  for (int i = 0; i < DATA_BITS_LEN + parity_len; ++i) {
    t += (i == 0 ? BIT_READ_DELAY_US : 0); // t już ustawiony - pierwsza iteracja już ma właściwy czas
    // actually ensure next sample time:
    if (i > 0) {
      t = t + BIT_READ_DELAY_US;
    }
    while (esp_timer_get_time() < t) {}
    rest += (digitalRead(RX_PIN) ? '1' : '0');
  }

  return header + rest;
}

// --- Weryfikacja ramki ---
bool verify_frame(const String &frame) {
  if (frame.length() < HEADER_LEN + DATA_BITS_LEN + CRC_PARITY_LEN) {
    Serial.println("❌ Zbyt krótka ramka");
    return false;
  }
  String header = frame.substring(0, HEADER_LEN);
  char mode_flag = header.charAt(HEADER_LEN-1);
  int parity_len = (mode_flag == '1') ? CRC_PARITY_LEN : HAMMING_PARITY_LEN;
  int expected_len = HEADER_LEN + DATA_BITS_LEN + parity_len;
  if (frame.length() != expected_len) {
    Serial.print("❌ Błędna długość: "); Serial.println(frame.length());
    return false;
  }
  String data = frame.substring(HEADER_LEN, HEADER_LEN + DATA_BITS_LEN);
  String parity = frame.substring(HEADER_LEN + DATA_BITS_LEN);
  Serial.print("Nagłówek: "); Serial.println(header);
  Serial.print("Dane: "); Serial.println(data);
  Serial.print("Parz: "); Serial.println(parity);
  if (mode_flag == '1') {
    return verify_crc4(data, parity);
  } else {
    return verify_hamming(data, parity);
  }
}

// --- Dodawanie losowych bledow ---
String introduce_random_errors(const String &frame, float error_probability = 0.1) {
  String corrupted = frame;

  for (int i = PREAMBLE_LEN; i < corrupted.length(); i++) {
    if (((float)random(0, 1000) / 1000.0) < error_probability) {
      corrupted[i] = (corrupted[i] == '1') ? '0' : '1';
}
}

return corrupted;
}

// --- Setup i loop ---
void setup() {
  Serial.begin(115200);
  pinMode(RX_PIN, INPUT);
  pinMode(TX_PIN, OUTPUT);
  digitalWrite(TX_PIN, LOW);

  Serial.println("ESP32 ready: listening for Hamming frames...");
  Serial.print("Using bit read delay: "); Serial.println(BIT_READ_DELAY_US);
}

void loop() {
  uint64_t pre_ts = wait_for_preamble_and_get_end_ts(2000000);
  if (pre_ts!=0) {
    Serial.println("✅ Preambuła znaleziona!");

String frame = read_frame_after_preamble_ts(pre_ts);
    frame = introduce_random_errors(frame, 0.033);
    Serial.print("Odebrana ramka (");
    Serial.print(frame.length());
    Serial.print(" bitów): ");
    Serial.println(frame);

    if (verify_frame(frame)) {
      Serial.println("✅ RAMKA POPRAWNA - wysyłam ACK");
      delay(100);
      send_bits(build_ack_frame());
      //         ---------------|            |------------------------|
      // send_bits("10101010101010100000000001001011011101111011111011111011111");
      Serial.println("ACK wysłany");
    } else {
      Serial.println("❌ BŁĄD RAMKI - wysyłam NACK");
      delay(100);
      send_bits(build_nack_frame());
      Serial.println("NACK wysłany");
    }
  }
}