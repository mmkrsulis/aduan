import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/material.dart';
import 'package:aduanhub_mobile/main.dart';

void main() {
  testWidgets('renders flat metric card', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: MetricCard(
            label: 'Aduan',
            value: 3,
            icon: Icons.inbox_outlined,
          ),
        ),
      ),
    );
    expect(find.text('Aduan'), findsOneWidget);
    expect(find.text('3'), findsOneWidget);
  });
}
