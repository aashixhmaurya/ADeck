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
const uint8_t CONFIG_VERSION = 3;
const uint8_t PROTOCOL_VERSION = 2;
const uint8_t TOTAL_APPS = 6;
const uint8_t LABEL_SIZE = 11;
// Key cell on the TFT (touch box == draw box).
const uint8_t APP_W = 90;
const uint8_t APP_H = 90;
const uint8_t ICON_SIZE = 32;
// Logo size on TFT — must be a multiple of ICON_BAND or the last blit paints junk.
// Leave room for gap + label. Text size stays 1.
const uint8_t ICON_DRAW = 72;
const uint8_t ICON_BITMAP = ICON_DRAW; // draw size on panel (scaled up from 32×32 source)
const uint8_t ICON_INSET = 0;
const uint8_t ICON_BAND = 4;           // blit a few rows at a time — full bitmap won't fit RAM
const uint8_t ICON_GAP = 10;           // text sits a bit lower under the logo
const uint8_t TEXT_H = 8;              // built-in font height at size 1
const unsigned long ICON_STREAM_IDLE_MS = 120;  // wait for stream to settle before redraw
const unsigned long ICON_RECV_TIMEOUT_MS = 2000;

const int SCREEN_W = 320;              // after setRotation(1)
const int SCREEN_H = 240;

// 3×2 grid — draw box == touch box (no second geometry to drift)
const int KEY_W = APP_W;
const int KEY_H = APP_H;

const int PRESS_W = SCREEN_W - 60;
const int PRESS_H = SCREEN_H - 60;
const int PRESS_RADIUS = 12;
const uint16_t SERIAL_LINE_MAX = 180;
const uint16_t RECORD_SLOT_0 = 0;
const unsigned long CONFIG_TIMEOUT_MS = 5000;
const unsigned long PRESS_VIEW_MS = 800;  // press flash — long enough to notice, not sluggish
const unsigned long PRESS_DEBOUNCE_MS = 300;
const unsigned long RELEASE_DEBOUNCE_MS = 70;

TouchScreen ts(XP, YP, XM, YM, 300);
Arduino_DataBus *bus = new Arduino_SWPAR8(A2, A3, A1, A0, 8, 9, 2, 3, 4, 5, 6, 7);
Arduino_GFX *gfx = new Arduino_ILI9341(bus, A4, 0, false);

// Theme palette indices — host owns names/CSS; board only paints these colours.
const uint8_t THEME_BACKGROUND = 0;
const uint8_t THEME_TEXT = 1;
const uint8_t THEME_TEXT_MUTED = 2;
const uint8_t THEME_ACCENT = 3;
const uint8_t THEME_ACCENT_2 = 4;
const uint8_t THEME_SELECTED = 5;
const uint8_t THEME_PRESSED = 6;
const uint8_t THEME_COUNT = 7;

const uint8_t SELECTED_MIX = 100;  // blend slot colour toward theme when selected

struct SlotConfig {
  char label[LABEL_SIZE];
  uint16_t color;
};

struct ThemeConfig {
  uint16_t values[THEME_COUNT];
};

struct DeviceConfig {
  SlotConfig slots[TOTAL_APPS];
  ThemeConfig theme;
};

struct PersistentRecord {
  uint32_t magic;
  uint8_t version;
  uint8_t slotCount;
  uint16_t recordSize;
  uint32_t generation;
  char labels[TOTAL_APPS][LABEL_SIZE];
  uint16_t colors[TOTAL_APPS];
  uint16_t theme[THEME_COUNT];
  uint16_t crc;
};

const int slotX[TOTAL_APPS] = {15, 115, 215, 15, 115, 215};
const int slotY[TOTAL_APPS] = {20, 20, 20, 130, 130, 130};
const uint16_t RECORD_SLOT_1 = RECORD_SLOT_0 + sizeof(PersistentRecord);

