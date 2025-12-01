#include <Arduino.h>
#include <esp_timer.h>

const int RX_PIN = 21;
const int TX_PIN = 47;
const unsigned long BIT_LEN_US = 990;
const unsigned long BIT_READ_DELAY_US = 1030; // OPTYMALNE OPOŹNIENIE OD CZYTU

// --- Stałe ramki ---
const int PREAMBLE_LEN = 16;
const int HEADER_LEN = 12;
const int DATA_BITS_LEN = 26;
const int HAMMING_PARITY_LEN = 5;
const int TOTAL_FRAME_LEN = PREAMBLE_LEN + HEADER_LEN + DATA_BITS_LEN + HAMMING_PARITY_LEN;

const String PREAMBLE = "1010101010101010";

// --- Typy ramek ---
const String FRAME_TYPE_DATA = "0001";
const String FRAME_TYPE_ACK = "0010"; 
const String FRAME_TYPE_NACK = "0011";
const String FRAME_TYPE_SREJ = "0100";

// --- Dane ACK/NACK ---
const String ACK_DATA = "11111111111111111111111111";  // 26 jedynek
const String NACK_DATA = "00000000000000000000000000"; // 26 zer

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

// --- Budowanie ramek ACK/NACK ---
String build_ack_frame() {
  String header = FRAME_TYPE_ACK + "0000" + "1100"; // seq=0, długość=6, rezerwa=0
  return PREAMBLE + header + ACK_DATA + calculate_hamming_parity(ACK_DATA);
}

String build_nack_frame() {
  String header = FRAME_TYPE_NACK + "0000" + "1100"; 
  return PREAMBLE + header + NACK_DATA + calculate_hamming_parity(NACK_DATA);
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
bool wait_for_preamble() {
  uint64_t start_time = esp_timer_get_time();
  int bit_count = 0;
  int last_state = digitalRead(RX_PIN);

  while ((esp_timer_get_time() - start_time) < 2000000) { // 2s timeout
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

    if ((expected_bit=='1' && current_bit==HIGH) ||
        (expected_bit=='0' && current_bit==LOW)) {
      bit_count++;
      if (bit_count == PREAMBLE_LEN) return true;
    } else {
      bit_count = 0;
    }

    last_state = current_bit;
  }
  return false;
}

// --- Odczyt ramki po preambule ---
String read_frame_after_preamble() {
  String frame = "";
  int bits_to_read = HEADER_LEN + DATA_BITS_LEN + HAMMING_PARITY_LEN;

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

// --- Weryfikacja ramki ---
bool verify_frame(const String &frame) {
  if (frame.length() != HEADER_LEN + DATA_BITS_LEN + HAMMING_PARITY_LEN) {
    Serial.print("❌ Błędna długość ramki: "); Serial.println(frame.length());
    return false;
  }
  
  String header = frame.substring(0, HEADER_LEN);
  String data = frame.substring(HEADER_LEN, HEADER_LEN + DATA_BITS_LEN);
  String parity = frame.substring(HEADER_LEN + DATA_BITS_LEN);

  Serial.print("Nagłówek: "); Serial.println(header);
  Serial.print("Dane: "); Serial.println(data);
  Serial.print("Parzystość: "); Serial.println(parity);

  return verify_hamming(data, parity);
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
  if (wait_for_preamble()) {
    Serial.println("✅ Preambuła znaleziona!");

    String frame = read_frame_after_preamble();
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