package com.ican.digitalhuman.realtime;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ican.digitalhuman.config.AgentProperties;
import java.lang.reflect.Field;
import java.net.http.WebSocket;
import java.time.Duration;
import org.junit.jupiter.api.Test;
import org.springframework.web.socket.WebSocketSession;

class AgentRealtimeRelayTest {

    @Test
    void connectDoesNotLeakWhenWebSocketBuildFailsSynchronously() throws Exception {
        WebSocketSession browser = mock(WebSocketSession.class);
        AgentRealtimeRelay relay = relay(browser, "not a valid uri");

        assertThatCode(relay::connect).doesNotThrowAnyException();

        verify(browser).close();
    }

    @Test
    void synchronousSendFailureResetsRelayAndClosesBrowser() throws Exception {
        WebSocketSession browser = mock(WebSocketSession.class);
        WebSocket upstream = mock(WebSocket.class);
        when(upstream.sendText(anyString(), eq(true)))
                .thenThrow(new IllegalStateException("closed"));
        AgentRealtimeRelay relay = relay(browser, "http://127.0.0.1:8000");
        Field upstreamField = AgentRealtimeRelay.class.getDeclaredField("upstream");
        upstreamField.setAccessible(true);
        upstreamField.set(relay, upstream);

        relay.enqueueText("{\"type\":\"ping\"}");

        verify(browser).close();
    }

    private static AgentRealtimeRelay relay(WebSocketSession browser, String baseUrl) {
        AgentProperties properties = new AgentProperties(
                baseUrl,
                "test-token",
                Duration.ofSeconds(1),
                Duration.ofMillis(50),
                "/internal/realtime",
                64 * 1024,
                1_000,
                64 * 1024,
                4);
        return new AgentRealtimeRelay(browser, "u1", "tester", properties, new ObjectMapper());
    }
}
