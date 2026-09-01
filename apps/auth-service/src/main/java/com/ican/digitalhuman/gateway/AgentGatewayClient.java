package com.ican.digitalhuman.gateway;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ican.digitalhuman.common.GatewayException;
import com.ican.digitalhuman.config.AgentProperties;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.UUID;
import org.springframework.stereotype.Component;

@Component
public class AgentGatewayClient {

    private final AgentProperties properties;
    private final ObjectMapper objectMapper;
    private final HttpClient httpClient;

    public AgentGatewayClient(AgentProperties properties, ObjectMapper objectMapper) {
        this.properties = properties;
        this.objectMapper = objectMapper;
        // Uvicorn's clear-text HTTP endpoint does not reliably preserve POST
        // bodies during the JDK client's h2c upgrade attempt.  Keep the
        // gateway transport explicit and compatible with SSE/JSON requests.
        this.httpClient = HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(properties.connectTimeout())
                .build();
    }

    public JsonNode get(String path, String userId, String userName) {
        HttpRequest request = baseRequest(path, userId, userName).GET().build();
        return sendJson(request);
    }

    public JsonNode get(String path, String userId, String userName, String userRole) {
        HttpRequest request = baseRequest(path, userId, userName)
                .header("X-User-Role", userRole)
                .GET()
                .build();
        return sendJson(request);
    }

    public JsonNode post(String path, JsonNode body, String userId, String userName) {
        HttpRequest request = baseRequest(path, userId, userName)
                .POST(HttpRequest.BodyPublishers.ofString(write(body)))
                .build();
        return sendJson(request);
    }

    public JsonNode patch(String path, JsonNode body, String userId, String userName, String userRole) {
        HttpRequest request = baseRequest(path, userId, userName)
                .header("X-User-Role", userRole)
                .method("PATCH", HttpRequest.BodyPublishers.ofString(write(body)))
                .build();
        return sendJson(request);
    }

    public void delete(String path, String userId, String userName) {
        HttpRequest request = baseRequest(path, userId, userName).DELETE().build();
        sendJson(request);
    }

    public JsonNode deleteWithBody(String path, String userId, String userName) {
        HttpRequest request = baseRequest(path, userId, userName).DELETE().build();
        return sendJson(request);
    }

    public void stream(String path, JsonNode body, String userId, String userName, OutputStream output) {
        SseStreamEnvelope envelope = SseStreamEnvelope.create(body);
        HttpRequest request = baseRequest(path, userId, userName)
                .header("Accept", "text/event-stream")
                .POST(HttpRequest.BodyPublishers.ofString(write(body)))
                .build();
        try {
            HttpResponse<InputStream> response = httpClient.send(request, HttpResponse.BodyHandlers.ofInputStream());
            if (response.statusCode() >= 400) {
                String message;
                try (InputStream bodyStream = response.body()) {
                    message = readLimited(bodyStream);
                }
                writeStreamError(output, safeMessage(response.statusCode(), message), envelope);
                return;
            }
            try (InputStream input = response.body()) {
                byte[] buffer = new byte[4096];
                int read;
                while ((read = input.read(buffer)) != -1) {
                    if (read == 0) {
                        continue;
                    }
                    envelope.observe(new String(buffer, 0, read, StandardCharsets.UTF_8), objectMapper);
                    output.write(buffer, 0, read);
                    // Push each small SSE batch through the servlet response
                    // so the browser can render the acknowledgement/delta
                    // without waiting for the complete Agent run.
                    output.flush();
                }
            }
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            writeStreamError(output, "Agent 请求被中断", envelope);
        } catch (IOException exception) {
            writeStreamError(output, "Agent 服务不可达", envelope);
        }
    }

    private void writeStreamError(OutputStream output, String message, SseStreamEnvelope envelope) {
        try {
            long sequence = envelope.nextSequence();
            String eventId = envelope.eventId();
            String data = objectMapper.createObjectNode()
                    .put("message", message)
                    .put("traceId", envelope.traceId())
                    .put("runId", envelope.runId())
                    .put("seq", sequence)
                    .put("eventId", eventId)
                    .toString();
            output.write(("id:" + eventId + "\nevent:error\ndata:" + data + "\n\n")
                    .getBytes(StandardCharsets.UTF_8));
            output.flush();
        } catch (IOException ignored) {
            // The browser may have disconnected already; there is no useful
            // response left to write and no exception should trigger /error.
        }
    }

    private HttpRequest.Builder baseRequest(String path, String userId, String userName) {
        String normalizedPath = path.startsWith("/") ? path : "/" + path;
        String requestId = UUID.randomUUID().toString();
        return HttpRequest.newBuilder(URI.create(properties.baseUrl() + normalizedPath))
                .timeout(properties.readTimeout())
                .header("Content-Type", "application/json")
                .header("X-Internal-Token", properties.internalToken())
                .header("X-User-Id", userId)
                .header("X-User-Name", userName)
                // The authenticated account is the default tenant boundary.
                // A future org directory can replace this derivation without
                // changing the Agent contract.
                .header("X-Tenant-Id", "tenant-" + userId)
                .header("X-Request-Id", requestId);
    }

    private JsonNode sendJson(HttpRequest request) {
        try {
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() >= 400) {
                throw new GatewayException(response.statusCode(), safeMessage(response.statusCode(), response.body()));
            }
            if (response.body() == null || response.body().isBlank()) {
                return objectMapper.createObjectNode();
            }
            return objectMapper.readTree(response.body());
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new GatewayException(502, "Agent 请求被中断");
        } catch (IOException exception) {
            throw new GatewayException(502, "Agent 服务不可达");
        }
    }

    private String write(JsonNode body) {
        try {
            return objectMapper.writeValueAsString(body == null ? objectMapper.createObjectNode() : body);
        } catch (IOException exception) {
            throw new GatewayException(400, "请求体格式无效");
        }
    }

    private String safeMessage(int status, String body) {
        if (status >= 500) {
            return "Agent 服务暂时不可用";
        }
        if (status == 401) {
            return "Agent 请求未获授权";
        }
        if (status == 403) {
            return "无权访问 Agent 资源";
        }
        if (body == null || body.isBlank()) {
            return "Agent 请求失败";
        }
        String detail = extractDetail(body);
        if (detail.isBlank()) {
            return "Agent 请求失败";
        }
        String sanitized = detail.replaceAll("\\p{Cntrl}", " ").replaceAll("\\s+", " ").trim();
        return sanitized.substring(0, Math.min(sanitized.length(), 240));
    }

    private String extractDetail(String body) {
        try {
            JsonNode payload = objectMapper.readTree(body);
            if (payload != null && payload.isObject()) {
                for (String field : new String[]{"detail", "message"}) {
                    JsonNode value = payload.get(field);
                    if (value != null && value.isTextual()) {
                        return value.asText();
                    }
                }
            }
        } catch (IOException ignored) {
            // Invalid backend payloads are intentionally mapped to a generic message.
        }
        return "";
    }

    private String readLimited(InputStream input) throws IOException {
        byte[] buffer = input.readNBytes(2048);
        return new String(buffer, StandardCharsets.UTF_8);
    }

}
