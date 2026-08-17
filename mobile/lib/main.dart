import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:file_picker/file_picker.dart';
import 'package:intl/intl.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:workmanager/workmanager.dart';
import 'api.dart';
import 'notification_service.dart';

const storage = FlutterSecureStorage();

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await MobileNotifications.initialize();
  await Workmanager().initialize(backgroundDispatcher);
  await Workmanager().registerPeriodicTask(
    'aduanhub-periodic-notifications',
    backgroundTask,
    frequency: const Duration(minutes: 15),
    existingWorkPolicy: ExistingPeriodicWorkPolicy.keep,
    constraints: Constraints(networkType: NetworkType.connected),
  );
  runApp(const AduanHubApp());
}

class AduanHubApp extends StatefulWidget {
  const AduanHubApp({super.key});
  @override
  State<AduanHubApp> createState() => _AduanHubAppState();
}

class _AduanHubAppState extends State<AduanHubApp> {
  ApiClient? api;
  Map<String, dynamic>? profile;
  bool loading = true;
  ThemeMode mode = ThemeMode.system;

  @override
  void initState() {
    super.initState();
    restore();
  }

  Future<void> restore() async {
    final token = await storage.read(key: 'token');
    final baseUrl = await storage.read(key: 'api_base_url') ?? defaultApiBase;
    if (token != null) {
      final client = ApiClient(token, baseUrl);
      try {
        profile = await client.get('/me');
        api = client;
      } catch (_) {
        await storage.delete(key: 'token');
      }
    }
    if (mounted) setState(() => loading = false);
  }

  Future<void> signedIn(Map<String, dynamic> result, [String? baseUrl]) async {
    final token = result['token'] as String;
    await storage.write(key: 'token', value: token);
    final resolvedBase =
        baseUrl ?? await storage.read(key: 'api_base_url') ?? defaultApiBase;
    await storage.write(key: 'api_base_url', value: resolvedBase);
    final client = ApiClient(token, resolvedBase);
    final me = await client.get('/me');
    setState(() {
      api = client;
      profile = me;
    });
  }

  Future<void> signOut() async {
    await storage.delete(key: 'token');
    setState(() {
      api = null;
      profile = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    const seed = Color(0xFF2563EB);
    final light = ThemeData(
      useMaterial3: true,
      colorScheme: ColorScheme.fromSeed(
        seedColor: seed,
        brightness: Brightness.light,
      ),
      scaffoldBackgroundColor: const Color(0xFFF6F7F9),
      fontFamily: 'Roboto',
      cardTheme: const CardThemeData(elevation: 0, margin: EdgeInsets.zero),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: Colors.white,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: BorderSide.none,
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: const BorderSide(color: Color(0xFFE5E7EB)),
        ),
      ),
    );
    final dark = ThemeData(
      useMaterial3: true,
      colorScheme: ColorScheme.fromSeed(
        seedColor: seed,
        brightness: Brightness.dark,
      ),
      scaffoldBackgroundColor: const Color(0xFF0F1115),
      cardTheme: const CardThemeData(
        elevation: 0,
        margin: EdgeInsets.zero,
        color: Color(0xFF181B21),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: const Color(0xFF181B21),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: BorderSide.none,
        ),
      ),
    );
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'AduanHub',
      theme: light,
      darkTheme: dark,
      themeMode: mode,
      home: loading
          ? const SplashScreen()
          : api == null
          ? LoginScreen(onSignedIn: signedIn)
          : HomeShell(
              api: api!,
              profile: profile!,
              onSignOut: signOut,
              onTheme: () => setState(
                () => mode = mode == ThemeMode.dark
                    ? ThemeMode.light
                    : ThemeMode.dark,
              ),
            ),
    );
  }
}

class SplashScreen extends StatelessWidget {
  const SplashScreen({super.key});
  @override
  Widget build(BuildContext context) =>
      const Scaffold(body: Center(child: CircularProgressIndicator()));
}

class PairingScanner extends StatefulWidget {
  const PairingScanner({super.key});
  @override
  State<PairingScanner> createState() => _PairingScannerState();
}

class _PairingScannerState extends State<PairingScanner> {
  bool found = false;
  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Pindai QR dashboard')),
    body: Stack(
      fit: StackFit.expand,
      children: [
        MobileScanner(
          onDetect: (capture) {
            if (found || capture.barcodes.isEmpty) return;
            final raw = capture.barcodes.first.rawValue;
            if (raw == null) return;
            found = true;
            Navigator.pop(context, raw);
          },
        ),
        IgnorePointer(
          child: Center(
            child: Container(
              width: 260,
              height: 260,
              decoration: BoxDecoration(
                border: Border.all(color: Colors.white, width: 3),
                borderRadius: BorderRadius.circular(24),
              ),
            ),
          ),
        ),
        const Positioned(
          left: 24,
          right: 24,
          bottom: 42,
          child: Card(
            child: Padding(
              padding: EdgeInsets.all(16),
              child: Text(
                'Arahkan kamera ke QR “Hubungkan aplikasi” di dashboard.',
                textAlign: TextAlign.center,
              ),
            ),
          ),
        ),
      ],
    ),
  );
}

