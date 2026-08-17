import 'dart:convert';
import 'package:http/http.dart' as http;

const defaultApiBase = String.fromEnvironment(
  'API_BASE_URL',
  defaultValue: 'https://aduanhub.rekadev.site/api/v1',
);

class ApiException implements Exception {
  final String message;
  final int status;
  const ApiException(this.message, this.status);
  @override
  String toString() => message;
}

class ApiClient {
  String? token;
  final String baseUrl;
  ApiClient([this.token, this.baseUrl = defaultApiBase]);

  Map<String, String> get headers => {
    'Accept': 'application/json',
    'Content-Type': 'application/json',
    if (token != null) 'Authorization': 'Bearer $token',
  };

  Future<Map<String, dynamic>> _decode(http.Response response) async {
    final data = response.body.isEmpty
        ? <String, dynamic>{}
        : jsonDecode(response.body) as Map<String, dynamic>;
    if (response.statusCode >= 400) {
      throw ApiException(
        (data['message'] ?? data['error'] ?? 'Terjadi kesalahan').toString(),
        response.statusCode,
      );
    }
    return data;
  }

  Future<Map<String, dynamic>> login(String email, String password) async {
    final response = await http.post(
      Uri.parse('$baseUrl/auth/login'),
      headers: headers,
      body: jsonEncode({
        'email': email,
        'password': password,
        'device_name': 'Android',
      }),
    );
    return _decode(response);
  }

  Future<Map<String, dynamic>> get(
    String path, [
    Map<String, String>? query,
  ]) async {
    final uri = Uri.parse('$baseUrl$path').replace(queryParameters: query);
    return _decode(await http.get(uri, headers: headers));
  }

  Future<Map<String, dynamic>> post(
    String path,
    Map<String, dynamic> body,
  ) async {
    return _decode(
      await http.post(
        Uri.parse('$baseUrl$path'),
        headers: headers,
        body: jsonEncode(body),
      ),
    );
  }

  Future<Map<String, dynamic>> reply(
    int ticketId,
    String body, {
    String? attachmentPath,
  }) async {
    if (attachmentPath == null) {
      return post('/tickets/$ticketId/reply', {'body': body});
    }
    final request =
        http.MultipartRequest(
            'POST',
            Uri.parse('$baseUrl/tickets/$ticketId/reply'),
          )
          ..headers['Authorization'] = 'Bearer $token'
          ..fields['body'] = body
          ..files.add(
            await http.MultipartFile.fromPath('attachment', attachmentPath),
          );
    final streamed = await request.send();
    return _decode(await http.Response.fromStream(streamed));
  }
}
