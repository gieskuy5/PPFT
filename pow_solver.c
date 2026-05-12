/*
 * PFFT PoW Solver — C extension for fast keccak256 brute-force
 * Compile: gcc -O3 -march=native -o pow_solver pow_solver.c keccak.c -lpthread
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <time.h>
#include <pthread.h>

/* ---- Minimal Keccak-256 ---- */
static const uint64_t keccak_round_constants[24] = {
    0x0000000000000001ULL, 0x0000000000008082ULL, 0x800000000000808aULL,
    0x8000000080008000ULL, 0x000000000000808bULL, 0x0000000080000001ULL,
    0x8000000080008081ULL, 0x8000000000008009ULL, 0x000000000000008aULL,
    0x0000000000000088ULL, 0x0000000080008009ULL, 0x000000008000000aULL,
    0x000000008000808bULL, 0x800000000000008bULL, 0x8000000000008089ULL,
    0x8000000000008003ULL, 0x8000000000008002ULL, 0x8000000000000080ULL,
    0x000000000000800aULL, 0x800000008000000aULL, 0x8000000080008081ULL,
    0x8000000000008080ULL, 0x0000000080000001ULL, 0x8000000080008008ULL
};

static const int keccak_rotation_offsets[25] = {
     0,  1, 62, 28, 27,
    36, 44,  6, 55, 20,
     3, 10, 43, 25, 39,
    41, 45, 15, 21,  8,
    18,  2, 61, 56, 14
};

static const int keccak_pi_lane[25] = {
     0, 10,  7, 11, 17,
    20,  4, 14, 23, 15,
    22,  1, 12,  9, 19,
     6, 24,  3, 18, 13,
    16, 21,  2,  8,  5
};

#define ROT64(x, n) (((x) << (n)) | ((x) >> (64 - (n))))

static void keccak_f1600(uint64_t state[25]) {
    for (int round = 0; round < 24; round++) {
        uint64_t C[5], D[5], temp[25];

        /* Theta */
        for (int x = 0; x < 5; x++)
            C[x] = state[x] ^ state[x+5] ^ state[x+10] ^ state[x+15] ^ state[x+20];
        for (int x = 0; x < 5; x++) {
            D[x] = C[(x+4)%5] ^ ROT64(C[(x+1)%5], 1);
            for (int y = 0; y < 5; y++)
                state[x + 5*y] ^= D[x];
        }

        /* Rho & Pi */
        for (int i = 0; i < 25; i++)
            temp[keccak_pi_lane[i]] = ROT64(state[i], keccak_rotation_offsets[i]);

        /* Chi */
        for (int y = 0; y < 5; y++)
            for (int x = 0; x < 5; x++)
                state[x + 5*y] = temp[x + 5*y] ^ ((~temp[((x+1)%5) + 5*y]) & temp[((x+2)%5) + 5*y]);

        /* Iota */
        state[0] ^= keccak_round_constants[round];
    }
}

static void keccak256(const uint8_t *input, size_t len, uint8_t output[32]) {
    uint64_t state[25];
    memset(state, 0, 200);

    /* Absorb */
    size_t block_size = 136; /* rate for keccak-256 */
    size_t offset = 0;
    while (offset + block_size <= len) {
        for (size_t i = 0; i < block_size / 8; i++)
            state[i] ^= ((uint64_t*)(input + offset))[i];
        keccak_f1600(state);
        offset += block_size;
    }

    /* Final block with padding */
    uint8_t last[136];
    memset(last, 0, 136);
    memcpy(last, input + offset, len - offset);
    last[len - offset] = 0x01;      /* keccak domain separator */
    last[block_size - 1] |= 0x80;   /* pad10*1 */
    for (size_t i = 0; i < block_size / 8; i++)
        state[i] ^= ((uint64_t*)last)[i];
    keccak_f1600(state);

    /* Squeeze */
    memcpy(output, state, 32);
}

/* ---- Thread worker ---- */
typedef struct {
    const uint8_t *challenge; /* 32 bytes */
    uint8_t target_le[32];    /* target as 32-byte LE for comparison */
    uint64_t start_nonce;
    uint64_t step;
    uint64_t found_nonce;
    int found;
    int thread_id;
    uint64_t attempts;
} worker_args_t;

