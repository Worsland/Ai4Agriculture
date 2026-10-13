#include <WiFi.h>
#include <HTTPClient.h>
#include <DHT.h>
#include <ESP32Servo.h>

// Configuration des LEDs
#define led_1 22  // LED 1 connectée au GPIO 22
#define led_2 23  // LED 2 connectée au GPIO 23

// Configuration du capteur DHT22
#define DHTPIN 15     // Capteur DHT22 connecté au GPIO 15
#define DHTTYPE DHT22
DHT dht(DHTPIN, DHTTYPE);

// Capteurs analogiques (broches ADC1, compatibles avec le WiFi)
#define SOIL_PIN  34          // Potentiomètre : humidité du sol
#define PH_PIN    35          // Potentiomètre : pH
#define LIGHT_PIN 32          // Capteur de luminosité (sortie AO)
#define LIGHT_INVERTED false  // Passer à true si la lumière se lit à l'envers

// Vanne d'irrigation (servomoteur)
#define SERVO_PIN 18
#define VALVE_CLOSED_ANGLE 0
#define VALVE_OPEN_ANGLE   90
Servo valveServo;

#define databaseURL "oct-stage-default-rtdb.firebaseio.com"
#define apiKey "AIzaSyBOKDMWWuCalx1uIr878NNY3ZIO4HgvAxI"
#define WIFI_SSID "Wokwi-GUEST"
#define WIFI_PASSWORD ""

#define HISTORY_INTERVAL_MS 60000  // une mesure d'historique par minute

// Garde-fous de la vanne (indépendants du serveur Python)
#define VALVE_MAX_OPEN_MS  1200000UL  // 20 min : fermeture forcée (le serveur ferme normalement à 15 min)
#define VALVE_COMM_LOSS_MS  300000UL  // 5 min sans lecture Firebase réussie : fermeture

// --- valve safety begin ---
// Décide si la vanne peut rester ouverte. Logique pure, sans dépendance Arduino.
//  - durée maximale d'ouverture continue ;
//  - perte de liaison avec Firebase (le serveur ne peut alors plus fermer la vanne).
// Après une fermeture forcée, un verrou ignore la commande "ouvrir" tant qu'elle
// n'est pas repassée à false : la vanne ne se rouvre pas toute seule.
struct ValveSafety {
  enum Reason { REASON_NONE, REASON_MAX_OPEN, REASON_COMM_LOSS };
  unsigned long maxOpenMs;
  unsigned long commLossMs;
  bool lockout;
  bool open;
  unsigned long openedAt;
  Reason lastReason;

  ValveSafety(unsigned long maxOpen, unsigned long commLoss)
      : maxOpenMs(maxOpen), commLossMs(commLoss), lockout(false), open(false),
        openedAt(0), lastReason(REASON_NONE) {}

  // command : dernière commande lue dans Firebase ; lastOkMs : instant de la
  // dernière lecture Firebase réussie. Renvoie l'état voulu de la vanne.
  bool update(unsigned long now, bool command, unsigned long lastOkMs) {
    lastReason = REASON_NONE;
    bool desired = command && !lockout;
    if (lockout && !command) lockout = false;  // commande repassée à false : verrou levé
    if (desired && now - lastOkMs > commLossMs) {
      desired = false;
      lockout = true;
      lastReason = REASON_COMM_LOSS;
    }
    if (desired && !open) openedAt = now;
    if (desired && open && now - openedAt > maxOpenMs) {
      desired = false;
      lockout = true;
      lastReason = REASON_MAX_OPEN;
    }
    open = desired;
    return open;
  }
};
// --- valve safety end ---

ValveSafety valveGuard(VALVE_MAX_OPEN_MS, VALVE_COMM_LOSS_MS);

// Variables pour stocker les valeurs lues depuis Firebase
bool led1State = false;
bool led2State = false;
bool valveOpen = false;             // état voulu de la vanne, après les garde-fous
bool valveCommand = false;          // dernière commande lue dans Firebase (/valve/command)
unsigned long lastFirebaseOk = 0;   // dernière lecture Firebase réussie
bool pendingCommandReset = false;   // /valve/command à remettre à false après une fermeture forcée

