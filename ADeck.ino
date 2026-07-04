#include <Arduino_GFX_Library.h>
#include <TouchScreen.h>
#include <EEPROM.h>

#define YP A1
#define XM A2
#define YM 7
#define XP 6
#define MINPRESSURE 200
#define MAXPRESSURE 2500

TouchScreen ts = TouchScreen(XP, YP, XM, YM, 300);

Arduino_DataBus *bus = new Arduino_SWPAR8(A2, A3, A1, A0, 8, 9, 2, 3, 4, 5, 6, 7);
Arduino_GFX *gfx = new Arduino_ILI9341(bus, A4, 0, false); 

int bw = 90;
int bh = 90;

struct AppDef {
  int x;
  int y;
  uint16_t col;
  String txt;
};

AppDef app0 = {15, 20, 0x07E0, "W-APP"};
AppDef app1 = {115, 20, 0xF800, "Y-TUBE"};
AppDef app2 = {215, 20, 0x780F, "DISCORD"};
AppDef app3 = {15, 130, 0x03E0, "SPOTIFY"};
AppDef app4 = {115, 130, 0x001F, "VS CODE"};
AppDef app5 = {215, 130, 0xFFE0, "CHROME"};

unsigned long last_ms = 0;

void showGrid() {
  gfx->fillScreen(0x0000); 
  
  gfx->drawRect(app0.x, app0.y, bw, bh, 0xFFFF);
  gfx->fillRect(app0.x + 2, app0.y + 2, bw - 4, bh - 4, app0.col);
  gfx->setTextColor(0x0000); gfx->setTextSize(2);
  gfx->setCursor(app0.x + 10, app0.y + 40); gfx->print(app0.txt);

  gfx->drawRect(app1.x, app1.y, bw, bh, 0xFFFF);
  gfx->fillRect(app1.x + 2, app1.y + 2, bw - 4, bh - 4, app1.col);
  gfx->setCursor(app1.x + 10, app1.y + 40); gfx->print(app1.txt);

  gfx->drawRect(app2.x, app2.y, bw, bh, 0xFFFF);
  gfx->fillRect(app2.x + 2, app2.y + 2, bw - 4, bh - 4, app2.col);
  gfx->setCursor(app2.x + 10, app2.y + 40); gfx->print(app2.txt);

  gfx->drawRect(app3.x, app3.y, bw, bh, 0xFFFF);
  gfx->fillRect(app3.x + 2, app3.y + 2, bw - 4, bh - 4, app3.col);
  gfx->setCursor(app3.x + 10, app3.y + 40); gfx->print(app3.txt);

  gfx->drawRect(app4.x, app4.y, bw, bh, 0xFFFF);
  gfx->fillRect(app4.x + 2, app4.y + 2, bw - 4, bh - 4, app4.col);
  gfx->setCursor(app4.x + 10, app4.y + 40); gfx->print(app4.txt);

  gfx->drawRect(app5.x, app5.y, bw, bh, 0xFFFF);
  gfx->fillRect(app5.x + 2, app5.y + 2, bw - 4, bh - 4, app5.col);
  gfx->setCursor(app5.x + 10, app5.y + 40); gfx->print(app5.txt);
}

void setup() {
  Serial.begin(9600);
  gfx->begin();
  gfx->setRotation(1); 
  showGrid();
  last_ms = millis() + 1500; 
}

void loop() {
  TSPoint p = ts.getPoint();
  
  pinMode(XM, OUTPUT);
  pinMode(YP, OUTPUT);

  if(p.z > MINPRESSURE && p.z < MAXPRESSURE && p.x > 100 && p.x < 950 && p.y > 100 && p.y < 950 && (millis() - last_ms > 800)) {
    
    int tx = map(p.x, 150, 900, 0, 320); 
    int ty = map(p.y, 940, 120, 0, 240);

    bool hit = false;
    AppDef selected;

    if(tx > app0.x && tx < (app0.x + bw) && ty > app0.y && ty < (app0.y + bh)) {
      selected = app0; hit = true;
    } 
    else if(tx > app1.x && tx < (app1.x + bw) && ty > app1.y && ty < (app1.y + bh)) {
      selected = app1; hit = true;
    } 
    else if(tx > app2.x && tx < (app2.x + bw) && ty > app2.y && ty < (app2.y + bh)) {
      selected = app2; hit = true;
    } 
    else if(tx > app3.x && tx < (app3.x + bw) && ty > app3.y && ty < (app3.y + bh)) {
      selected = app3; hit = true;
    } 
    else if(tx > app4.x && tx < (app4.x + bw) && ty > app4.y && ty < (app4.y + bh)) {
      selected = app4; hit = true;
    } 
    else if(tx > app5.x && tx < (app5.x + bw) && ty > app5.y && ty < (app5.y + bh)) {
      selected = app5; hit = true;
    }

    if(hit) {
      gfx->fillScreen(selected.col);
      gfx->setTextColor(0x0000);
      gfx->setTextSize(3);
      gfx->setCursor(100, 110);
      gfx->print(selected.txt);
      
      Serial.println(selected.txt);
      
      delay(800);
      showGrid();
      last_ms = millis();
    }
  }
}