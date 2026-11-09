import 'package:flutter/material.dart';

import '../utils/request.dart';
import '../utils/theme.dart';
import 'login.dart';

/// 首页看板：总净资产大数字 + 收入/支出/待报销三卡 + 原生底部 TabBar 导航。
class HomePage extends StatefulWidget {
  const HomePage({super.key});

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  int _index = 0;
  bool _loading = true;
  String? _error;
  String _email = '';
  Map<String, dynamic> _stats = const <String, dynamic>{};

  @override
  void initState() {
    super.initState();
    _load();
  }

  double _num(String key) {
    final dynamic value = _stats[key];
    if (value is num) {
      return value.toDouble();
    }
    return double.tryParse((value ?? '').toString()) ?? 0.0;
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      // GET /api/statistics：income_total / expense_total / balance_total /
      // reimbursement_pending / reimbursement_done
      final Map<String, dynamic> stats = await ApiClient.get('/statistics');
      final String email = await ApiClient.getEmail();
      if (!mounted) {
        return;
      }
      setState(() {
        _stats = stats;
        _email = email;
        _loading = false;
      });
    } on ApiException catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _error = error.message;
        _loading = false;
      });
    } catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _error = '数据加载失败：$error';
        _loading = false;
      });
    }
  }

  Future<void> _logout() async {
    await ApiClient.clearSession();
    if (!mounted) {
      return;
    }
    Navigator.of(context).pushReplacement(
      MaterialPageRoute<void>(
        builder: (BuildContext context) => const LoginPage(),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('智汇账'),
        backgroundColor: Colors.white,
        foregroundColor: ZhColors.textStrong,
        elevation: 0.5,
        actions: <Widget>[
          IconButton(
            tooltip: '刷新',
            icon: const Icon(Icons.refresh),
            onPressed: _loading ? null : _load,
          ),
        ],
      ),
      body: IndexedStack(
        index: _index,
        children: <Widget>[
          _buildDashboard(),
          _buildBills(),
          _buildProfile(),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (int value) => setState(() => _index = value),
        destinations: const <NavigationDestination>[
          NavigationDestination(
            icon: Icon(Icons.home_outlined),
            selectedIcon: Icon(Icons.home),
            label: '首页',
          ),
          NavigationDestination(
            icon: Icon(Icons.receipt_long_outlined),
            selectedIcon: Icon(Icons.receipt_long),
            label: '账单',
          ),
          NavigationDestination(
            icon: Icon(Icons.person_outline),
            selectedIcon: Icon(Icons.person),
            label: '我的',
          ),
        ],
      ),
    );
  }

  Widget _buildDashboard() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null) {
      return _buildErrorState();
    }
    final double balance = _num('balance_total');
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(16),
        children: <Widget>[
          _buildAssetCard(balance),
          const SizedBox(height: 16),
          Row(
            children: <Widget>[
              Expanded(
                child: _StatCard(
                  label: '总收入',
                  value: _num('income_total'),
                  color: ZhColors.income,
                  background: ZhColors.incomeSoft,
                  icon: Icons.arrow_downward,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: _StatCard(
                  label: '总支出',
                  value: _num('expense_total'),
                  color: ZhColors.expense,
                  background: ZhColors.expenseSoft,
                  icon: Icons.arrow_upward,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: _StatCard(
                  label: '待报销',
                  value: _num('reimbursement_pending'),
                  color: ZhColors.neutral,
                  background: ZhColors.neutralSoft,
                  icon: Icons.pending_actions,
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          _InfoRow(
            label: '已报销',
            value: _num('reimbursement_done'),
            color: ZhColors.neutral,
          ),
          const SizedBox(height: 12),
          const Text(
            '数据来自 /api/statistics，按当前登录用户隔离；下拉可刷新。',
            style: TextStyle(fontSize: 12, color: ZhColors.textMuted),
          ),
        ],
      ),
    );
  }

  Widget _buildAssetCard(double balance) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 26),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: ZhColors.line),
        boxShadow: const <BoxShadow>[
          BoxShadow(
            color: Color(0x140F172A),
            blurRadius: 12,
            offset: Offset(0, 4),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          const Row(
            children: <Widget>[
              Icon(Icons.account_balance, size: 18, color: ZhColors.neutral),
              SizedBox(width: 8),
              Text(
                '总净资产',
                style: TextStyle(fontSize: 14, color: ZhColors.textMuted),
              ),
            ],
          ),
          const SizedBox(height: 14),
          FittedBox(
            fit: BoxFit.scaleDown,
            alignment: Alignment.centerLeft,
            child: Text(
              '¥ ${formatMoney(balance)}',
              style: TextStyle(
                fontSize: 38,
                fontWeight: FontWeight.w700,
                height: 1.1,
                color: balance < 0 ? ZhColors.expense : ZhColors.textStrong,
              ),
            ),
          ),
          const SizedBox(height: 8),
          const Text(
            '口径：所有账户余额之和（SUM(accounts.balance)）',
            style: TextStyle(fontSize: 11, color: ZhColors.textMuted),
          ),
        ],
      ),
    );
  }

  Widget _buildErrorState() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            const Icon(Icons.cloud_off, size: 44, color: ZhColors.neutral),
            const SizedBox(height: 12),
            Text(
              _error ?? '数据加载失败',
              textAlign: TextAlign.center,
              style: const TextStyle(color: ZhColors.expense, fontSize: 14),
            ),
            const SizedBox(height: 16),
            FilledButton.icon(
              onPressed: _load,
              icon: const Icon(Icons.refresh),
              label: const Text('重新加载'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildBills() {
    return const Center(
      child: Padding(
        padding: EdgeInsets.all(28),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Icon(Icons.receipt_long, size: 48, color: ZhColors.neutral),
            SizedBox(height: 14),
            Text('账单', style: TextStyle(fontSize: 18, color: ZhColors.textStrong)),
            SizedBox(height: 8),
            Text(
              '下一阶段接入 /api/records（分页、筛选、分类），\n当前版本先打通登录与统计主链路。',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 13, color: ZhColors.textMuted),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildProfile() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(28),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            const CircleAvatar(
              radius: 34,
              backgroundColor: ZhColors.neutralSoft,
              child: Icon(Icons.person, size: 38, color: ZhColors.neutral),
            ),
            const SizedBox(height: 14),
            Text(
              _email.isEmpty ? '未登录' : _email,
              style: const TextStyle(fontSize: 15, color: ZhColors.textStrong),
            ),
            const SizedBox(height: 6),
            const Text(
              'JWT 已保存在本机，重启 App 自动免登录',
              style: TextStyle(fontSize: 12, color: ZhColors.textMuted),
            ),
            const SizedBox(height: 24),
            OutlinedButton.icon(
              onPressed: _logout,
              icon: const Icon(Icons.logout, color: ZhColors.expense),
              label: const Text('退出登录',
                  style: TextStyle(color: ZhColors.expense)),
            ),
          ],
        ),
      ),
    );
  }
}

class _StatCard extends StatelessWidget {
  const _StatCard({
    required this.label,
    required this.value,
    required this.color,
    required this.background,
    required this.icon,
  });

  final String label;
  final double value;
  final Color color;
  final Color background;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 14),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: color.withAlpha(60)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Icon(icon, size: 16, color: color),
          const SizedBox(height: 8),
          Text(label,
              style: const TextStyle(fontSize: 11, color: ZhColors.textMuted)),
          const SizedBox(height: 4),
          FittedBox(
            fit: BoxFit.scaleDown,
            alignment: Alignment.centerLeft,
            child: Text(
              '¥ ${formatMoney(value)}',
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w700,
                color: color,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _InfoRow extends StatelessWidget {
  const _InfoRow({
    required this.label,
    required this.value,
    required this.color,
  });

  final String label;
  final double value;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: ZhColors.line),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: <Widget>[
          Text(label,
              style: const TextStyle(fontSize: 13, color: ZhColors.textMuted)),
          Text(
            '¥ ${formatMoney(value)}',
            style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: color),
          ),
        ],
      ),
    );
  }
}
