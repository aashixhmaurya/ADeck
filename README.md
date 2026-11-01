# adeck

a local stream deck for the desk but it is an arduino uno r4 wifi with a 2.4 inch ili9341 touch screen. you set six keys in a web app on your pc then the board shows them and when you tap a key the pc runs that app or command.

you can make a few profiles switch themes and pick a sleep screen. the active setup is saved on the board in eeprom so it comes back after unplug or reset.

there is also a hosted web page for people who do not have the board. they can press try anyway and look around. the real pad still needs the uno on usb.

## heres the demo

https://youtu.be/hYH821wEFZI

## install

- download the zip and extract the folder to somewhere easy like the desktop
- open the extracted folder you should see setup adeck.bat and start adeck.bat
- plug in the uno r4 wifi with a data usb cable and close arduino serial monitor if it is open
- double click setup adeck.bat and wait until it says adeck is ready
- setup makes the python stuff flashes the board if needed and puts an adeck icon on the desktop
- after that just open the adeck desktop icon or start adeck.bat you do not run setup every time
- if something fails open adeck-control.bat and pick check system or install / repair

## how to use

- after install the web app opens at http://127.0.0.1:8765
- pick a profile on the left then click the slot you want to fill. there are six slots top left is 1 then across and down
- the app list is fetched from this windows pc so installed apps show up on their own. click add and pick one
- you can also type a command yourself like notepad or explorer or git status
- git commands work the same way. put git status git add git commit git push or git pull on a slot then tap that key on the tft
- set the label you want on the screen and a color if you like
- press save so the board gets the new layout
- tap that key on the tft and the pc runs it
- tft theme is only the board background. space has slow stars cat walks the gaps around the keys and bee flies then sits on an icon
- appearance is only the web page colors not the tft
- sleep is on the settings page. pick how long to wait then black screen or a custom image
- if you open the hosted site and see service is not running press try anyway to explore the ui

## tft themes

- space is the default. dark screen with drifting stars behind the keys
- cat is a small cat that walks the empty space around the keys
- bee is a honeybee that flies around then lands on top of an app icon
- pick the theme on the dashboard then apply and save so the board uses it

## appearance

- this only changes the web app look. the tft stays on the theme you picked above
- there are four looks classic red and red code cactus and oled
- classic is the normal adeck colors
- red and red is dark panels with red accents
- code cactus is cream page with rose selection
- oled is pure black and dark blue and it stays dark
- the idea for these web looks came from the hackatime website

## sleep

- the tft goes to sleep after you leave it alone. you can pick 30 seconds 1 minute 5 minutes or never
- touch anywhere on the screen to wake it
- black screen is the default. the display just goes black
- custom image lets you add a png or jpg. it is resized small and shown when the pad sleeps
- save settings after you pick the image so the board has it

## hardware used

- windows 10 or 11
- arduino uno r4 wifi
- 2.4 inch ili9341 tft with resistive touch
- a data usb cable not a charge only one

## features

- six keys in a 3 by 2 layout
- more than one profile saved on the pc
- windows apps are fetched automatically so you can drop them on a slot
- git status add commit push and pull can sit on a key and run from a tap
- any other command you type also works
- labels colors and icons sync to the tft over usb
- tft background colour is customizable so you can pick whatever you want
- three tft themes space cat and bee
- four web appearances classic red and red code cactus and oled
- sleep timeout with black screen or a custom image
- rotate the display if you want
- local web app no internet needed
- hosted page so others can look without a board
- settings stay in appdata not in the repo
- board config stays in eeprom after restart

