import serial
import subprocess
import os

port = 'COM5'
baud = 9600

cmds = {
    "W-APP":"start whatsapp:", 
    "Y-TUBE":"start brave --app=https://youtube.com",
    "DISCORD":f"C:\\Users\\{os.getlogin()}\\AppData\\Local\\Discord\\Update.exe --processStart Discord.exe",
    "SPOTIFY":"start spotify:",
    "VS CODE":"code",
    "CHROME":"start chrome"
}

try:
    s = serial.Serial(port, baud)
    print("running on " + port)
    
    while 1:
        if s.in_waiting > 0:
            data = s.readline().decode('utf-8').strip()
            
            if data in cmds:
                print("exec: " + data)
                subprocess.Popen(cmds[data], shell=True)
                
except Exception as err:
    print(err)