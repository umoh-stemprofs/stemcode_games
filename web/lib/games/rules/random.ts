/**
 * A Python-compatible `random.Random` for offline play (P9-T03).
 *
 * The server re-scores an offline batch by replaying it, so the letters in a
 * Word Scramble round and the number behind a Number Guess round must be the
 * same on both sides. That means matching CPython exactly, not "a random
 * number": Mersenne Twister (MT19937), CPython's `init_by_array` seeding of a
 * large integer, its string-seeding rule (`int.from_bytes(s + sha512(s))`),
 * `shuffle`, `sample` and `_randbelow`.
 *
 * This is not a security primitive: offline seeds are generated on the device
 * and never unlock XP or rank (D-12). It exists so two implementations agree.
 *
 * The shared vectors in `shared/parity/game-rules.json` pin every part of it.
 */

const N = 624;
const M = 397;
const MATRIX_A = 0x9908b0df;
const UPPER_MASK = 0x80000000;
const LOWER_MASK = 0x7fffffff;

const textEncoder = new TextEncoder();

export type Seed = bigint | number | string;

export class PythonRandom {
  private readonly mt = new Uint32Array(N);
  private index = N;

  constructor(seed: Seed) {
    this.seed(seed);
  }

  /** Reseed exactly as `random.Random(seed)` does. */
  seed(seed: Seed): void {
    if (typeof seed === "string") {
      this.seedFromInteger(bytesToInteger(concatBytes(textEncoder.encode(seed), sha512(textEncoder.encode(seed)))));
      return;
    }
    if (typeof seed === "number") {
      if (!Number.isSafeInteger(seed)) {
        // A 63-bit server seed cannot be a JS number: use bigint or decimal text.
        throw new RangeError("seed must be a safe integer; pass a bigint for wide seeds");
      }
      this.seedFromInteger(BigInt(seed));
      return;
    }
    this.seedFromInteger(seed);
  }

  /** CPython splits the absolute value into little-endian 32-bit words. */
  private seedFromInteger(value: bigint): void {
    let rest = value < 0n ? -value : value;
    const key: number[] = [];
    do {
      key.push(Number(rest & 0xffffffffn));
      rest >>= 32n;
    } while (rest > 0n);
    this.initByArray(key);
  }

  private initGenrand(seed: number): void {
    this.mt[0] = seed >>> 0;
    for (let i = 1; i < N; i += 1) {
      const previous = this.mt[i - 1]!;
      this.mt[i] = (Math.imul(1812433253, (previous ^ (previous >>> 30)) >>> 0) + i) >>> 0;
    }
    this.index = N;
  }

  private initByArray(key: number[]): void {
    this.initGenrand(19650218);
    let i = 1;
    let j = 0;
    let k = Math.max(N, key.length);
    for (; k > 0; k -= 1) {
      const previous = this.mt[i - 1]!;
      const mixed = Math.imul(previous ^ (previous >>> 30), 1664525) >>> 0;
      this.mt[i] = (((this.mt[i]! ^ mixed) >>> 0) + key[j]! + j) >>> 0;
      i += 1;
      j += 1;
      if (i >= N) {
        this.mt[0] = this.mt[N - 1]!;
        i = 1;
      }
      if (j >= key.length) j = 0;
    }
    for (k = N - 1; k > 0; k -= 1) {
      const previous = this.mt[i - 1]!;
      const mixed = Math.imul(previous ^ (previous >>> 30), 1566083941) >>> 0;
      this.mt[i] = (((this.mt[i]! ^ mixed) >>> 0) - i) >>> 0;
      i += 1;
      if (i >= N) {
        this.mt[0] = this.mt[N - 1]!;
        i = 1;
      }
    }
    this.mt[0] = 0x80000000;
  }