// Variables pour stocker les mesures des capteurs
float temperature = 0.0;
float humidity = 0.0;
float soilMoisture = 0.0;  // % (0 = sec, 100 = saturé)
float ph = 7.0;            // 0 à 14
float light = 0.0;         // % (0 = nuit, 100 = plein soleil)

// Déclaration en avant (obligatoire en .cpp, contrairement à .ino)
void initValve();
void getCommandsFromFirebase();
void readAndSendSensorData();
void applyValve();
void updateValveSafety();
void flushCommandReset();

// Moyenne de 10 lectures pour lisser le bruit de l'ADC
float readAnalogRaw(int pin) {
  long sum = 0;
  for (int i = 0; i < 10; i++) sum += analogRead(pin);
  return sum / 10.0;
}

// Cherche "clé":true ou "clé":false dans la réponse JSON de Firebase
void parseBool(const String& payload, const char* key, bool& state) {
  String t = String("\"") + key + "\":true";
  String f = String("\"") + key + "\":false";
  if (payload.indexOf(t) != -1) state = true;
  else if (payload.indexOf(f) != -1) state = false;
}

void setup() {
  Serial.begin(115200);

  pinMode(led_1, OUTPUT);
  pinMode(led_2, OUTPUT);

  dht.begin();

  valveServo.setPeriodHertz(50);
  valveServo.attach(SERVO_PIN, 500, 2400);
  valveServo.write(VALVE_CLOSED_ANGLE);

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(1000);
    Serial.println("Connexion au WiFi...");
  }
  Serial.println("Connecté au WiFi");
  // Forcer un serveur DNS public (Google DNS)
  IPAddress dns(8, 8, 8, 8);
  WiFi.config(WiFi.localIP(), WiFi.gatewayIP(), WiFi.subnetMask(), dns);

  initValve();
  lastFirebaseOk = millis();
}

void loop() {
  getCommandsFromFirebase();
  readAndSendSensorData();

  digitalWrite(led_1, led1State ? HIGH : LOW);
  digitalWrite(led_2, led2State ? HIGH : LOW);
  updateValveSafety();
  applyValve();
  flushCommandReset();

  delay(2000);
}

// Au démarrage : vanne fermée, mode automatique
void initValve() {
  HTTPClient http;
  http.begin(String("https://") + databaseURL + "/valve.json?auth=" + apiKey);
  http.addHeader("Content-Type", "application/json");
  http.PUT("{\"mode\":\"auto\",\"command\":false}");
  http.end();
}

// Lit uniquement led_1, led_2, sensors et valve (et non toute la base,
// qui contient l'historique et grossit sans cesse)
void getCommandsFromFirebase() {
  String url = String("https://") + databaseURL +
               "/.json?orderBy=%22$key%22&startAt=%22led_1%22&endAt=%22valve%22&auth=" + apiKey;

  HTTPClient http;
  http.begin(url);
  int httpResponseCode = http.GET();

  if (httpResponseCode > 0) {
    String payload = http.getString();
    parseBool(payload, "led_1", led1State);
    parseBool(payload, "led_2", led2State);
    parseBool(payload, "command", valveCommand);  // /valve/command
    if (httpResponseCode == 200) lastFirebaseOk = millis();

    Serial.print("LED1 : ");
    Serial.print(led1State);
    Serial.print(" | LED2 : ");
    Serial.print(led2State);
    Serial.print(" | Commande vanne : ");
    Serial.println(valveCommand ? "ouvrir" : "fermer");
  } else {
    Serial.println("Échec de la requête vers Firebase !");
    Serial.println("Code de réponse HTTP : " + String(httpResponseCode));
  }

  http.end();
}

// Applique les garde-fous : l'état voulu de la vanne (valveOpen) peut différer
// de la commande lue dans Firebase (valveCommand).
void updateValveSafety() {
  valveOpen = valveGuard.update(millis(), valveCommand, lastFirebaseOk);

  if (valveGuard.lastReason == ValveSafety::REASON_MAX_OPEN) {
    Serial.println("SECURITE : duree maximale d'ouverture atteinte, vanne fermee");
    pendingCommandReset = true;  // remettre aussi la commande Firebase à false
  } else if (valveGuard.lastReason == ValveSafety::REASON_COMM_LOSS) {
    Serial.println("SECURITE : plus de lecture Firebase, vanne fermee");
  }
}

