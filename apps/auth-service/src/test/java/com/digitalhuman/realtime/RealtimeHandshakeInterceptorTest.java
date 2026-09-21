package com.digitalhuman.realtime;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.digitalhuman.auth.AuthService;
import com.digitalhuman.auth.UserAccount;
import com.digitalhuman.common.BizException;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.http.server.ServletServerHttpRequest;
import org.springframework.http.server.ServletServerHttpResponse;
import org.springframework.web.socket.WebSocketHandler;

class RealtimeHandshakeInterceptorTest {

    @Test
    void copiesAuthenticatedUserIntoHandshakeAttributes() throws Exception {
        AuthService authService = mock(AuthService.class);
        when(authService.requireCurrentUser())
                .thenReturn(new UserAccount("u1", "demo", "演示用户", "user", null));
        RealtimeHandshakeInterceptor interceptor = new RealtimeHandshakeInterceptor(
                authService, new ObjectMapper());
        Map<String, Object> attributes = new HashMap<>();

        boolean accepted = interceptor.beforeHandshake(
                new ServletServerHttpRequest(new MockHttpServletRequest()),
                new ServletServerHttpResponse(new MockHttpServletResponse()),
                mock(WebSocketHandler.class),
                attributes);

        assertThat(accepted).isTrue();
        assertThat(attributes)
                .containsEntry(RealtimeHandshakeInterceptor.USER_ID, "u1")
                .containsEntry(RealtimeHandshakeInterceptor.USER_NAME, "demo");
    }

    @Test
    void returnsStructuredUnauthorizedResponseBeforeUpgrade() throws Exception {
        AuthService authService = mock(AuthService.class);
        when(authService.requireCurrentUser()).thenThrow(new BizException(401, "not logged in"));
        RealtimeHandshakeInterceptor interceptor = new RealtimeHandshakeInterceptor(
                authService, new ObjectMapper());
        MockHttpServletResponse servletResponse = new MockHttpServletResponse();

        boolean accepted = interceptor.beforeHandshake(
                new ServletServerHttpRequest(new MockHttpServletRequest()),
                new ServletServerHttpResponse(servletResponse),
                mock(WebSocketHandler.class),
                new HashMap<>());

        assertThat(accepted).isFalse();
        assertThat(servletResponse.getStatus()).isEqualTo(401);
        assertThat(servletResponse.getContentType()).isEqualTo("application/json");
        assertThat(servletResponse.getContentAsByteArray())
                .asString(StandardCharsets.UTF_8)
                .isEqualTo("{\"status\":401,\"message\":\"请先登录\"}");
    }
}
