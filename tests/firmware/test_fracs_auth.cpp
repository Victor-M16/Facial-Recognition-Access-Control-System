// Host-side test of wifi_servo/fracs_auth.h, with OpenSSL standing in for mbedtls.
// Built and run by tests/test_firmware_auth.py:
//   ./test_fracs_auth                      run the checks
//   ./test_fracs_auth sign SECRET ACTION NONCE   print a signature (to compare with app/lock.py)
#include <openssl/hmac.h>

#include <climits>
#include <cstdio>
#include <cstring>

#include "../../wifi_servo/fracs_auth.h"

void fracs_hmac_sha256(const uint8_t* key, size_t key_len, const uint8_t* msg, size_t msg_len,
                       uint8_t out[32]) {
  unsigned int len = 32;
  HMAC(EVP_sha256(), key, (int)key_len, msg, msg_len, out, &len);
}

static uint8_t counter = 0;
void fracs_random_bytes(uint8_t* out, size_t len) {
  for (size_t i = 0; i < len; i++) out[i] = ++counter;
}

static int failures = 0;
#define CHECK(cond)                                              \
  do {                                                           \
    if (!(cond)) {                                               \
      printf("FAIL line %d: %s\n", __LINE__, #cond);             \
      failures++;                                                \
    }                                                            \
  } while (0)

static const char* SECRET = "0123456789abcdef0123456789abcdef";

int main(int argc, char** argv) {
  if (argc == 5 && strcmp(argv[1], "sign") == 0) {
    char sig[fracs::SIGNATURE_HEX_LEN + 1];
    fracs::signature_hex(argv[2], argv[3], argv[4], sig);
    printf("%s\n", sig);
    return 0;
  }

  fracs::NonceStore store;
  fracs::init(store);
  char nonce[fracs::NONCE_HEX_LEN + 1], sig[fracs::SIGNATURE_HEX_LEN + 1];

  // Placeholder or short secrets refuse everything
  CHECK(!fracs::secret_configured("*****"));
  CHECK(!fracs::secret_configured("short"));
  CHECK(!fracs::secret_configured(nullptr));
  CHECK(fracs::secret_configured(SECRET));
  fracs::issue_nonce(store, 1000, nonce);
  fracs::signature_hex("*****", "unlock", nonce, sig);
  CHECK(fracs::verify(store, "*****", "unlock", nonce, sig, 1000) == fracs::NOT_CONFIGURED);

  // A correctly signed request works exactly once
  fracs::signature_hex(SECRET, "unlock", nonce, sig);
  CHECK(strlen(nonce) == 32 && strlen(sig) == 64);
  CHECK(fracs::verify(store, SECRET, "unlock", nonce, nullptr, 1000) == fracs::MISSING_HEADERS);
  CHECK(fracs::verify(store, SECRET, "unlock", nonce, sig, 1500) == fracs::OK);
  CHECK(fracs::verify(store, SECRET, "unlock", nonce, sig, 1600) == fracs::BAD_NONCE);

  // A signature is bound to its action and to the secret
  fracs::issue_nonce(store, 2000, nonce);
  fracs::signature_hex(SECRET, "lock", nonce, sig);
  CHECK(fracs::verify(store, SECRET, "unlock", nonce, sig, 2000) == fracs::BAD_SIGNATURE);
  fracs::signature_hex("another-secret-of-enough-length", "unlock", nonce, sig);
  CHECK(fracs::verify(store, SECRET, "unlock", nonce, sig, 2000) == fracs::BAD_SIGNATURE);
  // ...and bad attempts don't burn the nonce for the real request
  fracs::signature_hex(SECRET, "unlock", nonce, sig);
  CHECK(fracs::verify(store, SECRET, "unlock", nonce, sig, 2000) == fracs::OK);

  // Unknown and malformed nonces
  CHECK(fracs::verify(store, SECRET, "unlock", "00000000000000000000000000000000", sig, 2000) == fracs::BAD_NONCE);
  CHECK(fracs::verify(store, SECRET, "unlock", "abc", sig, 2000) == fracs::BAD_NONCE);

  // Nonces expire
  fracs::issue_nonce(store, 3000, nonce);
  fracs::signature_hex(SECRET, "status", nonce, sig);
  CHECK(fracs::verify(store, SECRET, "status", nonce, sig, 3000 + fracs::NONCE_TTL_MS + 1) == fracs::BAD_NONCE);

  // Expiry still works when millis() wraps around
  fracs::issue_nonce(store, ULONG_MAX - 100, nonce);
  fracs::signature_hex(SECRET, "status", nonce, sig);
  CHECK(fracs::verify(store, SECRET, "status", nonce, sig, 50) == fracs::OK);

  // Only NONCE_SLOTS nonces are kept; the oldest is dropped
  char first[fracs::NONCE_HEX_LEN + 1];
  fracs::issue_nonce(store, 4000, first);
  for (int i = 0; i < fracs::NONCE_SLOTS; i++) fracs::issue_nonce(store, 4000, nonce);
  fracs::signature_hex(SECRET, "lock", first, sig);
  CHECK(fracs::verify(store, SECRET, "lock", first, sig, 4000) == fracs::BAD_NONCE);
  fracs::signature_hex(SECRET, "lock", nonce, sig);
  CHECK(fracs::verify(store, SECRET, "lock", nonce, sig, 4000) == fracs::OK);

  if (failures) return 1;
  printf("all firmware auth checks passed\n");
  return 0;
}
