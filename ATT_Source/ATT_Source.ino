#include <Arduino.h>

// --- CONFIGURATION ---

const uint8_t SOLENOID_COUNT = 10;

const uint8_t SENSOR_COUNT = 5;

const uint8_t AUTO_SOLENOID_INDEX = 9;

const uint8_t solenoidPins[SOLENOID_COUNT] = {
  12, 3, 4, 5, 6, 7, 8, 9, 11, 10
};

const uint8_t sensorPins[SENSOR_COUNT] = {
  A0, A1, A2, A3, A4
};

const uint8_t sensorGroundPins[SENSOR_COUNT] = {
  30, 32, 34, 38, 40
};

const char *solenoidNames[SOLENOID_COUNT] = {
  "Y2", "Y3", "Y4", "Y5", "Y6",
  "Y7", "Y8", "Y9", "Y1", "Y10"
};

const uint8_t RELAY_ON = LOW;
const uint8_t RELAY_OFF = HIGH;

// Дефинираме ОГЛЕДАЛНА (ОБЪРНАТА) логика специално за релето на пин 44
const uint8_t INDUCTANCE_RELAY_ON = HIGH;
const uint8_t INDUCTANCE_RELAY_OFF = LOW;

const float REFERENCE_RESISTOR_OHMS = 100.0;
const unsigned long AUTO_INTERVAL_MS = 2000;
const unsigned long SENSOR_SETTLE_MS = 1000;

// --- INDUCTANCE (PISTON POSITION) CONFIGURATION ---
const uint8_t inductanceGroundRelayPin = 44; // Реле за заземяване на индуктивните датчици

// Конфигурираме масиви за пиновете на 4-те индуктивни датчика (0 означава неокабелен)
const uint8_t inductanceOutPins[4] = {24, 26, 0, 0};
const uint8_t inductanceInPins[4]  = {25, 27, 0, 0};

// ТОЧНИТЕ ТЕСТВАНИ ХАРДУЕРНИ ПАРАМЕТРИ
const double INDUCTANCE_CAPACITANCE = 1.04E-6; // Капацитет 1.04 uF

// --- TEST PROFILES ---
struct TestProfile {
  const char *name;
  bool states[10];
};

const TestProfile testProfiles[] = {
  {"1",  {false, true,  false, true,  false, true,  true,  false, false, false}},
  {"2",  {true,  false, false, true,  false, true,  true,  false, false, false}},
  {"3",  {false, true,  true,  false, true,  false, true,  false, false, false}},
  {"4",  {true,  false, true,  false, true,  false, true,  false, false, false}},
  {"5",  {false, true,  true,  false, false, true,  true,  false, false, false}},
  {"6",  {true,  false, true,  false, false, true,  true,  false, false, false}},
  {"7",  {false, true,  false, true,  false, true,  false, true,  false, false}},
  {"8",  {true,  false, false, true,  false, true,  false, true,  false, false}},
  {"9",  {false, true,  true,  false, true,  false, false, true,  false, false}},
  {"10", {true,  false, true,  false, true,  false, false, true,  false, false}},
  {"11", {false, true,  true,  false, false, true,  false, true,  false, false}},
  {"12", {true,  false, true,  false, false, true,  false, true,  false, false}},
  {"RL", {false, true,  false, true,  true,  false, true,  false, false, false}},
  {"RH", {true,  false, false, true,  true,  false, true,  false, false, false}},
};

const uint8_t TEST_COUNT = sizeof(testProfiles) / sizeof(testProfiles[0]);

// --- GLOBAL STATE ---
bool solenoidStates[SOLENOID_COUNT] = {false};
String inputBuffer = "";
String currentMode = "MANUAL";
bool autoRunEnabled = false;
int autoRunCurrentIndex = -1;
unsigned long lastAutoStepMillis = 0;

// --- SENSOR STATE MACHINE ---
enum SensorReadState {
  SENSOR_IDLE,
  SENSOR_WAITING,
  SENSOR_READING
};

SensorReadState sensorReadState = SENSOR_IDLE;
uint8_t sensorReadIndex = 0;
unsigned long sensorSettleStart = 0;
float sensorResults[SENSOR_COUNT];
bool sensorReadPending = false;

