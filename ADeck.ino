#include <Arduino_GFX_Library.h>
#include <TouchScreen.h>

#define YP A1
#define XM A2
#define YM 7
#define XP 6
#define MINPRESSURE 200 
#define MAXPRESSURE 3000

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

AppDef apps[6] = {
  {15, 20, 0x07E0, "W-APP"},
  {115,20,0xF800,"Y-TUBE"},
  {215, 20, 0x780F, "DISCORD"},
  {15,130,0x03E0,"SPOTIFY"},
  {115, 130, 0x001F, "VS CODE"},
  {215,130,0xFFE0,"CHROME"}
};

int state = 0; 
unsigned long last_ms = 0;

void showGrid() {
  gfx->fillScreen(0x0000); 
  
  for(int i=0; i<6; i++) {
    gfx->drawRect(apps[i].x, apps[i].y, bw, bh, 0xFFFF);
    gfx->fillRect(apps[i].x + 2, apps[i].y + 2, bw - 4, bh - 4, apps[i].col);

    gfx->setTextColor(0x0000); 
    gfx->setTextSize(2);
    gfx->setCursor(apps[i].x + 10, apps[i].y + 40);
    gfx->print(apps[i].txt);
  }
}

void setup() {
  Serial.begin(9600);
  gfx->begin();
  gfx->setRotation(1); 
  showGrid();
}

void loop() {
  TSPoint p = ts.getPoint();
  
  pinMode(XM, OUTPUT);
  pinMode(YP, OUTPUT);

  if(p.z > MINPRESSURE && p.z < MAXPRESSURE && (millis() - last_ms > 600)) {
    
    int tx = map(p.x, 150, 900, 0, 320); 
    int ty = map(p.y, 940, 120, 0, 240);

    Serial.print("Mapped X: "); 
    Serial.print(tx);
    Serial.print(" | Mapped Y: "); 
    Serial.println(ty);

    if(state == 0) {
      for(int i=0; i<6; i++) {
        if(tx > apps[i].x && tx < (apps[i].x + bw) && ty > apps[i].y && ty < (apps[i].y + bh)) {
            state = i + 1;
            gfx->fillScreen(apps[i].col);
            
            gfx->setTextColor(0x0000);
            gfx->setTextSize(3);
            gfx->setCursor(100, 110);
            gfx->print(apps[i].txt);
            
            last_ms = millis();
            break;
        }
      }
    } else {
      state = 0;
      showGrid();
      last_ms = millis();
    }
  }
}