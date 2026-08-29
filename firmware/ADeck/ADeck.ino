#include <Arduino_GFX_Library.h>
#include <EEPROM.h>
#include <TouchScreen.h>
#include <stddef.h>

#define YP A3
#define XM A2
#define YM 9
#define XP 8

#define MINPRESSURE 5
#define MAXPRESSURE 3500
#define TS_MINX 150
#define TS_MAXX 900
#define TS_MINY 120
#define TS_MAXY 920

const uint32_t CONFIG_MAGIC = 0x41444543;
const uint8_t CONFIG_VERSION = 2;
const uint8_t PROTOCOL_VERSION = 2;
const uint8_t TOTAL_APPS = 6;
const uint8_t LABEL_SIZE = 11;
const uint8_t APP_W = 90;
const uint8_t APP_H = 90;
const uint16_t RECORD_SLOT_0 = 0;
const unsigned long CONFIG_TIMEOUT_MS = 5000;
const unsigned long PRESS_VIEW_MS = 250;
const unsigned long PRESS_DEBOUNCE_MS = 300;
const unsigned long RELEASE_DEBOUNCE_MS = 70;

TouchScreen ts(XP, YP, XM, YM, 300);
Arduino_DataBus *bus = new Arduino_SWPAR8(A2, A3, A1, A0, 8, 9, 2, 3, 4, 5, 6, 7);
Arduino_GFX *gfx = new Arduino_ILI9341(bus, A4, 0, false);

struct SlotConfig {
  char label[LABEL_SIZE];
  uint16_t color;
};

struct DeviceConfig {
  SlotConfig slots[TOTAL_APPS];
};

struct PersistentRecord {
  uint32_t magic;
  uint8_t version;
  uint8_t slotCount;
  uint16_t recordSize;
  uint32_t generation;
  char labels[TOTAL_APPS][LABEL_SIZE];
  uint16_t colors[TOTAL_APPS];
  uint16_t crc;
};

const int slotX[TOTAL_APPS] = {15, 115, 215, 15, 115, 215};
const int slotY[TOTAL_APPS] = {20, 20, 20, 130, 130, 130};
const uint16_t RECORD_SLOT_1 = RECORD_SLOT_0 + sizeof(PersistentRecord);

DeviceConfig config;
DeviceConfig stagedConfig;
uint32_t stagedRgb[TOTAL_APPS];
uint8_t stagedSlots = 0;
uint32_t activeGeneration = 0;
int8_t activeRecord = -1;

String serialLine;
String transactionId;
bool receivingConfig = false;
bool serialOverflow = false;
unsigned long transactionLastActivity = 0;

bool displayReady = false;
bool pressedVisible = false;
bool touchLatched = false;
unsigned long pressedUntil = 0;
unsigned long nextPressAllowed = 0;
unsigned long lastTouchAt = 0;

uint16_t crc16Update(uint16_t crc, uint8_t value) {
  crc ^= static_cast<uint16_t>(value) << 8;
  for (uint8_t bit = 0; bit < 8; bit++) {
    crc = (crc & 0x8000) ? static_cast<uint16_t>((crc << 1) ^ 0x1021)
                         : static_cast<uint16_t>(crc << 1);
  }
  return crc;
}

uint16_t crc16Bytes(const uint8_t *bytes, size_t count) {
  uint16_t crc = 0xFFFF;
  for (size_t i = 0; i < count; i++) {
    crc = crc16Update(crc, bytes[i]);
  }
  return crc;
}

uint16_t recordCrc(const PersistentRecord &record) {
  return crc16Bytes(
    reinterpret_cast<const uint8_t *>(&record),
    offsetof(PersistentRecord, crc)
  );
}

void copyLabel(char *target, const String &label) {
  memset(target, 0, LABEL_SIZE);
  const uint8_t count = label.length() < LABEL_SIZE - 1
    ? label.length()
    : LABEL_SIZE - 1;
  for (uint8_t i = 0; i < count; i++) {
    target[i] = label.charAt(i);
  }
}

bool labelIsValid(const String &label) {
  if (label.length() > LABEL_SIZE - 1) return false;
  for (unsigned int i = 0; i < label.length(); i++) {
    const char value = label.charAt(i);
    if (value < 32 || value > 126) return false;
  }
  return true;
}

