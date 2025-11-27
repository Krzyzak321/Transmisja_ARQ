#include <Arduino.h>
#include <esp_timer.h>

const int RX_PIN = 21;
const int TX_PIN = 47;
const unsigned long BIT_LEN_US = 1000;
const int PREAMBLE_LEN = 16;
const int DATA_BITS_LEN = 32;
const int TOTAL_BITS_LEN = PREAMBLE_LEN + DATA_BITS_LEN + 1;
const String PREAMBLE = "1010101010101010";
const String DATA_BITS = "11100010111000101110001011100010";
const String ACK_SIGNAL = "11111111111111111111111111111111";
const String NACK_SIGNAL = "00000000000000000000000000000000";

String calculate_parity(const String &data) {
  int count = 0;
  for (int i = 0; i < data.length(); i++) {
    if (data[i] == '1') count++;
  }
  return (count % 2 == 0) ? "0" : "1";
}

String build_ack_frame() {
  return PREAMBLE + ACK_SIGNAL + calculate_parity(ACK_SIGNAL);
}

String build_nack_frame() {
  return PREAMBLE + NACK_SIGNAL + calculate_parity(NACK_SIGNAL);
}

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
  
  while ((esp_timer_get_time() - start_time) < 2000000) { // 2 sekundy timeout
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
    
    // Odczekaj 0.5 bitu do środka (jak u Ciebie)
    uint64_t bit_center_time = esp_timer_get_time() + (BIT_LEN_US * 0.5);
    while (esp_timer_get_time() < bit_center_time) {
      // busy wait
    }
    
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
  for (int i = 0; i < DATA_BITS_LEN + 1; i++) {
    uint64_t bit_read_time = esp_timer_get_time() + BIT_LEN_US;
    while (esp_timer_get_time() < bit_read_time) {
      // busy wait
    }
    frame += (digitalRead(RX_PIN) ? '1' : '0');
  }
  return frame;
}

bool verify_frame(const String &frame) {
  if (frame.length() != DATA_BITS_LEN + 1) return false;
  
  String data = frame.substring(0, DATA_BITS_LEN);
  String received_parity = frame.substring(DATA_BITS_LEN);
  String calculated_parity = calculate_parity(data);
  
  return received_parity == calculated_parity;
}

void setup() {
  Serial.begin(115200);
  pinMode(RX_PIN, INPUT);
  pinMode(TX_PIN, OUTPUT);
  digitalWrite(TX_PIN, 0);
  Serial.println("ESP32 ready: listening for data frames...");
}

void loop() {
  if (wait_for_preamble()) {
    Serial.println("✅ Znaleziono preambułę ramki danych!");
    
    String data_frame = read_frame_after_preamble();
    Serial.print("Odebrana ramka: ");
    Serial.println(data_frame);
    
    if (verify_frame(data_frame)) {
      String data = data_frame.substring(0, DATA_BITS_LEN);
      Serial.println("✅ RAMKA POPRAWNA - WYSYŁAM ACK");
      
      // Krótka przerwa przed wysłaniem ACK
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