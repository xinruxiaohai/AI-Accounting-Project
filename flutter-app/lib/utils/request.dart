import 'package:dio/dio.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 后端返回的统一异常：把 DioException / 后端 error 字段收敛成一句可读文案。
class ApiException implements Exception {
  const ApiException(this.message, {this.statusCode});

  final String message;
  final int? statusCode;

  @override
  String toString() => message;
}

/// 《智汇账》网络层：dio + JWT 自动注入 + shared_preferences 持久化。
///
/// 后端是 Flask，所有接口都在 /api 下，所以 baseUrl 里已经带了 /api，
/// 调用时路径写成 '/auth/login'、'/statistics'，不要再重复写 '/api'。
class ApiClient {
  ApiClient._();

  static const String tokenKey = 'ai_accounting_token';
  static const String emailKey = 'ai_accounting_email';

  /// 默认指向线上服务器；局域网/本地调试用 dart-define 覆盖：
  /// flutter run --dart-define=ZHZ_API_BASE=http://192.168.1.10:5000/api
  static const String baseUrl = String.fromEnvironment(
    'ZHZ_API_BASE',
    defaultValue: 'http://8.134.12.135/api',
  );

  static final Dio dio = Dio(
    BaseOptions(
      baseUrl: baseUrl,
      connectTimeout: const Duration(seconds: 10),
      sendTimeout: const Duration(seconds: 10),
      receiveTimeout: const Duration(seconds: 15),
      responseType: ResponseType.json,
    ),
  );

  static bool _installed = false;

  /// 在 main() 里调用一次：每次请求前读取本地 Token 并注入 Authorization。
  static Future<void> init() async {
    if (_installed) {
      return;
    }
    _installed = true;
    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (RequestOptions options, RequestInterceptorHandler handler) async {
          options.headers['Accept'] = 'application/json';
          final String token = await getToken();
          if (token.isNotEmpty) {
            options.headers['Authorization'] = 'Bearer $token';
          }
          handler.next(options);
        },
      ),
    );
  }

  static Future<SharedPreferences> _prefs() => SharedPreferences.getInstance();

  static Future<String> getToken() async {
    final SharedPreferences prefs = await _prefs();
    return prefs.getString(tokenKey) ?? '';
  }

  static Future<String> getEmail() async {
    final SharedPreferences prefs = await _prefs();
    return prefs.getString(emailKey) ?? '';
  }

  static Future<void> saveSession(String token, {String email = ''}) async {
    final SharedPreferences prefs = await _prefs();
    await prefs.setString(tokenKey, token);
    if (email.isNotEmpty) {
      await prefs.setString(emailKey, email);
    }
  }

  static Future<void> clearSession() async {
    final SharedPreferences prefs = await _prefs();
    await prefs.remove(tokenKey);
    await prefs.remove(emailKey);
  }

  static Future<Map<String, dynamic>> get(
    String path, {
    Map<String, dynamic>? query,
  }) async {
    try {
      final Response<dynamic> response =
          await dio.get<dynamic>(path, queryParameters: query);
      return _asMap(response.data);
    } on DioException catch (error) {
      throw _toException(error);
    }
  }

  static Future<Map<String, dynamic>> post(String path, {Object? data}) async {
    try {
      final Response<dynamic> response = await dio.post<dynamic>(path, data: data);
      return _asMap(response.data);
    } on DioException catch (error) {
      throw _toException(error);
    }
  }

  static Map<String, dynamic> _asMap(dynamic data) {
    if (data is Map<String, dynamic>) {
      return data;
    }
    if (data is Map) {
      return Map<String, dynamic>.from(data);
    }
    throw const ApiException('服务器返回的数据格式不正确');
  }

  static ApiException _toException(DioException error) {
    final int? status = error.response?.statusCode;
    final dynamic payload = error.response?.data;
    if (payload is Map && payload['error'] != null) {
      return ApiException(payload['error'].toString(), statusCode: status);
    }
    switch (error.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
      case DioExceptionType.transformTimeout:
        return const ApiException('连接超时，请检查服务器地址或网络');
      case DioExceptionType.connectionError:
        return const ApiException('无法连接服务器，请检查网络或 BaseURL');
      case DioExceptionType.badCertificate:
        return const ApiException('证书校验失败，请检查 HTTPS 配置');
      case DioExceptionType.cancel:
        return const ApiException('请求已取消');
      case DioExceptionType.badResponse:
      case DioExceptionType.unknown:
        return ApiException('请求失败（HTTP ${status ?? 0}）', statusCode: status);
    }
  }
}
