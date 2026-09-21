package com.digitalhuman.realtime;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.digitalhuman.auth.AuthService;
import com.digitalhuman.auth.UserAccount;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.server.ServerHttpRequest;
import org.springframework.http.server.ServerHttpResponse;
import org.springframework.web.socket.WebSocketHandler;
import org.springframework.web.socket.server.HandshakeInterceptor;

class RealtimeHandshakeInterceptor implements HandshakeInterceptor {

    static final String USER_ID = "realtime.userId";
    static final String USER_NAME = "realtime.userName";

    private final AuthService authService;
    private final ObjectMapper objectMapper;

    RealtimeHandshakeInterceptor(AuthService authService, ObjectMapper objectMapper) {
        this.authService = authService;
        this.objectMapper = objectMapper;
    }

    @Override
    public boolean beforeHandshake(
            ServerHttpRequest request,
            ServerHttpResponse response,
            WebSocketHandler wsHandler,
            Map<String, Object> attributes
    ) throws IOException {
        try {
            UserAccount user = authService.requireCurrentUser();
            attributes.put(USER_ID, user.id());
            attributes.put(USER_NAME, user.username());
            return true;
        } catch (RuntimeException exception) {
            writeUnauthorized(response);
            return false;
        }
    }

    @Override
    public void afterHandshake(
            ServerHttpRequest request,
            ServerHttpResponse response,
            WebSocketHandler wsHandler,
            Exception exception
    ) {
        // Authentication state is copied into the WebSocket session attributes.
    }

    private void writeUnauthorized(ServerHttpResponse response) throws IOException {
        response.setStatusCode(HttpStatus.UNAUTHORIZED);
        response.getHeaders().set(HttpHeaders.CONTENT_TYPE, MediaType.APPLICATION_JSON_VALUE);
        var payload = objectMapper.createObjectNode()
                .put("status", HttpStatus.UNAUTHORIZED.value())
                .put("message", "请先登录");
        response.getBody().write(payload.toString().getBytes(StandardCharsets.UTF_8));
    }
}