  private twist(): void {
    let kk = 0;
    for (; kk < N - M; kk += 1) {
      const y = ((this.mt[kk]! & UPPER_MASK) | (this.mt[kk + 1]! & LOWER_MASK)) >>> 0;
      this.mt[kk] = (this.mt[kk + M]! ^ (y >>> 1) ^ (y & 1 ? MATRIX_A : 0)) >>> 0;
    }
    for (; kk < N - 1; kk += 1) {
      const y = ((this.mt[kk]! & UPPER_MASK) | (this.mt[kk + 1]! & LOWER_MASK)) >>> 0;
      this.mt[kk] = (this.mt[kk + (M - N)]! ^ (y >>> 1) ^ (y & 1 ? MATRIX_A : 0)) >>> 0;
    }
    const y = ((this.mt[N - 1]! & UPPER_MASK) | (this.mt[0]! & LOWER_MASK)) >>> 0;
    this.mt[N - 1] = (this.mt[M - 1]! ^ (y >>> 1) ^ (y & 1 ? MATRIX_A : 0)) >>> 0;
    this.index = 0;
  }

  private nextUint32(): number {
    if (this.index >= N) this.twist();
    let y = this.mt[this.index]!;
    this.index += 1;
    y ^= y >>> 11;
    y ^= (y << 7) & 0x9d2c5680;
    y ^= (y << 15) & 0xefc60000;
    y ^= y >>> 18;
    return y >>> 0;
  }

  /** `getrandbits(k)` for 1..32 bits, which is every draw these games make. */
  getrandbits(bits: number): number {
    if (!Number.isInteger(bits) || bits < 1 || bits > 32) {
      throw new RangeError("getrandbits supports 1..32 bits here");
    }
    const value = this.nextUint32();
    return bits === 32 ? value : value >>> (32 - bits);
  }

  /** `_randbelow`: uniform in [0, n), by rejection so there is no modulo bias. */
  randbelow(n: number): number {
    if (!Number.isInteger(n) || n <= 0) throw new RangeError("randbelow needs n > 0");
    // CPython uses ``n.bit_length()``, not ``(n - 1).bit_length()``. The
    // difference only shows at exact powers of two, where the extra bit means
    // a rejection draw — and therefore shifts every later value.
    const bits = 32 - Math.clz32(n);
    let value = this.getrandbits(bits);
    while (value >= n) value = this.getrandbits(bits);
    return value;
  }

  /** `randint(a, b)`, inclusive at both ends. */
  randint(a: number, b: number): number {
    if (!Number.isInteger(a) || !Number.isInteger(b) || b < a) {
      throw new RangeError("randint needs integer a <= b");
    }
    return a + this.randbelow(b - a + 1);
  }

  /** `random.shuffle`: in place, backwards, and returned for convenience. */
  shuffle<T>(values: T[]): T[] {
    for (let i = values.length - 1; i >= 1; i -= 1) {
      const j = this.randbelow(i + 1);
      const swap = values[i]!;
      values[i] = values[j]!;
      values[j] = swap;
    }
    return values;
  }

  /**
   * `random.sample`: without replacement, in selection order.
   *
   * CPython chooses between a pool (small populations) and a set (large ones)
   * by a threshold, and the two branches consume different numbers of draws.
   * Both are implemented because a 15-item pack and a 200-item pack take
   * different paths.
   */
  sample<T>(population: readonly T[], k: number): T[] {
    const n = population.length;
    if (!Number.isInteger(k) || k < 0 || k > n) {
      throw new RangeError("sample larger than population or is negative");
    }
    const result = new Array<T>(k);
    let setsize = 21;
    if (k > 5) setsize += 4 ** Math.ceil(Math.log(k * 3) / Math.log(4));

    if (n <= setsize) {
      const pool = [...population];
      for (let i = 0; i < k; i += 1) {
        const j = this.randbelow(n - i);
        result[i] = pool[j]!;
        pool[j] = pool[n - i - 1]!;
      }
      return result;
    }

    const selected = new Set<number>();
    for (let i = 0; i < k; i += 1) {
      let j = this.randbelow(n);
      while (selected.has(j)) j = this.randbelow(n);
      selected.add(j);
      result[i] = population[j]!;
    }
    return result;
  }
}