bool storedLabelIsValid(const char *label) {
  bool terminated = false;
  for (uint8_t i = 0; i < LABEL_SIZE; i++) {
    const char value = label[i];
    if (value == '\0') {
      terminated = true;
      break;
    }
    if (value < 32 || value > 126) return false;
  }
  return terminated;
}

void loadDefaults(DeviceConfig &target) {
  const char *labels[TOTAL_APPS] = {
    "W-APP", "Y-TUBE", "DISCORD", "SPOTIFY", "VS CODE", "CHROME"
  };
  const uint16_t colors[TOTAL_APPS] = {
    0x07E0, 0xF800, 0x780F, 0x03E0, 0x001F, 0xFFE0
  };

  memset(&target, 0, sizeof(target));
  for (uint8_t i = 0; i < TOTAL_APPS; i++) {
    copyLabel(target.slots[i].label, String(labels[i]));
    target.slots[i].color = colors[i];
  }
}

bool recordIsValid(const PersistentRecord &record) {
  if (
    record.magic != CONFIG_MAGIC ||
    record.version != CONFIG_VERSION ||
    record.slotCount != TOTAL_APPS ||
    record.recordSize != sizeof(PersistentRecord) ||
    record.crc != recordCrc(record)
  ) {
    return false;
  }

  for (uint8_t i = 0; i < TOTAL_APPS; i++) {
    if (!storedLabelIsValid(record.labels[i])) return false;
  }
  return true;
}

bool storageAvailable() {
  return EEPROM.length() >= RECORD_SLOT_1 + sizeof(PersistentRecord);
}

void configFromRecord(DeviceConfig &target, const PersistentRecord &record) {
  memset(&target, 0, sizeof(target));
  for (uint8_t i = 0; i < TOTAL_APPS; i++) {
    memcpy(target.slots[i].label, record.labels[i], LABEL_SIZE);
    target.slots[i].color = record.colors[i];
  }
}

void fillRecord(
  PersistentRecord &record,
  const DeviceConfig &source,
  uint32_t generation
) {
  memset(&record, 0, sizeof(record));
  record.magic = CONFIG_MAGIC;
  record.version = CONFIG_VERSION;
  record.slotCount = TOTAL_APPS;
  record.recordSize = sizeof(PersistentRecord);
  record.generation = generation;
  for (uint8_t i = 0; i < TOTAL_APPS; i++) {
    memcpy(record.labels[i], source.slots[i].label, LABEL_SIZE);
    record.colors[i] = source.slots[i].color;
  }
  record.crc = recordCrc(record);
}

bool writeRecord(uint16_t address, const PersistentRecord &record) {
  const uint8_t *bytes = reinterpret_cast<const uint8_t *>(&record);

  for (uint8_t i = 0; i < sizeof(record.magic); i++) {
    EEPROM.update(address + i, 0);
  }
  for (size_t i = sizeof(record.magic); i < sizeof(PersistentRecord); i++) {
    EEPROM.update(address + i, bytes[i]);
  }
  for (uint8_t i = 0; i < sizeof(record.magic); i++) {
    EEPROM.update(address + i, bytes[i]);
  }

  PersistentRecord verified;
  EEPROM.get(address, verified);
  return recordIsValid(verified) &&
         verified.generation == record.generation;
}

bool commitConfig(const DeviceConfig &source) {
  if (!storageAvailable()) return false;

  const int8_t targetRecord = activeRecord == 0 ? 1 : 0;
  const uint16_t targetAddress = targetRecord == 0 ? RECORD_SLOT_0 : RECORD_SLOT_1;
  PersistentRecord record;
  fillRecord(record, source, activeGeneration + 1);

  if (!writeRecord(targetAddress, record)) return false;
  activeRecord = targetRecord;
  activeGeneration = record.generation;
  return true;
}

bool generationIsNewer(uint32_t first, uint32_t second) {
  return static_cast<int32_t>(first - second) > 0;
}

void loadConfig() {
  if (storageAvailable()) {
    PersistentRecord first;
    PersistentRecord second;
    EEPROM.get(RECORD_SLOT_0, first);
    EEPROM.get(RECORD_SLOT_1, second);
    const bool firstValid = recordIsValid(first);
    const bool secondValid = recordIsValid(second);

    if (firstValid || secondValid) {
      const bool useSecond = secondValid &&
        (!firstValid || generationIsNewer(second.generation, first.generation));
      const PersistentRecord &selected = useSecond ? second : first;
      activeRecord = useSecond ? 1 : 0;
      activeGeneration = selected.generation;
      configFromRecord(config, selected);
      return;
    }
  }

  loadDefaults(config);
  commitConfig(config);
}

