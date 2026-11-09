import 'package:flutter/material.dart';

import 'pages/home.dart';
import 'pages/login.dart';
import 'utils/request.dart';
import 'utils/theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await ApiClient.init();
  final String token = await ApiClient.getToken();
  runApp(ZhihuizhangApp(signedIn: token.isNotEmpty));
}

class ZhihuizhangApp extends StatelessWidget {
  const ZhihuizhangApp({super.key, required this.signedIn});

  final bool signedIn;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '智汇账',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(seedColor: ZhColors.brand),
        scaffoldBackgroundColor: ZhColors.surface,
        appBarTheme: const AppBarTheme(
          backgroundColor: Colors.white,
          foregroundColor: ZhColors.textStrong,
        ),
      ),
      home: signedIn ? const HomePage() : const LoginPage(),
    );
  }
}
