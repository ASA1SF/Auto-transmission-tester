const uint8_t SOLENOID_COUNT = 10;
const uint8_t AUTO_SOLENOID_INDEX = 9;  // solenoidPins[9] = pin 10

const uint8_t solenoidPins[SOLENOID_COUNT] = {
  12, 3, 4, 5, 6, 7, 8, 9, 11, 10
};

const uint8_t sensorPins[SOLENOID_COUNT] = {
  A0
};

const char *solenoidNames[SOLENOID_COUNT] = {
  "Y2", "Y3", "Y4", "Y5", "Y6",
  "Y7", "Y8", "Y9", "Y1", "Y10"
};

// Логика за пиновете на релетата
const uint8_t RELAY_ON = LOW;
const uint8_t RELAY_OFF = HIGH;

const float REFERENCE_RESISTOR_OHMS = 1000.0;
const unsigned long SENSOR_STREAM_INTERVAL_MS = 200;
const uint8_t SENSOR_SAMPLES = 8;
const unsigned long AUTO_INTERVAL_MS = 2000;

struct TestProfile {
  const char *name;
  bool states[10];
};

const TestProfile testProfiles[] = {
  {"1", {false, true, false, true, false, true, true, false, false, false}},
  {"2", {true, false, false, true, false, true, true, false, false, false}},
  {"3", {false, true, true, false, true, false, true, false, false, false}},
  {"4", {true, false, true, false, true, false, true, false, false, false}},
  {"5", {false, true, true, false, false, true, true, false, false, false}},
  {"6", {true, false, true, false, false, true, true, false, false, false}},
  {"7", {false, true, false, true, false, true, false, true, false, false}},
  {"8", {true, false, false, true, false, true, false, true, false, false}},
  {"9", {false, true, true, false, true, false, false, true, false, false}},
  {"10", {true, false, true, false, true, false, false, true, false, false}},
  {"11", {false, true, true, false, false, true, false, true, false, false}},
  {"12", {true, false, true, false, false, true, false, true, false, false}},
  {"RL", {false, true, false, true, true, false, true, false, false, false}},
  {"RH", {true, false, false, true, true, false, true, false, false, false}},
};

const uint8_t TEST_COUNT = sizeof(testProfiles) / sizeof(testProfiles[0]);

bool solenoidStates[SOLENOID_COUNT] = {
  false, false, false, false, false,
  false, false, false, false, false
};

String inputBuffer = "";
String currentMode = "MANUAL";

bool sensorStreamEnabled = true;
unsigned long lastSensorStreamMillis = 0;

bool autoRunEnabled = false;
int autoRunCurrentIndex = -1;
unsigned long lastAutoStepMillis = 0;

bool shouldEnableAutoSolenoid() {
  for (uint8_t i = 0; i < SOLENOID_COUNT; i++) {
    if (i == AUTO_SOLENOID_INDEX) {
      continue;
    }

    if (solenoidStates[i]) {
      return true;
    }
  }

  return false;
}

bool getEffectiveSolenoidState(uint8_t index) {
  if (index == AUTO_SOLENOID_INDEX) {
    return shouldEnableAutoSolenoid();
  }

  return solenoidStates[index];
}

void normalizeAutoManagedState() {
  // Pin 10 е автоматично управляван и не пазим ръчно състояние за него
  solenoidStates[AUTO_SOLENOID_INDEX] = false;
}

void sendMode() {
  Serial.print("MODE ");
  Serial.println(currentMode);
}

void sendAutoState() {
  Serial.print("AUTO_STATE ");
  Serial.println(autoRunEnabled ? "RUNNING" : "STOPPED");
}

void sendAutoStep(int testIndex) {
  if (testIndex < 0 || testIndex >= TEST_COUNT) {
    return;
  }

  Serial.print("AUTO_STEP ");
  Serial.print(testIndex + 1);
  Serial.print(" ");
  Serial.print(TEST_COUNT);
  Serial.print(" ");
  Serial.println(testProfiles[testIndex].name);
}

void writeAllOutputs() {
  normalizeAutoManagedState();

  for (uint8_t i = 0; i < SOLENOID_COUNT; i++) {
    bool stateToWrite = getEffectiveSolenoidState(i);

    digitalWrite(solenoidPins[i], stateToWrite ? RELAY_ON : RELAY_OFF);
  }
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

float readSensorResistanceOhms(uint8_t index) {
  uint32_t sum = 0;

  analogRead(sensorPins[index]);

  for (uint8_t i = 0; i < SENSOR_SAMPLES; i++) {
    sum += analogRead(sensorPins[index]);
  }

  float adc = (float)sum / SENSOR_SAMPLES;

  if (adc >= 1022.0) {
    return -1.0;
  }

  if (adc <= 0.5) {
    return 0.0;
  }

  return REFERENCE_RESISTOR_OHMS * adc / (1023.0 - adc);
}

void sendAllSensorValues() {
  Serial.print("SENSORS");

  for (uint8_t i = 0; i < SOLENOID_COUNT; i++) {
    float resistance = readSensorResistanceOhms(i);

    Serial.print(" ");
    Serial.print(i + 1);
    Serial.print(":");

    if (resistance < 0) {
      Serial.print("OPEN");
    } else {
      unsigned long rounded = (unsigned long)(resistance + 0.5);
      Serial.print(rounded);
    }
  }

  Serial.println();
}

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
  }

  Serial.print("SOL ");
  Serial.print(index + 1);
  Serial.print(" ");
  Serial.println(on ? "ON" : "OFF");

  if (manualCommand) {
    sendMode();
  }
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

  Serial.print("TEST_APPLIED ");
  Serial.println(testProfiles[testIndex].name);

  sendMode();
  sendAllStates();
  sendAllSensorValues();
}

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
  if (!autoRunEnabled) {
    return;
  }

  unsigned long now = millis();

  if (now - lastAutoStepMillis < AUTO_INTERVAL_MS) {
    return;
  }

  lastAutoStepMillis = now;
  autoRunCurrentIndex++;

  if (autoRunCurrentIndex >= TEST_COUNT) {
    stopAutoRun(true);
    return;
  }

  applyTest(autoRunCurrentIndex, true);
}

