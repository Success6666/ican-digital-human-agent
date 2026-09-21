package com.digitalhuman.realtime;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.digitalhuman.config.AgentProperties;
import java.net.http.HttpClient;
import java.net.http.WebSocket;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import org.springframework.web.socket.BinaryMessage;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;

/** Relays one authenticated browser connection to the internal Agent socket. */
class AgentRealtimeRelay {

    private static final int NORMAL_CLOSE = 1000;
    private static final int MAX_INBOUND_TEXT_BYTES = 256 * 1024;
    private static final int MAX_INBOUND_BINARY_BYTES = 256 * 1024;

    private final WebSocketSession browser;
    private final String userId;
    private final String userName;
    private final AgentProperties properties;
    private final ObjectMapper objectMapper;
    private final HttpClient httpClient;
    private final Deque<RealtimeOutboundFrame> queue = new ArrayDeque<>();
    private final Object lock = new Object();
    private final AtomicBoolean closed = new AtomicBoolean();
    private int queuedBytes;
    private boolean sending;
    private WebSocket upstream;
    private final RealtimeInboundBuffer inboundBuffer = new RealtimeInboundBuffer(MAX_INBOUND_BINARY_BYTES);

    AgentRealtimeRelay(
            WebSocketSession browser,
            String userId,
            String userName,
            AgentProperties properties,
            ObjectMapper objectMapper
    ) {
        this.browser = browser;
        this.userId = userId;
        this.userName = userName;
        this.properties = properties;
        this.objectMapper = objectMapper;
        this.httpClient = HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(properties.connectTimeout())
                .build();
    }

    void connect() {
        if (closed.get()) {
            return;
        }
        try {
            httpClient.newWebSocketBuilder()
                    .connectTimeout(properties.connectTimeout())
                    .header("X-Internal-Token", properties.internalToken())
                    .header("X-User-Id", userId)
                    .header("X-User-Name", userName)
                    .header("X-Request-Id", UUID.randomUUID().toString())
                    .buildAsync(
                            RealtimeRelaySupport.agentUri(properties.baseUrl(), properties.realtimePath()),
                            listener())
                    .orTimeout(Math.max(1L, properties.readTimeout().toMillis()), TimeUnit.MILLISECONDS)
                    .whenComplete((socket, error) -> {
                        if (error != null) {
                            fail("Agent 实时通道不可用");
                            return;
                        }
                        synchronized (lock) {
                            if (closed.get()) {
                                socket.sendClose(NORMAL_CLOSE, "closed");
                                return;
                            }
                            upstream = socket;
                        }
                        drain();
                    });
        } catch (RuntimeException exception) {
            fail("Agent 实时通道初始化失败");
        }
    }

    void enqueueText(String payload) {
        if (payload == null || payload.getBytes(StandardCharsets.UTF_8).length > MAX_INBOUND_TEXT_BYTES) {
            fail("实时文本帧超出大小限制");
            return;
        }
        enqueue(RealtimeOutboundFrame.text(payload));
    }

    void enqueueBinary(byte[] payload) {
        if (payload == null || payload.length > MAX_INBOUND_BINARY_BYTES) {
            fail("实时音频帧超出大小限制");
            return;
        }
        enqueue(RealtimeOutboundFrame.binary(payload));
    }

    void close() {
        if (!closed.compareAndSet(false, true)) {
            return;
        }
        WebSocket socket;
        synchronized (lock) {
            socket = upstream;
            upstream = null;
            queue.clear();
            queuedBytes = 0;
        }
        if (socket != null) {
            socket.sendClose(NORMAL_CLOSE, "browser closed");
        }
    }

    private void enqueue(RealtimeOutboundFrame frame) {
        boolean overflow;
        synchronized (lock) {
            if (closed.get()) {
                return;
            }
            int maxBytes = properties.realtimeMaxQueueBytes();
            overflow = frame.bytes() > maxBytes || queuedBytes > maxBytes - frame.bytes();
            if (!overflow) {
                queue.addLast(frame);
                queuedBytes += frame.bytes();
            }
        }
        if (overflow) {
            fail("实时发送队列已满");
            return;
        }
        drain();
    }

    private void drain() {
        RealtimeOutboundFrame frame;
        WebSocket socket;
        synchronized (lock) {
            if (closed.get() || sending || upstream == null || queue.isEmpty()) {
                return;
            }
            socket = upstream;
            frame = queue.removeFirst();
            queuedBytes -= frame.bytes();
            sending = true;
        }
        CompletableFuture<?> result;
        try {
            result = frame.binary()
                    ? socket.sendBinary(ByteBuffer.wrap(frame.payload()), true)
                    : socket.sendText(new String(frame.payload(), StandardCharsets.UTF_8), true);
        } catch (RuntimeException exception) {
            synchronized (lock) {
                sending = false;
            }
            fail("Agent 实时通道发送失败");
            return;
        }
        result.whenComplete((ignored, error) -> {
            synchronized (lock) {
                sending = false;
            }
            if (error != null) {
                fail("Agent 实时通道发送失败");
                return;
            }
            drain();
        });
    }

    private WebSocket.Listener listener() {
        return new WebSocket.Listener() {
            @Override
            public void onOpen(WebSocket webSocket) {
                webSocket.request(1);
            }

            @Override
            public java.util.concurrent.CompletionStage<?> onText(
                    WebSocket webSocket,
                    CharSequence data,
                    boolean last
            ) {
                if (!inboundBuffer.appendText(data, last, payload -> sendBrowser(new TextMessage(payload)))) {
                    fail("Agent 文本帧超出大小限制");
                    return null;
                }
                webSocket.request(1);
                return null;
            }

            @Override
            public java.util.concurrent.CompletionStage<?> onBinary(
                    WebSocket webSocket,
                    ByteBuffer data,
                    boolean last
            ) {
                if (!inboundBuffer.appendBinary(data, last, payload -> sendBrowser(new BinaryMessage(payload)))) {
                    fail("Agent 音频帧超出大小限制");
                    return null;
                }
                webSocket.request(1);
                return null;
            }

            @Override
            public void onError(WebSocket webSocket, Throwable error) {
                fail("Agent 实时通道异常");
            }

            @Override
            public java.util.concurrent.CompletionStage<?> onClose(
                    WebSocket webSocket,
                    int statusCode,
                    String reason
            ) {
                if (!closed.get()) {
                    fail("Agent 实时通道已关闭");
                }
                return null;
            }
        };
    }

    private void sendBrowser(org.springframework.web.socket.WebSocketMessage<?> message) {
        if (closed.get()) {
            return;
        }
        try {
            browser.sendMessage(message);
        } catch (Exception exception) {
            close();
        }
    }

    private void fail(String message) {
        if (!closed.compareAndSet(false, true)) {
            return;
        }
        try {
            var payload = objectMapper.createObjectNode()
                    .put("type", "error")
                    .put("code", "realtime_relay_error")
                    .put("message", message);
            browser.sendMessage(new TextMessage(payload.toString()));
        } catch (Exception ignored) {
            // The browser may have disconnected already.
        }
        WebSocket socket;
        synchronized (lock) {
            socket = upstream;
            upstream = null;
            queue.clear();
            queuedBytes = 0;
        }
        if (socket != null) {
            socket.sendClose(1011, "relay error");
        }
        try {
            browser.close();
        } catch (Exception ignored) {
            // No response remains to close.
        }
    }

}