/**
 * A locally generated 63-bit seed for offline play.
 *
 * Never a server seed and never sent as one: offline sessions are re-scored on
 * the server from this seed and their actions, and earn no XP or rank (D-12).
 */
export function localSeed(): bigint {
  const words = new Uint32Array(2);
  crypto.getRandomValues(words);
  return (BigInt(words[0]!) << 32n) | BigInt(words[1]! >>> 1);
}

function concatBytes(first: Uint8Array, second: Uint8Array): Uint8Array {
  const joined = new Uint8Array(first.length + second.length);
  joined.set(first, 0);
  joined.set(second, first.length);
  return joined;
}

function bytesToInteger(bytes: Uint8Array): bigint {
  let value = 0n;
  for (const byte of bytes) value = (value << 8n) | BigInt(byte);
  return value;
}

// SHA-512, FIPS 180-4. CPython hashes a text seed with it; Web Crypto is
// async, and a round must be generated synchronously on a phone.
const MASK64 = (1n << 64n) - 1n;

const ROUND_CONSTANTS: readonly bigint[] = [
  0x428a2f98d728ae22n, 0x7137449123ef65cdn, 0xb5c0fbcfec4d3b2fn, 0xe9b5dba58189dbbcn,
  0x3956c25bf348b538n, 0x59f111f1b605d019n, 0x923f82a4af194f9bn, 0xab1c5ed5da6d8118n,
  0xd807aa98a3030242n, 0x12835b0145706fben, 0x243185be4ee4b28cn, 0x550c7dc3d5ffb4e2n,
  0x72be5d74f27b896fn, 0x80deb1fe3b1696b1n, 0x9bdc06a725c71235n, 0xc19bf174cf692694n,
  0xe49b69c19ef14ad2n, 0xefbe4786384f25e3n, 0x0fc19dc68b8cd5b5n, 0x240ca1cc77ac9c65n,
  0x2de92c6f592b0275n, 0x4a7484aa6ea6e483n, 0x5cb0a9dcbd41fbd4n, 0x76f988da831153b5n,
  0x983e5152ee66dfabn, 0xa831c66d2db43210n, 0xb00327c898fb213fn, 0xbf597fc7beef0ee4n,
  0xc6e00bf33da88fc2n, 0xd5a79147930aa725n, 0x06ca6351e003826fn, 0x142929670a0e6e70n,
  0x27b70a8546d22ffcn, 0x2e1b21385c26c926n, 0x4d2c6dfc5ac42aedn, 0x53380d139d95b3dfn,
  0x650a73548baf63den, 0x766a0abb3c77b2a8n, 0x81c2c92e47edaee6n, 0x92722c851482353bn,
  0xa2bfe8a14cf10364n, 0xa81a664bbc423001n, 0xc24b8b70d0f89791n, 0xc76c51a30654be30n,
  0xd192e819d6ef5218n, 0xd69906245565a910n, 0xf40e35855771202an, 0x106aa07032bbd1b8n,
  0x19a4c116b8d2d0c8n, 0x1e376c085141ab53n, 0x2748774cdf8eeb99n, 0x34b0bcb5e19b48a8n,
  0x391c0cb3c5c95a63n, 0x4ed8aa4ae3418acbn, 0x5b9cca4f7763e373n, 0x682e6ff3d6b2b8a3n,
  0x748f82ee5defb2fcn, 0x78a5636f43172f60n, 0x84c87814a1f0ab72n, 0x8cc702081a6439ecn,
  0x90befffa23631e28n, 0xa4506cebde82bde9n, 0xbef9a3f7b2c67915n, 0xc67178f2e372532bn,
  0xca273eceea26619cn, 0xd186b8c721c0c207n, 0xeada7dd6cde0eb1en, 0xf57d4f7fee6ed178n,
  0x06f067aa72176fban, 0x0a637dc5a2c898a6n, 0x113f9804bef90daen, 0x1b710b35131c471bn,
  0x28db77f523047d84n, 0x32caab7b40c72493n, 0x3c9ebe0a15c9bebcn, 0x431d67c49c100d4cn,
  0x4cc5d4becb3e42b6n, 0x597f299cfc657e2an, 0x5fcb6fab3ad6faecn, 0x6c44198c4a475817n,
];

