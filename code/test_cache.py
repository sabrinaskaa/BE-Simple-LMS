import time

from weather_api import (
    clear_weather_cache,
    get_weather,
    get_weather_cache_ttl,
    make_cache_key,
    redis_client,
)


def print_separator():
    print("-" * 60)


def main():
    city = "Jakarta"
    cache_key = make_cache_key(city)

    print_separator()
    print("REDIS WEATHER CACHE TEST")
    print_separator()

    clear_weather_cache(city)
    print(f"Cache key dibersihkan: {cache_key}")
    print()

    print("1. First call - cache MISS, harus sekitar 2 detik")
    start = time.time()
    result1 = get_weather(city)
    time1 = time.time() - start

    print(f"Result 1: {result1}")
    print(f"First call time: {time1:.2f}s")
    print(f"TTL setelah first call: {get_weather_cache_ttl(city)} detik")
    print()

    print("2. Second call - cache HIT, harus cepat")
    start = time.time()
    result2 = get_weather(city)
    time2 = time.time() - start

    print(f"Result 2: {result2}")
    print(f"Second call time: {time2:.4f}s")
    print(f"TTL setelah second call: {get_weather_cache_ttl(city)} detik")
    print()
    print("3. Perbandingan response time")
    print(f"First call  : {time1:.2f}s")
    print(f"Second call : {time2:.4f}s")

    if time2 < time1:
        print("Kesimpulan: second call lebih cepat karena data diambil dari Redis cache.")
    else:
        print("Kesimpulan: hasil belum sesuai, cek koneksi Redis atau logic caching.")
    print()

    print("4. Simulasi cache expiry")
    print("Pada implementasi asli, cache expired setelah 300 detik.")
    print("Untuk demo, key dipaksa expired dalam 2 detik menggunakan Redis EXPIRE.")
    redis_client.expire(cache_key, 2)

    print(f"TTL setelah dipaksa expire 2 detik: {get_weather_cache_ttl(city)} detik")
    time.sleep(3)
    print(f"TTL setelah menunggu 3 detik: {get_weather_cache_ttl(city)} detik")

    print()
    print("5. Third call setelah cache expired - harus lambat lagi")
    start = time.time()
    result3 = get_weather(city)
    time3 = time.time() - start

    print(f"Result 3: {result3}")
    print(f"Third call time: {time3:.2f}s")
    print(f"TTL setelah third call: {get_weather_cache_ttl(city)} detik")

    print_separator()


if __name__ == "__main__":
    main()