// Door camera firmware for the XIAO ESP32S3 Sense and AI-Thinker ESP32-CAM.
//
//   http://door-cam.local/         test page
//   http://door-cam.local/capture  one JPEG
//   http://door-cam.local/status   JSON health info
//   http://door-cam.local/control?framesize=vga&quality=12&vflip=1&hmirror=0
//   http://door-cam.local:81/stream  MJPEG, up to 4 viewers at once
//   http://door-cam.local:82/audio   16 kHz mono PCM, training builds only
//
// There is no authentication, so keep this on a trusted network and never
// port-forward it.

#include <Arduino.h>
#include <ESPmDNS.h>
#include <WiFi.h>
#include <WiFiManager.h>

#include "esp_camera.h"
#include "esp_heap_caps.h"
#include "freertos/semphr.h"
#include "esp_http_server.h"

#ifdef AUDIO_STREAM
#include "driver/i2s_pdm.h"
#endif

static const char *HOSTNAME = "door-cam";
static const char *SETUP_AP = "door-cam-setup";

static camera_config_t cameraConfig() {
  camera_config_t c = {};
#ifdef BOARD_XIAO_S3_SENSE
  c.pin_pwdn = -1;
  c.pin_reset = -1;
  c.pin_xclk = 10;
  c.pin_sccb_sda = 40;
  c.pin_sccb_scl = 39;
  c.pin_d7 = 48;
  c.pin_d6 = 11;
  c.pin_d5 = 12;
  c.pin_d4 = 14;
  c.pin_d3 = 16;
  c.pin_d2 = 18;
  c.pin_d1 = 17;
  c.pin_d0 = 15;
  c.pin_vsync = 38;
  c.pin_href = 47;
  c.pin_pclk = 13;
#else  // AI-Thinker ESP32-CAM
  c.pin_pwdn = 32;
  c.pin_reset = -1;
  c.pin_xclk = 0;
  c.pin_sccb_sda = 26;
  c.pin_sccb_scl = 27;
  c.pin_d7 = 35;
  c.pin_d6 = 34;
  c.pin_d5 = 39;
  c.pin_d4 = 36;
  c.pin_d3 = 21;
  c.pin_d2 = 19;
  c.pin_d1 = 18;
  c.pin_d0 = 5;
  c.pin_vsync = 25;
  c.pin_href = 23;
  c.pin_pclk = 22;
#endif
  c.xclk_freq_hz = 20000000;
  c.ledc_timer = LEDC_TIMER_0;
  c.ledc_channel = LEDC_CHANNEL_0;
  c.pixel_format = PIXFORMAT_JPEG;
  c.frame_size = FRAMESIZE_VGA;
  c.jpeg_quality = 12;
  c.fb_count = 2;
  c.fb_location = CAMERA_FB_IN_PSRAM;
  c.grab_mode = CAMERA_GRAB_LATEST;  // live view: drop stale frames
  return c;
}

static const int MAX_STREAM_CLIENTS = 4;
static const int MAX_CAPTURE_FAILURES = 5;

static volatile uint32_t framesSent = 0;
static volatile int streamClients = 0;

// One task grabs each camera frame and shares it with every viewer through
// reference-counted copies in PSRAM, so a slow or dead connection can't hold up
// the others.
struct SharedFrame {
  uint8_t *buf;
  size_t len;
  uint32_t seq;
  int refs;
};

static SemaphoreHandle_t frameLock;
static SharedFrame *latestFrame = nullptr;
static volatile int viewers = 0;

static void releaseLocked(SharedFrame *frame) {
  if (frame && --frame->refs == 0) {
    heap_caps_free(frame->buf);
    heap_caps_free(frame);
  }
}

static void frameRelease(SharedFrame *frame) {
  xSemaphoreTake(frameLock, portMAX_DELAY);
  releaseLocked(frame);
  xSemaphoreGive(frameLock);
}

static uint32_t latestSeq() {
  xSemaphoreTake(frameLock, portMAX_DELAY);
  uint32_t seq = latestFrame ? latestFrame->seq : 0;
  xSemaphoreGive(frameLock);
  return seq;
}