uint16_t textColorFor(uint16_t color) {
  const uint8_t red = ((color >> 11) & 0x1F) << 3;
  const uint8_t green = ((color >> 5) & 0x3F) << 2;
  const uint8_t blue = (color & 0x1F) << 3;
  const uint16_t brightness = (red * 3 + green * 6 + blue) / 10;
  return brightness > 145 ? 0x0000 : 0xFFFF;
}

void renderIcon(uint8_t index) {
  const SlotConfig &slot = config.slots[index];
  gfx->drawRect(slotX[index], slotY[index], APP_W, APP_H, 0xFFFF);
  gfx->fillRect(slotX[index] + 2, slotY[index] + 2, APP_W - 4, APP_H - 4, slot.color);

  const String label = slot.label[0] ? String(slot.label) : String("EMPTY");
  const uint8_t textSize = label.length() > 7 ? 1 : 2;
  const int textWidth = label.length() * 6 * textSize;
  const int textX = slotX[index] + max(4, (APP_W - textWidth) / 2);
  const int textY = slotY[index] + (APP_H - 8 * textSize) / 2;

  gfx->setTextColor(textColorFor(slot.color));
  gfx->setTextSize(textSize);
  gfx->setCursor(textX, textY);
  gfx->print(label);
}

void loadHomeScreen() {
  if (!displayReady) return;
  gfx->fillScreen(0x0000);
  for (uint8_t i = 0; i < TOTAL_APPS; i++) {
    renderIcon(i);
  }
}

void showPressedSlot(uint8_t index) {
  if (!displayReady) return;
  const SlotConfig &slot = config.slots[index];
  const String label = slot.label[0] ? String(slot.label) : String("EMPTY");
  const uint8_t textSize = label.length() > 7 ? 2 : 3;
  const int textWidth = label.length() * 6 * textSize;

  gfx->fillScreen(slot.color);
  gfx->setTextColor(textColorFor(slot.color));
  gfx->setTextSize(textSize);
  gfx->setCursor(max(8, (320 - textWidth) / 2), (240 - 8 * textSize) / 2);
  gfx->print(label);
}

bool timeReached(unsigned long now, unsigned long deadline) {
  return static_cast<long>(now - deadline) >= 0;
}

bool validTransactionId(const String &value) {
  if (value.length() < 1 || value.length() > 16) return false;
  for (unsigned int i = 0; i < value.length(); i++) {
    const char c = value.charAt(i);
    const bool valid = (c >= 'a' && c <= 'z') ||
                       (c >= 'A' && c <= 'Z') ||
                       (c >= '0' && c <= '9') ||
                       c == '-' || c == '_';
    if (!valid) return false;
  }
  return true;
}

int8_t hexValue(char value) {
  if (value >= '0' && value <= '9') return value - '0';
  if (value >= 'a' && value <= 'f') return value - 'a' + 10;
  if (value >= 'A' && value <= 'F') return value - 'A' + 10;
  return -1;
}

bool parseColor(const String &value, uint32_t &rgb) {
  if (value.length() != 7 || value.charAt(0) != '#') return false;
  rgb = 0;
  for (uint8_t i = 1; i < 7; i++) {
    const int8_t nibble = hexValue(value.charAt(i));
    if (nibble < 0) return false;
    rgb = (rgb << 4) | nibble;
  }
  return true;
}

bool parseCrc(const String &value, uint16_t &crc) {
  if (value.length() != 4) return false;
  crc = 0;
  for (uint8_t i = 0; i < 4; i++) {
    const int8_t nibble = hexValue(value.charAt(i));
    if (nibble < 0) return false;
    crc = static_cast<uint16_t>((crc << 4) | nibble);
  }
  return true;
}

uint16_t rgb565(uint32_t rgb) {
  const uint8_t red = (rgb >> 16) & 0xFF;
  const uint8_t green = (rgb >> 8) & 0xFF;
  const uint8_t blue = rgb & 0xFF;
  return ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3);
}

