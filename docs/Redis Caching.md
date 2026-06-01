# Cache Report - Redis Weather API

## 1. Screenshot

## 2. Kode yang Dimodifikasi

Pada tugas ini, fungsi `get_weather(city)` dimodifikasi agar menggunakan Redis sebagai cache.

Alur program:

1. Membuat cache key berdasarkan nama kota.
2. Mengecek apakah data sudah ada di Redis menggunakan `GET`.
3. Jika data ada, program langsung mengembalikan data dari cache.
4. Jika data belum ada, program menjalankan API call lambat.
5. Hasil API disimpan ke Redis menggunakan `SET`.
6. Cache diberi waktu kedaluwarsa 5 menit menggunakan `EXPIRE`.

## 3. Redis Commands yang Digunakan

### GET

Digunakan untuk mengambil data dari Redis.

```python
cached_data = redis_client.get(cache_key)
```

Jika data ditemukan, maka response langsung dikembalikan dari cache.

### SET

Digunakan untuk menyimpan hasil API call ke Redis.

```python
redis_client.set(cache_key, json.dumps(data))
```

Data disimpan dalam bentuk JSON string agar bisa dimasukkan ke Redis.

### EXPIRE

Digunakan untuk mengatur masa berlaku cache selama 5 menit atau 300 detik.

```python
redis_client.expire(cache_key, 300)
```

Setelah 300 detik, data cache akan otomatis dihapus oleh Redis.

## 4. Kenapa Response Time Berbeda?

Response time berbeda karena pemanggilan pertama belum memiliki data di cache, sehingga program harus menjalankan API call lambat yang membutuhkan sekitar 2 detik.

Pada pemanggilan kedua, data sudah tersimpan di Redis. Karena Redis menyimpan data di memory, proses pengambilan data menjadi jauh lebih cepat, biasanya kurang dari 0.1 detik.

## 5. Apa Keuntungan Caching?

Keuntungan caching adalah:

1. Response API menjadi lebih cepat.
2. Mengurangi beban server dan database.
3. Mengurangi jumlah request ke API eksternal.
4. Cocok untuk data yang sering diakses tetapi jarang berubah.
5. Membantu meningkatkan performa aplikasi.

## 6. Kapan Sebaiknya Tidak Menggunakan Cache?

Cache sebaiknya tidak digunakan ketika:

1. Data harus selalu real-time.
2. Data sangat sering berubah.
3. Data bersifat sensitif dan tidak aman jika disimpan sementara.
4. Ukuran data terlalu besar sehingga membebani memory.
5. Proses invalidasi cache terlalu rumit dibandingkan manfaatnya.
