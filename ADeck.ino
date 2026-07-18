#include <Arduino_GFX_Library.h>
#include <TouchScreen.h>

#define YP A3
#define XM A2
#define YM 9
#define XP 8

#define MINPRESSURE 5
#define MAXPRESSURE 3500

// display calibration vals
#define TS_MINX 150
#define TS_MAXX 900
#define TS_MINY 120
#define TS_MAXY 920

TouchScreen ts = TouchScreen(XP, YP, XM, YM, 300);

// sw spi config
Arduino_DataBus *bus = new Arduino_SWPAR8(A2, A3, A1, A0, 8, 9, 2, 3, 4, 5, 6, 7);
Arduino_GFX *gfx = new Arduino_ILI9341(bus, A4, 0, false); 

const int APP_W = 90;
const int APP_H = 90;
const int TOTAL_APPS = 6;

struct AppItem {
  int startX;
  int startY;
  uint16_t themeCol;
  String appLabel;
};

AppItem myApps[TOTAL_APPS] = {
  {15,  20,  0x07E0, "W-APP"},
  {115, 20,  0xF800, "Y-TUBE"},
  {215, 20,  0x780F, "DISCORD"},
  {15,  130, 0x03E0, "SPOTIFY"},
  {115, 130, 0x001F, "VS CODE"},
  {215, 130, 0xFFE0, "CHROME"}
};

unsigned long debounceTimer = 0; 

void renderIcon(int idx) {
  gfx->drawRect(myApps[idx].startX, myApps[idx].startY, APP_W, APP_H, 0xFFFF);
  gfx->fillRect(myApps[idx].startX + 2, myApps[idx].startY + 2, APP_W - 4, APP_H - 4, myApps[idx].themeCol);

  gfx->setTextColor(0x0000); 
  gfx->setTextSize(2);
  gfx->setCursor(myApps[idx].startX + 10, myApps[idx].startY + 40);
  gfx->print(myApps[idx].appLabel);
}

void loadHomeScreen() {
  gfx->fillScreen(0x0000); 
  for(int j = 0; j < TOTAL_APPS; j++) {
    renderIcon(j);
  }
}

void setup() {
  Serial.begin(9600);
  gfx->begin();
  gfx->setRotation(1); 
  
  loadHomeScreen();
  
  debounceTimer = millis() + 1500; 
}

void loop() {
  TSPoint p = ts.getPoint();
  
  // fix: touch lib changes pins to input, resetting to output to prevent white screen
  pinMode(XM, OUTPUT);
  pinMode(YP, OUTPUT);

  if(p.z > MINPRESSURE && p.z < MAXPRESSURE && (millis() - debounceTimer > 300)) {
    
    // x and y are swapped for landscape orientation
    int mappedX = map(p.y, TS_MINY, TS_MAXY, 320, 0); 
    int mappedY = map(p.x, TS_MINX, TS_MAXX, 240, 0);

    for(int k = 0; k < TOTAL_APPS; k++) {
      
      bool hitX = (mappedX > myApps[k].startX) && (mappedX < (myApps[k].startX + APP_W));
      bool hitY = (mappedY > myApps[k].startY) && (mappedY < (myApps[k].startY + APP_H));

      if(hitX && hitY) {
          gfx->fillScreen(myApps[k].themeCol);
          gfx->setTextColor(0x0000);
          gfx->setTextSize(3);
          gfx->setCursor(100, 110);
          gfx->print(myApps[k].appLabel);
          
          Serial.println(myApps[k].appLabel);
          
          delay(800); 
          loadHomeScreen();
          
          debounceTimer = millis();
          break; 
      }
    }
  }
}