// ============================================================
// SOLENOID LOGIC
// ============================================================
bool shouldEnableAutoSolenoid() {
  for (uint8_t i = 0; i < SOLENOID_COUNT; i++) {
    if (i == AUTO_SOLENOID_INDEX) continue;
    if (solenoidStates[i]) return true;
  }
  return false;
}

bool getEffectiveSolenoidState(uint8_t index) {
  if (index == AUTO_SOLENOID_INDEX) return shouldEnableAutoSolenoid();
  return solenoidStates[index];
}

void normalizeAutoManagedState() {
  solenoidStates[AUTO_SOLENOID_INDEX] = false;
}

void writeAllOutputs() {
  normalizeAutoManagedState();
  for (uint8_t i = 0; i < SOLENOID_COUNT; i++) {
    digitalWrite(
      solenoidPins[i],
      getEffectiveSolenoidState(i) ? RELAY_ON : RELAY_OFF
    );
  }
}

// ============================================================
// SERIAL SEND HELPERS
// ============================================================
void sendMode() {
  Serial.print("MODE ");
  Serial.println(currentMode);
}

void sendAutoState() {
  Serial.print("AUTO_STATE ");
  Serial.println(autoRunEnabled ? "RUNNING" : "STOPPED");
}

void sendAutoStep(int testIndex) {
  if (testIndex < 0 || testIndex >= TEST_COUNT) return;
  Serial.print("AUTO_STEP ");
  Serial.print(testIndex + 1);
  Serial.print(" ");
  Serial.print(TEST_COUNT);
  Serial.print(" ");
  Serial.println(testProfiles[testIndex].name);
}

void sendSolenoidState(uint8_t index) {
  Serial.print("STATE ");
  Serial.print(index + 1);
  Serial.print(" ");
  Serial.println(getEffectiveSolenoidState(index) ? "ON" : "OFF");
}

void sendAllStates() {
  Serial.print("ALL");
  for (uint8_t i = 0; i < SOLENOID_COUNT; i++) {
    Serial.print(" ");
    Serial.print(i + 1);
    Serial.print(":");
    Serial.print(getEffectiveSolenoidState(i) ? "ON" : "OFF");
  }
  Serial.println();
}

void sendCachedSensorValues() {
  Serial.print("SENSORS");
  for (uint8_t i = 0; i < SENSOR_COUNT; i++) {
    Serial.print(" ");
    Serial.print(i + 1);
    Serial.print(":");
    if (sensorResults[i] < 0) {
      Serial.print("OPEN");
    } else {
      unsigned long rounded = (unsigned long)(sensorResults[i] + 0.5);
      Serial.print(rounded);
    }
  }
  Serial.println();
}

// ============================================================
// SENSOR STATE MACHINE (RESISTIVE)
// ============================================================
void triggerSensorRead() {
  if (sensorReadState != SENSOR_IDLE) return;
  
  // КРИТИЧЕН ФИКС: Изключваме напълно възбуждането на индуктивните пинове (INPUT), докато четем съпротивлението!
  for (uint8_t i = 0; i < 4; i++) {
    if (inductanceOutPins[i] != 0) {
      pinMode(inductanceOutPins[i], INPUT);
    }
  }

  sensorReadIndex = 0;
  sensorReadPending = true;
  sensorReadState = SENSOR_WAITING;
  digitalWrite(sensorGroundPins[0], RELAY_ON);
  sensorSettleStart = millis();
}

void processSensorStateMachine() {
  if (sensorReadState == SENSOR_IDLE) return;
  unsigned long now = millis();
  if (sensorReadState == SENSOR_WAITING) {
    if (now - sensorSettleStart < SENSOR_SETTLE_MS) return;
    sensorReadState = SENSOR_READING;
  }
  if (sensorReadState == SENSOR_READING) {
    int adc = analogRead(sensorPins[sensorReadIndex]);
    digitalWrite(sensorGroundPins[sensorReadIndex], RELAY_OFF);
    if (adc >= 1022) {
      sensorResults[sensorReadIndex] = -1.0;
    } else if (adc <= 1) {
      sensorResults[sensorReadIndex] = 0.0;
    } else {
      float calculated = REFERENCE_RESISTOR_OHMS * (float)adc / (1023.0 - (float)adc);
      
      // КОРЕКЦИЯ: Добавяме +167 ома калибрация за Сензор 3 (CH 3 - индекс 2)
      if (sensorReadIndex == 2) {
        calculated += 167.0;
      }
      
      sensorResults[sensorReadIndex] = calculated;
    }
    sensorReadIndex++;
    if (sensorReadIndex >= SENSOR_COUNT) {
      sensorReadState = SENSOR_IDLE;
      
      // ВЪЗСТАНОВЯВАМЕ пиновете като изходи след края на резистивния тест
      for (uint8_t i = 0; i < 4; i++) {
        if (inductanceOutPins[i] != 0) {
          pinMode(inductanceOutPins[i], OUTPUT);
          digitalWrite(inductanceOutPins[i], LOW);
        }
      }
      
      if (sensorReadPending) {
        sendCachedSensorValues();
        sensorReadPending = false;
      }
    } else {
      digitalWrite(sensorGroundPins[sensorReadIndex], RELAY_ON);
      sensorSettleStart = millis();
      sensorReadState = SENSOR_WAITING;
    }
  }
}

