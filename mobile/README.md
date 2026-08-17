# AduanHub Android

Aplikasi Flutter untuk Admin Pusat, supervisor, dan petugas bidang. Aplikasi menggunakan API AduanHub dan menerapkan hak akses berdasarkan disposisi.

## Fitur

- Login token dengan penyimpanan aman Android
- Dashboard sesuai kewenangan akun
- Daftar dan pencarian aduan yang didisposisikan
- Percakapan dua arah dengan auto-refresh
- Pengiriman foto, video, audio, dan PDF
- Notifikasi disposisi dan pesan pengadu
- Status penanganan, profil, serta tema terang/gelap

## Build

```bash
flutter pub get
flutter test
flutter build apk --release \
  --dart-define=API_BASE_URL=https://aduanhub.rekadev.site/api/v1
```

APK internal tersimpan di `build/app/outputs/flutter-apk/app-release.apk`.

Untuk rilis Google Play, ganti konfigurasi signing debug pada `android/app/build.gradle.kts` dengan upload key organisasi dan hasilkan AAB melalui `flutter build appbundle --release`.
