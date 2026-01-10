#include <Arduino.h>
#include <esp_timer.h>
#include "esp_system.h" // dla esp_random()

const int RX_PIN = 21;
const int TX_PIN = 47;
const unsigned long BIT_LEN_US = 990;
const unsigned long BIT_READ_DELAY_US = 1030;

// --- Tryb korekcji błędów ---
const bool USE_HAMMING = false; // true = Hamming (31,26), false = CRC-4

// --- Tryb transmisji ---
const bool USE_SELECTIVE_REPEAT = true; // true = Selective Repeat, false = Stop-and-Wait
const int WINDOW_SIZE = 3; // Rozmiar okna

// --- Burst / powtórzenia ---
const int BURST_COUNT = 3;         // Ile razy wysyłamy tę samą ramkę pod rząd
const int INTER_FRAME_GAP_MS = 10; // przerwa między powtórzeniami ramek w ms

// --- Stałe ramki ---
const int PREAMBLE_LEN = 16;
const int HEADER_LEN = 12;
const int DATA_BITS_LEN = 26;
const int HAMMING_PARITY_LEN = 5;
const int CRC_PARITY_LEN = 4;
const int PARITY_LEN = USE_HAMMING ? HAMMING_PARITY_LEN : CRC_PARITY_LEN;

const String PREAMBLE = "1010101010101010";

// --- Typy ramek ---
const String FRAME_TYPE_DATA = "0001";
const String FRAME_TYPE_ACK = "0010"; 
const String FRAME_TYPE_NACK = "0011";

// --- Dane ACK/NACK ---
const String ACK_DATA = "11111111111111111111111111";
const String NACK_DATA = "00000000000000000000000000";

// --- Funkcje CRC-4 ---
String calculate_crc4(const String &data) {
    const int poly_len = 5;
    const int poly[poly_len] = {1,0,0,1,1};

    int data_len = data.length();
    int bits_size = data_len + CRC_PARITY_LEN;
    if (bits_size > 64) {
      return String("0000");
    }

    int bits[64];
    for (int i = 0; i < data_len; ++i) {
        bits[i] = (data[i] == '1') ? 1 : 0;
    }
    for (int i = 0; i < CRC_PARITY_LEN; ++i) {
        bits[data_len + i] = 0;
    }

    for (int i = 0; i < data_len; ++i) {
        if (bits[i] == 1) {
            for (int j = 0; j < poly_len; ++j) {
                bits[i + j] ^= poly[j];
            }
        }
    }

    String out = "";
    for (int k = 0; k < CRC_PARITY_LEN; ++k) {
        out += bits[data_len + k] ? '1' : '0';
    }
    return out;
}

bool verify_crc4(const String &data, const String &parity) {
    String calculated = calculate_crc4(data);
    Serial.print("CRC-4 - Dane: "); Serial.print(data);
    Serial.print(", Parzystość: "); Serial.print(parity);
    Serial.print(", Obliczona: "); Serial.println(calculated);
    return calculated == parity;
}

// Mapowanie pozycji danych (1-31) na indeksy w tablicy 26-bitowej Stringa
const int data_positions[26] = {3,5,6,7,9,10,11,12,13,14,15,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31};

// Funkcja pomocnicza Hamminga
int calculate_syndrome_bit(int bit_pos, int word[]) {
    int parity = 0;
    for (int j = 1; j <= 31; j++) {
        if (j & bit_pos) {
            parity ^= word[j];
        }
    }
    return parity;
}

// Funkcja tylko do obliczania (używana przy wysyłaniu)
String calculate_hamming_parity(const String &data) {
    int word[32] = {0};
    for (int i = 0; i < 26; i++) {
        word[data_positions[i]] = (data[i] == '1') ? 1 : 0;
    }
    String p = "";
    p += String(calculate_syndrome_bit(1, word));
    p += String(calculate_syndrome_bit(2, word));
    p += String(calculate_syndrome_bit(4, word));
    p += String(calculate_syndrome_bit(8, word));
    p += String(calculate_syndrome_bit(16, word));
    return p;
}