class LoginScreen extends StatefulWidget {
  final Future<void> Function(Map<String, dynamic>, [String?]) onSignedIn;
  const LoginScreen({super.key, required this.onSignedIn});
  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final email = TextEditingController();
  final password = TextEditingController();
  bool busy = false, hidden = true;
  String? error;
  Future<void> scan() async {
    final value = await Navigator.of(
      context,
    ).push<String>(MaterialPageRoute(builder: (_) => const PairingScanner()));
    if (value == null || !mounted) return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final payload = jsonDecode(value) as Map<String, dynamic>;
      final server = (payload['server'] ?? '').toString().replaceAll(
        RegExp(r'/+$'),
        '',
      );
      final token = (payload['token'] ?? '').toString();
      if (payload['v'] != 1 ||
          !Uri.parse(server).isScheme('https') ||
          token.isEmpty) {
        throw const FormatException();
      }
      final base = '$server/api/v1';
      final result = await ApiClient(
        null,
        base,
      ).post('/auth/pair', {'token': token, 'device_name': 'Android'});
      await widget.onSignedIn(result, base);
    } on ApiException catch (e) {
      setState(() => error = e.message);
    } catch (_) {
      setState(() => error = 'QR tidak valid atau tidak dapat dihubungi.');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> submit() async {
    if (email.text.trim().isEmpty || password.text.isEmpty) return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await widget.onSignedIn(
        await ApiClient().login(email.text.trim(), password.text),
      );
    } on ApiException catch (e) {
      setState(() => error = e.message);
    } catch (_) {
      setState(() => error = 'Tidak dapat terhubung ke layanan.');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    body: SafeArea(
      child: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 440),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(
                  width: 52,
                  height: 52,
                  decoration: BoxDecoration(
                    color: Theme.of(context).colorScheme.primary,
                    borderRadius: BorderRadius.circular(16),
                  ),
                  child: const Icon(Icons.forum_outlined, color: Colors.white),
                ),
                const SizedBox(height: 32),
                Text(
                  'Selamat datang',
                  style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                    fontWeight: FontWeight.w800,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  'Masuk untuk menangani aduan dan percakapan yang ditugaskan kepada Anda.',
                  style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                    height: 1.5,
                  ),
                ),
                const SizedBox(height: 32),
                SizedBox(
                  width: double.infinity,
                  height: 54,
                  child: FilledButton.icon(
                    onPressed: busy ? null : scan,
                    icon: const Icon(Icons.qr_code_scanner),
                    label: const Text('Pindai QR dari dashboard'),
                  ),
                ),
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 22),
                  child: Row(
                    children: [
                      Expanded(child: Divider()),
                      Padding(
                        padding: EdgeInsets.symmetric(horizontal: 14),
                        child: Text('atau masuk manual'),
                      ),
                      Expanded(child: Divider()),
                    ],
                  ),
                ),
                TextField(
                  controller: email,
                  keyboardType: TextInputType.emailAddress,
                  textInputAction: TextInputAction.next,
                  decoration: const InputDecoration(
                    labelText: 'Email',
                    prefixIcon: Icon(Icons.mail_outline),
                  ),
                ),
                const SizedBox(height: 14),
                TextField(
                  controller: password,
                  obscureText: hidden,
                  onSubmitted: (_) => submit(),
                  decoration: InputDecoration(
                    labelText: 'Kata sandi',
                    prefixIcon: const Icon(Icons.lock_outline),
                    suffixIcon: IconButton(
                      onPressed: () => setState(() => hidden = !hidden),
                      icon: Icon(
                        hidden
                            ? Icons.visibility_outlined
                            : Icons.visibility_off_outlined,
                      ),
                    ),
                  ),
                ),
                if (error != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 14),
                    child: Text(
                      error!,
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.error,
                      ),
                    ),
                  ),
                const SizedBox(height: 22),
                SizedBox(
                  width: double.infinity,
                  height: 52,
                  child: FilledButton(
                    onPressed: busy ? null : submit,
                    child: busy
                        ? const SizedBox(
                            width: 22,
                            height: 22,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Text('Masuk'),
                  ),
                ),
                const SizedBox(height: 18),
                Center(
                  child: Text(
                    'Gunakan akun resmi yang diberikan Admin Pusat.',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    ),
  );
}