// Waits for a frame newer than afterSeq. Returns nullptr on timeout.
static SharedFrame *frameAcquire(uint32_t afterSeq, TickType_t timeout) {
  TickType_t start = xTaskGetTickCount();
  for (;;) {
    xSemaphoreTake(frameLock, portMAX_DELAY);
    SharedFrame *frame = latestFrame;
    if (frame && frame->seq > afterSeq) {
      frame->refs++;
      xSemaphoreGive(frameLock);
      return frame;
    }
    xSemaphoreGive(frameLock);
    if (xTaskGetTickCount() - start >= timeout) return nullptr;
    vTaskDelay(pdMS_TO_TICKS(5));
  }
}

static void viewerAdd() {
  xSemaphoreTake(frameLock, portMAX_DELAY);
  viewers = viewers + 1;
  xSemaphoreGive(frameLock);
}

// Claims a stream slot. False when all are taken.
static bool streamSlotClaim() {
  xSemaphoreTake(frameLock, portMAX_DELAY);
  bool ok = streamClients < MAX_STREAM_CLIENTS;
  if (ok) streamClients = streamClients + 1;
  xSemaphoreGive(frameLock);
  return ok;
}

static void streamSlotRelease() {
  xSemaphoreTake(frameLock, portMAX_DELAY);
  streamClients = streamClients - 1;
  xSemaphoreGive(frameLock);
}

static void viewerRemove() {
  xSemaphoreTake(frameLock, portMAX_DELAY);
  viewers = viewers - 1;
  xSemaphoreGive(frameLock);
}

// Only captures while someone is watching.
static void captureTask(void *) {
  uint32_t seq = 0;
  int failures = 0;
  for (;;) {
    if (viewers <= 0) {
      vTaskDelay(pdMS_TO_TICKS(20));
      continue;
    }
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) {
      if (++failures >= MAX_CAPTURE_FAILURES) {
        Serial.println("Camera keeps failing. Restarting.");
        ESP.restart();
      }
      vTaskDelay(pdMS_TO_TICKS(10));
      continue;
    }
    failures = 0;
    SharedFrame *frame = (SharedFrame *)heap_caps_malloc(sizeof(SharedFrame), MALLOC_CAP_SPIRAM);
    uint8_t *buf = (uint8_t *)heap_caps_malloc(fb->len, MALLOC_CAP_SPIRAM);
    if (!frame || !buf) {
      heap_caps_free(frame);
      heap_caps_free(buf);
      esp_camera_fb_return(fb);
      Serial.println("Out of PSRAM for a frame copy");
      vTaskDelay(pdMS_TO_TICKS(50));
      continue;
    }
    memcpy(buf, fb->buf, fb->len);
    *frame = {buf, fb->len, ++seq, 1};
    esp_camera_fb_return(fb);

    xSemaphoreTake(frameLock, portMAX_DELAY);
    SharedFrame *old = latestFrame;
    latestFrame = frame;
    releaseLocked(old);
    xSemaphoreGive(frameLock);
  }
}

static const char PAGE[] = R"html(<!doctype html>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Door cam</title>
<style>body{font:16px system-ui;margin:16px;background:#111;color:#eee}img{max-width:100%}a{color:#8cf}</style>
<h1>Door cam</h1>
<img id=s alt="live stream">
<p><a href=/capture>Snapshot</a> · <a href=/status>Status</a></p>
<script>s.src=location.protocol+'//'+location.hostname+':81/stream'</script>
)html";

