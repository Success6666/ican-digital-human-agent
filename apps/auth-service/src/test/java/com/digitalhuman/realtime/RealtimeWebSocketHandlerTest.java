package com.digitalhuman.realtime;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.digitalhuman.config.AgentProperties;
import java.nio.ByteBuffer;
import java.time.Duration;
import java.util.HashMap;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.web.socket.BinaryMessage;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;

class RealtimeWebSocketHandlerTest {

    @Test
    void forwardsTextAndBinaryFramesAndReleasesConnection() throws Exception {
        AgentProperties properties = properties(4);
        AgentRealtimeRelay relay = mock(AgentRealtimeRelay.class);
        RealtimeWebSocketHandler handler = new RealtimeWebSocketHandler(
                properties,
                new ObjectMapper(),
                (browser, userId, userName, ignored, mapper) -> relay);
        WebSocketSession session = session("browser-1");

        handler.afterConnectionEstablished(session);
        handler.handleMessage(session, new TextMessage("{\"type\":\"hello\"}"));
        handler.handleMessage(session, new BinaryMessage(ByteBuffer.wrap(new byte[] {1, 2, 3})));

        verify(relay).connect();
        verify(relay).enqueueText("{\"type\":\"hello\"}");
        verify(relay).enqueueBinary(new byte[] {1, 2, 3});
        assertThat(handler.activeConnections()).isEqualTo(1);

        handler.afterConnectionClosed(session, CloseStatus.NORMAL);

        verify(relay).close();
        assertThat(handler.activeConnections()).isZero();
    }

    @Test
    void rejectsConnectionsAboveConfiguredLimit() throws Exception {
        AgentProperties properties = properties(1);
        AgentRealtimeRelay relay = mock(AgentRealtimeRelay.class);
        RealtimeWebSocketHandler handler = new RealtimeWebSocketHandler(
                properties,
                new ObjectMapper(),
                (browser, userId, userName, ignored, mapper) -> relay);
        WebSocketSession first = session("browser-1");
        WebSocketSession second = session("browser-2");

        handler.afterConnectionEstablished(first);
        handler.afterConnectionEstablished(second);

        assertThat(handler.activeConnections()).isEqualTo(1);
        verify(second).close(new CloseStatus(1013, "实时连接繁忙，请稍后重试"));
    }

    private static AgentProperties properties(int maxConnections) {
        return new AgentProperties(
                "http://127.0.0.1:8000",
                "test-token",
                Duration.ofSeconds(1),
                Duration.ofSeconds(2),
                "/internal/realtime",
                64 * 1024,
                1_000,
                64 * 1024,
                maxConnections);
    }

    private static WebSocketSession session(String id) {
        WebSocketSession session = mock(WebSocketSession.class);
        when(session.getId()).thenReturn(id);
        Map<String, Object> attributes = new HashMap<>();
        attributes.put(RealtimeHandshakeInterceptor.USER_ID, "u1");
        attributes.put(RealtimeHandshakeInterceptor.USER_NAME, "demo");
        when(session.getAttributes()).thenReturn(attributes);
        return session;
    }
}