class HomeShell extends StatefulWidget {
  final ApiClient api;
  final Map<String, dynamic> profile;
  final VoidCallback onTheme;
  final Future<void> Function() onSignOut;
  const HomeShell({
    super.key,
    required this.api,
    required this.profile,
    required this.onTheme,
    required this.onSignOut,
  });
  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  int index = 0;
  int unread = 0;
  Timer? notificationTimer;
  StreamSubscription<int>? notificationTapSubscription;
  final ticketKey = GlobalKey<TicketListScreenState>();
  @override
  void initState() {
    super.initState();
    unread = (widget.profile['unread'] as num?)?.toInt() ?? 0;
    checkNotifications();
    notificationTimer = Timer.periodic(
      const Duration(seconds: 20),
      (_) => checkNotifications(),
    );
    notificationTapSubscription = MobileNotifications.ticketClicks.stream
        .listen(openNotificationTicket);
    final pending = MobileNotifications.pendingTicketId;
    if (pending != null) {
      MobileNotifications.pendingTicketId = null;
      WidgetsBinding.instance.addPostFrameCallback(
        (_) => openNotificationTicket(pending),
      );
    }
  }

  void openNotificationTicket(int ticketId) {
    if (!mounted) return;
    MobileNotifications.pendingTicketId = null;
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => TicketDetailScreen(api: widget.api, ticketId: ticketId),
      ),
    );
  }

  Future<void> checkNotifications() async {
    try {
      final count = await MobileNotifications.poll(widget.api);
      if (mounted) setState(() => unread = count);
    } catch (_) {}
  }

  @override
  void dispose() {
    notificationTimer?.cancel();
    notificationTapSubscription?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final pages = [
      DashboardScreen(
        api: widget.api,
        onOpenTickets: () => setState(() => index = 1),
      ),
      TicketListScreen(key: ticketKey, api: widget.api),
      NotificationScreen(api: widget.api),
      ProfileScreen(
        profile: widget.profile,
        onTheme: widget.onTheme,
        onSignOut: widget.onSignOut,
      ),
    ];
    return Scaffold(
      body: IndexedStack(index: index, children: pages),
      bottomNavigationBar: NavigationBar(
        selectedIndex: index,
        onDestinationSelected: (value) {
          setState(() {
            index = value;
            if (value == 2) unread = 0;
          });
          if (value == 1) ticketKey.currentState?.reload();
        },
        destinations: [
          const NavigationDestination(
            icon: Icon(Icons.space_dashboard_outlined),
            selectedIcon: Icon(Icons.space_dashboard),
            label: 'Ringkasan',
          ),
          const NavigationDestination(
            icon: Icon(Icons.inbox_outlined),
            selectedIcon: Icon(Icons.inbox),
            label: 'Aduan',
          ),
          NavigationDestination(
            icon: Badge(
              isLabelVisible: unread > 0,
              label: Text(unread > 99 ? '99+' : '$unread'),
              child: const Icon(Icons.notifications_none),
            ),
            selectedIcon: const Icon(Icons.notifications),
            label: 'Notifikasi',
          ),
          const NavigationDestination(
            icon: Icon(Icons.person_outline),
            selectedIcon: Icon(Icons.person),
            label: 'Profil',
          ),
        ],
      ),
    );
  }
}

class PageHeader extends StatelessWidget {
  final String eyebrow, title, subtitle;
  const PageHeader({
    super.key,
    required this.eyebrow,
    required this.title,
    required this.subtitle,
  });
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.fromLTRB(20, 18, 20, 14),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          eyebrow.toUpperCase(),
          style: TextStyle(
            color: Theme.of(context).colorScheme.primary,
            fontSize: 11,
            letterSpacing: 1.3,
            fontWeight: FontWeight.w700,
          ),
        ),
        const SizedBox(height: 6),
        Text(
          title,
          style: Theme.of(
            context,
          ).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800),
        ),
        const SizedBox(height: 5),
        Text(
          subtitle,
          style: TextStyle(
            color: Theme.of(context).colorScheme.onSurfaceVariant,
          ),
        ),
      ],
    ),
  );
}

class DashboardScreen extends StatefulWidget {
  final ApiClient api;
  final VoidCallback onOpenTickets;
  const DashboardScreen({
    super.key,
    required this.api,
    required this.onOpenTickets,
  });
  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  Map<String, dynamic>? counts;
  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    final data = await widget.api.get('/dashboard');
    if (mounted) setState(() => counts = data['counts']);
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    body: SafeArea(
      child: RefreshIndicator(
        onRefresh: load,
        child: ListView(
          children: [
            const PageHeader(
              eyebrow: 'Workspace',
              title: 'Ringkasan layanan',
              subtitle: 'Aduan yang berada dalam kewenangan Anda.',
            ),
            if (counts == null)
              const Padding(
                padding: EdgeInsets.all(40),
                child: Center(child: CircularProgressIndicator()),
              )
            else
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 20),
                child: GridView.count(
                  shrinkWrap: true,
                  physics: const NeverScrollableScrollPhysics(),
                  crossAxisCount: 2,
                  mainAxisSpacing: 12,
                  crossAxisSpacing: 12,
                  childAspectRatio: 1.4,
                  children: [
                    MetricCard(
                      label: 'Semua aduan',
                      value: counts!['all'],
                      icon: Icons.inbox_outlined,
                    ),
                    MetricCard(
                      label: 'Ditugaskan',
                      value: counts!['assigned'],
                      icon: Icons.assignment_ind_outlined,
                    ),
                    MetricCard(
                      label: 'Diproses',
                      value: counts!['in_progress'],
                      icon: Icons.timelapse,
                    ),
                    MetricCard(
                      label: 'Menunggu',
                      value: counts!['waiting'],
                      icon: Icons.schedule_outlined,
                    ),
                  ],
                ),
              ),
            Padding(
              padding: const EdgeInsets.all(20),
              child: FilledButton.icon(
                onPressed: widget.onOpenTickets,
                icon: const Icon(Icons.arrow_forward),
                label: const Text('Buka daftar aduan'),
              ),
            ),
          ],
        ),
      ),
    ),
  );
}