DeviceConfig config;
DeviceConfig stagedConfig;
uint32_t stagedRgb[TOTAL_APPS];
uint8_t stagedSlots = 0;
// Theme stages separately from slots — a failed theme push shouldn't wipe keys.
uint32_t stagedThemeRgb[THEME_COUNT];
uint8_t stagedThemeMask = 0;
bool receivingTheme = false;
String themeTransactionId;
unsigned long themeLastActivity = 0;
uint32_t activeGeneration = 0;
int8_t activeRecord = -1;
uint16_t slotIcons[TOTAL_APPS][ICON_SIZE * ICON_SIZE];
uint16_t iconBand[ICON_BITMAP * ICON_BAND];  // reusable blit band
bool slotHasIcon[TOTAL_APPS];
String lastSyncId;
int8_t iconRecvIndex = -1;
uint32_t iconRecvMask = 0;
unsigned long iconRecvAt = 0;
unsigned long iconStreamAt = 0;

String serialLine;
String transactionId;
bool receivingConfig = false;
bool serialOverflow = false;
unsigned long transactionLastActivity = 0;

bool displayReady = false;
// Redraws run from the main loop only — serial just sets flags (keeps icon stream alive).
bool drawing = false;
bool fullRedrawPending = false;
uint8_t keyRedrawPending = 0;
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
  // ADeck Classic. only ever paints a board that has never been configured and
  // has no host attached - the moment the host says hello it sends the real
  // theme, so these just have to look right on their own for a minute
  const uint16_t theme[THEME_COUNT] = {
    0x0000,  // background  #000000
    0xFFFF,  // text        #ffffff
    0x39E7,  // textMuted   #3a3d3a
    0xC638,  // accent      #c5c5c3
    0x2965,  // accent2     #2c2c28
    0xFFFF,  // selected    #ffffff
    0x10A2,  // pressed     #141412
  };

  memset(&target, 0, sizeof(target));
  for (uint8_t i = 0; i < TOTAL_APPS; i++) {
    copyLabel(target.slots[i].label, String(labels[i]));
    target.slots[i].color = colors[i];
  }
  memcpy(target.theme.values, theme, sizeof(theme));
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
  memcpy(target.theme.values, record.theme, sizeof(record.theme));
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
  memcpy(record.theme, source.theme.values, sizeof(record.theme));
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

// layout helpers
int cardX(uint8_t index) {
  return slotX[index];
}

int cardY(uint8_t index) {
  return slotY[index];
}

uint16_t mixColor(uint16_t from, uint16_t to, uint8_t amount) {
  const int fromRed = (from >> 11) & 0x1F;
  const int fromGreen = (from >> 5) & 0x3F;
  const int fromBlue = from & 0x1F;
  const int toRed = (to >> 11) & 0x1F;
  const int toGreen = (to >> 5) & 0x3F;
  const int toBlue = to & 0x1F;
  const int red = fromRed + ((toRed - fromRed) * amount) / 255;
  const int green = fromGreen + ((toGreen - fromGreen) * amount) / 255;
  const int blue = fromBlue + ((toBlue - fromBlue) * amount) / 255;
  return (red << 11) | (green << 5) | blue;
}

const uint8_t PRESS_TINT = 110;  // blend key colour toward theme when pressed

void drawKeyLabel(const char *text, int centerX, int y, uint8_t size, uint16_t color) {
  const int width = strlen(text) * 6 * size;
  gfx->setTextColor(color);
  gfx->setTextSize(size);
  gfx->setCursor(centerX - width / 2, y);
  gfx->print(text);
}

// Scale 32×32 source → ICON_BITMAP with nearest-neighbour (one RAM band at a time).
void scaleIconBand(uint8_t index, uint8_t firstRow, uint8_t bandRows) {
  const uint16_t *src = slotIcons[index];
  for (uint8_t row = 0; row < bandRows; row++) {
    const uint8_t srcY = static_cast<uint16_t>(firstRow + row) * ICON_SIZE / ICON_BITMAP;
    const uint16_t *line = src + srcY * ICON_SIZE;
    uint16_t *dest = &iconBand[row * ICON_BITMAP];
    for (uint8_t dx = 0; dx < ICON_BITMAP; dx++) {
      dest[dx] = line[static_cast<uint16_t>(dx) * ICON_SIZE / ICON_BITMAP];
    }
  }
}