// ============================================================
// NEW FEATURE: INDUCTANCE MEASUREMENT WITH STATISTICAL FILTER
// ============================================================

// Помощна функция за тестване на единичен индуктивен канал с ДЕБЪГ ИНФОРМАЦИЯ и 50 ПРОБИ
double measureSingleChannel(uint8_t outPin, uint8_t inPin, uint8_t channelNum) {
  pinMode(outPin, OUTPUT);
  double samples[50]; // Увеличено на 50 проби за максимална статистическа стабилност
  int validCount = 0;
  
  // Принтираме заглавието на суровите данни в конзолата
  Serial.print("DEBUG_PULSES CH:");
  Serial.print(channelNum);
  Serial.print(" -> ");
  
  for (int sampleIdx = 0; sampleIdx < 50; sampleIdx++) {
    digitalWrite(outPin, HIGH);
    
    // Време за възбуждане: 100 микросекунди за генериране на силен и отчетлив LC импулс
    delayMicroseconds(100); 
    
    digitalWrite(outPin, LOW);
    
    // Минимално изчакване за улавяне на много къси импулси
    delayMicroseconds(5); 
    
    double pulse = pulseIn(inPin, HIGH, 7000);
    
    // Извеждаме суровите импулси в реално време в серийния порт
    Serial.print((int)pulse);
    if (sampleIdx < 49) Serial.print(",");
    
    if (pulse > 100.0) {
      double frequency = 1.0E6 / (2.0 * pulse);
      double calculatedInductance = 1.0 / (INDUCTANCE_CAPACITANCE * frequency * frequency * 4.0 * 3.14159 * 3.14159);
      calculatedInductance *= 1E6; // В uH
      double inductance_mH = calculatedInductance / 1000.0;
      
      samples[validCount] = inductance_mH;
      validCount++;
    }
    delay(60); // Намален интервал на 60ms за бързодействие (3 сек за 50 проби на канал)
  }
  Serial.println(); // Нов ред след изписване на 50-те проби
  
  if (validCount > 0) {
    double rawSum = 0.0;
    for (int j = 0; j < validCount; j++) {
      rawSum += samples[j];
    }
    double rawAvg = rawSum / validCount;
    
    double filteredSum = 0.0;
    int filteredCount = 0;
    for (int j = 0; j < validCount; j++) {
      if (abs(samples[j] - rawAvg) < (rawAvg * 0.25)) {
        filteredSum += samples[j];
        filteredCount++;
      }
    }
    
    if (filteredCount > 0) {
      return (filteredSum / filteredCount) * 1000.0; // В uH
    } else {
      return rawAvg * 1000.0; // В uH
    }
  }
  
  return -1.0; // Сигнализира за неуспешно измерване
}