static void *worker(void *arg) {
    worker_args_t *a = (worker_args_t *)arg;
    uint8_t buf[64];
    uint8_t hash[32];

    memcpy(buf, a->challenge, 32);

    for (uint64_t nonce = a->start_nonce; !a->found; nonce += a->step) {
        /* Pack nonce as big-endian uint256 in last 32 bytes */
        memset(buf + 32, 0, 24);
        buf[56] = (nonce >> 56) & 0xFF;
        buf[57] = (nonce >> 48) & 0xFF;
        buf[58] = (nonce >> 40) & 0xFF;
        buf[59] = (nonce >> 32) & 0xFF;
        buf[60] = (nonce >> 24) & 0xFF;
        buf[61] = (nonce >> 16) & 0xFF;
        buf[62] = (nonce >> 8)  & 0xFF;
        buf[63] = (nonce)       & 0xFF;

        keccak256(buf, 64, hash);

        /* Compare hash < target (both big-endian) */
        if (memcmp(hash, a->target_le, 32) <= 0) {
            a->found_nonce = nonce;
            a->found = 1;
            a->attempts = nonce - a->start_nonce;
            return NULL;
        }

        a->attempts = nonce - a->start_nonce;
    }
    return NULL;
}

/* ---- Main ---- */
int main(int argc, char **argv) {
    if (argc < 4) {
        fprintf(stderr, "Usage: %s <challenge_hex_64> <target_hex_64> <num_threads>\n", argv[0]);
        return 1;
    }

    /* Parse challenge (32 bytes hex) */
    uint8_t challenge[32];
    for (int i = 0; i < 32; i++)
        sscanf(argv[1] + i*2, "%2hhx", &challenge[i]);

    /* Parse target (32 bytes hex) */
    uint8_t target[32];
    for (int i = 0; i < 32; i++)
        sscanf(argv[2] + i*2, "%2hhx", &target[i]);

    int num_threads = atoi(argv[3]);
    if (num_threads < 1) num_threads = 1;
    if (num_threads > 64) num_threads = 64;

    fprintf(stderr, "⛏️  PFFT PoW Solver (C)\n");
    fprintf(stderr, "   Challenge: %.16s...\n", argv[1]);
    fprintf(stderr, "   Target:    %.16s...\n", argv[2]);
    fprintf(stderr, "   Threads:   %d\n", num_threads);

    worker_args_t workers[64];
    pthread_t threads[64];

    struct timespec ts_start;
    clock_gettime(CLOCK_MONOTONIC, &ts_start);

    for (int i = 0; i < num_threads; i++) {
        workers[i].challenge = challenge;
        memcpy(workers[i].target_le, target, 32);
        workers[i].start_nonce = i;
        workers[i].step = num_threads;
        workers[i].found = 0;
        workers[i].thread_id = i;
        workers[i].attempts = 0;
        pthread_create(&threads[i], NULL, worker, &workers[i]);
    }

    /* Monitor & print hashrate */
    int found = 0;
    uint64_t winner_nonce = 0;
    while (!found) {
        sleep(2);
        struct timespec ts_now;
        clock_gettime(CLOCK_MONOTONIC, &ts_now);
        double elapsed = (ts_now.tv_sec - ts_start.tv_sec) + (ts_now.tv_nsec - ts_start.tv_nsec) / 1e9;

        uint64_t total_attempts = 0;
        for (int i = 0; i < num_threads; i++) {
            total_attempts += workers[i].attempts;
            if (workers[i].found) {
                found = 1;
                winner_nonce = workers[i].found_nonce;
            }
        }

        double rate = total_attempts / elapsed;
        fprintf(stderr, "\r  ⛏️  %lu attempts | %.0f H/s | %.0fs elapsed    ", total_attempts, rate, elapsed);
    }

    /* Wait for all threads */
    for (int i = 0; i < num_threads; i++)
        pthread_join(threads[i], NULL);

    fprintf(stderr, "\n  ✅ FOUND nonce=%lu\n", winner_nonce);

    /* Print nonce to stdout (for Python to read) */
    printf("%lu\n", winner_nonce);
    return 0;
}