// Paint icon in bands; drain serial between bands so the 256-byte buffer doesn't overflow.
void drawKeyIcon(uint8_t index, int x, int y) {
  x += ICON_INSET;
  y += ICON_INSET;
  for (uint8_t row = 0; row < ICON_BITMAP; row += ICON_BAND) {
    const uint8_t bandRows = (row + ICON_BAND <= ICON_BITMAP)
      ? ICON_BAND
      : static_cast<uint8_t>(ICON_BITMAP - row);
    scaleIconBand(index, row, bandRows);
    gfx->draw16bitRGBBitmap(x, y + row, iconBand, ICON_BITMAP, bandRows);
    readSerial();
  }
}

void drawKey(uint8_t index) {
  const SlotConfig &slot = config.slots[index];
  const int x = cardX(index);
  const int y = cardY(index);
  const String label = String(slot.label);

  // Wipe the key cell first — stops ghost labels showing through transparent icon pixels.
  gfx->fillRect(x, y, KEY_W, KEY_H, config.theme.values[THEME_BACKGROUND]);

  if (!slot.label[0]) {
    drawKeyLabel(
      "EMPTY", x + KEY_W / 2, y + (KEY_H - TEXT_H) / 2, 1,
      config.theme.values[THEME_TEXT_MUTED]
    );
    return;
  }

  if (!slotHasIcon[index]) {
    // Label-only until an icon arrives from the host. Same size as under-icon names.
    const uint16_t accent = mixColor(
      slot.color, config.theme.values[THEME_SELECTED], SELECTED_MIX
    );
    drawKeyLabel(
      label.c_str(), x + KEY_W / 2, y + (KEY_H - TEXT_H) / 2, 1, accent
    );
    return;
  }

  // Icons stay fixed size/position; labels are always size 1 so every key matches.
  const int groupTop = y + (KEY_H - (ICON_DRAW + ICON_GAP + TEXT_H)) / 2;
  drawKeyIcon(index, x + (KEY_W - ICON_DRAW) / 2, groupTop);
  drawKeyLabel(
    label.c_str(), x + KEY_W / 2, groupTop + ICON_DRAW + ICON_GAP, 1,
    config.theme.values[THEME_TEXT]
  );
}

bool iconStreamActive(unsigned long now) {
  return iconRecvIndex >= 0 || !timeReached(now, iconStreamAt + ICON_STREAM_IDLE_MS);
}

void requestFullRedraw() {
  fullRedrawPending = true;
}

void requestKeyRedraw(uint8_t index) {
  keyRedrawPending |= static_cast<uint8_t>(1 << index);
}

// Single place keys redraw. Incoming serial only sets flags — never re-enters mid-paint.
void serviceRedraw(unsigned long now) {
  if (!displayReady || drawing || pressedVisible) return;
  if (!fullRedrawPending && !keyRedrawPending) return;

  if (fullRedrawPending) {
    fullRedrawPending = false;
    keyRedrawPending = 0;
    drawing = true;
    gfx->fillScreen(config.theme.values[THEME_BACKGROUND]);
    for (uint8_t i = 0; i < TOTAL_APPS; i++) {
      drawKey(i);
      readSerial();
    }
    drawing = false;
    return;
  }

  if (iconStreamActive(now)) return;  // wait until icon stream goes idle
  const uint8_t pending = keyRedrawPending;
  keyRedrawPending = 0;
  drawing = true;
  for (uint8_t i = 0; i < TOTAL_APPS; i++) {
    if (!(pending & static_cast<uint8_t>(1 << i))) continue;
    drawKey(i);
    readSerial();
  }
  drawing = false;
}