const INITIAL_HASH: readonly bigint[] = [
  0x6a09e667f3bcc908n, 0xbb67ae8584caa73bn, 0x3c6ef372fe94f82bn, 0xa54ff53a5f1d36f1n,
  0x510e527fade682d1n, 0x9b05688c2b3e6c1fn, 0x1f83d9abfb41bd6bn, 0x5be0cd19137e2179n,
];

function rotr64(value: bigint, places: bigint): bigint {
  return ((value >> places) | (value << (64n - places))) & MASK64;
}

export function sha512(data: Uint8Array): Uint8Array {
  const paddedLength = Math.ceil((data.length + 17) / 128) * 128;
  const padded = new Uint8Array(paddedLength);
  padded.set(data);
  padded[data.length] = 0x80;
  const view = new DataView(padded.buffer);
  view.setBigUint64(paddedLength - 16, 0n);
  view.setBigUint64(paddedLength - 8, BigInt(data.length) * 8n);

  const hash = [...INITIAL_HASH];
  const words = new Array<bigint>(80);

  for (let offset = 0; offset < paddedLength; offset += 128) {
    for (let i = 0; i < 16; i += 1) words[i] = view.getBigUint64(offset + i * 8);
    for (let i = 16; i < 80; i += 1) {
      const first = words[i - 15]!;
      const second = words[i - 2]!;
      const s0 = rotr64(first, 1n) ^ rotr64(first, 8n) ^ (first >> 7n);
      const s1 = rotr64(second, 19n) ^ rotr64(second, 61n) ^ (second >> 6n);
      words[i] = (words[i - 16]! + s0 + words[i - 7]! + s1) & MASK64;
    }

    let [a, b, c, d, e, f, g, h] = hash as [
      bigint, bigint, bigint, bigint, bigint, bigint, bigint, bigint,
    ];
    for (let i = 0; i < 80; i += 1) {
      const sum1 = rotr64(e, 14n) ^ rotr64(e, 18n) ^ rotr64(e, 41n);
      const choose = ((e & f) ^ (~e & g)) & MASK64;
      const temp1 = (h + sum1 + choose + ROUND_CONSTANTS[i]! + words[i]!) & MASK64;
      const sum0 = rotr64(a, 28n) ^ rotr64(a, 34n) ^ rotr64(a, 39n);
      const majority = ((a & b) ^ (a & c) ^ (b & c)) & MASK64;
      const temp2 = (sum0 + majority) & MASK64;
      h = g;
      g = f;
      f = e;
      e = (d + temp1) & MASK64;
      d = c;
      c = b;
      b = a;
      a = (temp1 + temp2) & MASK64;
    }

    hash[0] = (hash[0]! + a) & MASK64;
    hash[1] = (hash[1]! + b) & MASK64;
    hash[2] = (hash[2]! + c) & MASK64;
    hash[3] = (hash[3]! + d) & MASK64;
    hash[4] = (hash[4]! + e) & MASK64;
    hash[5] = (hash[5]! + f) & MASK64;
    hash[6] = (hash[6]! + g) & MASK64;
    hash[7] = (hash[7]! + h) & MASK64;
  }

  const digest = new Uint8Array(64);
  const digestView = new DataView(digest.buffer);
  hash.forEach((value, index) => digestView.setBigUint64(index * 8, value));
  return digest;
}