class MetricCard extends StatelessWidget {
  final String label;
  final dynamic value;
  final IconData icon;
  const MetricCard({
    super.key,
    required this.label,
    required this.value,
    required this.icon,
  });
  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Icon(icon, color: Theme.of(context).colorScheme.primary),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '${value ?? 0}',
                style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                  fontWeight: FontWeight.w800,
                ),
              ),
              Text(label, style: Theme.of(context).textTheme.bodySmall),
            ],
          ),
        ],
      ),
    ),
  );
}

class TicketListScreen extends StatefulWidget {
  final ApiClient api;
  const TicketListScreen({super.key, required this.api});
  @override
  State<TicketListScreen> createState() => TicketListScreenState();
}

class TicketListScreenState extends State<TicketListScreen> {
  List<dynamic> tickets = [];
  bool loading = true;
  String query = '';
  @override
  void initState() {
    super.initState();
    reload();
  }

  Future<void> reload() async {
    setState(() => loading = true);
    try {
      final result = await widget.api.get(
        '/tickets',
        query.isEmpty ? null : {'q': query},
      );
      if (mounted) setState(() => tickets = result['tickets']);
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    body: SafeArea(
      child: Column(
        children: [
          const PageHeader(
            eyebrow: 'Penugasan',
            title: 'Daftar aduan',
            subtitle: 'Hanya aduan yang boleh Anda tangani.',
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 0, 20, 14),
            child: TextField(
              onChanged: (value) => query = value,
              onSubmitted: (_) => reload(),
              decoration: InputDecoration(
                hintText: 'Cari nomor atau pelapor',
                prefixIcon: const Icon(Icons.search),
                suffixIcon: IconButton(
                  onPressed: reload,
                  icon: const Icon(Icons.arrow_forward),
                ),
              ),
            ),
          ),
          Expanded(
            child: loading
                ? const Center(child: CircularProgressIndicator())
                : RefreshIndicator(
                    onRefresh: reload,
                    child: tickets.isEmpty
                        ? ListView(
                            children: const [
                              EmptyState(
                                icon: Icons.inbox_outlined,
                                title: 'Belum ada penugasan',
                                body:
                                    'Aduan akan muncul setelah Admin Pusat melakukan disposisi.',
                              ),
                            ],
                          )
                        : ListView.separated(
                            padding: const EdgeInsets.fromLTRB(20, 4, 20, 24),
                            itemCount: tickets.length,
                            separatorBuilder: (_, _) =>
                                const SizedBox(height: 10),
                            itemBuilder: (_, index) => TicketCard(
                              ticket: tickets[index],
                              onTap: () async {
                                await Navigator.push(
                                  context,
                                  MaterialPageRoute(
                                    builder: (_) => TicketDetailScreen(
                                      api: widget.api,
                                      ticketId: tickets[index]['id'],
                                    ),
                                  ),
                                );
                                reload();
                              },
                            ),
                          ),
                  ),
          ),
        ],
      ),
    ),
  );
}

class TicketCard extends StatelessWidget {
  final Map<String, dynamic> ticket;
  final VoidCallback onTap;
  const TicketCard({super.key, required this.ticket, required this.onTap});
  @override
  Widget build(BuildContext context) => Card(
    child: InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(12),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    ticket['code'],
                    style: const TextStyle(fontWeight: FontWeight.w800),
                  ),
                ),
                StatusChip(ticket['status']),
              ],
            ),
            const SizedBox(height: 10),
            Text(
              ticket['subject'],
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(
                context,
              ).textTheme.bodyLarge?.copyWith(fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Icon(
                  ticket['channel'] == 'email'
                      ? Icons.email_outlined
                      : Icons.chat_outlined,
                  size: 16,
                ),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    ticket['contact']['name'],
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ),
                Text(
                  ticket['unit'] ?? 'Belum didisposisikan',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ],
            ),
          ],
        ),
      ),
    ),
  );
}

