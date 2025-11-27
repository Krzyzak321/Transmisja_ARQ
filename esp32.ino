#include <Arduino.h>
#include <esp_timer.h>

const int RX_PIN = 21;
const int TX_PIN = 47;
const unsigned long BIT_LEN_US = 990;

// --- Stałe dla Hamminga ---
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

// --- Sygnały ACK/NACK ---
const String ACK_DATA = "11111111111111111111111111";
const String NACK_DATA = "00000000000000000000000000";

// --- Struktura dla wyników synchronizacji ---
struct SyncResult {
  bool success;
  unsigned long measured_bit_len;
  uint64_t preamble_end_time;
};

// --- Funkcje Hamminga (31,26) ---
String calculate_hamming_parity(const String &data) {
  int data_positions[26] = {3,5,6,7,9,10,11,12,13,14,15,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31};
  int word[32] = {0};
  
  for (int i = 0; i < 26; i++) {
    int pos = data_positions[i];
    word[pos] = (data[i] == '1') ? 1 : 0;
  }
  
  int p1 = 0, p2 = 0, p4 = 0, p8 = 0, p16 = 0;
  
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
  String header = FRAME_TYPE_ACK + "0000" + "1100";
  String parity = calculate_hamming_parity(ACK_DATA);
  return PREAMBLE + header + ACK_DATA + parity;
}

String build_nack_frame() {
  String header = FRAME_TYPE_NACK + "0000" + "1100";
  String parity = calculate_hamming_parity(NACK_DATA);
  return PREAMBLE + header + NACK_DATA + parity;
}

// --- Funkcje komunikacji ---
void send_bits(String bits) {
  Serial.print("Wysyłanie: ");
  Serial.println(bits);
  
  for (int i = 0; i < bits.length(); i++) {
    digitalWrite(TX_PIN, bits[i] == '1' ? HIGH : LOW);
    ets_delay_us(BIT_LEN_US);
  }
  digitalWrite(TX_PIN, LOW);
}

SyncResult wait_for_preamble_with_sync() {
  uint64_t start_time = esp_timer_get_time();
  int bit_count = 0;
  int last_state = digitalRead(RX_PIN);
  uint64_t last_edge = start_time;
  uint64_t first_edge_time = 0;
  uint64_t last_edge_time = 0;
  
  while ((esp_timer_get_time() - start_time) < 3000000) { // 3s timeout
    int current_state = digitalRead(RX_PIN);
    
    if (current_state != last_state) {
      uint64_t now = esp_timer_get_time();
      uint64_t pulse_width = now - last_edge;
      
      // Sprawdź czy to prawidłowe przejście (około 1 BIT_LEN_US)
      if (pulse_width > BIT_LEN_US * 0.6 && pulse_width < BIT_LEN_US * 1.4) {
        // To jest potencjalna preambuła - sprawdź bit w środku impulsu
        uint64_t bit_center = now + (pulse_width / 2);
        while (esp_timer_get_time() < bit_center) {}
        
        int sampled_bit = digitalRead(RX_PIN);
        char expected_bit = PREAMBLE[bit_count];
        
        if ((expected_bit == '1' && sampled_bit == HIGH) || 
            (expected_bit == '0' && sampled_bit == LOW)) {
          if (bit_count == 0) {
            first_edge_time = now;
          }
          bit_count++;
          last_edge_time = now;
          
          if (bit_count == PREAMBLE_LEN) {
            SyncResult result;
            result.success = true;
            // Oblicz średni czas bitu na podstawie preambuły
            result.measured_bit_len = (last_edge_time - first_edge_time) / (PREAMBLE_LEN - 1);
            result.preamble_end_time = last_edge_time;
            Serial.print("Zmierzony czas bitu: ");
            Serial.println(result.measured_bit_len);
            return result;
          }
        } else {
          bit_count = 0;
        }
      } else {
        bit_count = 0;
      }
      
      last_edge = now;
      last_state = current_state;
    }
    
    // Sprawdź timeout między przejściami
    if ((esp_timer_get_time() - last_edge) > BIT_LEN_US * 3) {
      bit_count = 0;
      last_state = digitalRead(RX_PIN);
      last_edge = esp_timer_get_time();
    }
  }
  
  SyncResult result;
  result.success = false;
  result.measured_bit_len = BIT_LEN_US;
  return result;
}

String read_frame_with_sync(unsigned long bit_duration, uint64_t preamble_end_time) {
  String frame = "";
  int bits_to_read = HEADER_LEN + DATA_BITS_LEN + HAMMING_PARITY_LEN;
  
  // Poczekaj do końca ostatniego bitu preambuły + połowa bitu do środka pierwszego bitu danych
  uint64_t first_bit_center = preamble_end_time + bit_duration + (bit_duration / 2);
  while (esp_timer_get_time() < first_bit_center) {}
  
  for (int i = 0; i < bits_to_read; i++) {
    // Odczytaj bit w środku jego trwania
    frame += (digitalRead(RX_PIN) ? '1' : '0');
    
    // Przejdź do środka następnego bitu
    if (i < bits_to_read - 1) {
      uint64_t next_bit_center = esp_timer_get_time() + bit_duration;
      while (esp_timer_get_time() < next_bit_center) {}
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
  SyncResult sync = wait_for_preamble_with_sync();
  if (sync.success) {
    Serial.println("✅ Znaleziono preambułę ramki danych!");
    
    String frame = read_frame_with_sync(sync.measured_bit_len, sync.preamble_end_time);
    Serial.print("Odebrana ramka (");
    Serial.print(frame.length());
    Serial.print(" bitów): ");
    Serial.println(frame);
    
    if (verify_frame(frame)) {
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