bool verify_hamming(String &data, const String &parity) {
    int word[32] = {0};
    
    // 1. Kopiujemy dane do tablicy roboczej (pozycje 1-31)
    for (int i = 0; i < 26; i++) {
        word[data_positions[i]] = (data[i] == '1') ? 1 : 0;
    }
    
    // 2. Wstawiamy odebrane bity parzystości (p1, p2, p4, p8, p16)
    word[1] = (parity[0] == '1') ? 1 : 0;
    word[2] = (parity[1] == '1') ? 1 : 0;
    word[4] = (parity[2] == '1') ? 1 : 0;
    word[8] = (parity[3] == '1') ? 1 : 0;
    word[16] = (parity[4] == '1') ? 1 : 0;

    // 3. Obliczamy syndrom (adres błędu)
    int syndrome = 0;
    if (calculate_syndrome_bit(1, word)) syndrome += 1;
    if (calculate_syndrome_bit(2, word)) syndrome += 2;
    if (calculate_syndrome_bit(4, word)) syndrome += 4;
    if (calculate_syndrome_bit(8, word)) syndrome += 8;
    if (calculate_syndrome_bit(16, word)) syndrome += 16;

    // SCENARIUSZ A: Brak błędów wg matematyki Hamminga
    if (syndrome == 0) {
        return true; 
    }

    // SCENARIUSZ B: Hamming twierdzi, że znalazł błąd na pozycji 'syndrome'
    // Jeśli adres jest w zakresie 1-31, próbujemy naprawić
    if (syndrome >= 1 && syndrome <= 31) {
        word[syndrome] = !word[syndrome]; // Negacja bitu (naprawa)
    } else {
        return false; // Syndrom poza zakresem - ewidentny błąd wielokrotny
    }

    // 4. --- KRYTYCZNA WERYFIKACJA (ANTY-ALIASING) ---
    // Wyciągamy dane po naprawie
    String fixed_data = "";
    for (int i = 0; i < 26; i++) {
        fixed_data += (word[data_positions[i]] ? '1' : '0');
    }

    // Ponownie liczymy bity parzystości dla tych "naprawionych" danych
    String check_p = calculate_hamming_parity(fixed_data);
    
    // Wyciągamy bity parzystości z tablicy word (po naprawie)
    String fixed_p = "";
    fixed_p += (word[1] ? '1' : '0');
    fixed_p += (word[2] ? '1' : '0');
    fixed_p += (word[4] ? '1' : '0');
    fixed_p += (word[8] ? '1' : '0');
    fixed_p += (word[16] ? '1' : '0');

    // Jeśli po naprawie bity parzystości zgadzają się z danymi, to był 1 błąd.
    // Jeśli nadal się NIE ZGADZAJĄ, to znaczy, że błędów było więcej (np. Twoje 3 bity)
    if (check_p == fixed_p) {
        data = fixed_data;
        Serial.print("🛠️ Hamming: Naprawiono błąd na pozycji "); Serial.println(syndrome);
        return true;
    } else {
        Serial.println("❌ Hamming: Zbyt wiele błędów (aliasing)! Odrzucam ramkę.");
        return false; // Wyrzuci NACK w loopie
    }
}
// --- Funkcje uniwersalne ---
String calculate_parity(const String &data) {
    if (USE_HAMMING) {
        return calculate_hamming_parity(data);
    } else {
        return calculate_crc4(data);
    }
}

bool verify_parity(String &data, const String &parity) {
    if (USE_HAMMING) {
        return verify_hamming(data, parity);
    } else {
        return verify_crc4(data, parity);
    }
}

// --- Budowanie ramek ACK/NACK ---
String build_ack_frame(int seq_num) {
  String seq_bits = String(seq_num, BIN);
  while (seq_bits.length() < 4) seq_bits = "0" + seq_bits;
  String header = FRAME_TYPE_ACK + seq_bits + "1100";
  return PREAMBLE + header + ACK_DATA + calculate_parity(ACK_DATA);
}