class StatusChip extends StatelessWidget {
  final String status;
  const StatusChip(this.status, {super.key});
  @override
  Widget build(BuildContext context) {
    final color = switch (status) {
      'resolved' || 'closed' => Colors.green,
      'in_progress' => Colors.orange,
      'waiting' => Colors.purple,
      _ => Theme.of(context).colorScheme.primary,
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
      decoration: BoxDecoration(
        color: color.withValues(alpha: .12),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Text(
        status.replaceAll('_', ' '),
        style: TextStyle(
          color: color,
          fontSize: 11,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}

class TicketDetailScreen extends StatefulWidget {
  final ApiClient api;
  final int ticketId;
  const TicketDetailScreen({
    super.key,
    required this.api,
    required this.ticketId,
  });
  @override
  State<TicketDetailScreen> createState() => _TicketDetailScreenState();
}

class _TicketDetailScreenState extends State<TicketDetailScreen> {
  Map<String, dynamic>? data;
  bool loading = true, sending = false;
  final text = TextEditingController();
  final scroll = ScrollController();
  Timer? timer;
  PlatformFile? attachment;
  @override
  void initState() {
    super.initState();
    load();
    timer = Timer.periodic(
      const Duration(seconds: 8),
      (_) => load(silent: true),
    );
  }

  @override
  void dispose() {
    timer?.cancel();
    text.dispose();
    scroll.dispose();
    super.dispose();
  }

  Future<void> load({bool silent = false}) async {
    if (!silent) setState(() => loading = true);
    try {
      final result = await widget.api.get('/tickets/${widget.ticketId}');
      if (mounted) {
        setState(() => data = result);
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (scroll.hasClients) scroll.jumpTo(scroll.position.maxScrollExtent);
        });
      }
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> send() async {
    if (text.text.trim().isEmpty && attachment == null) return;
    setState(() => sending = true);
    try {
      await widget.api.reply(
        widget.ticketId,
        text.text.trim(),
        attachmentPath: attachment?.path,
      );
      text.clear();
      setState(() => attachment = null);
      await load(silent: true);
    } on ApiException catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(e.message)));
      }
    } finally {
      if (mounted) setState(() => sending = false);
    }
  }

  Future<void> pick() async {
    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: const [
        'jpg',
        'jpeg',
        'png',
        'webp',
        'mp4',
        'mp3',
        'ogg',
        'pdf',
      ],
    );
    if (result != null && result.files.single.path != null) {
      setState(() => attachment = result.files.single);
    }
  }

