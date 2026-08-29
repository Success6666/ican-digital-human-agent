package com.ican.digitalhuman.gateway;

import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ican.digitalhuman.common.GatewayException;
import com.ican.digitalhuman.config.AgentProperties;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
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
}
