// Request authentication for the lock controller.
//
// Protocol (the Pi side is app/lock.py):
//   1. GET /nonce                      -> {"nonce": "<32 hex chars>"}
//   2. POST /lock | POST /unlock | GET /lock-status with headers
//        X-Fracs-Nonce:     the nonce from step 1
//        X-Fracs-Signature: hex HMAC-SHA256(LOCK_SECRET, "fracs-v1:<action>:<nonce>")
//      where <action> is "lock", "unlock" or "status".
//
// Each nonce works once and expires after NONCE_TTL_MS, so a captured request
// can't be replayed, and the action is part of the signed message, so a
// signature for "lock" can't be reused to unlock. Requests travel as plain
// HTTP, so someone on the network can still see them, just not forge them.
//
// This file is plain C++ (no Arduino types), so tests/firmware compiles it on a
// PC. The sketch provides fracs_hmac_sha256() and fracs_random_bytes().
#pragma once

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

void fracs_hmac_sha256(const uint8_t* key, size_t key_len, const uint8_t* msg, size_t msg_len,
                       uint8_t out[32]);
void fracs_random_bytes(uint8_t* out, size_t len);

namespace fracs {

const int NONCE_SLOTS = 8;             // outstanding nonces; the oldest is overwritten
const unsigned long NONCE_TTL_MS = 10000;
const size_t NONCE_HEX_LEN = 32;       // 16 random bytes
const size_t SIGNATURE_HEX_LEN = 64;   // SHA-256
const size_t MIN_SECRET_LEN = 16;

enum Result { OK, NOT_CONFIGURED, MISSING_HEADERS, BAD_NONCE, BAD_SIGNATURE };

struct NonceStore {
  char value[NONCE_SLOTS][NONCE_HEX_LEN + 1];
  unsigned long issued_at[NONCE_SLOTS];
  int next;
};

inline void to_hex(const uint8_t* bytes, size_t len, char* out) {
  static const char digits[] = "0123456789abcdef";
  for (size_t i = 0; i < len; i++) {
    out[2 * i] = digits[bytes[i] >> 4];
    out[2 * i + 1] = digits[bytes[i] & 0x0f];
  }
  out[2 * len] = '\0';
}

inline void init(NonceStore& store) {
  memset(&store, 0, sizeof(store));
}

// Refuse to run with the placeholder or a short secret
inline bool secret_configured(const char* secret) {
  return secret != nullptr && strlen(secret) >= MIN_SECRET_LEN && strstr(secret, "*****") == nullptr;
}

inline void issue_nonce(NonceStore& store, unsigned long now_ms, char out[NONCE_HEX_LEN + 1]) {
  uint8_t bytes[NONCE_HEX_LEN / 2];
  fracs_random_bytes(bytes, sizeof(bytes));
  to_hex(bytes, sizeof(bytes), out);
  int slot = store.next;
  store.next = (store.next + 1) % NONCE_SLOTS;
  memcpy(store.value[slot], out, NONCE_HEX_LEN + 1);
  store.issued_at[slot] = now_ms;
}

inline void signature_hex(const char* secret, const char* action, const char* nonce,
                          char out[SIGNATURE_HEX_LEN + 1]) {
  char message[64];
  int len = snprintf(message, sizeof(message), "fracs-v1:%s:%s", action, nonce);
  if (len < 0 || len >= (int)sizeof(message)) {
    out[0] = '\0';
    return;
  }
  uint8_t mac[32];
  fracs_hmac_sha256((const uint8_t*)secret, strlen(secret), (const uint8_t*)message, (size_t)len, mac);
  to_hex(mac, sizeof(mac), out);
}

// Compares every byte regardless of where the first difference is
inline bool constant_time_equals(const char* a, const char* b, size_t len) {
  uint8_t diff = 0;
  for (size_t i = 0; i < len; i++) diff |= (uint8_t)a[i] ^ (uint8_t)b[i];
  return diff == 0;
}

inline Result verify(NonceStore& store, const char* secret, const char* action, const char* nonce,
                     const char* signature, unsigned long now_ms) {
  if (!secret_configured(secret)) return NOT_CONFIGURED;
  if (nonce == nullptr || signature == nullptr) return MISSING_HEADERS;
  if (strlen(nonce) != NONCE_HEX_LEN) return BAD_NONCE;
  if (strlen(signature) != SIGNATURE_HEX_LEN) return BAD_SIGNATURE;

  int slot = -1;
  for (int i = 0; i < NONCE_SLOTS; i++) {
    // Unsigned subtraction stays correct when millis() wraps around
    if (store.value[i][0] != '\0' && strcmp(store.value[i], nonce) == 0 &&
        now_ms - store.issued_at[i] <= NONCE_TTL_MS) {
      slot = i;
      break;
    }
  }
  if (slot < 0) return BAD_NONCE;

  char expected[SIGNATURE_HEX_LEN + 1];
  signature_hex(secret, action, nonce, expected);
  // A bad signature doesn't burn the nonce, so someone who sniffs a nonce
  // can't cancel the Pi's request by sending garbage with it first
  if (!constant_time_equals(expected, signature, SIGNATURE_HEX_LEN)) return BAD_SIGNATURE;

  store.value[slot][0] = '\0';  // single use
  return OK;
}

}  // namespace fracs