  Future<void> updateStatus(String status) async {
    try {
      await widget.api.post('/tickets/${widget.ticketId}/status', {
        'status': status,
      });
      await load(silent: true);
    } on ApiException catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(error.message)));
      }
    }
  }

  Future<void> assign() async {
    final options = await widget.api.get('/assignment-options');
    if (!mounted) return;
    int? unitId;
    int? assigneeId;
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, updateDialog) {
          final unit = unitId == null
              ? null
              : (options['units'] as List).firstWhere(
                  (item) => item['id'] == unitId,
                );
          final users = (options['users'] as List)
              .where((user) => unit != null && user['unit'] == unit['name'])
              .toList();
          return AlertDialog(
            title: const Text('Disposisikan aduan'),
            content: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                DropdownButtonFormField<int>(
                  initialValue: unitId,
                  decoration: const InputDecoration(labelText: 'Unit / bidang'),
                  items: (options['units'] as List)
                      .map<DropdownMenuItem<int>>(
                        (item) => DropdownMenuItem(
                          value: item['id'],
                          child: Text(item['name']),
                        ),
                      )
                      .toList(),
                  onChanged: (value) => updateDialog(() {
                    unitId = value;
                    assigneeId = null;
                  }),
                ),
                const SizedBox(height: 14),
                DropdownButtonFormField<int>(
                  initialValue: assigneeId,
                  decoration: const InputDecoration(
                    labelText: 'Petugas (opsional)',
                  ),
                  items: users
                      .map<DropdownMenuItem<int>>(
                        (item) => DropdownMenuItem(
                          value: item['id'],
                          child: Text(item['name']),
                        ),
                      )
                      .toList(),
                  onChanged: unitId == null
                      ? null
                      : (value) => updateDialog(() => assigneeId = value),
                ),
              ],
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(dialogContext),
                child: const Text('Batal'),
              ),
              FilledButton(
                onPressed: unitId == null
                    ? null
                    : () async {
                        await widget.api.post(
                          '/tickets/${widget.ticketId}/assign',
                          {'unit_id': unitId, 'assignee_id': assigneeId},
                        );
                        if (dialogContext.mounted) Navigator.pop(dialogContext);
                      },
                child: const Text('Disposisikan'),
              ),
            ],
          );
        },
      ),
    );
    await load(silent: true);
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: Text(data?['ticket']?['code'] ?? 'Percakapan'),
      actions: [
        if (data?['can_manage'] == true)
          IconButton(
            onPressed: assign,
            tooltip: 'Disposisi',
            icon: const Icon(Icons.assignment_ind_outlined),
          ),
        if (data != null)
          PopupMenuButton<String>(
            tooltip: 'Ubah status',
            onSelected: updateStatus,
            itemBuilder: (_) => (data!['allowed_statuses'] as List)
                .map<PopupMenuEntry<String>>(
                  (status) => PopupMenuItem(
                    value: status,
                    child: Text(status.toString().replaceAll('_', ' ')),
                  ),
                )
                .toList(),
          ),
        IconButton(onPressed: () => load(), icon: const Icon(Icons.refresh)),
      ],
    ),
    body: loading
        ? const Center(child: CircularProgressIndicator())
        : Column(
            children: [
              Container(
                width: double.infinity,
                padding: const EdgeInsets.fromLTRB(20, 8, 20, 14),
                decoration: BoxDecoration(
                  border: Border(
                    bottom: BorderSide(color: Theme.of(context).dividerColor),
                  ),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      data!['ticket']['contact']['name'],
                      style: const TextStyle(fontWeight: FontWeight.w700),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      '${data!['ticket']['channel'] == 'email' ? 'Email' : 'WhatsApp'} · ${data!['ticket']['unit'] ?? '-'} · ${data!['ticket']['status'].replaceAll('_', ' ')}',
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                ),
              ),
              Expanded(
                child: ListView.builder(
                  controller: scroll,
                  padding: const EdgeInsets.all(16),
                  itemCount: data!['messages'].length,
                  itemBuilder: (_, i) =>
                      MessageBubble(message: data!['messages'][i]),
                ),
              ),
              if (data!['can_reply'])
                SafeArea(
                  top: false,
                  child: Container(
                    padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
                    decoration: BoxDecoration(
                      color: Theme.of(context).colorScheme.surface,
                      border: Border(
                        top: BorderSide(color: Theme.of(context).dividerColor),
                      ),
                    ),
                    child: Column(
                      children: [
                        if (attachment != null)
                          Row(
                            children: [
                              const Icon(Icons.attach_file, size: 18),
                              const SizedBox(width: 6),
                              Expanded(
                                child: Text(
                                  attachment!.name,
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                ),
                              ),
                              IconButton(
                                onPressed: () =>
                                    setState(() => attachment = null),
                                icon: const Icon(Icons.close, size: 18),
                              ),
                            ],
                          ),
                        Row(
                          crossAxisAlignment: CrossAxisAlignment.end,
                          children: [
                            IconButton(
                              onPressed: pick,
                              icon: const Icon(
                                Icons.add_photo_alternate_outlined,
                              ),
                            ),
                            Expanded(
                              child: TextField(
                                controller: text,
                                minLines: 1,
                                maxLines: 5,
                                decoration: const InputDecoration(
                                  hintText: 'Tulis balasan...',
                                  contentPadding: EdgeInsets.symmetric(
                                    horizontal: 14,
                                    vertical: 11,
                                  ),
                                ),
                              ),
                            ),
                            const SizedBox(width: 8),
                            IconButton.filled(
                              onPressed: sending ? null : send,
                              icon: sending
                                  ? const SizedBox(
                                      width: 20,
                                      height: 20,
                                      child: CircularProgressIndicator(
                                        strokeWidth: 2,
                                      ),
                                    )
                                  : const Icon(Icons.send),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                )
              else
                const SafeArea(
                  top: false,
                  child: Padding(
                    padding: EdgeInsets.all(16),
                    child: Text('Percakapan ini tidak dapat dibalas.'),
                  ),
                ),
            ],
          ),
  );
}

class MessageBubble extends StatelessWidget {
  final Map<String, dynamic> message;
  const MessageBubble({super.key, required this.message});
  @override
  Widget build(BuildContext context) {
    final outgoing = message['direction'] == 'out';
    final internal = message['internal'] == true;
    final bg = internal
        ? Colors.amber.withValues(alpha: .14)
        : outgoing
        ? Theme.of(context).colorScheme.primary
        : Theme.of(context).colorScheme.surfaceContainerHighest;
    final fg = outgoing && !internal
        ? Colors.white
        : Theme.of(context).colorScheme.onSurface;
    return Align(
      alignment: internal
          ? Alignment.center
          : outgoing
          ? Alignment.centerRight
          : Alignment.centerLeft,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 320),
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: bg,
          borderRadius: BorderRadius.circular(15),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              message['sender'] ?? '',
              style: TextStyle(fontSize: 10, color: fg.withValues(alpha: .72)),
            ),
            if ((message['body'] ?? '').isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 5),
                child: Text(
                  message['body'],
                  style: TextStyle(color: fg, height: 1.4),
                ),
              ),
            if (message['attachment_name'] != null)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(Icons.attach_file, size: 16, color: fg),
                    const SizedBox(width: 4),
                    Flexible(
                      child: Text(
                        message['attachment_name'],
                        style: TextStyle(color: fg, fontSize: 12),
                      ),
                    ),
                  ],
                ),
              ),
            const SizedBox(height: 5),
            Text(
              formatDate(message['created_at']),
              style: TextStyle(fontSize: 9, color: fg.withValues(alpha: .65)),
            ),
          ],
        ),
      ),
    );
  }
}

