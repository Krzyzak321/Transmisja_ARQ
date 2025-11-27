#include <Arduino.h>
#include <esp_timer.h>

const int RX_PIN = 21;
const int TX_PIN = 47;
const unsigned long BIT_LEN_US = 990;

// --- Nowe stałe dla Hamminga ---
const int PREAMBLE_LEN = 16;
const int HEADER_LEN = 12;         // 4 typ + 4 sekw + 3 długość + 1 rezerwa
const int DATA_BITS_LEN = 26;      // 26 bitów danych
const int HAMMING_PARITY_LEN = 5;  // 5 bitów parzystości Hamminga
const int TOTAL_FRAME_LEN = PREAMBLE_LEN + HEADER_LEN + DATA_BITS_LEN + HAMMING_PARITY_LEN;

const String PREAMBLE = "1010101010101010";

// --- Typy ramek ---
const String FRAME_TYPE_DATA = "0001";
const String FRAME_TYPE_ACK = "0010"; 
const String FRAME_TYPE_NACK = "0011";
const String FRAME_TYPE_SREJ = "0100";

// --- Sygnały ACK/NACK ---
const String ACK_DATA = "11111111111111111111111111";  // 26 jedynek
const String NACK_DATA = "00000000000000000000000000"; // 26 zer

// --- Funkcje Hamminga (31,26) ---

String calculate_hamming_parity(const String &data) {
  // Tablica pozycji bitów danych w słowie 31-bitowym (indeksy 1..31)
  int data_positions[26] = {3,5,6,7,9,10,11,12,13,14,15,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31};
  int word[32] = {0}; // Słowo kodowe 31-bitowe (indeksy 1..31)
  
  // Wstaw bity danych na odpowiednie pozycje
  for (int i = 0; i < 26; i++) {
    int pos = data_positions[i];
    word[pos] = (data[i] == '1') ? 1 : 0;
  }
  
  // Oblicz bity parzystości
  int p1 = 0, p2 = 0, p4 = 0, p8 = 0, p16 = 0;
  
  for (int j = 1; j <= 31; j++) {
    if (j & 1) p1 ^= word[j];   // Bit 0: pozycje z ustawionym bitem 0
    if (j & 2) p2 ^= word[j];   // Bit 1: pozycje z ustawionym bitem 1  
    if (j & 4) p4 ^= word[j];   // Bit 2: pozycje z ustawionym bitem 2
    if (j & 8) p8 ^= word[j];   // Bit 3: pozycje z ustawionym bitem 3
    if (j & 16) p16 ^= word[j]; // Bit 4: pozycje z ustawionym bitem 4
  }
  
  return String(p1) + String(p2) + String(p4) + String(p8) + String(p16);
}

bool verify_hamming(const String &data, const String &parity) {
  String calculated_parity = calculate_hamming_parity(data);
  
  Serial.print("Hamming - Odebrane dane: ");
  Serial.print(data);
  Serial.print(", Odebrana parzystość: ");
  Serial.print(parity);
  Serial.print(", Obliczona parzystość: ");
  Serial.println(calculated_parity);
  
  return calculated_parity == parity;
}

// --- Funkcje budowania ramek ---

String build_ack_frame() {
  String header = FRAME_TYPE_ACK + "0000" + "1100"; // ACK, seq=0, długość=6, rezerwa=0
  String parity = calculate_hamming_parity(ACK_DATA);
  return PREAMBLE + header + ACK_DATA + parity;
}

String build_nack_frame() {
  String header = FRAME_TYPE_NACK + "0000" + "1100"; // NACK, seq=0, długość=6, rezerwa=0
  String parity = calculate_hamming_parity(NACK_DATA);
  return PREAMBLE + header + NACK_DATA + parity;
}

// --- Pozostałe funkcje (poprawione timingi) ---

void send_bits(String bits) {
  Serial.print("Wysyłanie: ");
  Serial.println(bits);
  
  for (int i = 0; i < bits.length(); i++) {
    digitalWrite(TX_PIN, bits[i] == '1' ? HIGH : LOW);
    ets_delay_us(BIT_LEN_US);
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
    
    // Ujednolicone timingi - 0.5 bitu do środka
    uint64_t bit_center_time = esp_timer_get_time() + (BIT_LEN_US * 0.5);
    while (esp_timer_get_time() < bit_center_time) {}
    
    int current_bit = digitalRead(RX_PIN);
    char expected_bit = PREAMBLE[bit_count];
    
    if ((expected_bit == '1' && current_bit == HIGH) || 
        (expected_bit == '0' && current_bit == LOW)) {
      bit_count++;
      if (bit_count == PREAMBLE_LEN) {
        return true;
      }
    } else {
      bit_count = 0;
    }
    
    last_state = current_bit;
  }
  return false;
}

String read_frame_after_preamble() {
  String frame = "";
  int bits_to_read = HEADER_LEN + DATA_BITS_LEN + HAMMING_PARITY_LEN;
  
  uint64_t first_bit_time = esp_timer_get_time() + (BIT_LEN_US * 0.52);
  while (esp_timer_get_time() < first_bit_time) {}
  
  for (int i = 0; i < bits_to_read; i++) {
    frame += (digitalRead(RX_PIN) ? '1' : '0');
    
    // Czekaj pełny okres bitu przed następnym odczytem
    if (i < bits_to_read - 1) {
      uint64_t next_bit_time = esp_timer_get_time() + BIT_LEN_US;
      while (esp_timer_get_time() < next_bit_time) {}
    }
  }
  
  return frame;
}

bool verify_frame(const String &frame) {
  if (frame.length() != HEADER_LEN + DATA_BITS_LEN + HAMMING_PARITY_LEN) {
    Serial.print("❌ Błędna długość ramki: ");
    Serial.print(frame.length());
    Serial.print(", oczekiwano: ");
    Serial.println(HEADER_LEN + DATA_BITS_LEN + HAMMING_PARITY_LEN);
    return false;
  }
  
  String header = frame.substring(0, HEADER_LEN);
  String data = frame.substring(HEADER_LEN, HEADER_LEN + DATA_BITS_LEN);
  String parity = frame.substring(HEADER_LEN + DATA_BITS_LEN);
  
  Serial.print("Odebrany nagłówek: ");
  Serial.println(header);
  Serial.print("Odebrane dane: ");
  Serial.println(data);
  Serial.print("Odebrana parzystość: ");
  Serial.println(parity);
  
  return verify_hamming(data, parity);
}

void setup() {
  Serial.begin(115200);
  pinMode(RX_PIN, INPUT);
  pinMode(TX_PIN, OUTPUT);
  digitalWrite(TX_PIN, 0);
  Serial.println("ESP32 ready: listening for Hamming-encoded data frames...");
}

void loop() {
  if (wait_for_preamble()) {
    Serial.println("✅ Znaleziono preambułę ramki danych!");
    
    String frame = read_frame_after_preamble();
    Serial.print("Odebrana ramka (");
    Serial.print(frame.length());
    Serial.print(" bitów): ");
    Serial.println(frame);
    
    if (verify_frame(frame)) {
      String header = frame.substring(0, HEADER_LEN);
      String data = frame.substring(HEADER_LEN, HEADER_LEN + DATA_BITS_LEN);
      
      Serial.println("✅ RAMKA POPRAWNA - WYSYŁAM ACK");
      
      delay(50);
      send_bits(build_ack_frame());
      Serial.println("ACK wysłany");
      
    } else {
      Serial.println("❌ BŁĄD RAMKI - WYSYŁAM NACK");
      delay(50);
      send_bits(build_nack_frame());
      Serial.println("NACK wysłany");
    }
  }
}