static esp_err_t pageHandler(httpd_req_t *req) {
  httpd_resp_set_type(req, "text/html");
  return httpd_resp_send(req, PAGE, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t captureHandler(httpd_req_t *req) {
  viewerAdd();
  SharedFrame *frame = frameAcquire(latestSeq(), pdMS_TO_TICKS(3000));
  viewerRemove();
  if (!frame) {
    httpd_resp_send_500(req);
    return ESP_FAIL;
  }
  httpd_resp_set_type(req, "image/jpeg");
  httpd_resp_set_hdr(req, "Cache-Control", "no-store");
  esp_err_t res = httpd_resp_send(req, (const char *)frame->buf, frame->len);
  frameRelease(frame);
  return res;
}

static esp_err_t statusHandler(httpd_req_t *req) {
  sensor_t *s = esp_camera_sensor_get();
  char json[256];
  snprintf(json, sizeof(json),
           "{\"ip\":\"%s\",\"rssi\":%d,\"uptime_s\":%lu,\"free_heap\":%u,"
           "\"free_psram\":%u,\"frames_sent\":%lu,\"stream_clients\":%d,"
           "\"framesize\":%d,\"quality\":%d}",
           WiFi.localIP().toString().c_str(), WiFi.RSSI(),
           (unsigned long)(millis() / 1000), (unsigned)ESP.getFreeHeap(),
           (unsigned)ESP.getFreePsram(), (unsigned long)framesSent,
           streamClients, s ? s->status.framesize : -1,
           s ? s->status.quality : -1);
  httpd_resp_set_type(req, "application/json");
  return httpd_resp_send(req, json, HTTPD_RESP_USE_STRLEN);
}

static int frameSizeFromName(const char *name) {
  if (!strcmp(name, "qvga")) return FRAMESIZE_QVGA;
  if (!strcmp(name, "vga")) return FRAMESIZE_VGA;
  if (!strcmp(name, "svga")) return FRAMESIZE_SVGA;
  if (!strcmp(name, "xga")) return FRAMESIZE_XGA;
  if (!strcmp(name, "hd")) return FRAMESIZE_HD;
  return -1;
}

static esp_err_t controlHandler(httpd_req_t *req) {
  char query[96], value[16];
  sensor_t *s = esp_camera_sensor_get();
  if (!s || httpd_req_get_url_query_str(req, query, sizeof(query)) != ESP_OK) {
    httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "missing settings");
    return ESP_FAIL;
  }
  if (httpd_query_key_value(query, "framesize", value, sizeof(value)) == ESP_OK) {
    int size = frameSizeFromName(value);
    if (size < 0) {
      httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "unknown framesize");
      return ESP_FAIL;
    }
    s->set_framesize(s, (framesize_t)size);
  }
  if (httpd_query_key_value(query, "quality", value, sizeof(value)) == ESP_OK)
    s->set_quality(s, constrain(atoi(value), 4, 63));
  if (httpd_query_key_value(query, "vflip", value, sizeof(value)) == ESP_OK)
    s->set_vflip(s, atoi(value) ? 1 : 0);
  if (httpd_query_key_value(query, "hmirror", value, sizeof(value)) == ESP_OK)
    s->set_hmirror(s, atoi(value) ? 1 : 0);
  return httpd_resp_sendstr(req, "ok");
}

#define BOUNDARY "doorcamframe"

// Each viewer gets its own task, so several can watch at once.
static void streamClientTask(void *arg) {
  httpd_req_t *req = (httpd_req_t *)arg;
  httpd_resp_set_type(req, "multipart/x-mixed-replace;boundary=" BOUNDARY);
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  viewerAdd();

  char header[64];
  uint32_t lastSeq = latestSeq();
  esp_err_t res = ESP_OK;
  while (res == ESP_OK) {
    SharedFrame *frame = frameAcquire(lastSeq, pdMS_TO_TICKS(3000));
    if (!frame) {
      Serial.println("No camera frame for 3s, closing a viewer");
      break;
    }
    lastSeq = frame->seq;
    int n = snprintf(header, sizeof(header),
                     "\r\n--" BOUNDARY "\r\nContent-Type: image/jpeg\r\n"
                     "Content-Length: %u\r\n\r\n",
                     (unsigned)frame->len);
    res = httpd_resp_send_chunk(req, header, n);
    if (res == ESP_OK)
      res = httpd_resp_send_chunk(req, (const char *)frame->buf, frame->len);
    frameRelease(frame);
    if (res == ESP_OK) framesSent = framesSent + 1;
  }

  viewerRemove();
  streamSlotRelease();
  httpd_req_async_handler_complete(req);
  vTaskDelete(nullptr);
}

static esp_err_t streamHandler(httpd_req_t *req) {
  if (!streamSlotClaim()) {
    httpd_resp_set_status(req, "503 Service Unavailable");
    return httpd_resp_sendstr(req, "too many viewers\n");
  }
  httpd_req_t *asyncReq = nullptr;
  esp_err_t err = httpd_req_async_handler_begin(req, &asyncReq);
  if (err == ESP_OK && xTaskCreate(streamClientTask, "stream_client", 4096, asyncReq, 5, nullptr) != pdPASS) {
    httpd_req_async_handler_complete(asyncReq);
    err = ESP_ERR_NO_MEM;
  }
  if (err != ESP_OK) streamSlotRelease();
  return err;
}

#ifdef AUDIO_STREAM
static i2s_chan_handle_t micChannel = nullptr;