String build_nack_frame(int seq_num) {
  String seq_bits = String(seq_num, BIN);
  while (seq_bits.length() < 4) seq_bits = "0" + seq_bits;
  String header = FRAME_TYPE_NACK + seq_bits + "1100";
  return PREAMBLE + header + NACK_DATA + calculate_parity(NACK_DATA);
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

bool is_line_idle(unsigned long required_us = 0) {
  if (required_us == 0) required_us = PREAMBLE_LEN * BIT_LEN_US;
  unsigned long start = esp_timer_get_time();
  while ((esp_timer_get_time() - start) < required_us) {
    if (digitalRead(RX_PIN) == HIGH) return false;
  }
  return true;
}

void send_frame_burst(const String &frame) {
  int attempts = 0;
  while (!is_line_idle() && attempts < 5) {
    uint32_t r = esp_random();
    int delay_ms = (r % 96) + 5;
    delay(delay_ms);
    attempts++;
  }
  for (int i = 0; i < BURST_COUNT; ++i) {
    send_bits(frame);
    delay(INTER_FRAME_GAP_MS);
  }
  digitalWrite(TX_PIN, LOW);
}

bool wait_for_preamble() {
  uint64_t start_time = esp_timer_get_time();
  int bit_count = 0;
  int last_state = digitalRead(RX_PIN);
  while ((esp_timer_get_time() - start_time) < 2000000) {
    uint64_t edge_start = esp_timer_get_time();
    while (digitalRead(RX_PIN) == last_state) {
      if ((esp_timer_get_time() - edge_start) > (BIT_LEN_US * 2)) {
        bit_count = 0;
        break;
      }
    }
    if ((esp_timer_get_time() - edge_start) > (BIT_LEN_US * 2)) {
      last_state = digitalRead(RX_PIN);
      continue;
    }
    uint64_t bit_center_time = esp_timer_get_time() + (BIT_LEN_US / 2);
    while (esp_timer_get_time() < bit_center_time) {}
    int current_bit = digitalRead(RX_PIN);
    char expected_bit = PREAMBLE[bit_count];
    if ((expected_bit=='1' && current_bit==HIGH) || (expected_bit=='0' && current_bit==LOW)) {
      bit_count++;
      if (bit_count == PREAMBLE_LEN) return true;
    } else {
      bit_count = 0;
    }
    last_state = current_bit;
  }
  return false;
}

String read_frame_after_preamble() {
  String frame = "";
  int bits_to_read = HEADER_LEN + DATA_BITS_LEN + PARITY_LEN;
  uint64_t first_bit_time = esp_timer_get_time() + (BIT_READ_DELAY_US / 2);
  while (esp_timer_get_time() < first_bit_time) {}
  for (int i=0; i < bits_to_read; i++) {
    frame += (digitalRead(RX_PIN)?'1':'0');
    if (i < bits_to_read-1) {
      uint64_t next_bit_time = esp_timer_get_time() + BIT_READ_DELAY_US;
      while (esp_timer_get_time() < next_bit_time) {}
    }
  }

  return frame;
}

bool verify_frame(String &frame, int &seq_num) {
  if (frame.length() != HEADER_LEN + DATA_BITS_LEN + PARITY_LEN) {
    Serial.print("❌ Błędna długość ramki: "); Serial.println(frame.length());
    return false;
  }
  String header = frame.substring(0, HEADER_LEN);
  String data = frame.substring(HEADER_LEN, HEADER_LEN + DATA_BITS_LEN);
  String parity = frame.substring(HEADER_LEN + DATA_BITS_LEN);
  String seq_bits = header.substring(4, 8);
  seq_num = strtol(seq_bits.c_str(), NULL, 2);

  bool ok = verify_parity(data, parity);
  if (USE_HAMMING && ok) {
      frame = header + data + parity; // Zaktualizuj ramkę naprawionymi danymi
  }
  return ok;
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



void setup() {
  Serial.begin(115200);
  pinMode(RX_PIN, INPUT);
  pinMode(TX_PIN, OUTPUT);
  digitalWrite(TX_PIN, LOW);
  Serial.println("ESP32 ready: listening...");
}

void loop() {
  if (wait_for_preamble()) {
    Serial.println("\n✅ Preambuła znaleziona!");
    String frame = read_frame_after_preamble();
    // frame = introduce_random_errors(frame, 0.5);
    // if(frame[15]=='0')frame[15]='1';
    // else frame[15]='0';
    // if(frame[16]=='0')frame[16]='1';
    // else frame[16]='0';
    int seq_num = 0;
    if (verify_frame(frame, seq_num)) {
      Serial.print("✅ RAMKA "); Serial.print(seq_num); Serial.println(" OK");
      delay(100);
      send_frame_burst(build_ack_frame(seq_num));
    } else {
      Serial.print("❌ BŁĄD RAMKI "); Serial.print(seq_num); Serial.println(" - NACK");
      delay(100);
      send_frame_burst(build_nack_frame(seq_num));
    }
  }
}