void showPressedSlot(uint8_t index) {
  if (!displayReady) return;
  const SlotConfig &slot = config.slots[index];
  const String label = slot.label[0] ? String(slot.label) : String("EMPTY");
  const uint8_t size = label.length() > 7 ? 2 : 3;
  const uint16_t fill = mixColor(
    slot.color, config.theme.values[THEME_PRESSED], PRESS_TINT
  );
  const uint16_t textColor = textColorFor(fill);
  const int x = (SCREEN_W - PRESS_W) / 2;
  const int y = (SCREEN_H - PRESS_H) / 2;

  gfx->fillScreen(config.theme.values[THEME_BACKGROUND]);
  gfx->fillRoundRect(x, y, PRESS_W, PRESS_H, PRESS_RADIUS, fill);
  gfx->drawRoundRect(
    x, y, PRESS_W, PRESS_H, PRESS_RADIUS, config.theme.values[THEME_ACCENT]
  );
  gfx->drawRoundRect(
    x + 3, y + 3, PRESS_W - 6, PRESS_H - 6, PRESS_RADIUS - 3,
    config.theme.values[THEME_ACCENT_2]
  );
  readSerial();

  if (slotHasIcon[index]) {
    // icon and label centred together
    const int groupTop = y + (PRESS_H - (ICON_DRAW + 16 + 8 * size)) / 2;
    drawKeyIcon(index, x + (PRESS_W - ICON_DRAW) / 2, groupTop);
    drawKeyLabel(label.c_str(), SCREEN_W / 2, groupTop + ICON_DRAW + 16, size, textColor);
    return;
  }

  drawKeyLabel(label.c_str(), SCREEN_W / 2, y + (PRESS_H - 8 * size) / 2, size, textColor);
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
  // the theme rides along from the live config rather than being wiped: this
  // transaction only carries slots, and it has no business forgetting the panel
  // colours while it does. every slot is rewritten before CFG_END commits, so
  // nothing stale survives anyway
  stagedConfig = config;
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
  memset(slotHasIcon, 0, sizeof(slotHasIcon));
  iconRecvIndex = -1;
  iconRecvMask = 0;
  lastSyncId = id;
  requestFullRedraw();
  Serial.print("CFG_OK\t");
  Serial.println(id);
  clearTransaction();
}

void sendThemeError(const String &id, const char *reason) {
  Serial.print("CFG_THEME_ERR\t");
  Serial.print(id.length() ? id : "-");
  Serial.print('\t');
  Serial.println(reason);
}

void clearThemeTransaction() {
  receivingTheme = false;
  stagedThemeMask = 0;
  themeTransactionId = "";
}

void failTheme(const String &id, const char *reason) {
  sendThemeError(id, reason);
  clearThemeTransaction();
}

uint16_t stagedThemeCrc() {
  uint16_t crc = 0xFFFF;
  for (uint8_t i = 0; i < THEME_COUNT; i++) {
    crc = crc16Update(crc, i);
    crc = crc16Update(crc, (stagedThemeRgb[i] >> 16) & 0xFF);
    crc = crc16Update(crc, (stagedThemeRgb[i] >> 8) & 0xFF);
    crc = crc16Update(crc, stagedThemeRgb[i] & 0xFF);
  }
  return crc;
}

