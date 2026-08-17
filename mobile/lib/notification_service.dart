import 'dart:async';
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/material.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:workmanager/workmanager.dart';
import 'api.dart';

const backgroundTask = 'aduanhub-notification-check';
const _secureStorage = FlutterSecureStorage();

class MobileNotifications {
  static final plugin = FlutterLocalNotificationsPlugin();
  static final ticketClicks = StreamController<int>.broadcast();
  static int? pendingTicketId;
  static ApiClient? _pushApi;
  static StreamSubscription<String>? _tokenSubscription;
  static bool _listenersReady = false;

  static void _handleTap(NotificationResponse response) {
    final ticketId = int.tryParse(response.payload ?? '');
    if (ticketId != null) {
      pendingTicketId = ticketId;
      ticketClicks.add(ticketId);
    }
  }

  static Future<void> initialize() async {
    await plugin.initialize(
      const InitializationSettings(
        android: AndroidInitializationSettings('ic_stat_aduanhub'),
      ),
      onDidReceiveNotificationResponse: _handleTap,
    );
    final launch = await plugin.getNotificationAppLaunchDetails();
    if (launch?.didNotificationLaunchApp ?? false) {
      _handleTap(launch!.notificationResponse!);
    }
    final android = plugin
        .resolvePlatformSpecificImplementation<
          AndroidFlutterLocalNotificationsPlugin
        >();
    await android?.requestNotificationsPermission();
  }

  static Future<void> bindFirebase(ApiClient api) async {
    _pushApi = api;
    await FirebaseMessaging.instance.requestPermission(
      alert: true,
      badge: true,
      sound: true,
    );
    await _registerToken(await FirebaseMessaging.instance.getToken());
    await _tokenSubscription?.cancel();
    _tokenSubscription = FirebaseMessaging.instance.onTokenRefresh.listen(
      (token) => _registerToken(token),
    );
    if (!_listenersReady) {
      _listenersReady = true;
      FirebaseMessaging.onMessage.listen(showRemoteMessage);
      FirebaseMessaging.onMessageOpenedApp.listen(openRemoteMessage);
      final initial = await FirebaseMessaging.instance.getInitialMessage();
      if (initial != null) openRemoteMessage(initial);
    }
  }

  static Future<void> unbindFirebase() async {
    final token = await FirebaseMessaging.instance.getToken();
    final api = _pushApi;
    if (token != null && api != null) {
      try {
        await api.post('/devices/push-token/remove', {'token': token});
      } catch (_) {}
    }
    _pushApi = null;
    await _tokenSubscription?.cancel();
    _tokenSubscription = null;
  }

  static Future<void> _registerToken(String? token) async {
    final api = _pushApi;
    if (token == null || api == null) return;
    try {
      await api.post('/devices/push-token', {
        'token': token,
        'platform': 'android',
      });
    } catch (_) {
      // Polling remains available if registration temporarily fails.
    }
  }

  static void openRemoteMessage(RemoteMessage message) {
    final ticketId = int.tryParse(message.data['ticket_id'] ?? '');
    if (ticketId != null) {
      pendingTicketId = ticketId;
      ticketClicks.add(ticketId);
    }
  }

  static Future<void> showRemoteMessage(RemoteMessage message) async {
    final prefs = await SharedPreferences.getInstance();
    if (!(prefs.getBool('notifications_enabled') ?? true)) return;
    final notificationId = int.tryParse(message.data['notification_id'] ?? '');
    final base = await _secureStorage.read(key: 'api_base_url');
    if (notificationId != null && base != null) {
      final key =
          'notification_latest_${base.replaceAll(RegExp(r'[^a-zA-Z0-9]'), '_')}';
      final previous = prefs.getInt(key) ?? 0;
      if (notificationId > previous) await prefs.setInt(key, notificationId);
    }
    await show(
      id: notificationId ?? message.messageId.hashCode,
      title: message.data['title'] ?? 'Pembaruan AduanHub',
      body: message.data['body'] ?? '',
      ticketId: message.data['ticket_id'],
      sound: prefs.getBool('notification_sound') ?? true,
      vibration: prefs.getBool('notification_vibration') ?? true,
    );
  }

  static Future<int> poll(ApiClient api, {bool background = false}) async {
    final prefs = await SharedPreferences.getInstance();
    if (!(prefs.getBool('notifications_enabled') ?? true)) return 0;
    final result = await api.get('/notifications');
    final items = (result['notifications'] as List<dynamic>? ?? []);
    final key =
        'notification_latest_${api.baseUrl.replaceAll(RegExp(r'[^a-zA-Z0-9]'), '_')}';
    final latest = items.isEmpty ? 0 : (items.first['id'] as num).toInt();
    final previous = prefs.getInt(key);
    if (previous == null) {
      await prefs.setInt(key, latest);
      return items.where((item) => item['read'] != true).length;
    }
    final fresh = items
        .where((item) => (item['id'] as num).toInt() > previous)
        .toList()
        .reversed;
    for (final item in fresh) {
      await show(
        id: (item['id'] as num).toInt(),
        title: item['title']?.toString() ?? 'Aduan baru',
        body: item['body']?.toString() ?? '',
        ticketId: item['ticket_id']?.toString(),
        sound: prefs.getBool('notification_sound') ?? true,
        vibration: prefs.getBool('notification_vibration') ?? true,
      );
    }
    if (latest > previous) await prefs.setInt(key, latest);
    return items.where((item) => item['read'] != true).length;
  }

  static Future<void> show({
    required int id,
    required String title,
    required String body,
    String? ticketId,
    bool sound = true,
    bool vibration = true,
  }) async {
    await plugin.show(
      id,
      title,
      body,
      NotificationDetails(
        android: AndroidNotificationDetails(
          sound ? 'aduanhub_alerts' : 'aduanhub_silent',
          sound ? 'Aduan dan pesan baru' : 'Aduan tanpa suara',
          channelDescription: 'Pemberitahuan aktivitas layanan aduan',
          importance: Importance.high,
          priority: Priority.high,
          playSound: sound,
          enableVibration: vibration,
          icon: 'ic_stat_aduanhub',
        ),
      ),
      payload: ticketId,
    );
  }
}

@pragma('vm:entry-point')
Future<void> firebaseMessagingBackgroundHandler(RemoteMessage message) async {
  WidgetsFlutterBinding.ensureInitialized();
  await Firebase.initializeApp();
  await MobileNotifications.initialize();
  await MobileNotifications.showRemoteMessage(message);
}

@pragma('vm:entry-point')
void backgroundDispatcher() {
  Workmanager().executeTask((task, inputData) async {
    WidgetsFlutterBinding.ensureInitialized();
    try {
      await MobileNotifications.initialize();
      final token = await _secureStorage.read(key: 'token');
      final base = await _secureStorage.read(key: 'api_base_url');
      if (token == null || base == null) return true;
      await MobileNotifications.poll(ApiClient(token, base), background: true);
    } catch (_) {
      // A later periodic run retries transient network or authentication errors.
    }
    return true;
  });
}
