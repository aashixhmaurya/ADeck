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
const uint8_t CONFIG_VERSION = 4;
const uint8_t PROTOCOL_VERSION = 2;
const uint8_t TOTAL_APPS = 6;
const uint8_t LABEL_SIZE = 11;

const uint8_t APP_W = 90;
const uint8_t APP_H = 90;
const uint8_t ICON_SIZE = 32;


const uint8_t ICON_DRAW = 72;
const uint8_t ICON_BITMAP = ICON_DRAW;
const uint8_t ICON_INSET = 0;
const uint8_t ICON_BAND = 2;
const uint8_t ICON_GAP = 10;
const uint8_t TEXT_H = 8;
const unsigned long ICON_STREAM_IDLE_MS = 120;
const unsigned long ICON_RECV_TIMEOUT_MS = 2000;
const uint8_t SLEEP_W = 128;
const uint8_t SLEEP_H = 96;
const uint8_t SLEEP_CHUNK = 16;
const uint8_t SLEEP_MODE_BLACK = 0;
const uint8_t SLEEP_MODE_IMAGE = 1;


int16_t screenW = 320;
int16_t screenH = 240;
uint8_t displayRotation = 1;
uint8_t gridCols = 3;
uint8_t gridRows = 2;


const int KEY_W = APP_W;
const int KEY_H = APP_H;

const int PRESS_RADIUS = 12;
const uint16_t SERIAL_LINE_MAX = 180;
const uint16_t RECORD_SLOT_0 = 0;
const unsigned long CONFIG_TIMEOUT_MS = 5000;
const unsigned long PRESS_VIEW_MS = 800;
const unsigned long PRESS_DEBOUNCE_MS = 300;
const unsigned long RELEASE_DEBOUNCE_MS = 70;

TouchScreen ts(XP, YP, XM, YM, 300);
Arduino_DataBus *bus = new Arduino_SWPAR8(A2, A3, A1, A0, 8, 9, 2, 3, 4, 5, 6, 7);
Arduino_GFX *gfx = new Arduino_ILI9341(bus, A4, 0, false);


const uint8_t THEME_BACKGROUND = 0;
const uint8_t THEME_TEXT = 1;
const uint8_t THEME_TEXT_MUTED = 2;
const uint8_t THEME_ACCENT = 3;
const uint8_t THEME_ACCENT_2 = 4;
const uint8_t THEME_SELECTED = 5;
const uint8_t THEME_PRESSED = 6;
const uint8_t THEME_COUNT = 7;

const uint8_t BG_EFFECT_NONE = 0;
const uint8_t BG_EFFECT_STARS = 1;
const uint8_t BG_EFFECT_CAT = 2;

const uint8_t STAR_COUNT = 16;
const uint8_t STAR_SIZE = 2;
const uint8_t STAR_MIN_SEP = 34;
const unsigned long STAR_FRAME_MS = 80;

const uint8_t CAT_W = 16;
const uint8_t CAT_H = 16;
const unsigned long CAT_FRAME_MS = 70;
const uint16_t CAT_BODY[2][16] = {
  { 0x8000, 0xC000, 0x6028, 0x707C, 0x387C, 0x18FE, 0x1FFE, 0x0FFE, 0x0FFE, 0x1FFE, 0x1FFC, 0x0A28, 0x0A28, 0x0820, 0x1830, 0x0000 },
  { 0x4000, 0xC000, 0x6028, 0x707C, 0x387C, 0x18FE, 0x1FFE, 0x0FFE, 0x0FFE, 0x1FFE, 0x1FFC, 0x1414, 0x1414, 0x1010, 0x3018, 0x0000 }
};
const uint16_t CAT_DOWN[2][16] = {
  { 0x0240, 0x0660, 0x0FF8, 0x0FF8, 0x0FF8, 0x07F0, 0x07F0, 0x03E0, 0x03E0, 0x03E0, 0x0630, 0x0410, 0x0410, 0x0C18, 0x0000, 0x0000 },
  { 0x0240, 0x0660, 0x0FF8, 0x0FF8, 0x0FF8, 0x07F0, 0x07F0, 0x03E0, 0x03E0, 0x05D0, 0x0550, 0x0220, 0x0630, 0x0000, 0x0000, 0x0000 }
};
const uint16_t CAT_UP[2][16] = {
  { 0x0100, 0x0300, 0x0240, 0x0660, 0x0FF8, 0x0FF8, 0x07F0, 0x07F0, 0x03E0, 0x03E0, 0x0630, 0x0410, 0x0410, 0x0C18, 0x0000, 0x0000 },
  { 0x0200, 0x0300, 0x0240, 0x0660, 0x0FF8, 0x0FF8, 0x07F0, 0x07F0, 0x03E0, 0x05D0, 0x0550, 0x0220, 0x0630, 0x0000, 0x0000, 0x0000 }
};

const uint8_t SELECTED_MIX = 100;

struct StarDot {
  int16_t x;
  int16_t y;
  int8_t dx;
  int8_t dy;
  uint8_t shade;
};

struct CatWalk {
  int16_t x;
  int16_t y;
  int16_t tx;
  int16_t ty;
  int8_t dx;
  int8_t dy;
  uint8_t frame;
  uint8_t facing;
  uint8_t gait;
  uint16_t roam;
  uint8_t zone;
  uint8_t back;
};

struct CatLane {
  uint8_t axis;
  int16_t at;
  int16_t lo;
  int16_t hi;
};

CatLane catLanes[8];
uint8_t catLaneN = 0;

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
  uint16_t sleepSeconds;
  uint8_t sleepMode;
  uint16_t crc;
};

int16_t slotX[TOTAL_APPS] = {15, 115, 215, 15, 115, 215};
int16_t slotY[TOTAL_APPS] = {20, 20, 20, 130, 130, 130};
const uint16_t RECORD_SLOT_1 = RECORD_SLOT_0 + sizeof(PersistentRecord);

DeviceConfig config;
DeviceConfig stagedConfig;
uint32_t stagedRgb[TOTAL_APPS];
uint8_t stagedSlots = 0;

uint32_t stagedThemeRgb[THEME_COUNT];
uint8_t stagedThemeMask = 0;
bool receivingTheme = false;
String themeTransactionId;
unsigned long themeLastActivity = 0;
uint8_t stagedBgEffect = BG_EFFECT_NONE;
uint8_t bgEffect = BG_EFFECT_NONE;
StarDot stars[STAR_COUNT];
unsigned long nextStarFrame = 0;
CatWalk cat;
unsigned long nextCatFrame = 0;
uint32_t activeGeneration = 0;
int8_t activeRecord = -1;
uint16_t slotIcons[TOTAL_APPS][ICON_SIZE * ICON_SIZE];
uint16_t iconBand[ICON_BITMAP * ICON_BAND];
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

