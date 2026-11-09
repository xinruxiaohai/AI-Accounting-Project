import 'package:flutter/material.dart';

import '../utils/request.dart';
import '../utils/theme.dart';
import 'home.dart';

/// 登录页：邮箱 + 密码 → POST /api/auth/login → 保存 JWT → 进入首页。
class LoginPage extends StatefulWidget {
  const LoginPage({super.key});

  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
  final GlobalKey<FormState> _formKey = GlobalKey<FormState>();
  final TextEditingController _emailController = TextEditingController();
  final TextEditingController _passwordController = TextEditingController();

  bool _submitting = false;
  bool _obscure = true;
  String? _error;

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_submitting) {
      return;
    }
    if (!(_formKey.currentState?.validate() ?? false)) {
      return;
    }
    setState(() {
      _submitting = true;
      _error = null;
    });
    try {
      final Map<String, dynamic> data = await ApiClient.post(
        '/auth/login',
        data: <String, String>{
          'email': _emailController.text.trim(),
          'password': _passwordController.text,
        },
      );
      final String token = (data['token'] ?? '').toString();
      if (token.isEmpty) {
        throw const ApiException('登录成功但服务器没有返回 Token');
      }
      final dynamic rawUser = data['user'];
      final String email = rawUser is Map
          ? (rawUser['email'] ?? _emailController.text.trim()).toString()
          : _emailController.text.trim();
      await ApiClient.saveSession(token, email: email);
      if (!mounted) {
        return;
      }
      Navigator.of(context).pushReplacement(
        MaterialPageRoute<void>(
          builder: (BuildContext context) => const HomePage(),
        ),
      );
    } on ApiException catch (error) {
      if (mounted) {
        setState(() => _error = error.message);
      }
    } catch (error) {
      if (mounted) {
        setState(() => _error = '登录失败：$error');
      }
    } finally {
      if (mounted) {
        setState(() => _submitting = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: ZhColors.surface,
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 32),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Form(
                key: _formKey,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  mainAxisSize: MainAxisSize.min,
                  children: <Widget>[
                    const Icon(Icons.account_balance_wallet,
                        size: 56, color: ZhColors.brand),
                    const SizedBox(height: 16),
                    const Text(
                      '智汇账',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        fontSize: 28,
                        fontWeight: FontWeight.w700,
                        color: ZhColors.textStrong,
                      ),
                    ),
                    const SizedBox(height: 6),
                    const Text(
                      '登录以同步你的云端账本',
                      textAlign: TextAlign.center,
                      style: TextStyle(fontSize: 13, color: ZhColors.textMuted),
                    ),
                    const SizedBox(height: 32),
                    TextFormField(
                      controller: _emailController,
                      keyboardType: TextInputType.emailAddress,
                      autocorrect: false,
                      decoration: const InputDecoration(
                        labelText: '邮箱',
                        prefixIcon: Icon(Icons.email_outlined),
                        border: OutlineInputBorder(),
                        filled: true,
                        fillColor: Colors.white,
                      ),
                      validator: (String? value) {
                        final String text = (value ?? '').trim();
                        if (text.isEmpty) {
                          return '请输入邮箱';
                        }
                        if (!text.contains('@')) {
                          return '邮箱格式不正确';
                        }
                        return null;
                      },
                    ),
                    const SizedBox(height: 16),
                    TextFormField(
                      controller: _passwordController,
                      obscureText: _obscure,
                      decoration: InputDecoration(
                        labelText: '密码',
                        prefixIcon: const Icon(Icons.lock_outline),
                        border: const OutlineInputBorder(),
                        filled: true,
                        fillColor: Colors.white,
                        suffixIcon: IconButton(
                          icon: Icon(
                            _obscure ? Icons.visibility_off : Icons.visibility,
                          ),
                          onPressed: () =>
                              setState(() => _obscure = !_obscure),
                        ),
                      ),
                      validator: (String? value) =>
                          (value ?? '').isEmpty ? '请输入密码' : null,
                      onFieldSubmitted: (String _) => _submit(),
                    ),
                    if (_error != null) ...<Widget>[
                      const SizedBox(height: 14),
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: ZhColors.expenseSoft,
                          borderRadius: BorderRadius.circular(10),
                          border: Border.all(color: ZhColors.expense),
                        ),
                        child: Text(
                          _error!,
                          style: const TextStyle(
                              color: ZhColors.expense, fontSize: 13),
                        ),
                      ),
                    ],
                    const SizedBox(height: 22),
                    SizedBox(
                      height: 48,
                      child: FilledButton(
                        onPressed: _submitting ? null : _submit,
                        child: _submitting
                            ? const SizedBox(
                                width: 20,
                                height: 20,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  color: Colors.white,
                                ),
                              )
                            : const Text('登录', style: TextStyle(fontSize: 15)),
                      ),
                    ),
                    const SizedBox(height: 18),
                    Text(
                      '当前服务器：${ApiClient.baseUrl}',
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                          fontSize: 11, color: ZhColors.textMuted),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