void sendConfigError(const String &id, const char *reason) {
  Serial.print("CFG_ERR\t");
  Serial.print(id.length() ? id : "-");
  Serial.print('\t');
  Serial.println(reason);
}

void clearTransaction() {
  receivingConfig = false;
  stagedSlots = 0;
  transactionId = "";
}

void failTransaction(const String &id, const char *reason) {
  sendConfigError(id, reason);
  clearTransaction();
}

uint16_t stagedConfigCrc() {
  uint16_t crc = 0xFFFF;
  for (uint8_t i = 0; i < TOTAL_APPS; i++) {
    crc = crc16Update(crc, i);
    crc = crc16Update(crc, (stagedRgb[i] >> 16) & 0xFF);
    crc = crc16Update(crc, (stagedRgb[i] >> 8) & 0xFF);
    crc = crc16Update(crc, stagedRgb[i] & 0xFF);
    const uint8_t labelLength = strlen(stagedConfig.slots[i].label);
    crc = crc16Update(crc, labelLength);
    for (uint8_t j = 0; j < labelLength; j++) {
      crc = crc16Update(crc, stagedConfig.slots[i].label[j]);
    }
  }
  return crc;
}

void beginConfig(const String &line) {
  const int firstTab = line.indexOf('\t');
  const int secondTab = line.indexOf('\t', firstTab + 1);
  if (firstTab < 0 || secondTab < 0 || line.indexOf('\t', secondTab + 1) >= 0) {
    sendConfigError("-", "BAD_BEGIN");
    return;
  }

  const String id = line.substring(firstTab + 1, secondTab);
  const String count = line.substring(secondTab + 1);
  if (!validTransactionId(id)) {
    sendConfigError("-", "BAD_TX");
    return;
  }
  if (count != "6") {
    sendConfigError(id, "BAD_COUNT");
    return;
  }

  if (receivingConfig) {
    sendConfigError(transactionId, "SUPERSEDED");
  }
  memset(&stagedConfig, 0, sizeof(stagedConfig));
  memset(stagedRgb, 0, sizeof(stagedRgb));
  stagedSlots = 0;
  transactionId = id;
  transactionLastActivity = millis();
  receivingConfig = true;
}

void receiveSlot(const String &line) {
  const int firstTab = line.indexOf('\t');
  const int secondTab = line.indexOf('\t', firstTab + 1);
  const int thirdTab = line.indexOf('\t', secondTab + 1);
  const int fourthTab = line.indexOf('\t', thirdTab + 1);
  if (
    firstTab < 0 || secondTab < 0 || thirdTab < 0 || fourthTab < 0
  ) {
    failTransaction(transactionId, "BAD_SLOT");
    return;
  }

  const String id = line.substring(firstTab + 1, secondTab);
  if (!receivingConfig) {
    sendConfigError(id, "NO_TRANSACTION");
    return;
  }
  if (id != transactionId) {
    failTransaction(id, "TX_MISMATCH");
    return;
  }

  const String indexText = line.substring(secondTab + 1, thirdTab);
  if (
    indexText.length() != 1 ||
    indexText.charAt(0) < '0' ||
    indexText.charAt(0) >= '0' + TOTAL_APPS
  ) {
    failTransaction(id, "BAD_INDEX");
    return;
  }
  const uint8_t index = indexText.charAt(0) - '0';
  const uint8_t mask = 1 << index;
  if (stagedSlots & mask) {
    failTransaction(id, "DUP_SLOT");
    return;
  }

  uint32_t rgb;
  const String color = line.substring(thirdTab + 1, fourthTab);
  const String label = line.substring(fourthTab + 1);
  if (!parseColor(color, rgb)) {
    failTransaction(id, "BAD_COLOR");
    return;
  }
  if (!labelIsValid(label)) {
    failTransaction(id, "BAD_LABEL");
    return;
  }

  copyLabel(stagedConfig.slots[index].label, label);
  stagedConfig.slots[index].color = rgb565(rgb);
  stagedRgb[index] = rgb;
  stagedSlots |= mask;
  transactionLastActivity = millis();
}