bool drawing = false;
bool fullRedrawPending = false;
uint8_t keyRedrawPending = 0;
bool pressedVisible = false;
bool touchLatched = false;
unsigned long pressedUntil = 0;
unsigned long nextPressAllowed = 0;
unsigned long lastTouchAt = 0;
uint16_t sleepSeconds = 60;
uint8_t sleepMode = SLEEP_MODE_BLACK;
uint16_t sleepImgChunks = 0;
bool sleeping = false;
bool receivingSleepImg = false;
unsigned long lastActivityAt = 0;
unsigned long sleepImgAt = 0;
char sleepImgIdBuf[17];

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


  const uint16_t theme[THEME_COUNT] = {
    0x0000,
    0xFFFF,
    0x39E7,
    0xC638,
    0x2965,
    0xFFFF,
    0x10A2,
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
  sleepSeconds = record.sleepSeconds;
  if (
    sleepSeconds != 0 &&
    sleepSeconds != 30 &&
    sleepSeconds != 60 &&
    sleepSeconds != 300
  ) {
    sleepSeconds = 60;
  }
  sleepMode = record.sleepMode == SLEEP_MODE_IMAGE ? SLEEP_MODE_IMAGE : SLEEP_MODE_BLACK;
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
  record.sleepSeconds = sleepSeconds;
  record.sleepMode = sleepMode;
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


void rebuildSlotLayout() {
  if (screenH > screenW) {
    gridCols = 2;
    gridRows = 3;

    const int xs[2] = {25, 125};
    const int ys[3] = {15, 115, 215};
    for (uint8_t i = 0; i < TOTAL_APPS; i++) {
      slotX[i] = xs[i % gridCols];
      slotY[i] = ys[i / gridCols];
    }
  } else {
    gridCols = 3;
    gridRows = 2;

    const int xs[3] = {15, 115, 215};
    const int ys[2] = {20, 130};
    for (uint8_t i = 0; i < TOTAL_APPS; i++) {
      slotX[i] = xs[i % gridCols];
      slotY[i] = ys[i / gridCols];
    }
  }
}

void applyDisplayRotation(uint8_t rotation) {
  if (rotation > 3) rotation = 1;
  displayRotation = rotation;
  if (displayReady) {
    gfx->setRotation(displayRotation);
    screenW = static_cast<int16_t>(gfx->width());
    screenH = static_cast<int16_t>(gfx->height());
  } else if (displayRotation == 0 || displayRotation == 2) {
    screenW = 240;
    screenH = 320;
  } else {
    screenW = 320;
    screenH = 240;
  }
  rebuildSlotLayout();
  if (bgEffect == BG_EFFECT_STARS) {
    seedStars();
  } else if (bgEffect == BG_EFFECT_CAT) {
    seedCat();
  }
}

void mapTouchToScreen(const TSPoint &point, int &touchX, int &touchY) {

  switch (displayRotation) {
    case 0:
      touchX = map(point.x, TS_MINX, TS_MAXX, 0, screenW);
      touchY = map(point.y, TS_MINY, TS_MAXY, 0, screenH);
      break;
    case 2:
      touchX = map(point.x, TS_MINX, TS_MAXX, screenW, 0);
      touchY = map(point.y, TS_MINY, TS_MAXY, screenH, 0);
      break;
    case 3:
      touchX = map(point.y, TS_MINY, TS_MAXY, 0, screenW);
      touchY = map(point.x, TS_MINX, TS_MAXX, 0, screenH);
      break;
    case 1:
    default:
      touchX = map(point.y, TS_MINY, TS_MAXY, screenW, 0);
      touchY = map(point.x, TS_MINX, TS_MAXX, screenH, 0);
      break;
  }
}


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

const uint8_t PRESS_TINT = 110;

void drawKeyLabel(const char *text, int centerX, int y, uint8_t size, uint16_t color) {
  const int width = strlen(text) * 6 * size;
  gfx->setTextColor(color);
  gfx->setTextSize(size);
  gfx->setCursor(centerX - width / 2, y);
  gfx->print(text);
}


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


  gfx->fillRect(x, y, KEY_W, KEY_H, config.theme.values[THEME_BACKGROUND]);

  if (!slot.label[0]) {
    drawKeyLabel(
      "EMPTY", x + KEY_W / 2, y + (KEY_H - TEXT_H) / 2, 1,
      config.theme.values[THEME_TEXT_MUTED]
    );
    return;
  }

  if (!slotHasIcon[index]) {

    const uint16_t accent = mixColor(
      slot.color, config.theme.values[THEME_SELECTED], SELECTED_MIX
    );
    drawKeyLabel(
      label.c_str(), x + KEY_W / 2, y + (KEY_H - TEXT_H) / 2, 1, accent
    );
    return;
  }


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

bool pointInKeyCell(int x, int y) {
  for (uint8_t i = 0; i < TOTAL_APPS; i++) {
    if (
      x >= slotX[i] && x < slotX[i] + KEY_W &&
      y >= slotY[i] && y < slotY[i] + KEY_H
    ) {
      return true;
    }
  }
  return false;
}


bool starsOnLightBackground() {
  return textColorFor(config.theme.values[THEME_BACKGROUND]) == 0x0000;
}

uint8_t activeStarSize() {
  return starsOnLightBackground() ? 3 : STAR_SIZE;
}

bool starHitsKey(int x, int y) {
  const uint8_t w = starsOnLightBackground() ? 2 : STAR_SIZE;
  const uint8_t h = starsOnLightBackground() ? 3 : STAR_SIZE;
  for (uint8_t dy = 0; dy < h; dy++) {
    for (uint8_t dx = 0; dx < w; dx++) {
      if (pointInKeyCell(x + dx, y + dy)) return true;
    }
  }
  return false;
}

uint16_t starShadeColor(uint8_t shade) {
  if (starsOnLightBackground()) return 0x0000;
  if (shade == 0) return 0xFFFF;
  if (shade == 1) return 0xDEFB;
  return 0xC618;
}


void assignStarDrift(StarDot &star) {
  static const int8_t kDx[6] = {1, -1, 0, 0, 1, -1};
  static const int8_t kDy[6] = {0, 0, 1, -1, 1, -1};
  const uint8_t dir = static_cast<uint8_t>(random(6));
  star.dx = kDx[dir];
  star.dy = kDy[dir];
}

void nudgeStarDrift(StarDot &star) {
  assignStarDrift(star);
}

bool starCoordsTooClose(int16_t x, int16_t y, int8_t ignoreIndex) {
  for (uint8_t i = 0; i < STAR_COUNT; i++) {
    if (static_cast<int8_t>(i) == ignoreIndex) continue;
    int16_t adx = static_cast<int16_t>(stars[i].x - x);
    int16_t ady = static_cast<int16_t>(stars[i].y - y);
    if (adx < 0) adx = static_cast<int16_t>(-adx);
    if (ady < 0) ady = static_cast<int16_t>(-ady);
    if (adx < STAR_MIN_SEP && ady < STAR_MIN_SEP) return true;
  }
  return false;
}

uint8_t starGutterZoneCount() {
  const uint8_t colGaps = gridCols > 1 ? static_cast<uint8_t>(gridCols - 1) : 0;
  const uint8_t rowGaps = gridRows > 1 ? static_cast<uint8_t>(gridRows - 1) : 0;
  return static_cast<uint8_t>(4 + colGaps + rowGaps);
}

void pickGutterPoint(uint8_t zone, int16_t &x, int16_t &y) {
  const uint8_t zones = starGutterZoneCount();
  const uint8_t size = activeStarSize();
  zone = static_cast<uint8_t>(zone % (zones ? zones : 1));
  const uint8_t colGaps = gridCols > 1 ? static_cast<uint8_t>(gridCols - 1) : 0;

  if (zone == 0) {
    x = static_cast<int16_t>(random(screenW - size));
    y = static_cast<int16_t>(random(max(1, slotY[0])));
  } else if (zone == 1) {
    const int bottom = slotY[TOTAL_APPS - 1] + KEY_H;
    x = static_cast<int16_t>(random(screenW - size));
    y = static_cast<int16_t>(
      bottom + random(max(1, screenH - bottom - size + 1))
    );
  } else if (zone == 2) {
    x = static_cast<int16_t>(random(max(1, slotX[0])));
    y = static_cast<int16_t>(random(screenH - size));
  } else if (zone == 3) {
    const int right = slotX[gridCols - 1] + KEY_W;
    x = static_cast<int16_t>(
      right + random(max(1, screenW - right - size + 1))
    );
    y = static_cast<int16_t>(random(screenH - size));
  } else if (zone < static_cast<uint8_t>(4 + colGaps)) {
    const uint8_t gap = static_cast<uint8_t>(zone - 4);
    const int left = slotX[gap] + KEY_W;
    const int span = slotX[gap + 1] - left;
    x = static_cast<int16_t>(left + (span > 1 ? random(span) : 0));
    y = static_cast<int16_t>(random(screenH - size));
  } else {
    const uint8_t gap = static_cast<uint8_t>(zone - 4 - colGaps);
    const int top = slotY[gap * gridCols] + KEY_H;
    const int span = slotY[(gap + 1) * gridCols] - top;
    x = static_cast<int16_t>(random(screenW - size));
    y = static_cast<int16_t>(top + (span > 1 ? random(span) : 0));
  }
  if (x < 0) x = 0;
  if (y < 0) y = 0;
  if (x > screenW - size) x = screenW - size;
  if (y > screenH - size) y = screenH - size;
}


void placeStarInGutter(StarDot &star, int8_t ignoreIndex, int8_t forcedZone) {
  const uint8_t zones = starGutterZoneCount();
  for (uint8_t attempt = 0; attempt < 40; attempt++) {
    const uint8_t zone = forcedZone >= 0
      ? static_cast<uint8_t>(forcedZone)
      : static_cast<uint8_t>(random(zones));
    int16_t x = 0;
    int16_t y = 0;
    pickGutterPoint(zone, x, y);
    if (!starHitsKey(x, y) && !starCoordsTooClose(x, y, ignoreIndex)) {
      star.x = x;
      star.y = y;
      return;
    }
  }

  int16_t x = 0;
  int16_t y = 0;
  pickGutterPoint(forcedZone >= 0 ? static_cast<uint8_t>(forcedZone) : 0, x, y);
  star.x = x;
  star.y = y;
}

void seedStars() {
  randomSeed(micros() ^ (analogRead(A5) << 16) ^ millis());
  const uint8_t zones = starGutterZoneCount();
  for (uint8_t i = 0; i < STAR_COUNT; i++) {

    placeStarInGutter(
      stars[i], static_cast<int8_t>(i), static_cast<int8_t>(i % zones)
    );
    assignStarDrift(stars[i]);
    stars[i].shade = static_cast<uint8_t>(i % 3);
  }
  nextStarFrame = 0;
}

void paintStarBlock(int x, int y, uint16_t color) {
  const uint8_t w = starsOnLightBackground() ? 2 : STAR_SIZE;
  const uint8_t h = starsOnLightBackground() ? 3 : STAR_SIZE;
  if (
    starsOnLightBackground() &&
    x >= 0 && y >= 0 &&
    x + w <= screenW && y + h <= screenH &&
    !starHitsKey(x, y)
  ) {
    gfx->fillRect(x, y, w, h, color);
    return;
  }
  for (uint8_t dy = 0; dy < h; dy++) {
    for (uint8_t dx = 0; dx < w; dx++) {
      const int px = x + dx;
      const int py = y + dy;
      if (px < 0 || px >= screenW || py < 0 || py >= screenH) continue;
      if (pointInKeyCell(px, py)) continue;
      gfx->drawPixel(px, py, color);
    }
  }
}

void paintAllStars() {
  if (bgEffect != BG_EFFECT_STARS || !displayReady) return;
  for (uint8_t i = 0; i < STAR_COUNT; i++) {
    paintStarBlock(stars[i].x, stars[i].y, starShadeColor(stars[i].shade));
  }
}

void serviceStars(unsigned long now) {
  if (sleeping) return;
  if (bgEffect != BG_EFFECT_STARS) return;
  if (!displayReady || drawing || pressedVisible) return;
  if (iconStreamActive(now)) return;
  if (fullRedrawPending || keyRedrawPending) return;
  if (nextStarFrame != 0 && !timeReached(now, nextStarFrame)) return;
  nextStarFrame = now + STAR_FRAME_MS;

  static uint8_t starTick = 0;
  starTick++;

  const uint16_t bg = config.theme.values[THEME_BACKGROUND];
  for (uint8_t i = 0; i < STAR_COUNT; i++) {

    const uint8_t period = static_cast<uint8_t>(1 + stars[i].shade);
    if ((starTick % period) != 0) continue;

    StarDot &star = stars[i];
    const int16_t ox = star.x;
    const int16_t oy = star.y;
    int16_t nx = static_cast<int16_t>(star.x + star.dx);
    int16_t ny = static_cast<int16_t>(star.y + star.dy);


    if (
      nx < 0 || nx > screenW - STAR_SIZE ||
      ny < 0 || ny > screenH - STAR_SIZE
    ) {
      paintStarBlock(ox, oy, bg);
      placeStarInGutter(star, static_cast<int8_t>(i), static_cast<int8_t>(random(7)));
      assignStarDrift(star);
      paintStarBlock(star.x, star.y, starShadeColor(star.shade));
      continue;
    }


    if (starHitsKey(nx, ny)) {
      const int16_t tryX = static_cast<int16_t>(star.x - star.dx);
      const int16_t tryY2 = static_cast<int16_t>(star.y - star.dy);
      if (
        tryX >= 0 && tryX <= screenW - STAR_SIZE &&
        !starHitsKey(tryX, ny)
      ) {
        star.dx = static_cast<int8_t>(-star.dx);
        nx = tryX;
      } else if (
        tryY2 >= 0 && tryY2 <= screenH - STAR_SIZE &&
        !starHitsKey(nx, tryY2)
      ) {
        star.dy = static_cast<int8_t>(-star.dy);
        ny = tryY2;
      } else if (
        tryX >= 0 && tryX <= screenW - STAR_SIZE &&
        tryY2 >= 0 && tryY2 <= screenH - STAR_SIZE &&
        !starHitsKey(tryX, tryY2)
      ) {
        star.dx = static_cast<int8_t>(-star.dx);
        star.dy = static_cast<int8_t>(-star.dy);
        nx = tryX;
        ny = tryY2;
      } else {
        nudgeStarDrift(star);
        nx = star.x;
        ny = star.y;
      }
      if (starHitsKey(nx, ny)) {
        nx = star.x;
        ny = star.y;
      }
    }


    if (starCoordsTooClose(nx, ny, static_cast<int8_t>(i))) {
      int16_t pushX = 0;
      int16_t pushY = 0;
      for (uint8_t j = 0; j < STAR_COUNT; j++) {
        if (j == i) continue;
        int16_t adx = static_cast<int16_t>(nx - stars[j].x);
        int16_t ady = static_cast<int16_t>(ny - stars[j].y);
        int16_t absx = adx < 0 ? static_cast<int16_t>(-adx) : adx;
        int16_t absy = ady < 0 ? static_cast<int16_t>(-ady) : ady;
        if (absx < STAR_MIN_SEP && absy < STAR_MIN_SEP) {
          if (adx != 0) pushX += adx > 0 ? 1 : -1;
          if (ady != 0) pushY += ady > 0 ? 1 : -1;
        }
      }
      if (pushX != 0) star.dx = pushX > 0 ? 1 : -1;
      if (pushY != 0) star.dy = pushY > 0 ? 1 : -1;
      if (star.dx == 0 && star.dy == 0) assignStarDrift(star);
      nx = static_cast<int16_t>(star.x + star.dx);
      ny = static_cast<int16_t>(star.y + star.dy);
      if (
        nx < 0 || nx > screenW - STAR_SIZE ||
        ny < 0 || ny > screenH - STAR_SIZE ||
        starHitsKey(nx, ny) ||
        starCoordsTooClose(nx, ny, static_cast<int8_t>(i))
      ) {
        nx = star.x;
        ny = star.y;
      }
    }


    if (random(520) == 0) {
      nudgeStarDrift(star);
    }


    if (nx == ox && ny == oy) {
      static const int8_t kTryDx[4] = {1, -1, 0, 0};
      static const int8_t kTryDy[4] = {0, 0, 1, -1};
      bool stepped = false;
      for (uint8_t t = 0; t < 4; t++) {
        const int16_t tx = static_cast<int16_t>(ox + kTryDx[t]);
        const int16_t ty = static_cast<int16_t>(oy + kTryDy[t]);
        if (
          tx < 0 || tx > screenW - STAR_SIZE ||
          ty < 0 || ty > screenH - STAR_SIZE ||
          starHitsKey(tx, ty) ||
          starCoordsTooClose(tx, ty, static_cast<int8_t>(i))
        ) {
          continue;
        }
        star.dx = kTryDx[t];
        star.dy = kTryDy[t];
        nx = tx;
        ny = ty;
        stepped = true;
        break;
      }
      if (!stepped) {
        paintStarBlock(ox, oy, bg);
        placeStarInGutter(
          star, static_cast<int8_t>(i), static_cast<int8_t>(random(7))
        );
        assignStarDrift(star);
        paintStarBlock(star.x, star.y, starShadeColor(star.shade));
        continue;
      }
    }

    if (nx != ox || ny != oy) {
      paintStarBlock(ox, oy, bg);
      star.x = nx;
      star.y = ny;
    }
    paintStarBlock(star.x, star.y, starShadeColor(star.shade));
  }
}

void addCatLane(uint8_t axis, int16_t at, int16_t lo, int16_t hi) {
  if (catLaneN >= 8) return;
  if (hi < lo) hi = lo;
  catLanes[catLaneN].axis = axis;
  catLanes[catLaneN].at = at;
  catLanes[catLaneN].lo = lo;
  catLanes[catLaneN].hi = hi;
  catLaneN++;
}

void buildCatLanes() {
  catLaneN = 0;
  const int16_t xMax = static_cast<int16_t>(screenW - CAT_W);
  const int16_t yMax = static_cast<int16_t>(screenH - CAT_H);
  addCatLane(0, 0, 0, xMax);
  addCatLane(0, yMax, 0, xMax);
  addCatLane(1, 0, 0, yMax);
  addCatLane(1, xMax, 0, yMax);

  const uint8_t colGaps = gridCols > 1 ? static_cast<uint8_t>(gridCols - 1) : 0;
  const uint8_t rowGaps = gridRows > 1 ? static_cast<uint8_t>(gridRows - 1) : 0;
  for (uint8_t g = 0; g < colGaps && catLaneN < 8; g++) {
    const int left = slotX[g] + KEY_W;
    const int span = slotX[g + 1] - left;
    int x = left + span / 2 - CAT_W / 2;
    if (x < 0) x = 0;
    if (x > xMax) x = xMax;
    addCatLane(1, static_cast<int16_t>(x), 0, yMax);
  }
  for (uint8_t g = 0; g < rowGaps && catLaneN < 8; g++) {
    const int top = slotY[g * gridCols] + KEY_H;
    const int span = slotY[(g + 1) * gridCols] - top;
    int y = top + (span > CAT_H ? (span - CAT_H) / 2 : 0);
    if (y < 0) y = 0;
    if (y > yMax) y = yMax;
    addCatLane(0, static_cast<int16_t>(y), 0, xMax);
  }
}

bool catLaneIsGap(uint8_t i) {
  if (i >= catLaneN) return false;
  if (catLanes[i].axis == 0) {
    return catLanes[i].at != 0 && catLanes[i].at != static_cast<int16_t>(screenH - CAT_H);
  }
  return catLanes[i].at != 0 && catLanes[i].at != static_cast<int16_t>(screenW - CAT_W);
}

bool catFree(int x, int y) {
  if (x < 0 || y < 0 || x > screenW - CAT_W || y > screenH - CAT_H) return false;
  if (!catLaneN) buildCatLanes();
  for (uint8_t i = 0; i < catLaneN; i++) {
    if (catLanes[i].axis == 0) {
      if (y == catLanes[i].at && x >= catLanes[i].lo && x <= catLanes[i].hi) return true;
    } else if (x == catLanes[i].at && y >= catLanes[i].lo && y <= catLanes[i].hi) {
      return true;
    }
  }
  return false;
}

uint8_t catChoices(int x, int y, int8_t *dxs, int8_t *dys) {
  static const int8_t kDx[4] = {1, -1, 0, 0};
  static const int8_t kDy[4] = {0, 0, 1, -1};
  uint8_t n = 0;
  for (uint8_t i = 0; i < 4; i++) {
    if (catFree(x + kDx[i], y + kDy[i])) {
      dxs[n] = kDx[i];
      dys[n] = kDy[i];
      n++;
    }
  }
  return n;
}

void faceCat() {
  if (cat.dx > 0) cat.facing = 1;
  else if (cat.dx < 0) cat.facing = 0;
  else if (cat.dy < 0) cat.facing = 2;
  else if (cat.dy > 0) cat.facing = 3;
}

int16_t catManhattan(int16_t x, int16_t y) {
  int16_t dx = static_cast<int16_t>(x - cat.tx);
  int16_t dy = static_cast<int16_t>(y - cat.ty);
  if (dx < 0) dx = static_cast<int16_t>(-dx);
  if (dy < 0) dy = static_cast<int16_t>(-dy);
  return static_cast<int16_t>(dx + dy);
}

bool catBehindHeading(int16_t x, int16_t y) {
  int16_t ax = static_cast<int16_t>(x - cat.x);
  int16_t ay = static_cast<int16_t>(y - cat.y);
  if (ax < 0) ax = static_cast<int16_t>(-ax);
  if (ay < 0) ay = static_cast<int16_t>(-ay);
  if (cat.dx > 0 && x <= cat.x && ay < 12) return true;
  if (cat.dx < 0 && x >= cat.x && ay < 12) return true;
  if (cat.dy > 0 && y <= cat.y && ax < 12) return true;
  if (cat.dy < 0 && y >= cat.y && ax < 12) return true;
  return false;
}

void pickCatTarget() {
  if (!catLaneN) buildCatLanes();
  uint8_t gaps[8];
  uint8_t g = 0;
  for (uint8_t i = 0; i < catLaneN; i++) {
    if (catLaneIsGap(i)) gaps[g++] = i;
  }
  const bool lastGap = catLaneIsGap(cat.zone);
  uint8_t lane = 0;
  if (g && (!lastGap || random(10) < 8)) {
    lane = gaps[static_cast<uint8_t>(random(g))];
  } else if (catLaneN) {
    lane = static_cast<uint8_t>(random(catLaneN));
  }
  const CatLane &L = catLanes[lane];
  int16_t x = 0;
  int16_t y = 0;
  for (uint8_t t = 0; t < 6; t++) {
    if (L.axis == 0) {
      x = static_cast<int16_t>(L.lo + random(L.hi - L.lo + 1));
      y = L.at;
    } else {
      x = L.at;
      y = static_cast<int16_t>(L.lo + random(L.hi - L.lo + 1));
    }
    if (!catBehindHeading(x, y) && catFree(x, y)) break;
  }
  cat.tx = x;
  cat.ty = y;
  cat.zone = lane;
  cat.roam = 0;
}

void steerCat() {
  int8_t dxs[4];
  int8_t dys[4];
  const uint8_t n = catChoices(cat.x, cat.y, dxs, dys);
  if (!n) {
    cat.dx = 0;
    cat.dy = 0;
    return;
  }

  int8_t keepX[4];
  int8_t keepY[4];
  uint8_t m = 0;
  bool headingOpen = false;
  int8_t hx = 0;
  int8_t hy = 0;
  for (uint8_t i = 0; i < n; i++) {
    const bool back =
      n > 1 &&
      dxs[i] == static_cast<int8_t>(-cat.dx) &&
      dys[i] == static_cast<int8_t>(-cat.dy);
    if (back) continue;
    keepX[m] = dxs[i];
    keepY[m] = dys[i];
    m++;
    if (dxs[i] == cat.dx && dys[i] == cat.dy) {
      headingOpen = true;
      hx = dxs[i];
      hy = dys[i];
    }
  }

  if (!m) {
    cat.dx = dxs[0];
    cat.dy = dys[0];
    faceCat();
    return;
  }

  if (headingOpen && n <= 2) {
    cat.dx = hx;
    cat.dy = hy;
    faceCat();
    return;
  }

  int16_t stay = 32767;
  if (headingOpen) {
    stay = catManhattan(
      static_cast<int16_t>(cat.x + hx),
      static_cast<int16_t>(cat.y + hy)
    );
  }

  int8_t bx = keepX[0];
  int8_t by = keepY[0];
  int16_t bestD = 32767;
  for (uint8_t i = 0; i < m; i++) {
    const int16_t d = catManhattan(
      static_cast<int16_t>(cat.x + keepX[i]),
      static_cast<int16_t>(cat.y + keepY[i])
    );
    if (d < bestD) {
      bestD = d;
      bx = keepX[i];
      by = keepY[i];
    }
  }

  if (headingOpen && stay <= bestD) {
    cat.dx = hx;
    cat.dy = hy;
  } else {
    cat.dx = bx;
    cat.dy = by;
  }
  faceCat();
}

void placeCatInGutter() {
  buildCatLanes();
  int8_t dxs[4];
  int8_t dys[4];
  for (uint8_t attempt = 0; attempt < 40; attempt++) {
    if (!catLaneN) break;
    uint8_t i = static_cast<uint8_t>(random(catLaneN));
    if (attempt < 24 && !catLaneIsGap(i) && random(3)) continue;
    const CatLane &L = catLanes[i];
    int16_t x;
    int16_t y;
    if (L.axis == 0) {
      x = static_cast<int16_t>(L.lo + random(L.hi - L.lo + 1));
      y = L.at;
    } else {
      x = L.at;
      y = static_cast<int16_t>(L.lo + random(L.hi - L.lo + 1));
    }
    if (catFree(x, y) && catChoices(x, y, dxs, dys)) {
      cat.x = x;
      cat.y = y;
      cat.tx = x;
      cat.ty = y;
      cat.dx = 1;
      cat.dy = 0;
      cat.zone = i;
      pickCatTarget();
      steerCat();
      return;
    }
  }
  if (catLaneN) {
    cat.x = catLanes[0].axis == 0 ? catLanes[0].lo : catLanes[0].at;
    cat.y = catLanes[0].axis == 0 ? catLanes[0].at : catLanes[0].lo;
    cat.tx = cat.x;
    cat.ty = cat.y;
    cat.dx = 1;
    cat.dy = 0;
    cat.facing = 1;
    pickCatTarget();
    steerCat();
  }
}

void seedCat() {
  randomSeed(micros() ^ (analogRead(A5) << 16) ^ millis());
  buildCatLanes();
  cat.zone = 255;
  cat.roam = 0;
  cat.back = 0;
  cat.dx = 1;
  cat.dy = 0;
  cat.facing = 1;
  placeCatInGutter();
  cat.frame = 0;
  cat.gait = 0;
  nextCatFrame = 0;
}

void paintCatBox(int x, int y, bool spriteOnly) {
  const uint16_t bg = config.theme.values[THEME_BACKGROUND];
  const uint16_t fur = config.theme.values[THEME_ACCENT];
  const uint16_t eye = config.theme.values[THEME_TEXT];
  const uint8_t pose = cat.frame & 1;
  for (uint8_t dy = 0; dy < CAT_H; dy++) {
    for (uint8_t dx = 0; dx < CAT_W; dx++) {
      uint16_t color = bg;
      if (spriteOnly) {
        const uint8_t srcX = cat.facing == 0
          ? static_cast<uint8_t>(CAT_W - 1 - dx)
          : dx;
        const uint16_t mask = static_cast<uint16_t>(1u << (CAT_W - 1 - srcX));
        uint16_t eyeBits = 0;
        uint16_t bodyBits = 0;
        if (cat.facing == 2) {
          bodyBits = CAT_UP[pose][dy];
        } else if (cat.facing == 3) {
          bodyBits = CAT_DOWN[pose][dy];
          if (dy == 3 || dy == 4) eyeBits = 0x0420;
        } else {
          bodyBits = CAT_BODY[pose][dy];
          if (dy == 3 || dy == 4) eyeBits = 0x0028;
        }
        if (eyeBits & mask) color = eye;
        else if (bodyBits & mask) color = fur;
        else continue;
      }
      const int px = x + dx;
      const int py = y + dy;
      if (px < 0 || px >= screenW || py < 0 || py >= screenH) continue;
      if (pointInKeyCell(px, py)) continue;
      gfx->drawPixel(px, py, color);
    }
  }
}

void paintCat() {
  if (bgEffect != BG_EFFECT_CAT || !displayReady) return;
  paintCatBox(cat.x, cat.y, true);
}

void serviceCat(unsigned long now) {
  if (sleeping) return;
  if (bgEffect != BG_EFFECT_CAT) return;
  if (!displayReady || drawing || pressedVisible) return;
  if (iconStreamActive(now)) return;
  if (fullRedrawPending || keyRedrawPending) return;
  if (nextCatFrame != 0 && !timeReached(now, nextCatFrame)) return;
  nextCatFrame = now + CAT_FRAME_MS;

  int8_t dxs[4];
  int8_t dys[4];
  const uint8_t n = catChoices(cat.x, cat.y, dxs, dys);
  if (!n) {
    paintCatBox(cat.x, cat.y, false);
    placeCatInGutter();
    paintCat();
    return;
  }

  if (!cat.back && (catManhattan(cat.x, cat.y) <= 2 || cat.roam > 380)) {
    pickCatTarget();
    if (
      random(100) < 3 &&
      (cat.dx || cat.dy) &&
      catFree(cat.x - cat.dx, cat.y - cat.dy)
    ) {
      cat.back = static_cast<uint8_t>(4 + random(3));
    }
  }

  bool reversing = cat.back > 0;
  if (reversing) {
    cat.back = static_cast<uint8_t>(cat.back - 1);
  } else {
    steerCat();
  }

  const int16_t ox = cat.x;
  const int16_t oy = cat.y;
  const int8_t stepX = reversing ? static_cast<int8_t>(-cat.dx) : cat.dx;
  const int8_t stepY = reversing ? static_cast<int8_t>(-cat.dy) : cat.dy;
  int16_t nx = static_cast<int16_t>(cat.x + stepX);
  int16_t ny = static_cast<int16_t>(cat.y + stepY);
  if (!catFree(nx, ny)) {
    cat.back = 0;
    steerCat();
    nx = static_cast<int16_t>(cat.x + cat.dx);
    ny = static_cast<int16_t>(cat.y + cat.dy);
    if (!catFree(nx, ny)) {
      paintCatBox(ox, oy, false);
      placeCatInGutter();
      paintCat();
      return;
    }
  }

  paintCatBox(ox, oy, false);
  cat.x = nx;
  cat.y = ny;
  faceCat();
  cat.roam = static_cast<uint16_t>(cat.roam + 1);
  cat.gait = static_cast<uint8_t>(cat.gait + 1);
  if (cat.gait >= 2) {
    cat.gait = 0;
    cat.frame = static_cast<uint8_t>((cat.frame + 1) & 1);
  }
  paintCat();
}

void requestFullRedraw() {
  fullRedrawPending = true;
}

void requestKeyRedraw(uint8_t index) {
  keyRedrawPending |= static_cast<uint8_t>(1 << index);
}

void serviceRedraw(unsigned long now) {
  if (sleeping) return;
  if (!displayReady || drawing || pressedVisible) return;
  if (!fullRedrawPending && !keyRedrawPending) return;

  if (fullRedrawPending) {
    fullRedrawPending = false;
    keyRedrawPending = 0;
    drawing = true;
    gfx->fillScreen(config.theme.values[THEME_BACKGROUND]);

    paintAllStars();
    paintCat();
    for (uint8_t i = 0; i < TOTAL_APPS; i++) {
      drawKey(i);
      readSerial();
    }
    drawing = false;
    return;
  }

  if (iconStreamActive(now)) return;
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
  const int pressW = screenW - 60;
  const int pressH = screenH - 60;
  const int x = (screenW - pressW) / 2;
  const int y = (screenH - pressH) / 2;

  gfx->fillScreen(config.theme.values[THEME_BACKGROUND]);
  gfx->fillRoundRect(x, y, pressW, pressH, PRESS_RADIUS, fill);
  gfx->drawRoundRect(
    x, y, pressW, pressH, PRESS_RADIUS, config.theme.values[THEME_ACCENT]
  );
  gfx->drawRoundRect(
    x + 3, y + 3, pressW - 6, pressH - 6, PRESS_RADIUS - 3,
    config.theme.values[THEME_ACCENT_2]
  );
  readSerial();

  if (slotHasIcon[index]) {

    const int groupTop = y + (pressH - (ICON_DRAW + 16 + 8 * size)) / 2;
    drawKeyIcon(index, x + (pressW - ICON_DRAW) / 2, groupTop);
    drawKeyLabel(label.c_str(), screenW / 2, groupTop + ICON_DRAW + 16, size, textColor);
    return;
  }

  drawKeyLabel(label.c_str(), screenW / 2, y + (pressH - 8 * size) / 2, size, textColor);
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

uint8_t parseBgEffect(const String &name) {
  if (name == "stars") return BG_EFFECT_STARS;
  if (name == "cat") return BG_EFFECT_CAT;
  return BG_EFFECT_NONE;
}

void beginTheme(const String &line) {
  const int firstTab = line.indexOf('\t');
  const int secondTab = line.indexOf('\t', firstTab + 1);
  const int thirdTab = line.indexOf('\t', secondTab + 1);
  if (firstTab < 0 || secondTab < 0) {
    sendThemeError("-", "BAD_BEGIN");
    return;
  }

  if (thirdTab >= 0 && line.indexOf('\t', thirdTab + 1) >= 0) {
    sendThemeError("-", "BAD_BEGIN");
    return;
  }

  const String id = line.substring(firstTab + 1, secondTab);
  const String count = thirdTab < 0
    ? line.substring(secondTab + 1)
    : line.substring(secondTab + 1, thirdTab);
  const String effect = thirdTab < 0 ? String("") : line.substring(thirdTab + 1);
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
  if (iconRecvIndex >= 0) {
    sendThemeError(id, "BUSY");
    return;
  }
  if (receivingTheme) {
    sendThemeError(themeTransactionId, "SUPERSEDED");
  }
  memset(stagedThemeRgb, 0, sizeof(stagedThemeRgb));
  stagedThemeMask = 0;
  stagedBgEffect = parseBgEffect(effect);
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
  bgEffect = stagedBgEffect;
  if (bgEffect == BG_EFFECT_STARS) {
    seedStars();
  } else if (bgEffect == BG_EFFECT_CAT) {
    seedCat();
  }

  pressedVisible = false;
  memset(slotHasIcon, 0, sizeof(slotHasIcon));
  iconRecvIndex = -1;
  iconRecvMask = 0;
  requestFullRedraw();
  Serial.print("CFG_THEME_OK\t");
  Serial.println(id);
  clearThemeTransaction();
}

void receiveRotate(const String &line) {

  const int firstTab = line.indexOf('\t');
  const int secondTab = line.indexOf('\t', firstTab + 1);
  if (firstTab < 0 || secondTab < 0 || line.indexOf('\t', secondTab + 1) >= 0) {
    Serial.println("CFG_ROTATE_ERR\t-\tBAD_LINE");
    return;
  }
  const String id = line.substring(firstTab + 1, secondTab);
  const String valueText = line.substring(secondTab + 1);
  if (!validTransactionId(id)) {
    Serial.println("CFG_ROTATE_ERR\t-\tBAD_TX");
    return;
  }
  if (
    valueText.length() != 1 ||
    valueText.charAt(0) < '0' ||
    valueText.charAt(0) > '3'
  ) {
    Serial.print("CFG_ROTATE_ERR\t");
    Serial.print(id);
    Serial.println("\tBAD_VALUE");
    return;
  }
  if (receivingConfig || receivingTheme || iconRecvIndex >= 0 || receivingSleepImg) {
    Serial.print("CFG_ROTATE_ERR\t");
    Serial.print(id);
    Serial.println("\tBUSY");
    return;
  }

  const uint8_t rotation = static_cast<uint8_t>(valueText.charAt(0) - '0');
  applyDisplayRotation(rotation);
  pressedVisible = false;
  requestFullRedraw();
  Serial.print("CFG_ROTATE_OK\t");
  Serial.println(id);
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


  if (receivingConfig || receivingTheme || receivingSleepImg) {
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

void noteActivity() {
  lastActivityAt = millis();
}

void paintSleepPixel(uint8_t x, uint8_t y, uint16_t color) {
  if (!displayReady || !sleeping || x >= SLEEP_W || y >= SLEEP_H) return;
  const int16_t x0 = static_cast<int16_t>((static_cast<uint16_t>(x) * screenW) / SLEEP_W);
  const int16_t x1 = static_cast<int16_t>((static_cast<uint16_t>(x + 1) * screenW) / SLEEP_W);
  const int16_t y0 = static_cast<int16_t>((static_cast<uint16_t>(y) * screenH) / SLEEP_H);
  const int16_t y1 = static_cast<int16_t>((static_cast<uint16_t>(y + 1) * screenH) / SLEEP_H);
  const int16_t w = x1 - x0;
  const int16_t h = y1 - y0;
  if (w <= 0 || h <= 0) return;
  gfx->fillRect(x0, y0, w, h, color);
}

void enterSleep() {
  if (sleeping) return;
  sleeping = true;
  if (displayReady) gfx->fillScreen(0x0000);
  if (sleepMode == SLEEP_MODE_IMAGE) Serial.println("SLEEP");
}

void wakeFromSleep() {
  if (!sleeping) return;
  sleeping = false;
  receivingSleepImg = false;
  noteActivity();
  requestFullRedraw();
}

void sendSleepError(const String &id, const char *reason) {
  Serial.print("CFG_SLEEP_ERR\t");
  if (id.length()) Serial.print(id);
  else Serial.print('-');
  Serial.print('\t');
  Serial.println(reason);
}

void sendSleepImgError(const String &id, const char *reason) {
  Serial.print("CFG_SLEEPIMG_ERR\t");
  if (id.length()) Serial.print(id);
  else Serial.print('-');
  Serial.print('\t');
  Serial.println(reason);
}

void receiveSleep(const String &line) {
  const int firstTab = line.indexOf('\t');
  const int secondTab = line.indexOf('\t', firstTab + 1);
  const int thirdTab = line.indexOf('\t', secondTab + 1);
  if (firstTab < 0 || secondTab < 0 || thirdTab < 0 || line.indexOf('\t', thirdTab + 1) >= 0) {
    sendSleepError("-", "BAD_LINE");
    return;
  }
  const String id = line.substring(firstTab + 1, secondTab);
  if (!validTransactionId(id)) {
    sendSleepError("-", "BAD_TX");
    return;
  }
  if (receivingConfig || receivingTheme || iconRecvIndex >= 0 || receivingSleepImg) {
    sendSleepError(id, "BUSY");
    return;
  }
  const int seconds = line.substring(secondTab + 1, thirdTab).toInt();
  const int mode = line.substring(thirdTab + 1).toInt();
  if (seconds != 0 && seconds != 30 && seconds != 60 && seconds != 300) {
    sendSleepError(id, "BAD_VALUE");
    return;
  }
  if (mode != SLEEP_MODE_BLACK && mode != SLEEP_MODE_IMAGE) {
    sendSleepError(id, "BAD_MODE");
    return;
  }
  sleepSeconds = static_cast<uint16_t>(seconds);
  sleepMode = static_cast<uint8_t>(mode);
  commitConfig(config);
  if (sleeping) {
    if (displayReady) gfx->fillScreen(0x0000);
    if (sleepMode == SLEEP_MODE_IMAGE) Serial.println("SLEEP");
  }
  Serial.print("CFG_SLEEP_OK\t");
  Serial.println(id);
}

void beginSleepImg(const String &line) {
  const int firstTab = line.indexOf('\t');
  const int secondTab = line.indexOf('\t', firstTab + 1);
  const int thirdTab = line.indexOf('\t', secondTab + 1);
  if (firstTab < 0 || secondTab < 0 || thirdTab < 0) {
    sendSleepImgError("-", "BAD_BEGIN");
    return;
  }
  const String id = line.substring(firstTab + 1, secondTab);
  if (!validTransactionId(id)) {
    sendSleepImgError("-", "BAD_TX");
    return;
  }
  if (receivingConfig || receivingTheme || iconRecvIndex >= 0) {
    sendSleepImgError(id, "BUSY");
    return;
  }
  if (!sleeping) {
    sendSleepImgError(id, "NOT_SLEEPING");
    return;
  }
  if (
    line.substring(secondTab + 1, thirdTab).toInt() != SLEEP_W ||
    line.substring(thirdTab + 1).toInt() != SLEEP_H
  ) {
    sendSleepImgError(id, "BAD_BEGIN");
    return;
  }
  receivingSleepImg = true;
  memset(sleepImgIdBuf, 0, sizeof(sleepImgIdBuf));
  id.toCharArray(sleepImgIdBuf, sizeof(sleepImgIdBuf));
  sleepImgAt = millis();
  sleepImgChunks = 0;
}

void receiveSleepImgRow(const String &line) {
  if (!receivingSleepImg) return;
  const int firstTab = line.indexOf('\t');
  const int secondTab = line.indexOf('\t', firstTab + 1);
  const int thirdTab = line.indexOf('\t', secondTab + 1);
  const int fourthTab = line.indexOf('\t', thirdTab + 1);
  if (firstTab < 0 || secondTab < 0 || thirdTab < 0 || fourthTab < 0) return;
  const String id = line.substring(firstTab + 1, secondTab);
  if (id != sleepImgIdBuf) return;
  const int row = line.substring(secondTab + 1, thirdTab).toInt();
  const int off = line.substring(thirdTab + 1, fourthTab).toInt();
  if (row < 0 || row >= SLEEP_H) return;
  if (off < 0 || off >= SLEEP_W || (off % SLEEP_CHUNK) != 0) return;
  const uint8_t count = static_cast<uint8_t>(
    SLEEP_W - off < SLEEP_CHUNK ? SLEEP_W - off : SLEEP_CHUNK
  );
  const char *hex = line.c_str() + fourthTab + 1;
  if (strlen(hex) != static_cast<size_t>(count) * 4) return;
  for (uint8_t x = 0; x < count; x++) {
    uint16_t pixel = 0;
    for (uint8_t nibble = 0; nibble < 4; nibble++) {
      const int8_t value = hexValue(hex[x * 4 + nibble]);
      if (value < 0) return;
      pixel = static_cast<uint16_t>((pixel << 4) | value);
    }
    paintSleepPixel(static_cast<uint8_t>(off + x), static_cast<uint8_t>(row), pixel);
  }
  sleepImgChunks++;
  sleepImgAt = millis();
}

void endSleepImg(const String &line) {
  if (!receivingSleepImg) return;
  const int firstTab = line.indexOf('\t');
  if (firstTab < 0 || line.indexOf('\t', firstTab + 1) >= 0) return;
  const String id = line.substring(firstTab + 1);
  if (id != sleepImgIdBuf) return;
  receivingSleepImg = false;
  const uint16_t expect = static_cast<uint16_t>(
    SLEEP_H * ((SLEEP_W + SLEEP_CHUNK - 1) / SLEEP_CHUNK)
  );
  if (sleepImgChunks != expect) {
    sendSleepImgError(id, "INCOMPLETE");
    return;
  }
  Serial.print("CFG_SLEEPIMG_OK\t");
  Serial.println(id);
}

void handleSerialLine(const String &line) {
  if (line == "PING") {
    Serial.print("ADECK_PONG\t");
    Serial.println(PROTOCOL_VERSION);
    Serial.println("ADECK_CAPS\tICON");
    Serial.println("ADECK_CAPS\tTHEME");
    Serial.println("ADECK_CAPS\tROTATE");
    Serial.println("ADECK_CAPS\tSLEEP");
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
  if (line.startsWith("CFG_ROTATE\t")) {
    receiveRotate(line);
    return;
  }
  if (line.startsWith("CFG_SLEEP\t")) {
    receiveSleep(line);
    return;
  }
  if (line.startsWith("CFG_SLEEPIMG_BEGIN\t")) {
    beginSleepImg(line);
    return;
  }
  if (line.startsWith("CFG_SLEEPIMG_ROW\t")) {
    receiveSleepImgRow(line);
    return;
  }
  if (line.startsWith("CFG_SLEEPIMG_END\t")) {
    endSleepImg(line);
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
        if (serialLine.startsWith("CFG_") && !serialLine.startsWith("CFG_SLEEPIMG_")) {
          if (sleeping) wakeFromSleep();
          else noteActivity();
        }
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
  if (sleeping) {
    if (!touchLatched) {
      touchLatched = true;
      wakeFromSleep();
    }
    return;
  }
  noteActivity();
  if (touchLatched || !timeReached(now, nextPressAllowed)) return;
  touchLatched = true;

  int touchX = 0;
  int touchY = 0;
  mapTouchToScreen(point, touchX, touchY);
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
  applyDisplayRotation(1);


  loadConfig();
  requestFullRedraw();
  serviceRedraw(millis());
  nextPressAllowed = millis() + 1200;
  lastActivityAt = millis();

  Serial.println("ADECK_CAPS\tICON");
  Serial.println("ADECK_CAPS\tTHEME");
  Serial.println("ADECK_CAPS\tROTATE");
  Serial.println("ADECK_CAPS\tSLEEP");
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

    const uint8_t index = static_cast<uint8_t>(iconRecvIndex);
    iconRecvIndex = -1;
    iconRecvMask = 0;
    sendIconError(lastSyncId, index, "TIMEOUT");
  }

  if (receivingSleepImg && timeReached(now, sleepImgAt + ICON_RECV_TIMEOUT_MS)) {
    receivingSleepImg = false;
    sendSleepImgError(String(sleepImgIdBuf), "TIMEOUT");
  }

  if (
    !sleeping &&
    sleepSeconds > 0 &&
    timeReached(now, lastActivityAt + static_cast<unsigned long>(sleepSeconds) * 1000UL)
  ) {
    enterSleep();
  }

  updatePressedView(now);
  serviceRedraw(now);
  serviceStars(now);
  serviceCat(now);
  readTouch(now);
}