static bool startMic() {
  i2s_chan_config_t chan = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  if (i2s_new_channel(&chan, nullptr, &micChannel) != ESP_OK) return false;
  i2s_pdm_rx_config_t pdm = {};
  pdm.clk_cfg = I2S_PDM_RX_CLK_DEFAULT_CONFIG(16000);
  pdm.slot_cfg = I2S_PDM_RX_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO);
  pdm.gpio_cfg.clk = GPIO_NUM_42;
  pdm.gpio_cfg.din = GPIO_NUM_41;
  return i2s_channel_init_pdm_rx_mode(micChannel, &pdm) == ESP_OK &&
         i2s_channel_enable(micChannel) == ESP_OK;
}

static esp_err_t audioHandler(httpd_req_t *req) {
  static int16_t samples[1024];
  httpd_resp_set_type(req, "audio/L16;rate=16000;channels=1");
  esp_err_t res = ESP_OK;
  while (res == ESP_OK) {
    size_t bytes = 0;
    if (i2s_channel_read(micChannel, samples, sizeof(samples), &bytes, 1000) != ESP_OK) {
      Serial.println("Mic read failed");
      return ESP_FAIL;
    }
    res = httpd_resp_send_chunk(req, (const char *)samples, bytes);
  }
  return res;
}
#endif

static void addRoute(httpd_handle_t server, const char *uri,
                     esp_err_t (*handler)(httpd_req_t *)) {
  httpd_uri_t route = {};
  route.uri = uri;
  route.method = HTTP_GET;
  route.handler = handler;
  httpd_register_uri_handler(server, &route);
}

// Streams run on their own server so they can't get in the way of the control pages.
static bool startServers() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  httpd_handle_t web = nullptr, stream = nullptr;

  config.server_port = 80;
  config.ctrl_port = 32768;
  if (httpd_start(&web, &config) != ESP_OK) return false;
  addRoute(web, "/", pageHandler);
  addRoute(web, "/capture", captureHandler);
  addRoute(web, "/status", statusHandler);
  addRoute(web, "/control", controlHandler);

  config.server_port = 81;
  config.ctrl_port = 32769;
  config.max_open_sockets = MAX_STREAM_CLIENTS + 1;
  config.send_wait_timeout = 2;  // free a dead viewer's slot quickly
  if (httpd_start(&stream, &config) != ESP_OK) return false;
  addRoute(stream, "/stream", streamHandler);

#ifdef AUDIO_STREAM
  httpd_handle_t audio = nullptr;
  config.server_port = 82;
  config.ctrl_port = 32770;
  if (httpd_start(&audio, &config) != ESP_OK) return false;
  addRoute(audio, "/audio", audioHandler);
#endif
  return true;
}

void setup() {
  Serial.begin(115200);
  Serial.println("\nDoor cam starting");

  if (!psramFound()) Serial.println("Warning: no PSRAM found");
  camera_config_t config = cameraConfig();
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed: 0x%x. Check the ribbon cable. Restarting.\n", err);
    delay(5000);
    ESP.restart();
  }
  frameLock = xSemaphoreCreateMutex();
  xTaskCreatePinnedToCore(captureTask, "capture", 4096, nullptr, 6, nullptr, 1);
#ifdef BOARD_XIAO_S3_SENSE
  // The OV3660 is mirrored natively.
  esp_camera_sensor_get()->set_hmirror(esp_camera_sensor_get(), 1);
#endif
#ifdef AUDIO_STREAM
  if (!startMic()) Serial.println("Warning: mic failed to start");
#endif

  WiFi.mode(WIFI_STA);
  WiFi.setHostname(HOSTNAME);
  WiFi.setSleep(false);  // power save causes stutter on the stream

  // Credentials live in the board's flash, set from a phone on first boot.
  WiFiManager manager;
  manager.setConfigPortalTimeout(300);
  if (!manager.autoConnect(SETUP_AP)) {
    Serial.println("WiFi setup timed out. Restarting.");
    ESP.restart();
  }

  if (MDNS.begin(HOSTNAME)) MDNS.addService("http", "tcp", 80);
  if (!startServers()) {
    Serial.println("Could not start web servers. Restarting.");
    ESP.restart();
  }
  Serial.printf("Ready: http://%s/ or http://%s.local/\n",
                WiFi.localIP().toString().c_str(), HOSTNAME);
}

void loop() {
  static uint32_t lostSince = 0;
  if (WiFi.status() == WL_CONNECTED) {
    lostSince = 0;
  } else if (lostSince == 0) {
    lostSince = millis();
  } else if (millis() - lostSince > 60000) {
    Serial.println("WiFi lost for 60s. Restarting.");
    ESP.restart();
  }
  delay(1000);
}
