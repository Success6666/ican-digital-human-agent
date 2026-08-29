package com.ican.digitalhuman.gateway;

import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.ican.digitalhuman.common.GatewayException;
import com.ican.digitalhuman.config.AgentProperties;
import com.sun.net.httpserver.HttpServer;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class AgentGatewayClientTest {

    private HttpServer server;
    private AgentGatewayClient client;

    @BeforeEach
    void setUp() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        client = new AgentGatewayClient(
                new AgentProperties(
                        "http://127.0.0.1:" + server.getAddress().getPort(),
                        "test-token",
                        Duration.ofSeconds(1),
                        Duration.ofSeconds(2)),
                new ObjectMapper());
    }

    @AfterEach
    void tearDown() {
        server.stop(0);
    }

    @Test
    void hidesServerErrorBody() {
        respond(500, "{\"detail\":\"java.sql.SQLException: secret-password\"}");

        assertThatThrownBy(() -> client.get("/internal/health", "u1", "demo"))
                .isInstanceOf(GatewayException.class)
                .hasMessage("Agent 服务暂时不可用")
                .hasMessageNotContaining("secret-password");
    }

    @Test
    void keepsOnlyShortClientSafeDetailForClientErrors() {
        respond(422, "{\"detail\":\"参数无效\\n\\t请检查请求\"}");

        assertThatThrownBy(() -> client.get("/internal/health", "u1", "demo"))
                .isInstanceOf(GatewayException.class)
                .hasMessage("参数无效 请检查请求");
    }

    @Test
    void forwardsJsonBodyWithoutChangingItsShape() throws Exception {
        AtomicReference<String> body = new AtomicReference<>();
        server.createContext("/internal/sessions", exchange -> {
            body.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            byte[] payload = "{}".getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, payload.length);
            try (var output = exchange.getResponseBody()) {
                output.write(payload);
            }
        });
        server.start();

        ObjectNode request = new ObjectMapper().createObjectNode().put("provider", "mock");
        client.post("/internal/sessions", request, "u1", "demo");

        org.assertj.core.api.Assertions.assertThat(body).hasValue("{\"provider\":\"mock\"}");
    }

    @Test
    void forwardsStreamingPayloadInFlushableChunks() throws Exception {
        server.createContext("/internal/chat/stream", exchange -> {
            exchange.getResponseHeaders().set("Content-Type", "text/event-stream");
            exchange.sendResponseHeaders(200, 0);
            try (var output = exchange.getResponseBody()) {
                output.write("event:start\ndata:{\"runId\":\"run-1\"}\n\n".getBytes(StandardCharsets.UTF_8));
                output.flush();
                output.write("event:done\ndata:{\"runId\":\"run-1\"}\n\n".getBytes(StandardCharsets.UTF_8));
            }
        });
        server.start();

        var output = new FlushTrackingOutputStream();
        client.stream("/internal/chat/stream", new ObjectMapper().createObjectNode(), "u1", "demo", output);

        org.assertj.core.api.Assertions.assertThat(output.toString(StandardCharsets.UTF_8))
                .contains("event:start", "event:done", "run-1");
        org.assertj.core.api.Assertions.assertThat(output.flushes).isGreaterThanOrEqualTo(1);
    }

    @Test
    void convertsUpstreamStreamFailureToSseErrorFrame() throws Exception {
        respondStreamError(503, "{\"detail\":\"secret backend detail\"}");

        var output = new FlushTrackingOutputStream();
        client.stream("/internal/chat/stream", new ObjectMapper().createObjectNode(), "u1", "demo", output);

        org.assertj.core.api.Assertions.assertThat(output.toString(StandardCharsets.UTF_8))
                .contains("event:error", "Agent 服务暂时不可用")
                .doesNotContain("secret backend detail");
    }

    private static final class FlushTrackingOutputStream extends ByteArrayOutputStream {
        private int flushes;

        @Override
        public void flush() throws IOException {
            flushes++;
            super.flush();
        }
    }

    private void respond(int status, String body) {
        server.createContext("/internal/health", exchange -> {
            byte[] payload = body.getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(status, payload.length);
            try (var output = exchange.getResponseBody()) {
                output.write(payload);
            }
        });
        server.start();
    }

    private void respondStreamError(int status, String body) {
        server.createContext("/internal/chat/stream", exchange -> {
            byte[] payload = body.getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(status, payload.length);
            try (var output = exchange.getResponseBody()) {
                output.write(payload);
            }
        });
        server.start();
    }
}