// targetChannel определя дали да се мери определен канал (1-4) или всички (-1)
void measureAndSendInductance(int targetChannel = -1) {
  // 1. АКТИВИРАМЕ релето за индуктивна маса на пин 44
  digitalWrite(inductanceGroundRelayPin, INDUCTANCE_RELAY_ON);
  
  // 2. Чакаме 1 секунда за механично застопоряване
  delay(1000); 

  double results[4] = {-1.0, -1.0, -1.0, -1.0};

  // Измерваме само искания канал (или всички, ако targetChannel е -1)
  for (uint8_t i = 0; i < 4; i++) {
    uint8_t channelNum = i + 1;
    if (targetChannel == -1 || targetChannel == channelNum) {
      if (inductanceOutPins[i] != 0 && inductanceInPins[i] != 0) {
        results[i] = measureSingleChannel(inductanceOutPins[i], inductanceInPins[i], channelNum);
      }
    }
  }

  // --- ИЗПРАЩАМЕ САМО ТЕЗИ КАНАЛИ, КОИТО СА БИЛИ ИЗМЕРЕНИ ---
  Serial.print("INDUCTANCE");
  for (uint8_t i = 0; i < 4; i++) {
    uint8_t channelNum = i + 1;
    if (targetChannel == -1 || targetChannel == channelNum) {
      Serial.print(" ");
      Serial.print(channelNum);
      Serial.print(":");
      if (results[i] > 0) {
        Serial.print(results[i], 1);
      } else {
        Serial.print("UNKNOWN");
      }
    }
  }
  Serial.println();
  
  // 3. Изчакваме още 1 секунда след края на теста
  delay(1000);
  
  // 4. ДЕАКТИВИРАМЕ релето за индуктивна маса на пин 44
  digitalWrite(inductanceGroundRelayPin, INDUCTANCE_RELAY_OFF);
}

// ============================================================
// SOLENOID COMMANDS
// ============================================================
void cancelAutoRunIfNeeded() {
  if (autoRunEnabled) {
    autoRunEnabled = false;
    sendAutoState();
  }
}

void setSolenoid(uint8_t index, bool on, bool manualCommand = true) {
  if (index == AUTO_SOLENOID_INDEX) {
    Serial.print("ERROR AUTO_MANAGED_SOLENOID ");
    Serial.println(index + 1);
    return;
  }
  solenoidStates[index] = on;
  writeAllOutputs();
  if (manualCommand) {
    currentMode = "MANUAL";
    sendMode();
  }
  Serial.print("SOL ");
  Serial.print(index + 1);
  Serial.print(" ");
  Serial.println(on ? "ON" : "OFF");
}

void applyTest(uint8_t testIndex, bool fromAuto) {
  for (uint8_t i = 0; i < SOLENOID_COUNT; i++) {
    solenoidStates[i] = testProfiles[testIndex].states[i];
  }
  normalizeAutoManagedState();
  writeAllOutputs();
  currentMode = fromAuto ? "AUTO:" : "TEST:";
  currentMode += testProfiles[testIndex].name;
  if (fromAuto) {
    sendAutoStep(testIndex);
  }
  Serial.print("APPLIED_TEST ");
  Serial.println(testProfiles[testIndex].name);
  sendMode();
  sendAllStates();
  triggerSensorRead();
}

// ============================================================
// AUTO SEQUENCE
// ============================================================
void startAutoRun() {
  autoRunEnabled = true;
  autoRunCurrentIndex = 0;
  lastAutoStepMillis = millis();
  sendAutoState();
  applyTest(autoRunCurrentIndex, true);
}

void stopAutoRun(bool finished) {
  autoRunEnabled = false;
  sendAutoState();
  if (finished) {
    Serial.println("AUTO_DONE");
  }
}

void processAutoRun() {
  if (!autoRunEnabled) return;
  if (sensorReadState != SENSOR_IDLE) return;
  unsigned long now = millis();
  if (now - lastAutoStepMillis < AUTO_INTERVAL_MS) return;
  lastAutoStepMillis = now;
  autoRunCurrentIndex++;
  if (autoRunCurrentIndex >= TEST_COUNT) {
    stopAutoRun(true);
    return;
  }
  applyTest(autoRunCurrentIndex, true);
}

// ============================================================
// COMMAND PARSING
// ============================================================
int parseSolenoidIndex(String token) {
  token.trim();
  int index = token.toInt();
  if (index < 1 || index > SOLENOID_COUNT) return -1;
  return index - 1;
}

int findTestIndex(String token) {
  token.trim();
  token.toUpperCase();
  for (uint8_t i = 0; i < TEST_COUNT; i++) {
    if (token == String(testProfiles[i].name)) return i;
  }
  return -1;
}