void endConfig(const String &line) {
  const int firstTab = line.indexOf('\t');
  const int secondTab = line.indexOf('\t', firstTab + 1);
  if (firstTab < 0 || secondTab < 0 || line.indexOf('\t', secondTab + 1) >= 0) {
    failTransaction(transactionId, "BAD_END");
    return;
  }

  const String id = line.substring(firstTab + 1, secondTab);
  if (!receivingConfig) {
    sendConfigError(id, "NO_TRANSACTION");
    return;
  }
  if (id != transactionId) {
    failTransaction(id, "TX_MISMATCH");
    return;
  }
  if (stagedSlots != (1 << TOTAL_APPS) - 1) {
    failTransaction(id, "MISSING_SLOT");
    return;
  }

  uint16_t suppliedCrc;
  if (!parseCrc(line.substring(secondTab + 1), suppliedCrc)) {
    failTransaction(id, "BAD_CRC");
    return;
  }
  if (suppliedCrc != stagedConfigCrc()) {
    failTransaction(id, "CRC_MISMATCH");
    return;
  }
  if (!commitConfig(stagedConfig)) {
    failTransaction(id, "EEPROM");
    return;
  }

  config = stagedConfig;
  pressedVisible = false;
  loadHomeScreen();
  Serial.print("CFG_OK\t");
  Serial.println(id);
  clearTransaction();
}

void handleSerialLine(const String &line) {
  if (line == "PING") {
    Serial.print("ADECK_PONG\t");
    Serial.println(PROTOCOL_VERSION);
    return;
  }
  if (line.startsWith("CFG_BEGIN\t")) {
    beginConfig(line);
    return;
  }
  if (line.startsWith("CFG_SLOT\t")) {
    receiveSlot(line);
    return;
  }
  if (line.startsWith("CFG_END\t")) {
    endConfig(line);
  }
}

void readSerial() {
  while (Serial.available() > 0) {
    const char value = static_cast<char>(Serial.read());
    if (value == '\n') {
      if (serialOverflow) {
        failTransaction(transactionId, "LINE_TOO_LONG");
      } else if (serialLine.length()) {
        handleSerialLine(serialLine);
      }
      serialLine = "";
      serialOverflow = false;
    } else if (value != '\r') {
      if (serialLine.length() < 95) {
        serialLine += value;
      } else {
        serialOverflow = true;
      }
    }
  }
}

void updatePressedView(unsigned long now) {
  if (pressedVisible && timeReached(now, pressedUntil)) {
    pressedVisible = false;
    loadHomeScreen();
  }
}

void readTouch(unsigned long now) {
  TSPoint point = ts.getPoint();
  pinMode(XM, OUTPUT);
  pinMode(YP, OUTPUT);

  const bool touching = point.z > MINPRESSURE && point.z < MAXPRESSURE;
  if (!touching) {
    if (touchLatched && timeReached(now, lastTouchAt + RELEASE_DEBOUNCE_MS)) {
      touchLatched = false;
    }
    return;
  }

  lastTouchAt = now;
  if (touchLatched || !timeReached(now, nextPressAllowed)) return;
  touchLatched = true;

  const int touchX = map(point.y, TS_MINY, TS_MAXY, 320, 0);
  const int touchY = map(point.x, TS_MINX, TS_MAXX, 240, 0);
  for (uint8_t i = 0; i < TOTAL_APPS; i++) {
    const bool hitX = touchX > slotX[i] && touchX < slotX[i] + APP_W;
    const bool hitY = touchY > slotY[i] && touchY < slotY[i] + APP_H;
    if (!hitX || !hitY) continue;

    showPressedSlot(i);
    pressedVisible = true;
    pressedUntil = now + PRESS_VIEW_MS;
    nextPressAllowed = now + PRESS_DEBOUNCE_MS;
    Serial.print("PRESS\t");
    Serial.println(i);
    break;
  }
}

void setup() {
  Serial.begin(115200);
  serialLine.reserve(96);
  transactionId.reserve(16);

  displayReady = gfx->begin();
  if (displayReady) {
    gfx->setRotation(1);
    gfx->fillScreen(0x0000);
  }

  loadConfig();
  loadHomeScreen();
  nextPressAllowed = millis() + 1200;

  Serial.print("ADECK_READY\t");
  Serial.println(PROTOCOL_VERSION);
}

void loop() {
  readSerial();
  const unsigned long now = millis();

  if (
    receivingConfig &&
    timeReached(now, transactionLastActivity + CONFIG_TIMEOUT_MS)
  ) {
    failTransaction(transactionId, "TIMEOUT");
  }

  updatePressedView(now);
  readTouch(now);
}