// Theme uses its own transaction so a failed theme push can't wipe key config.
void beginTheme(const String &line) {
  const int firstTab = line.indexOf('\t');
  const int secondTab = line.indexOf('\t', firstTab + 1);
  if (firstTab < 0 || secondTab < 0 || line.indexOf('\t', secondTab + 1) >= 0) {
    sendThemeError("-", "BAD_BEGIN");
    return;
  }

  const String id = line.substring(firstTab + 1, secondTab);
  const String count = line.substring(secondTab + 1);
  if (!validTransactionId(id)) {
    sendThemeError("-", "BAD_TX");
    return;
  }
  if (count != String(THEME_COUNT)) {
    sendThemeError(id, "BAD_COUNT");
    return;
  }

  if (receivingConfig) {
    failTransaction(transactionId, "SUPERSEDED");
  }
  if (iconRecvIndex >= 0) {  // don't interrupt a half-received icon
    sendThemeError(id, "BUSY");
    return;
  }
  if (receivingTheme) {
    sendThemeError(themeTransactionId, "SUPERSEDED");
  }
  memset(stagedThemeRgb, 0, sizeof(stagedThemeRgb));
  stagedThemeMask = 0;
  themeTransactionId = id;
  themeLastActivity = millis();
  receivingTheme = true;
}

void receiveThemeValue(const String &line) {
  const int firstTab = line.indexOf('\t');
  const int secondTab = line.indexOf('\t', firstTab + 1);
  const int thirdTab = line.indexOf('\t', secondTab + 1);
  if (firstTab < 0 || secondTab < 0 || thirdTab < 0) {
    failTheme(themeTransactionId, "BAD_VALUE");
    return;
  }

  const String id = line.substring(firstTab + 1, secondTab);
  if (!receivingTheme) {
    sendThemeError(id, "NO_TRANSACTION");
    return;
  }
  if (id != themeTransactionId) {
    failTheme(id, "TX_MISMATCH");
    return;
  }

  const String indexText = line.substring(secondTab + 1, thirdTab);
  if (
    indexText.length() != 1 ||
    indexText.charAt(0) < '0' ||
    indexText.charAt(0) >= '0' + THEME_COUNT
  ) {
    failTheme(id, "BAD_INDEX");
    return;
  }
  const uint8_t index = indexText.charAt(0) - '0';
  const uint8_t mask = 1 << index;
  if (stagedThemeMask & mask) {
    failTheme(id, "DUP_VALUE");
    return;
  }

  uint32_t rgb;
  if (!parseColor(line.substring(thirdTab + 1), rgb)) {
    failTheme(id, "BAD_COLOR");
    return;
  }

  stagedThemeRgb[index] = rgb;
  stagedThemeMask |= mask;
  themeLastActivity = millis();
}

void endTheme(const String &line) {
  const int firstTab = line.indexOf('\t');
  const int secondTab = line.indexOf('\t', firstTab + 1);
  if (firstTab < 0 || secondTab < 0 || line.indexOf('\t', secondTab + 1) >= 0) {
    failTheme(themeTransactionId, "BAD_END");
    return;
  }

  const String id = line.substring(firstTab + 1, secondTab);
  if (!receivingTheme) {
    sendThemeError(id, "NO_TRANSACTION");
    return;
  }
  if (id != themeTransactionId) {
    failTheme(id, "TX_MISMATCH");
    return;
  }
  if (stagedThemeMask != (1 << THEME_COUNT) - 1) {
    failTheme(id, "MISSING_VALUE");
    return;
  }

  uint16_t suppliedCrc;
  if (!parseCrc(line.substring(secondTab + 1), suppliedCrc)) {
    failTheme(id, "BAD_CRC");
    return;
  }
  if (suppliedCrc != stagedThemeCrc()) {
    failTheme(id, "CRC_MISMATCH");
    return;
  }

  DeviceConfig next = config;
  for (uint8_t i = 0; i < THEME_COUNT; i++) {
    next.theme.values[i] = rgb565(stagedThemeRgb[i]);
  }
  if (!commitConfig(next)) {
    failTheme(id, "EEPROM");
    return;
  }

  config = next;
  // Drop icons — they were blended for the old background; host will re-send.
  pressedVisible = false;
  memset(slotHasIcon, 0, sizeof(slotHasIcon));
  iconRecvIndex = -1;
  iconRecvMask = 0;
  requestFullRedraw();
  Serial.print("CFG_THEME_OK\t");
  Serial.println(id);
  clearThemeTransaction();
}

