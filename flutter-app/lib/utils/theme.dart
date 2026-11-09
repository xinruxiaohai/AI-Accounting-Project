import 'package:flutter/material.dart';

/// 沿用 Web 端 static/style.css 的红 / 绿 / 灰语义色：
///   支出、负数 → 红；收入、正数 → 绿；中性、转账、辅助文字 → 灰。
class ZhColors {
  const ZhColors._();

  static const Color expense = Color(0xFFDC2626); // --color-expense
  static const Color expenseSoft = Color(0xFFFEF2F2);
  static const Color income = Color(0xFF047857); // --color-income
  static const Color incomeSoft = Color(0xFFECFDF5);
  static const Color neutral = Color(0xFF64748B); // --color-transfer
  static const Color neutralSoft = Color(0xFFF1F5F9);
  static const Color textStrong = Color(0xFF0F172A);
  static const Color textMuted = Color(0xFF64748B);
  static const Color surface = Color(0xFFF8FAFC);
  static const Color line = Color(0xFFE6EBF2);
  static const Color brand = Color(0xFF2563EB);
}

/// 千分位 + 两位小数，和 Web 端金额口径保持一致（不引入 intl 依赖）。
String formatMoney(num value) {
  final String fixed = value.abs().toStringAsFixed(2);
  final List<String> parts = fixed.split('.');
  final String integer = parts[0];
  final StringBuffer buffer = StringBuffer();
  for (int i = 0; i < integer.length; i++) {
    if (i > 0 && (integer.length - i) % 3 == 0) {
      buffer.write(',');
    }
    buffer.write(integer[i]);
  }
  final String sign = value < 0 ? '-' : '';
  return '$sign${buffer.toString()}.${parts[1]}';
}