// Après une fermeture forcée pour durée maximale : /valve/command repasse à false
// (réessayé à chaque cycle tant que l'écriture échoue).
void flushCommandReset() {
  if (!pendingCommandReset) return;

  HTTPClient http;
  http.begin(String("https://") + databaseURL + "/valve/command.json?auth=" + apiKey);
  http.addHeader("Content-Type", "application/json");
  int code = http.PUT("false");
  http.end();

  if (code == 200) {
    pendingCommandReset = false;
    Serial.println("Commande de la vanne remise a false dans Firebase.");
  }
}

// Positionne le servo et signale l'état réel de la vanne dans /valve/state
void applyValve() {
  static int reported = -1;
  valveServo.write(valveOpen ? VALVE_OPEN_ANGLE : VALVE_CLOSED_ANGLE);

  if (reported != (int)valveOpen) {
    HTTPClient http;
    http.begin(String("https://") + databaseURL + "/valve/state.json?auth=" + apiKey);
    http.addHeader("Content-Type", "application/json");
    String body = String("{\"open\":") + (valveOpen ? "true" : "false") +
                  ",\"angle\":" + (valveOpen ? VALVE_OPEN_ANGLE : VALVE_CLOSED_ANGLE) + "}";
    if (http.PUT(body) > 0) reported = (int)valveOpen;
    http.end();
    Serial.println(valveOpen ? "Vanne OUVERTE" : "Vanne FERMÉE");
  }
}

void readAndSendSensorData() {
  static unsigned long lastHistoryWrite = 0;

  // Lecture du capteur DHT22
  float h = dht.readHumidity();
  float t = dht.readTemperature(); // en °C

  // Vérifie que la lecture est valide avant d'envoyer
  if (isnan(h) || isnan(t)) {
    Serial.println("Échec de lecture du capteur DHT22 !");
    return;
  }

  temperature = t;
  humidity = h;

  // Lecture des capteurs analogiques (ADC 12 bits : 0 à 4095)
  soilMoisture = readAnalogRaw(SOIL_PIN) * 100.0 / 4095.0;
  ph = readAnalogRaw(PH_PIN) * 14.0 / 4095.0;
  light = readAnalogRaw(LIGHT_PIN) * 100.0 / 4095.0;
  if (LIGHT_INVERTED) light = 100.0 - light;

  Serial.printf("T=%.1f°C  H=%.1f%%  Sol=%.1f%%  pH=%.1f  Lumière=%.1f%%\n",
                temperature, humidity, soilMoisture, ph, light);

  // Construction du JSON à envoyer vers Firebase
  String values = "\"temperature\":" + String(temperature, 1) +
                  ",\"humidity\":" + String(humidity, 1) +
                  ",\"soil_moisture\":" + String(soilMoisture, 1) +
                  ",\"ph\":" + String(ph, 1) +
                  ",\"light\":" + String(light, 1);

  HTTPClient http;
  http.begin(String("https://") + databaseURL + "/sensors.json?auth=" + apiKey);
  http.addHeader("Content-Type", "application/json");

  // PUT remplace le contenu de "/sensors" par ce nouveau JSON
  int httpResponseCode = http.PUT("{" + values + "}");

  if (httpResponseCode > 0) {
    Serial.println("Données du capteur envoyées avec succès.");
  } else {
    Serial.println("Échec de l'envoi des données du capteur !");
    Serial.println("Code de réponse HTTP : " + String(httpResponseCode));
  }

  http.end();

  // Historique : une nouvelle entrée par minute (POST ajoute sans écraser)
  if (lastHistoryWrite == 0 || millis() - lastHistoryWrite >= HISTORY_INTERVAL_MS) {
    lastHistoryWrite = millis();

    HTTPClient historyHttp;
    historyHttp.begin(String("https://") + databaseURL + "/history.json?auth=" + apiKey);
    historyHttp.addHeader("Content-Type", "application/json");

    int historyResponseCode = historyHttp.POST("{" + values + ",\"timestamp\":{\".sv\":\"timestamp\"}}");
    if (historyResponseCode == 200) {
      Serial.println("Mesure ajoutée à l'historique Firebase.");
    } else {
      Serial.println("Échec de l'enregistrement de l'historique Firebase.");
      Serial.println("Code de réponse HTTP : " + String(historyResponseCode));
    }

    historyHttp.end();
  }
}