void handleSetCommand(String rest) {
  int spacePos = rest.indexOf(' ');
  if (spacePos == -1) { Serial.println("ERROR BAD_SET"); return; }
  int index = parseSolenoidIndex(rest.substring(0, spacePos));
  if (index == -1) { Serial.println("ERROR BAD_INDEX"); return; }
  if (index == AUTO_SOLENOID_INDEX) { Serial.println("ERROR AUTO_MANAGED"); return; }
  String stateToken = rest.substring(spacePos + 1);
  stateToken.trim();
  stateToken.toUpperCase();
  cancelAutoRunIfNeeded();
  if (stateToken == "ON")       setSolenoid(index, true, true);
  else if (stateToken == "OFF") setSolenoid(index, false, true);
  else                          Serial.println("ERROR BAD_STATE");
}

void handleAutoCommand(String rest) {
  rest.trim();
  rest.toUpperCase();
  if (rest == "START") startAutoRun();
  else if (rest == "STOP") cancelAutoRunIfNeeded();
  else if (rest == "STATUS") {
    sendAutoState();
    if (autoRunEnabled &&
        autoRunCurrentIndex >= 0 &&
        autoRunCurrentIndex < TEST_COUNT) {
      sendAutoStep(autoRunCurrentIndex);
    }
  }
  else Serial.println("ERROR BAD_AUTO");
}

void handleCommand(String cmd) {
  cmd.trim();
  String command = cmd;
  String args = "";
  int spaceIndex = cmd.indexOf(' ');
  if (spaceIndex != -1) {
    command = cmd.substring(0, spaceIndex);
    args = cmd.substring(spaceIndex + 1);
  }
  command.toUpperCase();
  if (command == "GETALL") {
    sendAllStates();
  } else if (command == "GETMODE") {
    sendMode();
  } else if (command == "READSENSORS") {
    triggerSensorRead();
  } else if (command == "READINDUCTANCE") {
    int targetChannel = -1; // -1 означава всички канали
    if (args.length() > 0) {
      args.trim();
      int val = args.toInt();
      if (val >= 1 && val <= 4) {
        targetChannel = val;
      }
    }
    measureAndSendInductance(targetChannel);
  } else if (command == "AUTO") {
    handleAutoCommand(args);
  } else if (command == "GET") {
    int index = parseSolenoidIndex(args);
    if (index != -1) sendSolenoidState(index);
    else             Serial.println("ERROR BAD_INDEX");
  } else if (command == "SET") {
    handleSetCommand(args);
  } else if (command == "TEST") {
    int testIndex = findTestIndex(args);
    if (testIndex != -1) {
      cancelAutoRunIfNeeded();
      applyTest(testIndex, false);
    } else {
      Serial.print("ERROR BAD_TEST");
    }
  } else {
    Serial.print("ERROR UNKNOWN_COMMAND ");
    Serial.println(cmd);
  }
}

// ============================================================
// SETUP & LOOP
// ============================================================
void setup() {
  for (uint8_t i = 0; i < SOLENOID_COUNT; i++) {
    pinMode(solenoidPins[i], OUTPUT);
    digitalWrite(solenoidPins[i], RELAY_OFF);
  }
  for (uint8_t i = 0; i < SENSOR_COUNT; i++) {
    pinMode(sensorPins[i], INPUT);
  }
  for (uint8_t i = 0; i < SENSOR_COUNT; i++) {
    pinMode(sensorGroundPins[i], OUTPUT);
    digitalWrite(sensorGroundPins[i], RELAY_OFF);
  }
  
  // Конфигуриране на релето за индуктивна маса на пин 44
  pinMode(inductanceGroundRelayPin, OUTPUT);
  digitalWrite(inductanceGroundRelayPin, INDUCTANCE_RELAY_OFF);
  
  // Настройка на измервателните пинове за Канал 1 и Канал 2
  for (uint8_t i = 0; i < 4; i++) {
    if (inductanceOutPins[i] != 0) {
      pinMode(inductanceOutPins[i], OUTPUT);
      digitalWrite(inductanceOutPins[i], LOW);
    }
    if (inductanceInPins[i] != 0) {
      pinMode(inductanceInPins[i], INPUT_PULLUP);
    }
  }

  analogReference(DEFAULT);
  writeAllOutputs();
  
  Serial.begin(115200);
  delay(100);
  Serial.println("READY");
  sendMode();
  sendAutoState();
  sendAllStates();
}

void loop() {
  if (Serial.available() > 0) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (inputBuffer.length() > 0) {
        handleCommand(inputBuffer);
        inputBuffer = "";
      }
    } else {
      inputBuffer += c;
    }
  }
  processSensorStateMachine();
  processAutoRun();
}