class NotificationScreen extends StatefulWidget {
  final ApiClient api;
  const NotificationScreen({super.key, required this.api});
  @override
  State<NotificationScreen> createState() => _NotificationScreenState();
}

class _NotificationScreenState extends State<NotificationScreen> {
  List<dynamic> items = [];
  bool loading = true;
  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    final result = await widget.api.get('/notifications');
    await widget.api.post('/notifications/read', {});
    if (mounted) {
      setState(() {
        items = result['notifications'];
        loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    body: SafeArea(
      child: Column(
        children: [
          const PageHeader(
            eyebrow: 'Aktivitas',
            title: 'Notifikasi',
            subtitle: 'Disposisi dan pesan terbaru untuk Anda.',
          ),
          Expanded(
            child: loading
                ? const Center(child: CircularProgressIndicator())
                : RefreshIndicator(
                    onRefresh: load,
                    child: items.isEmpty
                        ? ListView(
                            children: const [
                              EmptyState(
                                icon: Icons.notifications_none,
                                title: 'Belum ada notifikasi',
                                body:
                                    'Pembaruan penugasan akan tampil di sini.',
                              ),
                            ],
                          )
                        : ListView.separated(
                            padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
                            itemCount: items.length,
                            separatorBuilder: (_, _) =>
                                const Divider(height: 1),
                            itemBuilder: (_, index) {
                              final item = items[index];
                              return ListTile(
                                contentPadding: const EdgeInsets.symmetric(
                                  vertical: 8,
                                ),
                                leading: CircleAvatar(
                                  child: Icon(
                                    item['read']
                                        ? Icons.notifications_none
                                        : Icons.notifications_active_outlined,
                                  ),
                                ),
                                title: Text(
                                  item['title'],
                                  style: const TextStyle(
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                                subtitle: Padding(
                                  padding: const EdgeInsets.only(top: 5),
                                  child: Text(
                                    '${item['body'] ?? ''}\n${formatDate(item['created_at'])}',
                                  ),
                                ),
                                onTap: item['ticket_id'] == null
                                    ? null
                                    : () => Navigator.push(
                                        context,
                                        MaterialPageRoute(
                                          builder: (_) => TicketDetailScreen(
                                            api: widget.api,
                                            ticketId: item['ticket_id'],
                                          ),
                                        ),
                                      ),
                              );
                            },
                          ),
                  ),
          ),
        ],
      ),
    ),
  );
}

class ProfileScreen extends StatelessWidget {
  final Map<String, dynamic> profile;
  final VoidCallback onTheme;
  final Future<void> Function() onSignOut;
  const ProfileScreen({
    super.key,
    required this.profile,
    required this.onTheme,
    required this.onSignOut,
  });
  @override
  Widget build(BuildContext context) {
    final user = profile['user'];
    final organization = profile['organization'];
    return Scaffold(
      body: SafeArea(
        child: ListView(
          children: [
            const PageHeader(
              eyebrow: 'Akun',
              title: 'Profil',
              subtitle: 'Identitas dan akses workspace Anda.',
            ),
            Padding(
              padding: const EdgeInsets.all(20),
              child: Column(
                children: [
                  Card(
                    child: Padding(
                      padding: const EdgeInsets.all(20),
                      child: Column(
                        children: [
                          CircleAvatar(
                            radius: 34,
                            child: Text(
                              (user['name'] as String)
                                  .substring(0, 1)
                                  .toUpperCase(),
                              style: const TextStyle(
                                fontSize: 24,
                                fontWeight: FontWeight.w800,
                              ),
                            ),
                          ),
                          const SizedBox(height: 14),
                          Text(
                            user['name'],
                            style: Theme.of(context).textTheme.titleLarge
                                ?.copyWith(fontWeight: FontWeight.w800),
                          ),
                          const SizedBox(height: 4),
                          Text(user['email']),
                          const SizedBox(height: 12),
                          StatusChip(user['role']),
                          const Divider(height: 32),
                          InfoRow(
                            label: 'Organisasi',
                            value: organization['name'],
                          ),
                          InfoRow(
                            label: 'Unit / bidang',
                            value: user['unit'].toString().isEmpty
                                ? '-'
                                : user['unit'],
                          ),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                  ListTile(
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                    tileColor: Theme.of(context).colorScheme.surface,
                    leading: const Icon(Icons.contrast),
                    title: const Text('Ganti tema'),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: onTheme,
                  ),
                  const SizedBox(height: 10),
                  ListTile(
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                    tileColor: Theme.of(context).colorScheme.surface,
                    leading: const Icon(Icons.notifications_outlined),
                    title: const Text('Pengaturan notifikasi'),
                    subtitle: const Text('Suara, getar, dan alert background'),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () => Navigator.push(
                      context,
                      MaterialPageRoute(
                        builder: (_) => const NotificationPreferencesScreen(),
                      ),
                    ),
                  ),
                  const SizedBox(height: 10),
                  ListTile(
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                    tileColor: Theme.of(context).colorScheme.surface,
                    leading: Icon(
                      Icons.logout,
                      color: Theme.of(context).colorScheme.error,
                    ),
                    title: Text(
                      'Keluar',
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.error,
                      ),
                    ),
                    onTap: onSignOut,
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class NotificationPreferencesScreen extends StatefulWidget {
  const NotificationPreferencesScreen({super.key});
  @override
  State<NotificationPreferencesScreen> createState() =>
      _NotificationPreferencesScreenState();
}

class _NotificationPreferencesScreenState
    extends State<NotificationPreferencesScreen> {
  bool enabled = true, sound = true, vibration = true, loading = true;
  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    final prefs = await SharedPreferences.getInstance();
    if (!mounted) return;
    setState(() {
      enabled = prefs.getBool('notifications_enabled') ?? true;
      sound = prefs.getBool('notification_sound') ?? true;
      vibration = prefs.getBool('notification_vibration') ?? true;
      loading = false;
    });
  }

  Future<void> save(String key, bool value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(key, value);
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Pengaturan notifikasi')),
    body: loading
        ? const Center(child: CircularProgressIndicator())
        : ListView(
            padding: const EdgeInsets.all(20),
            children: [
              Card(
                child: Column(
                  children: [
                    SwitchListTile(
                      title: const Text('Aktifkan notifikasi'),
                      subtitle: const Text(
                        'Tampilkan alert untuk aduan dan pesan baru.',
                      ),
                      value: enabled,
                      onChanged: (value) {
                        setState(() => enabled = value);
                        save('notifications_enabled', value);
                      },
                    ),
                    const Divider(height: 1),
                    SwitchListTile(
                      title: const Text('Suara'),
                      subtitle: const Text('Gunakan suara notifikasi Android.'),
                      value: sound,
                      onChanged: enabled
                          ? (value) {
                              setState(() => sound = value);
                              save('notification_sound', value);
                            }
                          : null,
                    ),
                    const Divider(height: 1),
                    SwitchListTile(
                      title: const Text('Getar'),
                      subtitle: const Text(
                        'Getarkan perangkat saat alert masuk.',
                      ),
                      value: vibration,
                      onChanged: enabled
                          ? (value) {
                              setState(() => vibration = value);
                              save('notification_vibration', value);
                            }
                          : null,
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 16),
              SizedBox(
                height: 50,
                child: OutlinedButton.icon(
                  onPressed: enabled
                      ? () => MobileNotifications.show(
                          id: 999999,
                          title: 'Uji notifikasi',
                          body: 'Notifikasi AduanHub aktif pada perangkat ini.',
                          sound: sound,
                          vibration: vibration,
                        )
                      : null,
                  icon: const Icon(Icons.notifications_active_outlined),
                  label: const Text('Uji notifikasi'),
                ),
              ),
              const Padding(
                padding: EdgeInsets.only(top: 18),
                child: Text(
                  'Saat aplikasi terbuka, pembaruan diperiksa setiap 20 detik. Saat berjalan di background, Android menjadwalkan pemeriksaan berkala sekitar 15 menit.',
                  style: TextStyle(height: 1.5),
                ),
              ),
            ],
          ),
  );
}

class InfoRow extends StatelessWidget {
  final String label, value;
  const InfoRow({super.key, required this.label, required this.value});
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 7),
    child: Row(
      children: [
        Expanded(
          child: Text(label, style: Theme.of(context).textTheme.bodySmall),
        ),
        Flexible(
          child: Text(
            value,
            textAlign: TextAlign.right,
            style: const TextStyle(fontWeight: FontWeight.w600),
          ),
        ),
      ],
    ),
  );
}

class EmptyState extends StatelessWidget {
  final IconData icon;
  final String title, body;
  const EmptyState({
    super.key,
    required this.icon,
    required this.title,
    required this.body,
  });
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.all(48),
    child: Column(
      children: [
        Icon(icon, size: 44, color: Theme.of(context).colorScheme.outline),
        const SizedBox(height: 14),
        Text(title, style: const TextStyle(fontWeight: FontWeight.w700)),
        const SizedBox(height: 7),
        Text(
          body,
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.bodySmall,
        ),
      ],
    ),
  );
}

String formatDate(dynamic value) {
  if (value == null) return '';
  try {
    return DateFormat(
      'dd MMM, HH:mm',
    ).format(DateTime.parse(value.toString().replaceFirst(' ', 'T')).toLocal());
  } catch (_) {
    return value.toString();
  }
}
