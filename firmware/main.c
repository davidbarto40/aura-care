/*
 * Aura-Care · firmware/main.c
 * ────────────────────────────
 * Firmware ESP32-S3 (ESP-IDF).
 * Se conecta al WiFi, activa el callback CSI y envía
 * datagramas UDP al servidor Aura-Care.
 *
 * Formato del datagrama (little-endian):
 *   [uint32  magic = 0xABCD1234]
 *   [uint16  num_subcarriers   ]
 *   [int16   real_0, imag_0    ]  ← subportadora 0
 *   [int16   real_1, imag_1    ]  ← subportadora 1
 *   ...
 *
 * Compilar con:  idf.py build
 * Flashear con:  idf.py -p /dev/ttyUSB0 flash monitor
 */

#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "nvs_flash.h"
#include "lwip/sockets.h"

/* ── Configuración — editar por placa ───────────────────────────────────── */
#define WIFI_SSID     "TU_RED_WIFI"
#define WIFI_PASS     "TU_CONTRASEÑA"
#define SERVER_IP     "192.168.1.200"   /* IP del servidor Python          */
#define SERVER_PORT   5005
#define MAGIC_HEADER  0xABCD1234u

static const char *TAG = "aura-care";
static int udp_sock = -1;
static struct sockaddr_in server_addr;

/* ── Callback CSI ────────────────────────────────────────────────────────── */
static void csi_callback(void *ctx, wifi_csi_info_t *info)
{
    if (!info || info->len == 0) return;

    uint16_t num_sc  = (uint16_t)(info->len / 2);   /* 2 bytes por subportadora */
    size_t   buf_len = 4 + 2 + (size_t)num_sc * 4;

    uint8_t *buf = malloc(buf_len);
    if (!buf) return;

    /* Magic header */
    uint32_t magic = MAGIC_HEADER;
    memcpy(buf, &magic, 4);

    /* Número de subportadoras */
    memcpy(buf + 4, &num_sc, 2);

    /* Datos IQ: expandir int8 → int16 para que Python lea "<i2" */
    int8_t  *raw  = info->buf;
    int16_t *dest = (int16_t *)(buf + 6);
    for (int i = 0; i < num_sc * 2; i++) {
        dest[i] = (int16_t)raw[i];
    }

    sendto(udp_sock, buf, buf_len, 0,
           (struct sockaddr *)&server_addr, sizeof(server_addr));
    free(buf);
}

/* ── Manejador de eventos WiFi ───────────────────────────────────────────── */
static void wifi_event_handler(void *arg, esp_event_base_t base,
                               int32_t event_id, void *event_data)
{
    if (base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();

    } else if (base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "Desconectado — reconectando…");
        esp_wifi_connect();

    } else if (base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *e = (ip_event_got_ip_t *)event_data;
        ESP_LOGI(TAG, "IP: " IPSTR, IP2STR(&e->ip_info.ip));

        /* Crear socket UDP */
        udp_sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
        memset(&server_addr, 0, sizeof(server_addr));
        server_addr.sin_family = AF_INET;
        server_addr.sin_port   = htons(SERVER_PORT);
        inet_pton(AF_INET, SERVER_IP, &server_addr.sin_addr);

        /* Configurar y activar CSI */
        wifi_csi_config_t csi_cfg = {
            .lltf_en           = true,
            .htltf_en          = true,
            .stbc_htltf2_en    = true,
            .ltf_merge_en      = true,
            .channel_filter_en = true,
            .manu_scale        = false,
        };
        esp_wifi_set_csi_config(&csi_cfg);
        esp_wifi_set_csi_rx_cb(csi_callback, NULL);
        esp_wifi_set_csi(true);

        ESP_LOGI(TAG, "CSI activo → %s:%d", SERVER_IP, SERVER_PORT);
    }
}

/* ── app_main ────────────────────────────────────────────────────────────── */
void app_main(void)
{
    nvs_flash_init();
    esp_netif_init();
    esp_event_loop_create_default();
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    esp_wifi_init(&cfg);

    esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                               wifi_event_handler, NULL);
    esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
                               wifi_event_handler, NULL);

    wifi_config_t wifi_cfg = {
        .sta = {
            .ssid     = WIFI_SSID,
            .password = WIFI_PASS,
        },
    };
    esp_wifi_set_mode(WIFI_MODE_STA);
    esp_wifi_set_config(WIFI_IF_STA, &wifi_cfg);
    esp_wifi_start();

    /* El firmware vive en los callbacks — no hay bucle principal */
}