void sendIconError(const String &id, uint8_t index, const char *reason) {
  Serial.print("CFG_ICON_ERR\t");
  if (id.length()) {
    Serial.print(id);
  } else {
    Serial.print('-');
  }
  Serial.print('\t');
  Serial.print(static_cast<unsigned int>(index));
  Serial.print('\t');
  Serial.println(reason);
}

void beginIcon(const String &line) {
  const int firstTab = line.indexOf('\t');
  const int secondTab = line.indexOf('\t', firstTab + 1);
  const int thirdTab = line.indexOf('\t', secondTab + 1);
  if (firstTab < 0 || secondTab < 0 || thirdTab < 0) return;
  if (line.indexOf('\t', thirdTab + 1) >= 0) return;
  const String id = line.substring(firstTab + 1, secondTab);
  const String indexText = line.substring(secondTab + 1, thirdTab);
  uint8_t index = 0xFF;
  if (
    indexText.length() == 1 &&
    indexText.charAt(0) >= '0' &&
    indexText.charAt(0) < '0' + TOTAL_APPS
  ) {
    index = static_cast<uint8_t>(indexText.charAt(0) - '0');
  }

  // every refusal is reported: a silently ignored icon is a key that stays
  // empty on the panel with nothing anywhere to say why
  if (receivingConfig || receivingTheme) {
    sendIconError(id, index, "BUSY");
    return;
  }
  if (id != lastSyncId) {
    sendIconError(id, index, "NO_SYNC");
    return;
  }
  if (index == 0xFF || line.substring(thirdTab + 1).toInt() != ICON_SIZE) {
    sendIconError(id, index, "BAD_BEGIN");
    return;
  }

  iconRecvIndex = static_cast<int8_t>(index);
  iconRecvMask = 0;
  iconRecvAt = millis();
  iconStreamAt = iconRecvAt;
  slotHasIcon[index] = false;
}

void receiveIconRow(const String &line) {
  if (receivingConfig || receivingTheme || iconRecvIndex < 0) return;
  const int firstTab = line.indexOf('\t');
  const int secondTab = line.indexOf('\t', firstTab + 1);
  const int thirdTab = line.indexOf('\t', secondTab + 1);
  const int fourthTab = line.indexOf('\t', thirdTab + 1);
  if (firstTab < 0 || secondTab < 0 || thirdTab < 0 || fourthTab < 0) return;
  const String id = line.substring(firstTab + 1, secondTab);
  if (id != lastSyncId) return;
  const String indexText = line.substring(secondTab + 1, thirdTab);
  if (indexText.length() != 1 || (indexText.charAt(0) - '0') != iconRecvIndex) return;
  const int row = line.substring(thirdTab + 1, fourthTab).toInt();
  if (row < 0 || row >= ICON_SIZE) return;

  // Parse hex in place — no per-row String alloc (serial can't wait).
  const char *hex = line.c_str() + fourthTab + 1;
  if (strlen(hex) != ICON_SIZE * 4) return;

  uint16_t *dest = &slotIcons[iconRecvIndex][row * ICON_SIZE];
  for (uint8_t x = 0; x < ICON_SIZE; x++) {
    uint16_t pixel = 0;
    for (uint8_t nibble = 0; nibble < 4; nibble++) {
      const int8_t value = hexValue(hex[x * 4 + nibble]);
      if (value < 0) return;
      pixel = static_cast<uint16_t>((pixel << 4) | value);
    }
    dest[x] = pixel;
  }
  iconRecvMask |= (1UL << row);
  iconRecvAt = millis();
  iconStreamAt = iconRecvAt;
}

