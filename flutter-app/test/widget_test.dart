import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:zhihuizhang_app/main.dart';

void main() {
  testWidgets('未登录时进入登录页', (WidgetTester tester) async {
    await tester.pumpWidget(const ZhihuizhangApp(signedIn: false));

    expect(find.text('智汇账'), findsOneWidget);
    expect(find.text('登录'), findsOneWidget);
    expect(find.byType(TextFormField), findsNWidgets(2));
  });
}
