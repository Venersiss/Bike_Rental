#include <SPI.h>
#include <MFRC522.h>

#define SS_PIN 10
#define RST_PIN 9
#define RELAY_PIN 7
#define BUZZER_PIN 6
#define GREEN_LED_PIN 5

MFRC522 rfid(SS_PIN, RST_PIN);

byte allowedUID[][4] = {
  {0x54, 0x96, 0x2C, 0xDB},  // Your registered card
  {0xA1, 0xB2, 0xC3, 0xD4}   // Example UID 2
};
const int numberOfUIDs = sizeof(allowedUID) / sizeof(allowedUID[0]);

// Solenoid control variables
unsigned long unlockStartTime = 0;
bool isUnlocked = false;
const unsigned long unlockDuration = 3000;  // 3 seconds unlock time

void setup() {
  Serial.begin(9600);
  SPI.begin();
  rfid.PCD_Init();

  pinMode(RELAY_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(GREEN_LED_PIN, OUTPUT);

  // Initialize outputs
  digitalWrite(RELAY_PIN, LOW);    // Start in locked position
  digitalWrite(BUZZER_PIN, LOW);
  digitalWrite(GREEN_LED_PIN, LOW);

  Serial.println("System ready. Scan RFID to check access.");
}

void loop() {
  // Handle automatic relocking
  if (isUnlocked && (millis() - unlockStartTime >= unlockDuration)) {
    lock();
  }

  // Check for new cards
  if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) {
    return;
  }

  // Print UID for debugging
  Serial.print("Scanned UID: ");
  for (byte i = 0; i < rfid.uid.size; i++) {
    Serial.print(rfid.uid.uidByte[i], HEX);
    Serial.print(" ");
  }
  Serial.println();

  if (isAuthorized(rfid.uid.uidByte)) {
    grantAccess();
  } else {
    denyAccess();
  }

  rfid.PICC_HaltA();  // Stop communication
}

void grantAccess() {
  Serial.println("Access Granted");
  digitalWrite(GREEN_LED_PIN, HIGH);
  unlock();
  delay(500);  // Small delay to prevent multiple reads
}

void denyAccess() {
  Serial.println("Access Denied");
  digitalWrite(BUZZER_PIN, HIGH);
  delay(2000);
  digitalWrite(BUZZER_PIN, LOW);
}

void unlock() {
  digitalWrite(RELAY_PIN, HIGH);  // Energize relay to unlock
  isUnlocked = true;
  unlockStartTime = millis();
  Serial.println("Solenoid UNLOCKED");
}

void lock() {
  digitalWrite(RELAY_PIN, LOW);   // De-energize relay to lock
  digitalWrite(GREEN_LED_PIN, LOW);
  isUnlocked = false;
  Serial.println("Solenoid LOCKED");
}

bool isAuthorized(byte *scannedUID) {
  for (int i = 0; i < numberOfUIDs; i++) {
    bool match = true;
    for (int j = 0; j < 4; j++) {
      if (scannedUID[j] != allowedUID[i][j]) {
        match = false;
        break;
      }
    }
    if (match) return true;
  }
  return false;
}