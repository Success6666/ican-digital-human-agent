package com.digitalhuman.realtime;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.digitalhuman.config.AgentProperties;
import java.io.IOException;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import org.springframework.web.socket.BinaryMessage;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketHandler;
import org.springframework.web.socket.WebSocketMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.handler.ConcurrentWebSocketSessionDecorator;

class RealtimeWebSocketHandler implements WebSocketHandler {

    private final AgentProperties properties;
    private final ObjectMapper objectMapper;
    private final RealtimeRelayFactory relayFactory;
    private final Map<String, AgentRealtimeRelay> relays = new ConcurrentHashMap<>();
    private final AtomicInteger activeCount = new AtomicInteger();

    RealtimeWebSocketHandler(AgentProperties properties, ObjectMapper objectMapper) {
        this(properties, objectMapper, RealtimeRelayFactory.defaultFactory());
    }

    RealtimeWebSocketHandler(
            AgentProperties properties,
            ObjectMapper objectMapper,
            RealtimeRelayFactory relayFactory
    ) {
        this.properties = properties;
        this.objectMapper = objectMapper;
        this.relayFactory = RealtimeRelayFactory.require(relayFactory);
    }

    @Override
    public void afterConnectionEstablished(WebSocketSession session) {
        String userId = attribute(session, RealtimeHandshakeInterceptor.USER_ID);
        String userName = attribute(session, RealtimeHandshakeInterceptor.USER_NAME);
        if (userId == null || userName == null) {
            closeQuietly(session, CloseStatus.NOT_ACCEPTABLE.withReason("身份上下文缺失"));
            return;
        }
        WebSocketSession bounded = new ConcurrentWebSocketSessionDecorator(
                session,
                properties.realtimeSendTimeLimitMs(),
                properties.realtimeBufferSizeBytes()
        );
        if (!reserveConnection()) {
            closeQuietly(session, new CloseStatus(1013, "实时连接繁忙，请稍后重试"));
            return;
        }
        AgentRealtimeRelay relay;
        try {
            relay = relayFactory.create(bounded, userId, userName, properties, objectMapper);
        } catch (RuntimeException exception) {
            activeCount.decrementAndGet();
            closeQuietly(session, CloseStatus.SERVER_ERROR.withReason("实时通道初始化失败"));
            throw exception;
        }
        AgentRealtimeRelay previous = relays.putIfAbsent(session.getId(), relay);
        if (previous != null) {
            activeCount.decrementAndGet();
            relay.close();
            closeQuietly(session, CloseStatus.POLICY_VIOLATION.withReason("重复连接"));
            return;
        }
        relay.connect();
    }

    @Override
    public void handleMessage(WebSocketSession session, WebSocketMessage<?> message) {
        AgentRealtimeRelay relay = relays.get(session.getId());
        if (relay == null) {
            return;
        }
        if (message instanceof TextMessage text) {
            relay.enqueueText(text.getPayload());
        } else if (message instanceof BinaryMessage binary) {
            var payload = binary.getPayload().asReadOnlyBuffer();
            byte[] bytes = new byte[payload.remaining()];
            payload.get(bytes);
            relay.enqueueBinary(bytes);
        } else {
            closeQuietly(session, CloseStatus.NOT_ACCEPTABLE.withReason("不支持的 WebSocket 帧"));
        }
    }

    @Override
    public void handleTransportError(WebSocketSession session, Throwable exception) {
        removeAndClose(session.getId());
    }

    @Override
    public void afterConnectionClosed(WebSocketSession session, CloseStatus closeStatus) {
        removeAndClose(session.getId());
    }

    @Override
    public boolean supportsPartialMessages() {
        return false;
    }

    int activeConnections() {
        return activeCount.get();
    }

    private void removeAndClose(String sessionId) {
        AgentRealtimeRelay relay = relays.remove(sessionId);
        if (relay != null) {
            activeCount.decrementAndGet();
            relay.close();
        }
    }

    private boolean reserveConnection() {
        int max = properties.realtimeMaxConnections();
        while (true) {
            int current = activeCount.get();
            if (current >= max) return false;
            if (activeCount.compareAndSet(current, current + 1)) return true;
        }
    }

    private static String attribute(WebSocketSession session, String name) {
        Object value = session.getAttributes().get(name);
        return value instanceof String string && !string.isBlank() ? string : null;
    }

    private static void closeQuietly(WebSocketSession session, CloseStatus status) {
        try {
            session.close(status);
        } catch (IOException ignored) {
            // The transport may already be closed.
        }
    }
}
