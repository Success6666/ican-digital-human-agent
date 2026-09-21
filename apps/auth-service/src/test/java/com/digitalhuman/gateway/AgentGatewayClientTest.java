package com.digitalhuman.gateway;

import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.digitalhuman.common.GatewayException;
import com.digitalhuman.config.AgentProperties;
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
    void forwardsConfigurationPatchWithRoleContext() throws Exception {
        AtomicReference<String> method = new AtomicReference<>();
        AtomicReference<String> role = new AtomicReference<>();
        AtomicReference<String> body = new AtomicReference<>();
        server.createContext("/internal/configuration", exchange -> {
            method.set(exchange.getRequestMethod());
            role.set(exchange.getRequestHeaders().getFirst("X-User-Role"));
            body.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            byte[] payload = "{}".getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, payload.length);
            try (var output = exchange.getResponseBody()) {
                output.write(payload);
            }
        });
        server.start();

        ObjectNode request = new ObjectMapper().createObjectNode().put("defaultProvider", "mock");
        client.patch("/internal/configuration", request, "u1", "demo", "admin");

        org.assertj.core.api.Assertions.assertThat(method).hasValue("PATCH");
        org.assertj.core.api.Assertions.assertThat(role).hasValue("admin");
        org.assertj.core.api.Assertions.assertThat(body).hasValue("{\"defaultProvider\":\"mock\"}");
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

        String frame = output.toString(StandardCharsets.UTF_8);
        org.assertj.core.api.Assertions.assertThat(frame)
                .contains("event:error", "Agent 服务暂时不可用")
                .doesNotContain("secret backend detail");
        String data = frame.substring(frame.indexOf("data:") + "data:".length(), frame.indexOf("\n\n"));
        var payload = new ObjectMapper().readTree(data);
        org.assertj.core.api.Assertions.assertThat(payload.path("traceId").asText()).isNotBlank();
        org.assertj.core.api.Assertions.assertThat(payload.path("runId").asText()).isNotBlank();
        org.assertj.core.api.Assertions.assertThat(payload.path("seq").asInt()).isEqualTo(1);
        org.assertj.core.api.Assertions.assertThat(payload.path("eventId").asText())
                .isEqualTo(payload.path("traceId").asText() + ":1");
        org.assertj.core.api.Assertions.assertThat(frame)
                .startsWith("id:" + payload.path("eventId").asText() + "\nevent:error");
    }

    @Test
    void convertsTransportFailureToCorrelatedSseErrorFrame() throws Exception {
        AgentGatewayClient unavailable = new AgentGatewayClient(
                new AgentProperties(
                        "http://127.0.0.1:1",
                        "test-token",
                        Duration.ofMillis(100),
                        Duration.ofMillis(100)),
                new ObjectMapper());

        var output = new FlushTrackingOutputStream();
        unavailable.stream("/internal/chat/stream", new ObjectMapper().createObjectNode(), "u1", "demo", output);

        String frame = output.toString(StandardCharsets.UTF_8);
        String data = frame.substring(frame.indexOf("data:") + "data:".length(), frame.indexOf("\n\n"));
        var payload = new ObjectMapper().readTree(data);
        org.assertj.core.api.Assertions.assertThat(frame).contains("event:error", "Agent 服务不可达");
        org.assertj.core.api.Assertions.assertThat(payload.path("traceId").asText()).isNotBlank();
        org.assertj.core.api.Assertions.assertThat(payload.path("runId").asText()).isNotBlank();
        org.assertj.core.api.Assertions.assertThat(payload.path("seq").asInt()).isEqualTo(1);
        org.assertj.core.api.Assertions.assertThat(payload.path("eventId").asText())
                .isEqualTo(payload.path("traceId").asText() + ":1");
        org.assertj.core.api.Assertions.assertThat(frame)
                .startsWith("id:" + payload.path("eventId").asText() + "\nevent:error");
    }

    @Test
    void tracksFirstUpstreamIdentifiersAcrossCrLfFrames() {
        var envelope = SseStreamEnvelope.create(new ObjectMapper().createObjectNode());
        envelope.observe(
                "event:start\r\ndata:{\"traceId\":\"trace-a\",\"runId\":\"run-a\",\"seq\":7}\r\n\r\n",
                new ObjectMapper()
        );
        envelope.observe(
                "data:{\"traceId\":\"trace-b\",\"runId\":\"run-b\",\"seq\":8}\n\n",
                new ObjectMapper()
        );

        org.assertj.core.api.Assertions.assertThat(envelope.traceId()).isEqualTo("trace-a");
        org.assertj.core.api.Assertions.assertThat(envelope.runId()).isEqualTo("run-a");
        org.assertj.core.api.Assertions.assertThat(envelope.nextSequence()).isEqualTo(9);
    }

    @Test
    void boundsMalformedFramesAndRejectsExtremeSequenceValues() {
        var envelope = SseStreamEnvelope.create(null);
        envelope.observe("data:" + "x".repeat(300 * 1024), new ObjectMapper());
        envelope.observe("data:{\"seq\":2147483647}\n\n", new ObjectMapper());

        org.assertj.core.api.Assertions.assertThat(envelope.nextSequence()).isEqualTo(2);
    }

    @Test
    void sanitizesUpstreamIdentifiersBeforeUsingThemInAnSseId() {
        var envelope = SseStreamEnvelope.create(null);
        envelope.observe(
                "data:{\"traceId\":\"trace\\nid\",\"runId\":\"run\\r\\nid\"}\n\n",
                new ObjectMapper()
        );

        org.assertj.core.api.Assertions.assertThat(envelope.traceId()).isEqualTo("trace_id");
        org.assertj.core.api.Assertions.assertThat(envelope.runId()).isEqualTo("run__id");
        org.assertj.core.api.Assertions.assertThat(envelope.eventId()).doesNotContain("\n", "\r");
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