int parseSolenoidIndex(String token) {
  token.trim();

  int index = token.toInt();

  if (index < 1 || index > SOLENOID_COUNT) {
    return -1;
  }

  return index - 1;
}

int findTestIndex(String token) {
  token.trim();
  token.toUpperCase();

  for (uint8_t i = 0; i < TEST_COUNT; i++) {
    if (token == String(testProfiles[i].name)) {
      return i;
    }
  }

  return -1;
}

void handleSetCommand(String rest) {
  int secondSpace = rest.indexOf(' ');

  if (secondSpace == -1) {
    Serial.print("ERROR BAD_SET ");
    Serial.println(rest);
    return;
  }

  String indexToken = rest.substring(0, secondSpace);
  String stateToken = rest.substring(secondSpace + 1);

  int index = parseSolenoidIndex(indexToken);

  if (index == -1) {
    Serial.print("ERROR BAD_INDEX ");
    Serial.println(indexToken);
    return;
  }

  if (index == AUTO_SOLENOID_INDEX) {
    Serial.print("ERROR AUTO_MANAGED_SOLENOID ");
    Serial.println(index + 1);
    return;
  }

  stateToken.trim();
  stateToken.toUpperCase();

  cancelAutoRunIfNeeded();

  if (stateToken == "ON") {
    setSolenoid(index, true, true);
  } else if (stateToken == "OFF") {
    setSolenoid(index, false, true);
  } else {
    Serial.print("ERROR BAD_STATE ");
    Serial.println(stateToken);
  }
}

void handleAutoCommand(String rest) {
  rest.trim();
  rest.toUpperCase();

  if (rest == "START") {
    startAutoRun();
    return;
  }

  if (rest == "STOP") {
    cancelAutoRunIfNeeded();
    return;
  }

  if (rest == "STATUS") {
    sendAutoState();

    if (autoRunEnabled && autoRunCurrentIndex >= 0 &&
        autoRunCurrentIndex < TEST_COUNT) {
      sendAutoStep(autoRunCurrentIndex);
    }

    return;
  }

  Serial.print("ERROR BAD_AUTO ");
  Serial.println(rest);
}

void handleCommand(String cmd) {
  cmd.trim();
  cmd.toUpperCase();

  if (cmd == "GETALL") {
    sendAllStates();
    return;
  }

  if (cmd == "GETMODE") {
    sendMode();
    return;
  }

  if (cmd == "READSENSORS") {
    sendAllSensorValues();
    return;
  }

  if (cmd == "STREAM ON") {
    sensorStreamEnabled = true;
    Serial.println("STREAM ON");
    return;
  }

  if (cmd == "STREAM OFF") {
    sensorStreamEnabled = false;
    Serial.println("STREAM OFF");
    return;
  }

  if (cmd.startsWith("AUTO ")) {
    String rest = cmd.substring(5);
    handleAutoCommand(rest);
    return;
  }

  if (cmd.startsWith("GET ")) {
    String indexToken = cmd.substring(4);
    int index = parseSolenoidIndex(indexToken);

    if (index == -1) {
      Serial.print("ERROR BAD_INDEX ");
      Serial.println(indexToken);
      return;
    }

    sendSolenoidState(index);
    return;
  }

  if (cmd.startsWith("SET ")) {
    String rest = cmd.substring(4);
    handleSetCommand(rest);
    return;
  }

  if (cmd.startsWith("TEST ")) {
    String testName = cmd.substring(5);
    int testIndex = findTestIndex(testName);

    if (testIndex == -1) {
      Serial.print("ERROR BAD_TEST ");
      Serial.println(testName);
      return;
    }

    cancelAutoRunIfNeeded();
    applyTest(testIndex, false);
    return;
  }

  Serial.print("ERROR UNKNOWN_COMMAND ");
  Serial.println(cmd);
}

void setup() {
  for (uint8_t i = 0; i < SOLENOID_COUNT; i++) {
    pinMode(solenoidPins[i], OUTPUT);
    digitalWrite(solenoidPins[i], RELAY_OFF);
    pinMode(sensorPins[i], INPUT);
  }

  analogReference(DEFAULT);

  writeAllOutputs();

  Serial.begin(115200);
  Serial.println("READY");
  sendMode();
  sendAutoState();
  sendAllStates();
  sendAllSensorValues();
}

void loop() {
  while (Serial.available() > 0) {
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

  processAutoRun();

  unsigned long now = millis();

  if (sensorStreamEnabled &&
      now - lastSensorStreamMillis >= SENSOR_STREAM_INTERVAL_MS) {
    lastSensorStreamMillis = now;
    sendAllSensorValues();
  }
}