void endIcon(const String &line) {
  if (receivingConfig || receivingTheme || iconRecvIndex < 0) return;
  const int firstTab = line.indexOf('\t');
  const int secondTab = line.indexOf('\t', firstTab + 1);
  if (firstTab < 0 || secondTab < 0 || line.indexOf('\t', secondTab + 1) >= 0) return;
  const String id = line.substring(firstTab + 1, secondTab);
  if (id != lastSyncId) return;
  const String indexText = line.substring(secondTab + 1);
  if (indexText.length() != 1 || (indexText.charAt(0) - '0') != iconRecvIndex) return;

  const uint8_t index = static_cast<uint8_t>(iconRecvIndex);
  iconRecvIndex = -1;
  iconStreamAt = millis();
  const uint32_t mask = iconRecvMask;
  iconRecvMask = 0;

  if (mask != 0xFFFFFFFFUL) {
    // rows were dropped on the way in. tell the host instead of leaving the
    // key without an icon and no way for anyone to find out why
    sendIconError(id, index, "INCOMPLETE");
    return;
  }

  slotHasIcon[index] = true;
  Serial.print("CFG_ICON_OK\t");
  Serial.print(id);
  Serial.print('\t');
  Serial.println(index);
  requestKeyRedraw(index);
}

void handleSerialLine(const String &line) {
  if (line == "PING") {
    Serial.print("ADECK_PONG\t");
    Serial.println(PROTOCOL_VERSION);
    Serial.println("ADECK_CAPS\tICON");
    Serial.println("ADECK_CAPS\tTHEME");
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
    return;
  }
  if (line.startsWith("CFG_THEME_BEGIN\t")) {
    beginTheme(line);
    return;
  }
  if (line.startsWith("CFG_THEME_VALUE\t")) {
    receiveThemeValue(line);
    return;
  }
  if (line.startsWith("CFG_THEME_END\t")) {
    endTheme(line);
    return;
  }
  if (line.startsWith("CFG_ICON_BEGIN\t")) {
    beginIcon(line);
    return;
  }
  if (line.startsWith("CFG_ICON_ROW\t")) {
    receiveIconRow(line);
    return;
  }
  if (line.startsWith("CFG_ICON_END\t")) {
    endIcon(line);
  }
}

void readSerial() {
  while (Serial.available() > 0) {
    const char value = static_cast<char>(Serial.read());
    if (value == '\n') {
      if (serialOverflow) {
        if (receivingConfig) {
          failTransaction(transactionId, "LINE_TOO_LONG");
        }
        if (receivingTheme) {
          failTheme(themeTransactionId, "LINE_TOO_LONG");
        }
      } else if (serialLine.length()) {
        handleSerialLine(serialLine);
      }
      serialLine = "";
      serialOverflow = false;
    } else if (value != '\r') {
      if (serialLine.length() < SERIAL_LINE_MAX) {
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
    requestFullRedraw();
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
  serialLine.reserve(SERIAL_LINE_MAX + 1);
  transactionId.reserve(16);

  displayReady = gfx->begin();
  if (displayReady) {
    gfx->setRotation(1);
  }

  // config first: the panel's first paint is already its theme's background,
  // rather than black followed by a visible flash into the real colour
  loadConfig();
  requestFullRedraw();
  serviceRedraw(millis());
  nextPressAllowed = millis() + 1200;

  Serial.println("ADECK_CAPS\tICON");
  Serial.println("ADECK_CAPS\tTHEME");
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

  if (
    receivingTheme &&
    timeReached(now, themeLastActivity + CONFIG_TIMEOUT_MS)
  ) {
    failTheme(themeTransactionId, "TIMEOUT");
  }

  if (iconRecvIndex >= 0 && timeReached(now, iconRecvAt + ICON_RECV_TIMEOUT_MS)) {
    // the host stopped part way through an icon: release the slot and say so
    const uint8_t index = static_cast<uint8_t>(iconRecvIndex);
    iconRecvIndex = -1;
    iconRecvMask = 0;
    sendIconError(lastSyncId, index, "TIMEOUT");
  }

  updatePressedView(now);
  serviceRedraw(now);
  readTouch(now);
}
