#include <WiFi.h>
#include <HTTPClient.h>
#include <DHT.h>

// Configuration des LEDs
#define led_1 22  // LED 1 connectée au GPIO 22
#define led_2 23  // LED 2 connectée au GPIO 23

// Configuration du capteur DHT22
#define DHTPIN 15     // Capteur DHT22 connecté au GPIO 15
#define DHTTYPE DHT22
DHT dht(DHTPIN, DHTTYPE);

#define databaseURL "oct-stage-default-rtdb.firebaseio.com"
#define apiKey "AIzaSyBOKDMWWuCalx1uIr878NNY3ZIO4HgvAxI"
#define WIFI_SSID "Wokwi-GUEST"
#define WIFI_PASSWORD ""

// Variables pour stocker les valeurs lues depuis Firebase
bool led1State = false;
bool led2State = false;

// Variables pour stocker les valeurs lues depuis le DHT22
float temperature = 0.0;
float humidity = 0.0;

// Déclaration en avant (obligatoire en .cpp, contrairement à .ino)
void getLedStatesFromFirebase();
void readAndSendSensorData();

void setup() {
  Serial.begin(115200);

  pinMode(led_1, OUTPUT);
  pinMode(led_2, OUTPUT);

  dht.begin();

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(1000);
    Serial.println("Connexion au WiFi...");
  }
  Serial.println("Connecté au WiFi");
  // Forcer un serveur DNS public (Google DNS)
  IPAddress dns(8, 8, 8, 8);
  WiFi.config(WiFi.localIP(), WiFi.gatewayIP(), WiFi.subnetMask(), dns);
}

void loop() {
  getLedStatesFromFirebase();
  readAndSendSensorData();

  digitalWrite(led_1, led1State ? HIGH : LOW);
  digitalWrite(led_2    , led2State ? HIGH : LOW);

  delay(2000);
}

void getLedStatesFromFirebase() {
  String url = String("https://") + databaseURL + "/.json?auth=" + apiKey;

  HTTPClient http;
  http.begin(url);
  int httpResponseCode = http.GET();

  if (httpResponseCode > 0) {
    String payload = http.getString();
    Serial.println("Réponse Firebase : " + payload);

    if (payload.indexOf("\"led_1\":true") != -1) {
      led1State = true;
    } else if (payload.indexOf("\"led_1\":false") != -1) {
      led1State = false;
    }

    if (payload.indexOf("\"led_2\":true") != -1) {
      led2State = true;
    } else if (payload.indexOf("\"led_2\":false") != -1) {
      led2State = false;
    }

    Serial.print("État de LED 1 : ");
    Serial.println(led1State);
    Serial.print("État de LED 2 : ");
    Serial.println(led2State);
  } else {
    Serial.println("Échec de la requête vers Firebase !");
    Serial.println("Code de réponse HTTP : " + String(httpResponseCode));
  }

  http.end();
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

  Serial.print("Température : ");
  Serial.print(temperature);
  Serial.print(" °C | Humidité : ");
  Serial.print(humidity);
  Serial.println(" %");

  // Construction du JSON à envoyer vers Firebase
  String payload = "{\"temperature\":" + String(temperature, 1) +
                    ",\"humidity\":" + String(humidity, 1) + "}";

  String url = String("https://") + databaseURL + "/sensors.json?auth=" + apiKey;

  HTTPClient http;
  http.begin(url);
  http.addHeader("Content-Type", "application/json");

  // PUT remplace le contenu de "/sensors" par ce nouveau JSON
  int httpResponseCode = http.PUT(payload);

  if (httpResponseCode > 0) {
    Serial.println("Données du capteur envoyées avec succès.");
  } else {
    Serial.println("Échec de l'envoi des données du capteur !");
    Serial.println("Code de réponse HTTP : " + String(httpResponseCode));
  }

  http.end();

  if (lastHistoryWrite == 0 || millis() - lastHistoryWrite >= 60000) {
    lastHistoryWrite = millis();

    String historyPayload = "{\"temperature\":" + String(temperature, 1) +
                            ",\"humidity\":" + String(humidity, 1) +
                            ",\"timestamp\":{\".sv\":\"timestamp\"}}";
    String historyUrl = String("https://") + databaseURL + "/history.json?auth=" + apiKey;

    HTTPClient historyHttp;
    historyHttp.begin(historyUrl);
    historyHttp.addHeader("Content-Type", "application/json");

    int historyResponseCode = historyHttp.POST(historyPayload);
    if (historyResponseCode == 200) {
      Serial.println("Mesure ajoutée à l'historique Firebase.");
    } else {
      Serial.println("Échec de l'enregistrement de l'historique Firebase.");
      Serial.println("Code de réponse HTTP : " + String(historyResponseCode));
    }

    historyHttp.end();
  }
}